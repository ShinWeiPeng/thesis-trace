from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from starlette.requests import Request
from starlette.responses import Response

from thesis_trace.application.contracts import (
    CreateCompanyCommand,
    ListCompaniesQuery,
    PortfolioFlow,
    SubmitEvidenceRequest,
    ThesisLifecycleFlow,
    ValuationFlow,
)
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.application.flows.evidence_stage import (
    ConfirmEvidenceStageRequest,
    EvidenceStageFlow,
    EvidenceStageResult,
    QueryEvidenceStageRequest,
)
from thesis_trace.application.flows.anomaly_assessment import (
    ActionInboxFlow,
    ActionInboxResult,
    ActionItemResult,
    AnomalyAssessmentFlow,
    AnomalyAssessmentResult,
    AnomalySourceInput,
    RequestAnomalyAssessment,
    CreateAnomalyReviewActionRequest,
    QueryActionInboxRequest,
    QueryActionItemRequest,
    TransitionActionItemRequest,
)
from thesis_trace.modules.access.contracts import AuthenticatedActor
from thesis_trace.modules.access.contracts import Role
from thesis_trace.modules.access.identity_registry.contracts import ProviderIdentity
from thesis_trace.modules.access.orchestration import AccountActionService
from thesis_trace.modules.access.session_management.service import SessionService, _CAPABILITIES
from thesis_trace.modules.research.evidence_intake.contracts import EvidenceStatus


class CompanyCreateBody(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=200)


class CompanyResponse(BaseModel):
    company_id: str
    ticker: str
    name: str
    version: int


class EvidenceSubmissionBody(BaseModel):
    company_id: str
    company_version: int = Field(ge=1)
    url: HttpUrl
    idempotency_key: str = Field(min_length=1, max_length=200)


class EvidenceResponse(BaseModel):
    evidence_id: str
    version: int
    status: EvidenceStatus
    source_snapshot_id: str | None = None


class DimensionFactsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_confirmation: Literal["unverified", "official"]
    product_established: bool
    commercialization_established: bool
    identifiable_revenue: bool
    identifiable_profit_or_cash_flow: bool
    consecutive_financial_quarters: int = Field(ge=0, le=100)


class EvidenceStageConfirmationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_snapshot_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    facts: DimensionFactsBody
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class GateResultResponse(BaseModel):
    gate: str
    passed: bool
    code: str


class EvidenceStageResponse(BaseModel):
    evidence_id: str
    version: int
    source_snapshot_id: str
    actor_id: str
    confirmed_at: str
    reason: str
    facts: DimensionFactsBody
    stage: str
    gate_trace: list[GateResultResponse]
    policy_version: str


class AnomalySourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_snapshot_id: str = Field(min_length=1)


class AnomalyAssessmentRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_evidence_version: int = Field(ge=1)
    sources: list[AnomalySourceBody] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class AnomalyGateResponse(BaseModel):
    gate: str
    passed: bool
    code: str


class AnomalyTraceResponse(BaseModel):
    anomaly_class: Literal["soft", "would_be_hard"]
    source_tiers: list[Literal["A", "B", "C"]]
    clue_score: int | None
    clue_route: Literal["save_only", "watch_daily", "human_review"] | None
    gates: list[AnomalyGateResponse]
    policy_version: str


class AnomalyAssessmentResponse(BaseModel):
    assessment_id: str
    version: int
    evidence_id: str
    evidence_version: int
    source_snapshot_ids: list[str]
    status: Literal["pending", "succeeded", "failed", "superseded"]
    requested_at: str
    trace: AnomalyTraceResponse | None
    failure_code: str | None


class ActionItemCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessment_id: str = Field(min_length=1)
    expected_assessment_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    due_at: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)


class ActionItemTransitionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    target_status: Literal["pending", "in_progress", "deferred", "completed", "dismissed"]
    reason: str = Field(min_length=1, max_length=2000)
    defer_until: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)


class ActionInboxSummaryResponse(BaseModel):
    urgent: int
    due_today: int
    deferred: int
    all_open: int


class ActionItemResponse(BaseModel):
    item_id: str
    version: int
    item_type: Literal["anomaly_review"]
    source_domain: str
    source_record_id: str
    source_version: int
    company_id: str
    company_ticker: str
    company_name: str
    reason: str
    status: Literal["pending", "in_progress", "deferred", "completed", "dismissed"]
    system_priority: Literal["critical", "high", "normal", "low"]
    effective_priority: Literal["critical", "high", "normal", "low"]
    safety_floor: Literal["critical", "high", "normal", "low"] | None
    safety_locked: bool
    priority_rule_ids: list[str]
    priority_policy_version: str
    priority_reason: str
    created_at: str
    updated_at: str
    due_at: str | None
    defer_until: str | None
    recurrence_of: str | None
    allowed_transitions: list[Literal["pending", "in_progress", "deferred", "completed", "dismissed"]]


class ActionInboxResponse(BaseModel):
    summary: ActionInboxSummaryResponse
    total_count: int
    items: list[ActionItemResponse]
    next_cursor: str | None
    as_of: str


class ThesisResearchReferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1)
    version: int = Field(ge=1)


class ThesisCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    narrative: str = Field(min_length=1, max_length=50000)
    invalidation_conditions: list[str] = Field(min_length=1, max_length=50)
    evidence_refs: list[ThesisResearchReferenceBody] = Field(default_factory=list, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ThesisSaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    narrative: str = Field(min_length=1, max_length=50000)
    invalidation_conditions: list[str] = Field(min_length=1, max_length=50)
    evidence_refs: list[ThesisResearchReferenceBody] = Field(default_factory=list, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ThesisTransitionPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    target_status: Literal["draft", "active", "paused", "invalidated", "closed"]


class ThesisTransitionBody(ThesisTransitionPreviewBody):
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    challenge_token: str | None = None


class ThesisOutcomeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    observed_at: datetime
    result: str = Field(min_length=1, max_length=50000)
    evidence_refs: list[ThesisResearchReferenceBody] = Field(default_factory=list, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ThesisReflectionDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_draft_version: int = Field(ge=0)
    field: Literal["original_assumption", "judgment_errors", "missing_evidence", "improvement"]
    text: str = Field(max_length=50000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ThesisReflectionCompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    original_assumption: str = Field(min_length=1, max_length=50000)
    judgment_errors: str = Field(min_length=1, max_length=50000)
    missing_evidence: str = Field(min_length=1, max_length=50000)
    improvement: str = Field(min_length=1, max_length=50000)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ThesisResponse(BaseModel):
    thesis_id: str
    version: int
    owner_user_id: str
    company_id: str
    company_version: int
    title: str
    narrative: str
    status: Literal["draft", "active", "paused", "invalidated", "closed"]
    cycle: int
    reflection_pending: bool
    created_at: str
    updated_at: str
    conditions: list[dict[str, Any]]
    evidence_refs: list[dict[str, Any]]
    outcome: dict[str, Any] | None
    reflection: dict[str, Any] | None
    reflection_draft: dict[str, Any] | None
    valuation_draft: dict[str, Any] | None
    valuation_snapshots: list[dict[str, Any]]
    policy_version: str


class ThesisTransitionPreviewResponse(BaseModel):
    thesis_id: str
    target_version: int
    from_status: Literal["draft", "active", "paused", "invalidated", "closed"]
    to_status: Literal["draft", "active", "paused", "invalidated", "closed"]
    consequences: list[str]
    requires_confirmation: bool
    challenge_token: str | None = None
    challenge_expires_at: str | None = None
    impact_summary: dict[str, Any] | None = None


class CostProfileSaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    buy_rate: str = Field(min_length=1)
    minimum_buy_fee: str = Field(min_length=1)
    sell_rate: str = Field(min_length=1)
    minimum_sell_fee: str = Field(min_length=1)
    tax_rate: str = Field(min_length=1)
    effective_at: datetime
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class InvestableCashSaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    cash: str = Field(min_length=1)
    as_of: datetime
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class TradeAllocationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bucket_id: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0)


class TradePreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    source_kind: Literal["manual", "csv"]
    source_row_id: str = Field(min_length=1, max_length=200)
    broker_reference: str | None = Field(default=None, max_length=200)
    security_id: str = Field(min_length=1, max_length=100)
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    price: str = Field(min_length=1)
    fees: str = Field(min_length=1)
    tax: str = Field(min_length=1)
    executed_at: datetime
    allocations: list[TradeAllocationBody] = Field(min_length=1, max_length=100)


class TradeConfirmBody(TradePreviewBody):
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    challenge_token: str = Field(min_length=1)


class PortfolioResponse(BaseModel):
    version: int
    cost_profile: dict[str, Any] | None
    cash: str
    cash_as_of: str | None
    holdings: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    corrections: list[dict[str, Any]]
    company_actions: list[dict[str, Any]]
    exposure: dict[str, Any]
    updated_at: str


class TradePreviewResponse(BaseModel):
    target_version: int
    fingerprint: str
    preview_digest: str
    post_cash: str
    nav: str
    feasible: bool
    reasons: list[str]
    policy_version: str
    challenge_token: str
    challenge_expires_at: str
    impact_summary: dict[str, Any]


class CanonicalCsvPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=2_000_000)


class CanonicalCsvPreviewResponse(BaseModel):
    trades: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    policy_version: str


class TradeCorrectionPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    original_trade_id: str = Field(min_length=1, max_length=200)


class TradeCorrectionConfirmBody(TradeCorrectionPreviewBody):
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    challenge_token: str = Field(min_length=1)


class CompanyActionPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    security_id: str = Field(min_length=1, max_length=100)
    action_kind: Literal["split", "capital_reduction", "stock_dividend"]
    confirmed_post_action_shares: int = Field(ge=0)
    cash_in_lieu: str = Field(min_length=1)


class CompanyActionConfirmBody(CompanyActionPreviewBody):
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    challenge_token: str = Field(min_length=1)


class PortfolioMutationPreviewResponse(BaseModel):
    target_version: int
    preview_digest: str
    post_cash: str
    original_trade_id: str | None = None
    allocation: dict[str, Any] | None = None
    challenge_token: str
    challenge_expires_at: str
    impact_summary: dict[str, Any]


class ValuationSourceReferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    fact_id: str = Field(min_length=1, max_length=200)


class ValuationHistorySampleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: ValuationSourceReferenceBody


class PeerValuationMemberBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: str = Field(min_length=1, max_length=100)
    inclusion_reason: str = Field(min_length=1, max_length=2000)
    source: ValuationSourceReferenceBody


class ValuationDraftSaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_thesis_version: int = Field(ge=1)
    expected_draft_version: int = Field(ge=0)
    method: Literal["pe", "pb", "abstain"]
    benchmark_source: Literal["company_history", "peer_group", "abstain"]
    benchmark_variant: Literal["median", "p75"]
    company_history_samples: list[ValuationHistorySampleBody] = Field(default_factory=list, max_length=240)
    peer_members: list[PeerValuationMemberBody] = Field(default_factory=list, max_length=12)
    source_selection_reason: str = Field(min_length=1, max_length=2000)
    basis_date: date
    horizon_months: Literal[6, 12, 24]
    forecast_source: ValuationSourceReferenceBody | None = None
    quantity: str | None = Field(default=None, min_length=1)
    buy_price: str | None = Field(default=None, min_length=1)
    cash_dividend: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ValuationPublicationPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_thesis_version: int = Field(ge=1)
    expected_draft_version: int = Field(ge=1)


class ValuationPublicationBody(ValuationPublicationPreviewBody):
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    challenge_token: str = Field(min_length=1)


class ValuationPublicationPreviewResponse(BaseModel):
    target_version: int
    draft_version: int
    challenge_token: str
    challenge_expires_at: str
    impact_summary: dict[str, Any]


class OwnerSessionResponse(BaseModel):
    kind: Literal["owner"]
    user_id: str
    capabilities: list[str]
    session_expires_at: datetime
    is_recovery_session: bool
    display_name: str
    recovery_task_url: str | None = None


class LearnerSessionResponse(BaseModel):
    kind: Literal["learner"]
    user_id: str
    capabilities: list[str]
    session_expires_at: datetime
    is_recovery_session: bool
    display_name: str


class AdminSessionResponse(BaseModel):
    kind: Literal["admin"]
    user_id: str
    capabilities: list[str]
    session_expires_at: datetime
    is_recovery_session: bool
    display_name: str


SessionResponse = Annotated[
    Union[OwnerSessionResponse, LearnerSessionResponse, AdminSessionResponse],
    Field(discriminator="kind"),
]


class AccountCreateBody(BaseModel):
    role: Role
    provider_id: str = Field(min_length=1)
    provider_type: str = Field(min_length=1)
    provider_subject: str = Field(min_length=1)
    email_fact: str = Field(min_length=3)
    challenge_token: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class AccountResponse(BaseModel):
    user_id: str
    role: Role
    status: Literal["active", "disabled"]
    masked_identity: str
    version: int


class ConfirmationChallengeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    target_version: int = Field(ge=1)
    payload: dict[str, Any]


class ImpactSummaryResponse(BaseModel):
    subject: str
    action_label: str
    before: dict[str, str]
    after: dict[str, str]
    consequences: list[str]
    confirmation_verb: str


class ConfirmationChallengeResponse(BaseModel):
    challenge_token: str
    expires_at: datetime
    target_version: int
    impact_summary: ImpactSummaryResponse


class ConfirmedActionBody(BaseModel):
    challenge_token: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    target_version: int = Field(ge=1)
    payload: dict[str, Any]
    reason: str = Field(min_length=1)


class ConfirmedActionResponse(BaseModel):
    challenge_id: str
    accepted: bool


class ProblemResponse(BaseModel):
    code: str


class AccessProblem(Exception):
    def __init__(self, code: str = "resource_unavailable") -> None:
        self.code = code


class AccessApiPort(Protocol):
    def session_profile(self, actor: AuthenticatedActor, token: str) -> dict[str, Any]: ...
    def logout(self, actor: AuthenticatedActor, token: str) -> None: ...
    def list_accounts(self, actor: AuthenticatedActor) -> list[dict[str, Any]]: ...
    def get_account(self, actor: AuthenticatedActor, user_id: str) -> dict[str, Any]: ...
    def create_account(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]: ...
    def preview_confirmation(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]: ...
    def confirm_action(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]: ...


class AccessApi:
    """HTTP-facing orchestration; it exposes no persistence handles or raw tokens."""

    def __init__(self, repository: Any, sessions: SessionService, account_actions: AccountActionService) -> None:
        self._repository = repository
        self._sessions = sessions
        self._account_actions = account_actions

    @staticmethod
    def profile_for(account: Any, session: Any) -> dict[str, Any]:
        result = {"kind": account.role.value, "user_id": account.user_id,
                  "capabilities": sorted(_CAPABILITIES[account.role]), "session_expires_at": session.expires_at,
                  "is_recovery_session": session.recovery, "display_name": f"{account.role.value.title()} • {account.user_id[-4:]}"}
        return result

    def session_profile(self, actor: AuthenticatedActor, token: str) -> dict[str, Any]:
        account = self._repository.get_account(actor.actor_id)
        if account is None:
            raise LookupError("resource_unavailable")
        session = self._sessions.validate(token, account)
        return self.profile_for(account, session)

    def logout(self, actor: AuthenticatedActor, token: str) -> None:
        account = self._repository.get_account(actor.actor_id)
        if account is None:
            raise LookupError("resource_unavailable")
        self._sessions.revoke(token, account)

    def list_accounts(self, actor: AuthenticatedActor) -> list[dict[str, Any]]:
        return self._account_actions.list_accounts(actor)

    def get_account(self, actor: AuthenticatedActor, user_id: str) -> dict[str, Any]:
        return self._account_actions.get_account(actor, user_id)

    def create_account(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        payload = {key: body[key] for key in ("role", "provider_id", "provider_type", "provider_subject", "email_fact")}
        _confirmed, account = self._account_actions.confirm(
            actor, token=body["challenge_token"], action_type="create_account", target_version=1,
            payload=payload, reason=body["reason"],
        )
        if account is None:
            raise LookupError("resource_unavailable")
        return {"user_id": account.user_id, "role": account.role, "status": account.status,
                "masked_identity": body["provider_type"], "version": account.version}

    def preview_confirmation(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        preview = self._account_actions.preview(actor, action_type=body["action_type"], target_id=body["target_id"],
                                                target_version=body["target_version"], payload=body["payload"])
        return {"challenge_token": preview.challenge_token, "expires_at": preview.expires_at,
                "target_version": preview.target_version, "impact_summary": preview.impact_summary}

    def confirm_action(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        confirmed, _result = self._account_actions.confirm(
            actor, token=body["challenge_token"], action_type=body["action_type"],
            target_version=body["target_version"], payload=body["payload"], reason=body["reason"],
        )
        return {"challenge_id": confirmed.challenge_id, "accepted": confirmed.accepted}


class EvidenceApi:
    """Framework-independent HTTP boundary contract used by the FastAPI adapter."""

    def __init__(
        self,
        *,
        flow: EvidenceIntakeFlow,
        stage_flow: EvidenceStageFlow | None = None,
        anomaly_flow: AnomalyAssessmentFlow | None = None,
        action_inbox_flow: ActionInboxFlow | None = None,
        thesis_flow: ThesisLifecycleFlow | None = None,
        portfolio_flow: PortfolioFlow | None = None,
        valuation_flow: ValuationFlow | None = None,
    ) -> None:
        self._flow = flow
        self._stage_flow = stage_flow
        self._anomaly_flow = anomaly_flow
        self._action_inbox_flow = action_inbox_flow
        self._thesis_flow = thesis_flow
        self._portfolio_flow = portfolio_flow
        self._valuation_flow = valuation_flow

    def create_company(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        try:
            company = self._flow.create_company(CreateCompanyCommand(
                actor=actor, ticker=str(body.get("ticker", "")), name=str(body.get("name", ""))
            ))
        except PermissionError:
            return {"error": "forbidden"}
        return {"company_id": company.company_id, "ticker": company.ticker, "name": company.name, "version": company.version}

    def list_companies(self, actor: AuthenticatedActor) -> list[dict[str, Any]]:
        return [
            {"company_id": item.company_id, "ticker": item.ticker, "name": item.name, "version": item.version}
            for item in self._flow.list_companies(ListCompaniesQuery(actor=actor))
        ]

    def submit_evidence(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        result = self._flow.submit(
            SubmitEvidenceRequest(
                actor=actor,
                company_id=str(body.get("company_id", "")),
                company_version=int(body.get("company_version", 0)),
                url=str(body.get("url", "")),
                idempotency_key=str(body.get("idempotency_key", "")),
            )
        )
        if result.accepted is None:
            return {"error": result.rejection_code}
        return {
            "evidence_id": result.evidence_id,
            "version": result.version,
            "status": "received",
        }

    def get_evidence(self, actor: AuthenticatedActor, evidence_id: str) -> dict[str, Any]:
        snapshot = self._flow.get_status(actor, evidence_id)
        response = {
            "evidence_id": snapshot.evidence_id,
            "version": snapshot.version,
            "status": snapshot.status.value,
        }
        if snapshot.source_snapshot_id is not None:
            response["source_snapshot_id"] = snapshot.source_snapshot_id
        return response

    @staticmethod
    def _stage_response(record: EvidenceStageResult) -> dict[str, Any]:
        return {
            "evidence_id": record.evidence_id,
            "version": record.version,
            "source_snapshot_id": record.source_snapshot_id,
            "actor_id": record.actor_id,
            "confirmed_at": record.confirmed_at,
            "reason": record.reason,
            "facts": {
                "source_confirmation": record.facts.source_confirmation,
                "product_established": record.facts.product_established,
                "commercialization_established": record.facts.commercialization_established,
                "identifiable_revenue": record.facts.identifiable_revenue,
                "identifiable_profit_or_cash_flow": record.facts.identifiable_profit_or_cash_flow,
                "consecutive_financial_quarters": record.facts.consecutive_financial_quarters,
            },
            "stage": record.stage,
            "gate_trace": [
                {"gate": item.gate, "passed": item.passed, "code": item.code}
                for item in record.gate_trace
            ],
            "policy_version": record.policy_version,
        }

    def confirm_evidence_stage(self, actor: AuthenticatedActor, evidence_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._stage_flow is None:
            raise LookupError("resource_unavailable")
        facts = body["facts"]
        record = self._stage_flow.confirm(actor, ConfirmEvidenceStageRequest(
            evidence_id=evidence_id,
            source_snapshot_id=body["source_snapshot_id"],
            expected_version=body["expected_version"],
            source_confirmation=facts["source_confirmation"],
            product_established=facts["product_established"],
            commercialization_established=facts["commercialization_established"],
            identifiable_revenue=facts["identifiable_revenue"],
            identifiable_profit_or_cash_flow=facts["identifiable_profit_or_cash_flow"],
            consecutive_financial_quarters=facts["consecutive_financial_quarters"],
            reason=body["reason"],
            idempotency_key=body["idempotency_key"],
        ))
        return self._stage_response(record)

    def get_evidence_stage(self, actor: AuthenticatedActor, evidence_id: str) -> dict[str, Any]:
        if self._stage_flow is None:
            raise LookupError("resource_unavailable")
        return self._stage_response(
            self._stage_flow.get_stage(actor, QueryEvidenceStageRequest(evidence_id))
        )

    @staticmethod
    def _anomaly_response(record: AnomalyAssessmentResult) -> dict[str, Any]:
        trace = None
        if record.trace is not None:
            trace = {
                "anomaly_class": record.trace.anomaly_class,
                "source_tiers": list(record.trace.source_tiers),
                "clue_score": record.trace.clue_score,
                "clue_route": record.trace.clue_route,
                "gates": [
                    {"gate": item.gate, "passed": item.passed, "code": item.code}
                    for item in record.trace.gates
                ],
                "policy_version": record.trace.policy_version,
            }
        return {
            "assessment_id": record.assessment_id,
            "version": record.version,
            "evidence_id": record.evidence_id,
            "evidence_version": record.evidence_version,
            "source_snapshot_ids": list(record.source_snapshot_ids),
            "status": record.status,
            "requested_at": record.requested_at,
            "trace": trace,
            "failure_code": record.failure_code,
        }

    def request_anomaly_assessment(
        self, actor: AuthenticatedActor, evidence_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        if self._anomaly_flow is None:
            raise LookupError("resource_unavailable")
        return self._anomaly_response(
            self._anomaly_flow.request(
                actor,
                RequestAnomalyAssessment(
                    evidence_id=evidence_id,
                    expected_evidence_version=body["expected_evidence_version"],
                    sources=tuple(AnomalySourceInput(**item) for item in body["sources"]),
                    reason=body["reason"],
                    idempotency_key=body["idempotency_key"],
                ),
            )
        )

    def get_anomaly_assessment(
        self, actor: AuthenticatedActor, assessment_id: str
    ) -> dict[str, Any]:
        if self._anomaly_flow is None:
            raise LookupError("resource_unavailable")
        return self._anomaly_response(self._anomaly_flow.get(actor, assessment_id))

    @staticmethod
    def _action_item_response(item: ActionItemResult) -> dict[str, Any]:
        return {
            "item_id": item.item_id, "version": item.version, "item_type": item.item_type,
            "source_domain": item.source_domain, "source_record_id": item.source_record_id,
            "source_version": item.source_version, "company_id": item.company_id,
            "company_ticker": item.company_ticker, "company_name": item.company_name,
            "reason": item.reason, "status": item.status,
            "system_priority": item.system_priority, "effective_priority": item.effective_priority,
            "safety_floor": item.safety_floor, "safety_locked": item.safety_locked,
            "priority_rule_ids": list(item.priority_rule_ids),
            "priority_policy_version": item.priority_policy_version,
            "priority_reason": item.priority_reason, "created_at": item.created_at,
            "updated_at": item.updated_at, "due_at": item.due_at,
            "defer_until": item.defer_until, "recurrence_of": item.recurrence_of,
            "allowed_transitions": list(item.allowed_transitions),
        }

    def create_anomaly_review_action(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        if self._action_inbox_flow is None:
            raise LookupError("resource_unavailable")
        return self._action_item_response(self._action_inbox_flow.create(
            actor, CreateAnomalyReviewActionRequest(**body)
        ))

    def query_action_inbox(self, actor: AuthenticatedActor, request: QueryActionInboxRequest) -> dict[str, Any]:
        if self._action_inbox_flow is None:
            raise LookupError("resource_unavailable")
        page: ActionInboxResult = self._action_inbox_flow.query(actor, request)
        return {
            "summary": {"urgent": page.urgent, "due_today": page.due_today,
                        "deferred": page.deferred, "all_open": page.all_open},
            "total_count": page.total_count,
            "items": [self._action_item_response(item) for item in page.items],
            "next_cursor": page.next_cursor, "as_of": page.as_of,
        }

    def get_action_item(self, actor: AuthenticatedActor, item_id: str) -> dict[str, Any]:
        if self._action_inbox_flow is None:
            raise LookupError("resource_unavailable")
        return self._action_item_response(
            self._action_inbox_flow.get(actor, QueryActionItemRequest(item_id))
        )

    def transition_action_item(self, actor: AuthenticatedActor, item_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._action_inbox_flow is None:
            raise LookupError("resource_unavailable")
        return self._action_item_response(self._action_inbox_flow.transition(
            actor, TransitionActionItemRequest(item_id=item_id, **body)
        ))

    def _theses(self) -> ThesisLifecycleFlow:
        if self._thesis_flow is None:
            raise LookupError("resource_unavailable")
        return self._thesis_flow

    def create_thesis(self, actor: AuthenticatedActor, company_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._theses().create(actor, {"company_id": company_id, **body})

    def list_theses(self, actor: AuthenticatedActor, company_id: str) -> list[dict[str, Any]]:
        return self._theses().list_for_company(actor, company_id)

    def get_thesis(self, actor: AuthenticatedActor, thesis_id: str) -> dict[str, Any]:
        return self._theses().get(actor, thesis_id)

    def save_thesis(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._theses().save(actor, thesis_id, body)

    def preview_thesis_transition(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._theses().preview_transition(actor, thesis_id, body)

    def transition_thesis(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._theses().transition(actor, thesis_id, body)

    def save_thesis_outcome(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._theses().save_outcome(actor, thesis_id, body)

    def autosave_thesis_reflection(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._theses().autosave_reflection(actor, thesis_id, body)

    def complete_thesis_reflection(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._theses().complete_reflection(actor, thesis_id, body)

    def _portfolio(self) -> PortfolioFlow:
        if self._portfolio_flow is None:
            raise LookupError("resource_unavailable")
        return self._portfolio_flow

    def get_portfolio(self, actor: AuthenticatedActor) -> dict[str, Any]:
        return self._portfolio().get(actor)

    def save_cost_profile(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        return self._portfolio().save_cost_profile(actor, body)

    def save_investable_cash(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        return self._portfolio().save_cash(actor, body)

    def preview_portfolio_trade(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        return self._portfolio().preview_trade(actor, body)

    def preview_portfolio_csv(self, actor: AuthenticatedActor, content: str) -> dict[str, Any]:
        return self._portfolio().preview_csv(actor, content)

    def confirm_portfolio_trade(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        return self._portfolio().confirm_trade(actor, body)

    def preview_portfolio_correction(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        return self._portfolio().preview_correction(actor, body)

    def confirm_portfolio_correction(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        return self._portfolio().confirm_correction(actor, body)

    def preview_portfolio_company_action(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        return self._portfolio().preview_company_action(actor, body)

    def confirm_portfolio_company_action(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        return self._portfolio().confirm_company_action(actor, body)

    def _valuations(self) -> ValuationFlow:
        if self._valuation_flow is None:
            raise LookupError("resource_unavailable")
        return self._valuation_flow

    def save_valuation_draft(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._valuations().save(actor, thesis_id, body)

    def preview_valuation_publication(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._valuations().preview_publication(actor, thesis_id, body)

    def publish_valuation(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._valuations().publish(actor, thesis_id, body)


def create_fastapi_app(api: EvidenceApi, actor_provider: Any, access_api: AccessApiPort | None = None) -> Any:
    """Create the delivery adapter; import FastAPI only in installed runtimes."""
    from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response

    app = FastAPI(title="ThesisTrace", version="0.1.0")

    @app.post("/api/companies", status_code=201, response_model=CompanyResponse)
    async def create_company(body: CompanyCreateBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
        try:
            response = api.create_company(actor, body.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if "error" in response:
            raise HTTPException(status_code=403, detail=response["error"])
        return response

    @app.get("/api/companies", response_model=list[CompanyResponse])
    async def list_companies(actor: AuthenticatedActor = Depends(actor_provider)) -> list[dict[str, Any]]:
        try:
            return api.list_companies(actor)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="forbidden") from error

    @app.post("/api/evidence", status_code=202, response_model=EvidenceResponse, response_model_exclude_none=True)
    async def submit(body: EvidenceSubmissionBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
        response = api.submit_evidence(actor, {**body.model_dump(), "url": str(body.url)})
        if "error" in response:
            code = 403 if response["error"] == "forbidden" else 422
            raise HTTPException(status_code=code, detail=response["error"])
        return response

    @app.get("/api/evidence/{evidence_id}", response_model=EvidenceResponse, response_model_exclude_none=True)
    async def status(evidence_id: str, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
        try:
            return api.get_evidence(actor, evidence_id)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="forbidden") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="not_found") from error

    @app.post(
        "/api/evidence/{evidence_id}/stage-confirmations",
        status_code=201,
        response_model=EvidenceStageResponse,
    )
    async def confirm_evidence_stage(
        evidence_id: str,
        body: EvidenceStageConfirmationBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.confirm_evidence_stage(actor, evidence_id, body.model_dump())
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="forbidden") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error
        except ValueError as error:
            status_code = 409 if str(error) == "version_conflict" else 422
            raise HTTPException(status_code=status_code, detail=str(error)) from error

    @app.get("/api/evidence/{evidence_id}/stage", response_model=EvidenceStageResponse)
    async def get_evidence_stage(
        evidence_id: str,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.get_evidence_stage(actor, evidence_id)
        except (PermissionError, LookupError) as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error

    @app.post(
        "/api/evidence/{evidence_id}/anomaly-assessments",
        status_code=202,
        response_model=AnomalyAssessmentResponse,
    )
    async def request_anomaly_assessment(
        evidence_id: str,
        body: AnomalyAssessmentRequestBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.request_anomaly_assessment(actor, evidence_id, body.model_dump())
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="forbidden") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error
        except ValueError as error:
            status_code = 409 if str(error) in {"version_conflict", "idempotency_conflict"} else 422
            raise HTTPException(status_code=status_code, detail=str(error)) from error

    @app.get(
        "/api/anomaly-assessments/{assessment_id}",
        response_model=AnomalyAssessmentResponse,
    )
    async def get_anomaly_assessment(
        assessment_id: str,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.get_anomaly_assessment(actor, assessment_id)
        except (PermissionError, LookupError) as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error

    @app.post(
        "/api/action-items/anomaly-reviews", status_code=201,
        response_model=ActionItemResponse,
    )
    async def create_anomaly_review_action(
        body: ActionItemCreateBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.create_anomaly_review_action(actor, body.model_dump())
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="forbidden") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error
        except ValueError as error:
            code = 409 if str(error) in {"version_conflict", "idempotency_conflict"} else 422
            raise HTTPException(status_code=code, detail=str(error)) from error

    @app.get("/api/action-items", response_model=ActionInboxResponse)
    async def query_action_inbox(
        search: str | None = None, company_id: str | None = None,
        item_type: str | None = None, status: str | None = None,
        priority: str | None = None, created_from: str | None = None,
        created_to: str | None = None, due_from: str | None = None,
        due_to: str | None = None, open_only: bool = True,
        sort: str = "effective_priority", direction: str = "desc",
        page_size: int = 25, cursor: str | None = None,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.query_action_inbox(actor, QueryActionInboxRequest(
                search, company_id, item_type, status, priority, created_from, created_to,
                due_from, due_to, open_only, sort, direction, page_size, cursor,
            ))
        except PermissionError as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/action-items/{item_id}", response_model=ActionItemResponse)
    async def get_action_item(
        item_id: str, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.get_action_item(actor, item_id)
        except (PermissionError, LookupError) as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error

    @app.post("/api/action-items/{item_id}/transitions", response_model=ActionItemResponse)
    async def transition_action_item(
        item_id: str, body: ActionItemTransitionBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.transition_action_item(actor, item_id, body.model_dump())
        except (PermissionError, LookupError) as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error
        except ValueError as error:
            code = 409 if str(error) in {"version_conflict", "idempotency_conflict"} else 422
            raise HTTPException(status_code=code, detail=str(error)) from error

    def thesis_error(error: Exception) -> HTTPException:
        code = str(error)
        if isinstance(error, (PermissionError, LookupError)):
            return HTTPException(status_code=404, detail="resource_unavailable")
        if code in {"version_conflict", "idempotency_conflict", "research_version_conflict"}:
            return HTTPException(status_code=409, detail=code)
        return HTTPException(status_code=422, detail=code)

    @app.post("/api/companies/{company_id}/theses", status_code=201, response_model=ThesisResponse)
    async def create_thesis(
        company_id: str, body: ThesisCreateBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.create_thesis(actor, company_id, body.model_dump())
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.get("/api/companies/{company_id}/theses", response_model=list[ThesisResponse])
    async def list_theses(
        company_id: str, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> list[dict[str, Any]]:
        try:
            return api.list_theses(actor, company_id)
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.get("/api/theses/{thesis_id}", response_model=ThesisResponse)
    async def get_thesis(
        thesis_id: str, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.get_thesis(actor, thesis_id)
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.put("/api/theses/{thesis_id}", response_model=ThesisResponse)
    async def save_thesis(
        thesis_id: str, body: ThesisSaveBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.save_thesis(actor, thesis_id, body.model_dump())
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/theses/{thesis_id}/transition-previews", response_model=ThesisTransitionPreviewResponse)
    async def preview_thesis_transition(
        thesis_id: str, body: ThesisTransitionPreviewBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.preview_thesis_transition(actor, thesis_id, body.model_dump())
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/theses/{thesis_id}/transitions", response_model=ThesisResponse)
    async def transition_thesis(
        thesis_id: str, body: ThesisTransitionBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.transition_thesis(actor, thesis_id, body.model_dump())
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/theses/{thesis_id}/outcomes", response_model=ThesisResponse)
    async def save_thesis_outcome(
        thesis_id: str, body: ThesisOutcomeBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            payload = body.model_dump()
            payload["observed_at"] = body.observed_at.isoformat()
            return api.save_thesis_outcome(actor, thesis_id, payload)
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.put("/api/theses/{thesis_id}/reflection-draft", response_model=ThesisResponse)
    async def autosave_thesis_reflection(
        thesis_id: str, body: ThesisReflectionDraftBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.autosave_thesis_reflection(actor, thesis_id, body.model_dump())
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/theses/{thesis_id}/reflections", response_model=ThesisResponse)
    async def complete_thesis_reflection(
        thesis_id: str, body: ThesisReflectionCompleteBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.complete_thesis_reflection(actor, thesis_id, body.model_dump())
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.get("/api/portfolio", response_model=PortfolioResponse)
    async def get_portfolio(
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.get_portfolio(actor)
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.put("/api/theses/{thesis_id}/valuation-draft", response_model=ThesisResponse)
    async def save_valuation_draft(
        thesis_id: str, body: ValuationDraftSaveBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.save_valuation_draft(actor, thesis_id, body.model_dump(mode="json"))
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post(
        "/api/theses/{thesis_id}/valuation-publication-previews",
        response_model=ValuationPublicationPreviewResponse,
    )
    async def preview_valuation_publication(
        thesis_id: str, body: ValuationPublicationPreviewBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.preview_valuation_publication(actor, thesis_id, body.model_dump())
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/theses/{thesis_id}/valuations", response_model=ThesisResponse)
    async def publish_valuation(
        thesis_id: str, body: ValuationPublicationBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.publish_valuation(actor, thesis_id, body.model_dump())
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.put("/api/portfolio/cost-profile", response_model=PortfolioResponse)
    async def save_cost_profile(
        body: CostProfileSaveBody, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.save_cost_profile(actor, body.model_dump(mode="json"))
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.put("/api/portfolio/investable-cash", response_model=PortfolioResponse)
    async def save_investable_cash(
        body: InvestableCashSaveBody, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.save_investable_cash(actor, body.model_dump(mode="json"))
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/portfolio/trade-previews", response_model=TradePreviewResponse)
    async def preview_portfolio_trade(
        body: TradePreviewBody, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.preview_portfolio_trade(actor, body.model_dump(mode="json"))
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/portfolio/csv-previews", response_model=CanonicalCsvPreviewResponse)
    async def preview_portfolio_csv(
        body: CanonicalCsvPreviewBody, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.preview_portfolio_csv(actor, body.content)
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/portfolio/trades", response_model=PortfolioResponse)
    async def confirm_portfolio_trade(
        body: TradeConfirmBody, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.confirm_portfolio_trade(actor, body.model_dump(mode="json"))
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/portfolio/trade-correction-previews", response_model=PortfolioMutationPreviewResponse)
    async def preview_portfolio_correction(
        body: TradeCorrectionPreviewBody, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.preview_portfolio_correction(actor, body.model_dump(mode="json"))
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/portfolio/trade-corrections", response_model=PortfolioResponse)
    async def confirm_portfolio_correction(
        body: TradeCorrectionConfirmBody, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.confirm_portfolio_correction(actor, body.model_dump(mode="json"))
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/portfolio/company-action-previews", response_model=PortfolioMutationPreviewResponse)
    async def preview_portfolio_company_action(
        body: CompanyActionPreviewBody, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.preview_portfolio_company_action(actor, body.model_dump(mode="json"))
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    @app.post("/api/portfolio/company-actions", response_model=PortfolioResponse)
    async def confirm_portfolio_company_action(
        body: CompanyActionConfirmBody, actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.confirm_portfolio_company_action(actor, body.model_dump(mode="json"))
        except (PermissionError, LookupError, ValueError) as error:
            raise thesis_error(error) from error

    if access_api is not None:
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
        from fastapi.encoders import jsonable_encoder

        @app.exception_handler(AccessProblem)
        async def access_problem_handler(_request: Request, error: AccessProblem) -> JSONResponse:
            return JSONResponse(status_code=404, content={"code": error.code})

        @app.exception_handler(RequestValidationError)
        async def access_validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
            access_prefixes = ("/api/session", "/api/admin/accounts", "/api/confirmation-challenges", "/api/confirmed-actions")
            if request.url.path.startswith(access_prefixes):
                return JSONResponse(status_code=422, content={"code": "invalid_request"})
            return JSONResponse(status_code=422, content={"detail": jsonable_encoder(error.errors())})

        def unavailable(_error: Exception) -> AccessProblem:
            return AccessProblem()

        @app.get("/api/session", response_model=SessionResponse, responses={404: {"model": ProblemResponse}})
        async def get_session(request: Request, actor: AuthenticatedActor = Depends(actor_provider), thesis_trace_session: str = Cookie(default="")) -> dict[str, Any]:
            try:
                bootstrapped = getattr(request.state, "access_session_profile", None)
                if bootstrapped is not None:
                    return bootstrapped
                return access_api.session_profile(actor, thesis_trace_session)
            except (PermissionError, LookupError, ValueError) as error:
                raise unavailable(error) from error

        @app.delete("/api/session", status_code=204, responses={404: {"model": ProblemResponse}})
        async def delete_session(response: Response, actor: AuthenticatedActor = Depends(actor_provider), thesis_trace_session: str = Cookie(default="")) -> None:
            try:
                access_api.logout(actor, thesis_trace_session)
                response.delete_cookie("thesis_trace_session", secure=True, httponly=True, samesite="strict")
            except (PermissionError, LookupError) as error:
                raise unavailable(error) from error

        @app.get("/api/admin/accounts", response_model=list[AccountResponse], responses={404: {"model": ProblemResponse}})
        async def list_accounts(actor: AuthenticatedActor = Depends(actor_provider)) -> list[dict[str, Any]]:
            try:
                return access_api.list_accounts(actor)
            except (PermissionError, LookupError) as error:
                raise unavailable(error) from error

        @app.get("/api/admin/accounts/{user_id}", response_model=AccountResponse, responses={404: {"model": ProblemResponse}})
        async def account_detail(user_id: str, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
            try:
                return access_api.get_account(actor, user_id)
            except (PermissionError, LookupError) as error:
                raise unavailable(error) from error

        @app.post("/api/admin/accounts", status_code=201, response_model=AccountResponse, responses={404: {"model": ProblemResponse}})
        async def create_account(body: AccountCreateBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
            try:
                return access_api.create_account(actor, body.model_dump())
            except (PermissionError, LookupError) as error:
                raise unavailable(error) from error

        @app.post("/api/confirmation-challenges", status_code=201, response_model=ConfirmationChallengeResponse, responses={404: {"model": ProblemResponse}})
        async def preview_confirmation(body: ConfirmationChallengeBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
            try:
                return access_api.preview_confirmation(actor, body.model_dump())
            except (PermissionError, LookupError, ValueError) as error:
                raise unavailable(error) from error

        @app.post("/api/confirmed-actions", response_model=ConfirmedActionResponse, responses={404: {"model": ProblemResponse}})
        async def confirm_action(body: ConfirmedActionBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
            try:
                return access_api.confirm_action(actor, body.model_dump())
            except (PermissionError, LookupError, ValueError) as error:
                raise unavailable(error) from error

    return app
