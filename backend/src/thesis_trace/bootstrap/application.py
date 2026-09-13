from __future__ import annotations

import time
import uuid
import logging
from typing import Callable, Protocol
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Cookie, Header, HTTPException, Request, Response
from thesis_trace.api import AccessApi, EvidenceApi
from thesis_trace.adapters.cloudflare_identity.adapter import (
    CloudflareGetIdentityClient,
    CloudflareIdentityAdapter,
    CloudflareJwksDecoder,
)
from thesis_trace.adapters.postgres_access.adapter import PostgresAccessAdapter
from thesis_trace.adapters.postgres_atomic.adapter import (
    PostgresConfirmedPortfolioTrade,
    PostgresConfirmedThesisTransition,
    PostgresConfirmedValuationPublication,
    PostgresRecommendationTransaction,
)
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.application.flows.evidence_stage import EvidenceStageFlow
from thesis_trace.application.flows.anomaly_assessment import AnomalyAssessmentFlow
from thesis_trace.application.flows.anomaly_assessment import AnomalyJobProcessor
from thesis_trace.application.flows.anomaly_assessment import ActionInboxFlow
from thesis_trace.adapters.openai_recommendation.adapter import (
    OpenAIRecommendationAdapter,
)
from thesis_trace.adapters.postgres_workflow.adapter import PostgresWorkflowStore
from thesis_trace.adapters.postgres_thesis.adapter import PostgresThesisStore
from thesis_trace.adapters.postgres_portfolio.adapter import PostgresPortfolioStore
from thesis_trace.adapters.postgres_recommendation.adapter import (
    PostgresRecommendationStore,
)
from thesis_trace.application.contracts import RecommendationFlow
from thesis_trace.application.contracts import (
    PortfolioFlow,
    ThesisLifecycleFlow,
    ValuationFlow,
)
from thesis_trace.modules.access.contracts import (
    AuthenticatedActor,
    Role,
    SecurityContext,
)
from thesis_trace.modules.access.jwt_verifier import (
    AccessJwtConfiguration,
    CloudflareJwtVerifier,
    JwtVerificationError,
)
from thesis_trace.modules.access.jwt_verifier import derive_identity_facts
from thesis_trace.modules.access.identity_registry.service import IdentityRegistry
from thesis_trace.modules.access.session_management.service import SessionService
from thesis_trace.modules.access.recovery_policy import RecoveryPolicyConfiguration
from thesis_trace.modules.access.confirmation_challenge.service import (
    ConfirmationService,
)
from thesis_trace.modules.access.orchestration import AccountActionService
from thesis_trace.modules.access.identity_registry.contracts import ProviderIdentity
from thesis_trace.platform.postgres import (
    PostgresEvidenceStore,
    current_database_security_context,
    database_security_context,
    verify_schema_compatibility,
)
from thesis_trace.platform.runtime import (
    required_secret_provider,
    required_setting,
    minimum_return_configuration,
)
from thesis_trace.platform.source_fetch import RestrictedHttpSourceFetcher
from thesis_trace.modules.research.evidence_collection.service import EvidenceCollector
from thesis_trace.modules.research.evidence_stage.service import EvidenceStageService
from thesis_trace.modules.research.anomaly_assessment.service import (
    AnomalyAssessmentService,
)
from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyAnalysisVersions,
)
from thesis_trace.modules.research import (
    ResearchAnomalyFacade,
    ResearchStageFacade,
    ResearchRecommendationFacade,
)
from thesis_trace.modules.workflow.service import WorkflowService
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.modules.portfolio.service import PortfolioService


@dataclass(slots=True)
class ApiRuntime:
    """Process-lifetime API bindings retained by FastAPI application state."""

    store: PostgresEvidenceStore
    verifier: CloudflareJwtVerifier
    access_store: PostgresAccessAdapter
    identity_adapter: CloudflareIdentityAdapter
    workflow_store: PostgresWorkflowStore
    thesis_store: PostgresThesisStore
    portfolio_store: PostgresPortfolioStore


@dataclass(slots=True)
class CollectorRuntime:
    """Process-lifetime collector bindings retained by the bound run handle."""

    collector: EvidenceCollector

    def run_forever(self) -> int:
        while True:
            if not self.collector.run_once():
                time.sleep(2)


class AnomalyProcessor(Protocol):
    """Composition-local structural contract retained by the AI worker runtime."""

    def run_once(self) -> bool: ...


@dataclass(slots=True)
class AiWorkerRuntime:
    """Process-lifetime AI bindings retained by the isolated worker handle."""

    processor: AnomalyProcessor
    recommendation: Callable[[], bool] | None = None
    expiry: Callable[[], bool] | None = None

    def run_once(self) -> bool:
        worked = False
        for label, operation in (
            ("expiry", self.expiry),
            ("anomaly", self.processor.run_once),
            ("recommendation", self.recommendation),
        ):
            if operation is None:
                continue
            try:
                result = operation()
                worked = bool(result) or worked
            except Exception:
                # Durable queues/cursor retain recovery authority. Never log
                # exception text: it may contain provider input or credentials.
                logging.getLogger(__name__).warning(
                    "AI worker operation failed: %s", label
                )
        return worked

    def run_forever(self) -> int:
        while True:
            if not self.run_once():
                time.sleep(2)


def _recommendation_bindings(
    database_url_provider, research, access, theses, portfolio, workflow
):
    minimum, minimum_policy = minimum_return_configuration()
    versions = tuple(
        {
            "provider": "openai",
            "model": required_setting("THESIS_TRACE_OPENAI_MODEL"),
            "prompt": "investment-candidate-prompt-v1",
            "critic_model": required_setting("THESIS_TRACE_OPENAI_CRITIC_MODEL"),
            "critic_prompt": "investment-critic-prompt-v1",
            "build": required_setting("THESIS_TRACE_BUILD_ID"),
            "candidate_schema": "investment-candidate-v1",
            "critic_schema": "investment-critic-v1",
            "minimum_return_policy": minimum_policy,
            "risk_policy": "exposure-policy-v1",
            "cost_profile_policy": "cost-profile-v1",
            "sizing_policy": "dca-selection-v1",
            "return_policy": "valuation-return-v1",
        }.items()
    )
    store = PostgresRecommendationStore(
        database_url_provider,
        security_context_provider=current_database_security_context,
        build_version=dict(versions)["build"],
    )
    flow = RecommendationFlow(
        ThesisService(theses),
        PortfolioService(portfolio),
        research,
        minimum_return=minimum,
        minimum_return_policy_version=minimum_policy,
        source_queries=ResearchRecommendationFacade(research),
        versions=versions,
    )
    transactions = PostgresRecommendationTransaction(
        access=access,
        theses=theses,
        portfolio=portfolio,
        research=research,
        recommendations=store,
        workflow=workflow,
        flow=flow,
    )
    return flow, store, transactions, versions


def _anomaly_analysis_versions() -> AnomalyAnalysisVersions:
    return AnomalyAnalysisVersions(
        build_version=required_setting("THESIS_TRACE_BUILD_ID"),
        candidate_schema_version="anomaly-candidate-v1",
        candidate_prompt_version="anomaly-prompt-v1",
        provider_model_version=required_setting("THESIS_TRACE_OPENAI_MODEL"),
        critic_schema_version="recommendation-critic-v1",
        critic_prompt_version="recommendation-critic-prompt-v1",
        critic_model_version=required_setting("THESIS_TRACE_OPENAI_CRITIC_MODEL"),
    )


def create_authenticated_actor_dependency(
    identity_adapter, identity_registry, sessions
):
    async def authenticated_actor(
        request: Request,
        response: Response,
        cf_access_jwt_assertion: str | None = Header(
            default=None, alias="Cf-Access-Jwt-Assertion"
        ),
        thesis_trace_session: str = Cookie(default=""),
        recovery_reason: str | None = Header(
            default=None, alias="X-ThesisTrace-Recovery-Reason"
        ),
    ):
        try:
            # JWT verification and token-bound full identity lookup happen on every request,
            # even when a ThesisTrace session cookie already exists.
            principal = identity_adapter.verify(cf_access_jwt_assertion or "")
            account = identity_registry.resolve(principal)
            if thesis_trace_session:
                session = sessions.validate(thesis_trace_session, account)
            else:
                recovery = principal.identity.provider_type == "cloudflare"
                token, session, _profile = sessions.bootstrap(
                    account,
                    principal,
                    recovery=recovery,
                    recovery_reason=recovery_reason,
                )
                max_age = max(
                    0,
                    int(
                        (
                            session.expires_at - datetime.now(timezone.utc)
                        ).total_seconds()
                    ),
                )
                response.set_cookie(
                    "thesis_trace_session",
                    token,
                    max_age=max_age,
                    expires=session.expires_at,
                    secure=True,
                    httponly=True,
                    samesite="strict",
                    path="/",
                )
            actor = AuthenticatedActor(account.user_id, account.role, account.version)
            request.state.verified_principal = principal
            request.state.access_session_profile = AccessApi.profile_for(
                account, session
            )
        except (JwtVerificationError, PermissionError) as error:
            raise HTTPException(status_code=401, detail="access_denied") from error
        with database_security_context(
            SecurityContext(actor.actor_id, actor.role, str(uuid.uuid4()))
        ):
            yield actor

    # FastAPI evaluates nested dependency annotations independently of this closure.
    authenticated_actor.__annotations__.update(
        {"request": Request, "response": Response}
    )
    return authenticated_actor


def compose_application(role: str = "api") -> object:
    """Construct one release role while keeping all adapter selection behind one symbol."""
    if role not in {"api", "collector", "collector-healthcheck", "ai-worker"}:
        raise ValueError("unknown_runtime_role")
    database_url_provider = required_secret_provider("THESIS_TRACE_DATABASE_URL")
    runtime_role = (
        "collector"
        if role == "collector"
        else ("ai_worker" if role == "ai-worker" else None)
    )
    store = PostgresEvidenceStore(database_url_provider, runtime_role=runtime_role)
    verify_schema_compatibility(database_url_provider)

    if role == "collector-healthcheck":
        return store.ping

    if role == "collector":
        runtime = CollectorRuntime(
            EvidenceCollector(store=store, source_fetcher=RestrictedHttpSourceFetcher())
        )
        return runtime.run_forever

    if role == "ai-worker":
        service = AnomalyAssessmentService(
            store=store,
            clock=lambda: datetime.now(timezone.utc).isoformat(),
            versions=_anomaly_analysis_versions(),
        )
        provider = OpenAIRecommendationAdapter(
            api_key_provider=required_secret_provider("THESIS_TRACE_OPENAI_API_KEY"),
            model=required_setting("THESIS_TRACE_OPENAI_MODEL"),
            critic_model=required_setting("THESIS_TRACE_OPENAI_CRITIC_MODEL"),
        )
        _flow, recommendations, transactions, versions = _recommendation_bindings(
            database_url_provider,
            store,
            PostgresAccessAdapter(database_url_provider),
            PostgresThesisStore(
                database_url_provider,
                security_context_provider=current_database_security_context,
                build_version=required_setting("THESIS_TRACE_BUILD_ID"),
            ),
            PostgresPortfolioStore(
                database_url_provider,
                security_context_provider=current_database_security_context,
                build_version=required_setting("THESIS_TRACE_BUILD_ID"),
            ),
            PostgresWorkflowStore(
                database_url_provider,
                security_context_provider=current_database_security_context,
            ),
        )
        runtime = AiWorkerRuntime(
            AnomalyJobProcessor(
                research=ResearchAnomalyFacade(service),
                provider=provider,
                critic=provider,
            ),
            recommendation=lambda: RecommendationFlow.process_one(
                store=recommendations,
                provider=provider.analyze_investment,
                critic=provider.criticize_investment,
                transactions=transactions,
                versions=versions,
                clock=lambda: datetime.now(timezone.utc),
            ),
            expiry=transactions.reconcile_one,
        )
        return runtime.run_forever

    from thesis_trace.api import create_fastapi_app

    issuer = required_setting("THESIS_TRACE_ACCESS_ISSUER")
    audience = required_setting("THESIS_TRACE_ACCESS_AUDIENCE")
    identity_facts = derive_identity_facts(
        required_secret_provider("THESIS_TRACE_OWNER_IDENTITIES")()
    )
    jwt_configuration = AccessJwtConfiguration(issuer, audience, identity_facts)
    verifier = CloudflareJwtVerifier(
        jwt_configuration, decoder=CloudflareJwksDecoder(issuer, audience)
    )
    access_store = PostgresAccessAdapter(database_url_provider)
    identity_adapter = CloudflareIdentityAdapter(
        verifier, CloudflareGetIdentityClient(issuer)
    )
    identity_registry = IdentityRegistry(access_store)
    recovery_parts = required_secret_provider("THESIS_TRACE_RECOVERY_IDENTITY")().split(
        ":", 2
    )
    if len(recovery_parts) != 3:
        raise RuntimeError("recovery identity configuration is invalid")
    recovery_policy = RecoveryPolicyConfiguration(
        ProviderIdentity(*recovery_parts),
        required_setting("THESIS_TRACE_RECOVERY_POLICY_VERSION"),
        required_setting("THESIS_TRACE_RECOVERY_POLICY_ENABLED").casefold() == "true",
    )
    sessions = SessionService(access_store, recovery_policy=recovery_policy)
    confirmations = ConfirmationService(access_store)
    account_actions = AccountActionService(access_store, confirmations)

    authenticated_actor = create_authenticated_actor_dependency(
        identity_adapter, identity_registry, sessions
    )

    runtime = ApiRuntime(
        store=store,
        verifier=verifier,
        access_store=access_store,
        identity_adapter=identity_adapter,
        workflow_store=PostgresWorkflowStore(
            database_url_provider,
            security_context_provider=current_database_security_context,
        ),
        thesis_store=PostgresThesisStore(
            database_url_provider,
            security_context_provider=current_database_security_context,
            build_version=required_setting("THESIS_TRACE_BUILD_ID"),
        ),
        portfolio_store=PostgresPortfolioStore(
            database_url_provider,
            security_context_provider=current_database_security_context,
            build_version=required_setting("THESIS_TRACE_BUILD_ID"),
        ),
    )
    flow = EvidenceIntakeFlow(store=store, id_generator=lambda: str(uuid.uuid4()))
    stage_flow = EvidenceStageFlow(
        research=ResearchStageFacade(
            EvidenceStageService(
                store=store, clock=lambda: datetime.now(timezone.utc).isoformat()
            )
        )
    )
    research_anomaly = ResearchAnomalyFacade(
        AnomalyAssessmentService(
            store=store,
            clock=lambda: datetime.now(timezone.utc).isoformat(),
            versions=_anomaly_analysis_versions(),
        )
    )
    anomaly_flow = AnomalyAssessmentFlow(research=research_anomaly)
    action_inbox_flow = ActionInboxFlow(
        research=research_anomaly,
        workflow=WorkflowService(
            runtime.workflow_store,
            clock=lambda: datetime.now(timezone.utc).isoformat(),
            id_generator=lambda: str(uuid.uuid4()),
        ),
        clock=lambda: datetime.now(timezone.utc).isoformat(),
    )
    thesis_service = ThesisService(
        runtime.thesis_store, id_factory=lambda: str(uuid.uuid4())
    )
    thesis_flow = ThesisLifecycleFlow(
        thesis_service,
        store,
        confirmations=confirmations,
        confirmed_transitions=PostgresConfirmedThesisTransition(
            access_store,
            runtime.thesis_store,
            thesis_service,
        ),
        clock=lambda: datetime.now(timezone.utc),
    )
    portfolio_service = PortfolioService(runtime.portfolio_store)
    portfolio_flow = PortfolioFlow(
        portfolio_service,
        thesis=thesis_service,
        confirmations=confirmations,
        confirmed_trades=PostgresConfirmedPortfolioTrade(
            access_store,
            runtime.portfolio_store,
            portfolio_service,
        ),
        clock=lambda: datetime.now(timezone.utc),
    )
    valuation_flow = ValuationFlow(
        thesis_service,
        portfolio_service,
        store,
        confirmations=confirmations,
        confirmed_publications=PostgresConfirmedValuationPublication(
            access_store,
            runtime.thesis_store,
            thesis_service,
            store,
            runtime.portfolio_store,
        ),
        clock=lambda: datetime.now(timezone.utc),
    )
    (
        recommendation_flow,
        recommendation_store,
        recommendation_transactions,
        _versions,
    ) = _recommendation_bindings(
        database_url_provider,
        store,
        access_store,
        runtime.thesis_store,
        runtime.portfolio_store,
        runtime.workflow_store,
    )
    app = create_fastapi_app(
        EvidenceApi(
            flow=flow,
            stage_flow=stage_flow,
            anomaly_flow=anomaly_flow,
            action_inbox_flow=action_inbox_flow,
            thesis_flow=thesis_flow,
            portfolio_flow=portfolio_flow,
            valuation_flow=valuation_flow,
            recommendation_flow=recommendation_flow.with_runtime(
                recommendation_store, recommendation_transactions
            ),
        ),
        authenticated_actor,
        AccessApi(access_store, sessions, account_actions),
    )
    app.state.thesis_trace_runtime = runtime

    @app.get("/health/ready")
    async def readiness() -> dict[str, str]:
        if not store.ping():
            raise HTTPException(status_code=503, detail="not_ready")
        return {"status": "ready", "storage": "postgresql"}

    return app
