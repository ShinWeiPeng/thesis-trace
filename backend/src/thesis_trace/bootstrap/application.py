from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Cookie, Header, HTTPException, Request, Response
from thesis_trace.api import AccessApi, EvidenceApi
from thesis_trace.adapters.cloudflare_identity.adapter import CloudflareGetIdentityClient, CloudflareIdentityAdapter, CloudflareJwksDecoder
from thesis_trace.adapters.postgres_access.adapter import PostgresAccessAdapter
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.application.flows.evidence_stage import EvidenceStageFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, SecurityContext
from thesis_trace.modules.access.jwt_verifier import AccessJwtConfiguration, CloudflareJwtVerifier, JwtVerificationError
from thesis_trace.modules.access.jwt_verifier import derive_identity_facts
from thesis_trace.modules.access.identity_registry.service import IdentityRegistry
from thesis_trace.modules.access.session_management.service import SessionService
from thesis_trace.modules.access.recovery_policy import RecoveryPolicyConfiguration
from thesis_trace.modules.access.confirmation_challenge.service import ConfirmationService
from thesis_trace.modules.access.orchestration import AccountActionService
from thesis_trace.modules.access.identity_registry.contracts import ProviderIdentity
from thesis_trace.platform.postgres import PostgresEvidenceStore, database_security_context, verify_schema_compatibility
from thesis_trace.platform.runtime import required_secret_provider, required_setting
from thesis_trace.platform.source_fetch import RestrictedHttpSourceFetcher
from thesis_trace.modules.research.evidence_collection.service import EvidenceCollector
from thesis_trace.modules.research.evidence_stage.service import EvidenceStageService
from thesis_trace.modules.research import ResearchStageFacade


@dataclass(slots=True)
class ApiRuntime:
    """Process-lifetime API bindings retained by FastAPI application state."""

    store: PostgresEvidenceStore
    verifier: CloudflareJwtVerifier
    access_store: PostgresAccessAdapter
    identity_adapter: CloudflareIdentityAdapter


@dataclass(slots=True)
class CollectorRuntime:
    """Process-lifetime collector bindings retained by the bound run handle."""

    collector: EvidenceCollector

    def run_forever(self) -> int:
        while True:
            if not self.collector.run_once():
                time.sleep(2)


def create_authenticated_actor_dependency(identity_adapter, identity_registry, sessions):
    async def authenticated_actor(
        request: Request,
        response: Response,
        cf_access_jwt_assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
        thesis_trace_session: str = Cookie(default=""),
        recovery_reason: str | None = Header(default=None, alias="X-ThesisTrace-Recovery-Reason"),
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
                    account, principal, recovery=recovery, recovery_reason=recovery_reason,
                )
                max_age = max(0, int((session.expires_at - datetime.now(timezone.utc)).total_seconds()))
                response.set_cookie(
                    "thesis_trace_session", token, max_age=max_age, expires=session.expires_at,
                    secure=True, httponly=True, samesite="strict", path="/",
                )
            actor = AuthenticatedActor(account.user_id, account.role, account.version)
            request.state.verified_principal = principal
            request.state.access_session_profile = AccessApi.profile_for(account, session)
        except (JwtVerificationError, PermissionError) as error:
            raise HTTPException(status_code=401, detail="access_denied") from error
        with database_security_context(SecurityContext(actor.actor_id, actor.role, str(uuid.uuid4()))):
            yield actor
    # FastAPI evaluates nested dependency annotations independently of this closure.
    authenticated_actor.__annotations__.update({"request": Request, "response": Response})
    return authenticated_actor


def compose_application(role: str = "api") -> object:
    """Construct one release role while keeping all adapter selection behind one symbol."""
    if role not in {"api", "collector", "collector-healthcheck"}:
        raise ValueError("unknown_runtime_role")
    database_url_provider = required_secret_provider("THESIS_TRACE_DATABASE_URL")
    store = PostgresEvidenceStore(database_url_provider, runtime_role="collector" if role == "collector" else None)
    verify_schema_compatibility(database_url_provider)

    if role == "collector-healthcheck":
        return store.ping

    if role == "collector":
        runtime = CollectorRuntime(
            EvidenceCollector(store=store, source_fetcher=RestrictedHttpSourceFetcher())
        )
        return runtime.run_forever

    from thesis_trace.api import create_fastapi_app

    issuer = required_setting("THESIS_TRACE_ACCESS_ISSUER")
    audience = required_setting("THESIS_TRACE_ACCESS_AUDIENCE")
    identity_facts = derive_identity_facts(
        required_secret_provider("THESIS_TRACE_OWNER_IDENTITIES")()
    )
    jwt_configuration = AccessJwtConfiguration(issuer, audience, identity_facts)
    verifier = CloudflareJwtVerifier(jwt_configuration, decoder=CloudflareJwksDecoder(issuer, audience))
    access_store = PostgresAccessAdapter(database_url_provider)
    identity_adapter = CloudflareIdentityAdapter(verifier, CloudflareGetIdentityClient(issuer))
    identity_registry = IdentityRegistry(access_store)
    recovery_parts = required_secret_provider("THESIS_TRACE_RECOVERY_IDENTITY")().split(":", 2)
    if len(recovery_parts) != 3:
        raise RuntimeError("recovery identity configuration is invalid")
    recovery_policy = RecoveryPolicyConfiguration(
        ProviderIdentity(*recovery_parts), required_setting("THESIS_TRACE_RECOVERY_POLICY_VERSION"),
        required_setting("THESIS_TRACE_RECOVERY_POLICY_ENABLED").casefold() == "true",
    )
    sessions = SessionService(access_store, recovery_policy=recovery_policy)
    confirmations = ConfirmationService(access_store)
    account_actions = AccountActionService(access_store, confirmations)

    authenticated_actor = create_authenticated_actor_dependency(identity_adapter, identity_registry, sessions)

    runtime = ApiRuntime(
        store=store,
        verifier=verifier,
        access_store=access_store,
        identity_adapter=identity_adapter,
    )
    flow = EvidenceIntakeFlow(store=store, id_generator=lambda: str(uuid.uuid4()))
    stage_flow = EvidenceStageFlow(
        research=ResearchStageFacade(
            EvidenceStageService(store=store, clock=lambda: datetime.now(timezone.utc).isoformat())
        )
    )
    app = create_fastapi_app(
        EvidenceApi(flow=flow, stage_flow=stage_flow), authenticated_actor,
        AccessApi(access_store, sessions, account_actions),
    )
    app.state.thesis_trace_runtime = runtime

    @app.get("/health/ready")
    async def readiness() -> dict[str, str]:
        if not store.ping():
            raise HTTPException(status_code=503, detail="not_ready")
        return {"status": "ready", "storage": "postgresql"}

    return app
