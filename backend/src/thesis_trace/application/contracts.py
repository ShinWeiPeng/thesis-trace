from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from enum import Enum
import hashlib
import json
from typing import Any, Callable, Protocol

from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.access.orchestration import AccessConfirmationService
from thesis_trace.modules.thesis.contracts import (
    CompleteReflectionCommand,
    CreateThesisCommand,
    SaveOutcomeCommand,
    SaveReflectionDraftCommand,
    SaveThesisCommand,
    SaveValuationDraftCommand,
    ThesisActorContext,
    ThesisRecord,
    ThesisResearchReference,
    ThesisStatus,
    TransitionThesisCommand,
    PublishValuationCommand,
    ValuationDraft,
    ValuationSample,
    PeerValuationMember,
    ValuationMethod,
)
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.modules.thesis.ports import ThesisStorePort
from thesis_trace.modules.thesis.valuation import (
    add_calendar_months_clamped,
    final_size_valuation_return,
    ValuationAbstained,
)
from thesis_trace.modules.portfolio.contracts import (
    CanonicalTrade,
    ConfirmTradeCommand,
    ConfirmTradeCorrectionCommand,
    ConfirmCompanyActionCommand,
    PortfolioActorContext,
    PortfolioRecord,
    PortfolioRecommendationSnapshot,
    PortfolioSnapshot,
    PreviewTradeCommand,
    SaveCostProfileCommand,
    SaveInvestableCashCommand,
    TradeAllocation,
    TradePreview,
    TradeSide,
)
from thesis_trace.modules.portfolio.policy import aggregate_exposure
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.modules.portfolio.ports import PortfolioStorePort
from thesis_trace.modules.portfolio.trades import parse_canonical_csv
from thesis_trace.modules.recommendation.contracts import (
    BoundRecommendationInput,
    RecommendationActor,
    RecommendationInputSnapshot,
    RecommendationRecord,
    RecommendationSource,
    RecommendationJob,
    OwnerDecision,
)
from thesis_trace.modules.recommendation.ports import RecommendationStorePort
from thesis_trace.modules.research import (
    ResearchActorContext,
    ResearchRecommendationFacade,
    ResearchRecommendationQueryPort,
)
from thesis_trace.modules.recommendation.service import RecommendationService
from thesis_trace.modules.workflow.contracts import (
    WorkflowActorContext,
    ActionSourceRef,
    CreateActionItemCommand,
)
from thesis_trace.modules.workflow.ports import ActionItemStorePort
from thesis_trace.modules.workflow.service import WorkflowService


@dataclass(frozen=True, slots=True)
class SubmitEvidenceRequest:
    actor: AuthenticatedActor
    company_id: str
    company_version: int
    url: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class InvestmentAnalysisRequest:
    input_id: str
    source_context: tuple[tuple[str, str], ...]
    candidate_text: str | None
    candidate_digest: str | None
    schema_version: str
    prompt_version: str
    model_version: str


@dataclass(frozen=True, slots=True)
class RecommendationAdmissionCommand:
    actor_id: str
    identity_version: int
    thesis_id: str
    expected_thesis_version: int
    valuation_id: str
    expected_valuation_version: int
    expected_portfolio_version: int
    benchmark_source: str
    source_selection_reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RecommendationPublicationCommand:
    job_id: str
    input_id: str
    input_digest: str
    actor_id: str
    thesis_id: str
    cycle: int
    lease_token: str
    lease_expires_at: datetime
    attempt: int
    versions: tuple[tuple[str, str], ...]
    raw_candidate: str
    raw_critic: str
    now: datetime


@dataclass(frozen=True, slots=True)
class RecommendationView:
    record_id: str
    version: int
    decision_status: str | None
    input_validity: str
    allowed_actions: tuple[str, ...]
    reason_codes: tuple[str, ...]
    decision_sequence: int = 0


@dataclass(frozen=True, slots=True)
class RecommendationFieldView:
    """Human-readable immutable metadata pair."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class RecommendationSourceView:
    """Frozen cited source facts; no mutable current-source substitution."""

    snapshot_id: str
    publisher: str
    excerpt: str
    url: str
    category: str | None
    lineage: str | None
    published_at: datetime | None
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class RecommendationClaimView:
    """Original candidate statement and exact citation identities."""

    text: str
    citations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecommendationDecisionHistoryView:
    """Append-only decision facts distinct from present validity."""

    sequence: int
    status: str
    reason: str
    recorded_at: datetime
    defer_until: datetime | None
    confirmation_id: str | None
    checks: tuple[RecommendationFieldView, ...]


@dataclass(frozen=True, slots=True)
class RecommendationRiskRow:
    """Frozen all-bucket concentration comparison; ratios are display-only strings."""

    dimension: str
    subject: str
    current_ratio: str
    projected_ratio: str | None
    limit_ratio: str


@dataclass(frozen=True, slots=True)
class RecommendationRequestView:
    """Owner-visible durable admission state without provider output."""

    request_id: str
    thesis_id: str
    status: str
    error_code: str | None
    submitted_at: datetime
    result_version: int | None


@dataclass(frozen=True, slots=True)
class RecommendationRequestPage:
    """Bounded stable-key page of Owner-visible requests."""

    items: tuple[RecommendationRequestView, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class RecommendationDetailView:
    """L0 read projection separates immutable recommendation and current validity."""

    view: RecommendationView
    company_id: str
    thesis_id: str
    thesis_title: str
    published_at: datetime
    checked_at: datetime
    direction: str
    publication_reasons: tuple[str, ...]
    raw_ceiling: str
    final_multiplier: str
    annualized_return: str | None
    minimum_return: str | None
    benchmark_source: str
    source_selection_reason: str
    valuation_id: str
    portfolio_snapshot_id: str | None
    sources: tuple[RecommendationSourceView, ...]
    claims: tuple[RecommendationClaimView, ...]
    decisions: tuple[RecommendationDecisionHistoryView, ...]
    next_decision_sequence: int | None
    facts: tuple[RecommendationFieldView, ...]
    risk: tuple[RecommendationRiskRow, ...]


@dataclass(frozen=True, slots=True)
class RecommendationDecisionCommand:
    actor_id: str
    identity_version: int
    record_id: str
    version: int
    expected_sequence: int
    target_status: str
    reason: str
    defer_until: datetime | None
    idempotency_key: str
    challenge_token: str | None = None


@dataclass(frozen=True, slots=True)
class RecommendationDecisionPreview:
    view: RecommendationView
    challenge_token: str | None
    expires_at: datetime | None
    impact_summary: str


class RecommendationTransactionPort(Protocol):
    def reconcile_one(self) -> bool: ...

    def preview_decision(
        self, command: RecommendationDecisionCommand
    ) -> RecommendationDecisionPreview: ...

    def decide(self, command: RecommendationDecisionCommand) -> RecommendationView: ...

    def admit(self, command: RecommendationAdmissionCommand) -> str: ...

    def publish(
        self, command: RecommendationPublicationCommand
    ) -> RecommendationView: ...


class RecommendationFlow:
    """Parent-owned source, financial, worker and atomic participant mappings."""

    @staticmethod
    def decision_command_digest(
        command: RecommendationDecisionCommand, *, system_expiry: bool = False
    ) -> str:
        if (
            not isinstance(command, RecommendationDecisionCommand)
            or any(
                not isinstance(value, str) or not value.strip() or len(value) > 1024
                for value in (
                    command.actor_id,
                    command.record_id,
                    command.idempotency_key,
                )
            )
            or any(
                type(value) is not int or value < 1
                for value in (command.version, command.identity_version)
            )
            or type(command.expected_sequence) is not int
            or command.expected_sequence < 0
            or command.target_status
            not in (
                {"expired"} if system_expiry else {"accepted", "rejected", "deferred"}
            )
            or not isinstance(command.reason, str)
            or len(command.reason) > 8192
            or (
                command.challenge_token is not None
                and (
                    not isinstance(command.challenge_token, str)
                    or len(command.challenge_token) > 1024
                )
            )
            or (
                command.defer_until is not None
                and (
                    not isinstance(command.defer_until, datetime)
                    or command.defer_until.utcoffset() is None
                )
            )
            or (command.target_status != "deferred" and command.defer_until is not None)
            or (
                command.target_status == "deferred"
                and command.challenge_token is not None
            )
        ):
            raise ValueError("invalid_decision_intent")
        payload = asdict(command)
        payload["challenge_token"] = (
            hashlib.sha256(command.challenge_token.encode()).hexdigest()
            if command.challenge_token is not None
            else None
        )
        return hashlib.sha256(
            RecommendationFlow._canonical(payload).encode()
        ).hexdigest()

    @staticmethod
    def expiry_command(
        actor: AuthenticatedActor, record_id: str, version: int, sequence: int
    ) -> RecommendationDecisionCommand:
        key = hashlib.sha256(
            RecommendationFlow._canonical(
                [
                    "recommendation-expiry-v1",
                    actor.actor_id,
                    record_id,
                    version,
                    sequence,
                ]
            ).encode()
        ).hexdigest()
        return RecommendationDecisionCommand(
            actor.actor_id,
            actor.identity_version,
            record_id,
            version,
            sequence,
            "expired",
            "",
            None,
            "expiry:" + key,
        )

    @staticmethod
    def decision_receipt(
        command: RecommendationDecisionCommand,
        store: RecommendationStorePort,
        *,
        system_expiry: bool = False,
    ) -> RecommendationView | None:
        decision = store.find_decision_receipt(
            command.actor_id,
            command.idempotency_key,
            RecommendationFlow.decision_command_digest(
                command, system_expiry=system_expiry
            ),
        )
        if decision is None:
            return None
        return RecommendationView(
            decision.recommendation_id,
            decision.recommendation_version,
            decision.status,
            "not_revalidated",
            (),
            ("receipt_replay",),
            decision.sequence,
        )

    @staticmethod
    def decision_source_ids(
        command: RecommendationDecisionCommand, store: RecommendationStorePort
    ) -> tuple[str, tuple[str, ...]]:
        record = store.get_record(command.actor_id, command.record_id, command.version)
        if record is None:
            raise LookupError("resource_unavailable")
        return record.inputs.thesis_id, tuple(
            sorted(
                {
                    bound.record_id.removeprefix("evidence:")
                    for bound in record.inputs.bindings
                    if bound.owner_domain == "research"
                    and bound.record_id.startswith("evidence:")
                }
            )
        )

    @staticmethod
    def _decision_payload(
        command: RecommendationDecisionCommand, record: RecommendationRecord
    ) -> str:
        payload = asdict(command)
        payload.pop("challenge_token")
        payload["bindings"] = [asdict(bound) for bound in record.inputs.bindings]
        return RecommendationFlow._canonical(payload)

    def _decision_state(
        self,
        command: RecommendationDecisionCommand,
        *,
        actor: AuthenticatedActor,
        store: RecommendationStorePort,
        now: datetime,
    ) -> tuple[
        RecommendationRecord,
        OwnerDecision | None,
        tuple[BoundRecommendationInput, ...],
        RecommendationView,
    ]:
        self._authorize_owner(actor)
        if (
            actor.actor_id != command.actor_id
            or actor.identity_version != command.identity_version
        ):
            raise PermissionError("resource_unavailable")
        record = store.get_record(actor.actor_id, command.record_id, command.version)
        if record is None or record.inputs.actor.actor_id != actor.actor_id:
            raise LookupError("resource_unavailable")
        previous = store.latest_decision(
            actor.actor_id, command.record_id, command.version
        )
        sequence = previous.sequence if previous else 0
        if command.expected_sequence != sequence:
            raise ValueError("version_conflict")
        current = self.current_bindings(actor, record.inputs, now=now)
        reasons = RecommendationService.expiry_reasons(
            record.inputs.bindings, current, now=now
        )
        actionable = record.direction in {"buy", "hold"} and (
            previous is None or previous.status == "deferred"
        )
        view = RecommendationView(
            record.recommendation_id,
            record.version,
            previous.status if previous else None,
            "invalid" if reasons else "valid",
            ("accept", "reject", "defer") if actionable and not reasons else (),
            reasons,
            sequence,
        )
        return record, previous, current, view

    def preview_decision(
        self,
        command: RecommendationDecisionCommand,
        *,
        actor: AuthenticatedActor,
        store: RecommendationStorePort,
        confirmations: AccessConfirmationService,
        now: datetime,
    ) -> RecommendationDecisionPreview:
        self.decision_command_digest(command)
        if command.challenge_token is not None:
            raise ValueError("invalid_decision_intent")
        record, previous, current, view = self._decision_state(
            command, actor=actor, store=store, now=now
        )
        impact = {
            "accepted": "接受這份建議並結束審查待辦；不會建立交易或扣除現金。",
            "rejected": "拒絕這份建議並結束審查待辦；保留建議與決策歷史。",
            "deferred": "延後審查待辦；不延長建議有效期間，也不會自動接受。",
        }[command.target_status]
        if not view.allowed_actions:
            return RecommendationDecisionPreview(view, None, None, impact)
        RecommendationService.plan_decision(
            actor=RecommendationActor(actor.actor_id, True),
            owner_id=actor.actor_id,
            recommendation_id=command.record_id,
            recommendation_version=command.version,
            previous=previous,
            expected_sequence=command.expected_sequence,
            bound=record.inputs.bindings,
            current=current,
            target_status=command.target_status,
            reason=command.reason,
            now=now,
            defer_until=command.defer_until,
        )
        if command.target_status == "deferred":
            return RecommendationDecisionPreview(view, None, None, impact)
        company = self._research.get_company(record.inputs.company_id)
        if company is None:
            raise LookupError("resource_unavailable")
        impact = (
            f"公司／證券：{company.ticker} · {company.name}（{company.company_id}）\n"
            f"目標建議：{record.recommendation_id} / v{record.version}\n"
            f"關聯 Thesis：{record.inputs.thesis_id} / 週期 {record.inputs.cycle}\n"
            f"動作：{'接受建議' if command.target_status == 'accepted' else '拒絕建議'}\n"
            f"決策狀態：{'已延後' if previous else '尚未決策'} → "
            f"{'已接受' if command.target_status == 'accepted' else '已拒絕'}\n"
            "審查待辦：結束；保留建議與決策歷史。\n"
            "交易與資金：不會建立交易、下單、保留或扣除現金。"
        )
        token, expires = confirmations.preview(
            actor,
            action="recommendation_" + command.target_status,
            target=command.record_id,
            version=command.version,
            payload=self._decision_payload(command, record),
            impact=impact,
        )
        return RecommendationDecisionPreview(view, token, expires, impact)

    def commit_decision(
        self,
        command: RecommendationDecisionCommand,
        *,
        actor: AuthenticatedActor,
        store: RecommendationStorePort,
        workflow_store: ActionItemStorePort,
        confirmations: AccessConfirmationService,
        now: datetime,
        clock: Callable[[], datetime],
        system_expiry: bool = False,
    ) -> RecommendationView:
        digest = self.decision_command_digest(command, system_expiry=system_expiry)
        record, previous, current, view = self._decision_state(
            command, actor=actor, store=store, now=now
        )
        if record.direction not in {"buy", "hold"}:
            raise ValueError("invalid_transition")
        decision = RecommendationService.plan_decision(
            actor=RecommendationActor(actor.actor_id, True),
            owner_id=actor.actor_id,
            recommendation_id=command.record_id,
            recommendation_version=command.version,
            previous=previous,
            expected_sequence=command.expected_sequence,
            bound=record.inputs.bindings,
            current=current,
            target_status=command.target_status,
            reason=command.reason,
            now=now,
            defer_until=command.defer_until,
        )
        if decision is None:
            if system_expiry:
                return view
            raise ValueError("invalid_transition")
        challenge_expires = None
        if decision.status in {"accepted", "rejected"}:
            if not command.challenge_token:
                raise PermissionError("challenge_invalid")
            challenge_id, challenge_expires = confirmations.consume(
                actor,
                token=command.challenge_token,
                action="recommendation_" + command.target_status,
                version=command.version,
                payload=self._decision_payload(command, record),
                reason=command.reason,
            )
            decision = replace(decision, confirmation_id=challenge_id)
        store.append_decision(
            decision,
            expected_sequence=command.expected_sequence,
            idempotency_key=command.idempotency_key,
            command_digest=digest,
        )
        WorkflowService(
            workflow_store,
            clock=lambda: now.isoformat(),
            id_generator=lambda: command.record_id,
        ).reconcile_recommendation(
            actor=WorkflowActorContext(actor.actor_id, False, True, True),
            source_record_id=command.record_id,
            source_version=command.version,
            decision_sequence=decision.sequence,
            decision_status=decision.status,
            reason=decision.reason,
            server_time=decision.recorded_at.isoformat(),
            defer_until=decision.defer_until.isoformat()
            if decision.defer_until
            else None,
        )
        final_now = clock()
        if decision.status != "expired" and RecommendationService.expiry_reasons(
            record.inputs.bindings, current, now=final_now
        ):
            raise ValueError("recommendation_expired_during_commit")
        if challenge_expires is not None and final_now >= challenge_expires:
            raise PermissionError("challenge_invalid")
        return replace(
            view,
            decision_status=decision.status,
            decision_sequence=decision.sequence,
            allowed_actions=("accept", "reject", "defer")
            if decision.status == "deferred"
            else (),
        )

    def __init__(
        self,
        thesis: ThesisService,
        portfolio: PortfolioService,
        research: ThesisResearchQueryPort,
        *,
        minimum_return: Decimal | None,
        minimum_return_policy_version: str,
        source_queries: ResearchRecommendationFacade | None = None,
        versions: tuple[tuple[str, str], ...] = (),
        store: RecommendationStorePort | None = None,
        transactions: RecommendationTransactionPort | None = None,
    ) -> None:
        self._thesis = thesis
        self._portfolio = portfolio
        self._research = research
        self._minimum_return = minimum_return
        self._minimum_return_policy_version = minimum_return_policy_version
        self._source_queries = source_queries
        self._versions = versions
        self._store = store
        self._transactions = transactions

    def with_runtime(
        self,
        store: RecommendationStorePort,
        transactions: RecommendationTransactionPort,
    ) -> RecommendationFlow:
        return RecommendationFlow(
            self._thesis,
            self._portfolio,
            self._research,
            minimum_return=self._minimum_return,
            minimum_return_policy_version=self._minimum_return_policy_version,
            source_queries=self._source_queries,
            versions=self._versions,
            store=store,
            transactions=transactions,
        )

    def request_status(
        self, actor: AuthenticatedActor, request_id: str
    ) -> RecommendationRequestView:
        self._authorize_owner(actor)
        if self._store is None:
            raise RuntimeError("recommendation_unavailable")
        result = self._store.get_request(actor.actor_id, request_id)
        if result is None:
            raise LookupError("resource_unavailable")
        return RecommendationRequestView(*result)

    def requests(
        self, actor: AuthenticatedActor, company_id: str, *, before: str | None = None
    ) -> RecommendationRequestPage:
        self._authorize_owner(actor)
        if self._store is None:
            raise RuntimeError("recommendation_unavailable")
        if self._research.get_company(company_id) is None:
            raise LookupError("resource_unavailable")
        rows = self._store.list_requests(
            actor.actor_id, company_id, before=before, limit=26
        )
        return RecommendationRequestPage(
            tuple(RecommendationRequestView(*row) for row in rows[:25]),
            rows[24][0] if len(rows) > 25 else None,
        )

    def request_recommendation(
        self,
        actor: AuthenticatedActor,
        company_id: str,
        command: RecommendationAdmissionCommand,
    ) -> RecommendationRequestView:
        self._authorize_owner(actor)
        if self._transactions is None:
            raise RuntimeError("recommendation_unavailable")
        if (
            command.actor_id != actor.actor_id
            or command.identity_version != actor.identity_version
        ):
            raise PermissionError("resource_unavailable")
        thesis = self._thesis.get(
            ThesisActorContext(actor.actor_id, True), command.thesis_id
        )
        if thesis.company_id != company_id:
            raise LookupError("resource_unavailable")
        return self.request_status(actor, self._transactions.admit(command))

    def decision_preview(
        self, actor: AuthenticatedActor, command: RecommendationDecisionCommand
    ) -> RecommendationDecisionPreview:
        self._authorize_owner(actor)
        if self._transactions is None:
            raise RuntimeError("recommendation_unavailable")
        if (
            command.actor_id != actor.actor_id
            or command.identity_version != actor.identity_version
        ):
            raise PermissionError("resource_unavailable")
        return self._transactions.preview_decision(command)

    def decide(
        self, actor: AuthenticatedActor, command: RecommendationDecisionCommand
    ) -> RecommendationView:
        self._authorize_owner(actor)
        if self._transactions is None:
            raise RuntimeError("recommendation_unavailable")
        if (
            command.actor_id != actor.actor_id
            or command.identity_version != actor.identity_version
        ):
            raise PermissionError("resource_unavailable")
        return self._transactions.decide(command)

    def detail(
        self,
        actor: AuthenticatedActor,
        record_id: str,
        version: int,
        *,
        now: datetime,
        before_sequence: int | None = None,
    ) -> RecommendationDetailView:
        self._authorize_owner(actor)
        if self._store is None:
            raise RuntimeError("recommendation_unavailable")
        if type(version) is not int or version < 1:
            raise ValueError("invalid_query")
        record = self._store.get_record(actor.actor_id, record_id, version)
        if record is None:
            raise LookupError("resource_unavailable")
        latest = self._store.latest_decision(actor.actor_id, record_id, version)
        sequence = latest.sequence if latest else 0
        _, _, _, view = self._decision_state(
            self.expiry_command(actor, record_id, version, sequence),
            actor=actor,
            store=self._store,
            now=now,
        )
        history = self._store.decision_history(
            actor.actor_id,
            record_id,
            version,
            limit=11,
            before_sequence=before_sequence,
        )
        history_page = history[-10:]
        next_sequence = history_page[0].sequence if len(history) > 10 else None
        decisions = []
        for decision in history_page:
            checks = []
            for identity, value in decision.input_checks:
                saved = json.loads(value)
                checks.append(
                    RecommendationFieldView(
                        identity,
                        f"v{saved['version']} · {saved['digest']} · 有效至 {saved.get('valid_until') or '依版本有效性'}",
                    )
                )
            decisions.append(
                RecommendationDecisionHistoryView(
                    decision.sequence,
                    decision.status,
                    decision.reason,
                    decision.recorded_at,
                    decision.defer_until,
                    decision.confirmation_id,
                    tuple(checks),
                )
            )
        thesis = self._thesis.get(
            ThesisActorContext(actor.actor_id, True), record.inputs.thesis_id
        )
        valuation = next(
            (
                item
                for item in thesis.valuation_snapshots
                if item.valuation_id == record.inputs.valuation_id
            ),
            None,
        )
        facts = [
            RecommendationFieldView(label, value)
            for label, value in record.provenance + record.calculation_trace
        ]
        if valuation is not None:
            draft = valuation.draft
            facts.extend(
                RecommendationFieldView(label, str(value))
                for label, value in (
                    ("估值版本", valuation.version),
                    ("估值方法", draft.method.value),
                    ("基準日", draft.basis_date),
                    ("估值期間（月）", draft.horizon_months),
                    ("Forecast 目標日", draft.validity.target_date),
                    ("估值有效至", draft.validity.expires_at),
                    ("分位選擇", draft.benchmark_variant),
                    (
                        "公司歷史中位數",
                        draft.company_history.distribution.median
                        if draft.company_history
                        else "不可用",
                    ),
                    (
                        "公司歷史 P75",
                        draft.company_history.distribution.p75
                        if draft.company_history
                        else "不可用",
                    ),
                    (
                        "同儕中位數",
                        draft.peer_group.distribution.median
                        if draft.peer_group
                        else "不可用",
                    ),
                    (
                        "同儕 P75",
                        draft.peer_group.distribution.p75
                        if draft.peer_group
                        else "不可用",
                    ),
                )
            )
        risk_rows = []
        risk = (
            self._portfolio.get_recommendation_snapshot(
                PortfolioActorContext(actor.actor_id, True),
                record.inputs.portfolio_snapshot_id,
            )
            if record.inputs.portfolio_snapshot_id
            else None
        )
        if risk is not None:
            facts.extend(
                RecommendationFieldView(label, str(value))
                for label, value in (
                    ("風險快照日期", risk.created_at),
                    ("投資組合版本", risk.portfolio.version),
                    ("成本設定版本", risk.cost.version),
                    ("現金資料日期", risk.cash_as_of),
                    ("可投資現金", risk.portfolio.cash),
                    ("全桶淨值", risk.exposure.nav),
                    ("試算買入流出", risk.sizing.purchase_outflow),
                    ("試算買入股數", risk.sizing.acquired_quantity),
                )
            )
            for dimension, field, cap in (
                ("個股", "security_exposure", "0.1"),
                ("產業", "industry_exposure", "0.3"),
                ("主題", "theme_exposure", "0.3"),
            ):
                before = getattr(risk.exposure, field)
                after = (
                    getattr(risk.sizing.post_exposure, field)
                    if risk.sizing.post_exposure is not None
                    else None
                )
                for subject in sorted(set(before) | set(after or {})):
                    risk_rows.append(
                        RecommendationRiskRow(
                            dimension,
                            subject,
                            str(before.get(subject, Decimal(0))),
                            str(after.get(subject, Decimal(0)))
                            if after is not None
                            else None,
                            cap,
                        )
                    )
        else:
            facts.append(RecommendationFieldView("風險快照", "不可用；不重建歷史數值"))
        return RecommendationDetailView(
            view=view,
            company_id=record.inputs.company_id,
            thesis_id=record.inputs.thesis_id,
            thesis_title=thesis.title,
            published_at=record.published_at,
            checked_at=now,
            direction=record.direction,
            publication_reasons=record.reasons,
            raw_ceiling=str(record.candidate.raw_dca_ceiling),
            final_multiplier=str(record.final_multiplier),
            annualized_return=str(record.annualized_return)
            if record.annualized_return is not None
            else None,
            minimum_return=str(record.minimum_return)
            if record.minimum_return is not None
            else None,
            benchmark_source=record.inputs.benchmark_source,
            source_selection_reason=record.inputs.source_selection_reason,
            valuation_id=record.inputs.valuation_id,
            portfolio_snapshot_id=record.inputs.portfolio_snapshot_id,
            sources=tuple(
                RecommendationSourceView(
                    item.snapshot_id,
                    item.publisher,
                    item.excerpt,
                    item.canonical_url,
                    item.source_category,
                    item.lineage,
                    item.published_at,
                    item.retrieved_at,
                )
                for item in record.inputs.sources
            ),
            claims=tuple(
                RecommendationClaimView(text, citations)
                for text, citations in record.candidate.claims
            ),
            decisions=tuple(decisions),
            next_decision_sequence=next_sequence,
            facts=tuple(facts),
            risk=tuple(risk_rows),
        )

    @staticmethod
    def admission_command_digest(command: RecommendationAdmissionCommand) -> str:
        if (
            not isinstance(command, RecommendationAdmissionCommand)
            or any(
                type(value) is not int or value < 1
                for value in (
                    command.identity_version,
                    command.expected_thesis_version,
                    command.expected_valuation_version,
                    command.expected_portfolio_version,
                )
            )
            or any(
                not isinstance(value, str) or not value.strip()
                for value in (
                    command.actor_id,
                    command.thesis_id,
                    command.valuation_id,
                    command.source_selection_reason,
                    command.idempotency_key,
                )
            )
            or command.benchmark_source
            not in {"company_history", "peer_group", "abstain"}
        ):
            raise ValueError("invalid_admission_intent")
        raw = RecommendationFlow._canonical(asdict(command)).encode("utf-8")
        if len(raw) > 262144:
            raise ValueError("input_too_large")
        return hashlib.sha256(raw).hexdigest()

    def admission_source_ids(
        self, command: RecommendationAdmissionCommand
    ) -> tuple[str, ...]:
        thesis = self._thesis.get(
            ThesisActorContext(command.actor_id, True), command.thesis_id
        )
        if thesis.version != command.expected_thesis_version:
            raise ValueError("version_conflict")
        valuation = next(
            (
                item
                for item in thesis.valuation_snapshots
                if item.valuation_id == command.valuation_id
                and item.version == command.expected_valuation_version
            ),
            None,
        )
        if valuation is None:
            raise ValueError("valuation_version_conflict")
        references = list(thesis.evidence_refs)
        if valuation.draft.forecast_source is not None:
            references.append(valuation.draft.forecast_source)
        for benchmark in (valuation.draft.company_history, valuation.draft.peer_group):
            if benchmark is not None:
                references.extend(sample.source for sample in benchmark.valid_samples)
        return tuple(sorted({reference.record_id for reference in references}))

    def commit_admission(
        self,
        command: RecommendationAdmissionCommand,
        *,
        actor: AuthenticatedActor,
        store: RecommendationStorePort,
        input_id: str,
        job_id: str,
        portfolio_snapshot_id: str,
        now: datetime,
    ) -> str:
        self._authorize_owner(actor)
        if (
            actor.actor_id != command.actor_id
            or actor.identity_version != command.identity_version
        ):
            raise PermissionError("resource_unavailable")
        frozen = self.prepare_inputs(
            actor=actor,
            thesis_id=command.thesis_id,
            expected_thesis_version=command.expected_thesis_version,
            valuation_id=command.valuation_id,
            expected_valuation_version=command.expected_valuation_version,
            expected_portfolio_version=command.expected_portfolio_version,
            benchmark_source=command.benchmark_source,
            source_selection_reason=command.source_selection_reason,
            portfolio_snapshot_id=portfolio_snapshot_id,
            now=now,
        )
        return store.admit(
            inputs=frozen,
            input_id=input_id,
            job_id=job_id,
            versions=self._versions,
            idempotency_key=command.idempotency_key,
            command_digest=self.admission_command_digest(command),
        )

    def with_stores(
        self,
        thesis_store: ThesisStorePort,
        portfolio_store: PortfolioStorePort,
        research: ThesisResearchQueryPort,
        source_queries: ResearchRecommendationQueryPort,
    ) -> RecommendationFlow:
        return RecommendationFlow(
            self._thesis.with_store(thesis_store),
            self._portfolio.with_store(portfolio_store),
            research,
            minimum_return=self._minimum_return,
            minimum_return_policy_version=self._minimum_return_policy_version,
            source_queries=ResearchRecommendationFacade(source_queries),
            versions=self._versions,
        )

    @staticmethod
    def _publication_job(
        command: RecommendationPublicationCommand,
    ) -> RecommendationJob:
        return RecommendationJob(
            command.job_id,
            command.input_id,
            command.input_digest,
            command.actor_id,
            command.thesis_id,
            command.cycle,
            command.lease_token,
            command.lease_expires_at,
            command.attempt,
            command.versions,
        )

    @staticmethod
    def publication_source_ids(
        command: RecommendationPublicationCommand, store: RecommendationStorePort
    ) -> tuple[str, ...]:
        frozen = store.load_job_input(RecommendationFlow._publication_job(command))
        if (
            frozen.actor.actor_id != command.actor_id
            or frozen.thesis_id != command.thesis_id
            or frozen.cycle != command.cycle
        ):
            raise ValueError("input_digest_conflict")
        return tuple(
            sorted(
                {
                    bound.record_id.removeprefix("evidence:")
                    for bound in frozen.bindings
                    if bound.owner_domain == "research"
                    and bound.record_id.startswith("evidence:")
                }
            )
        )

    def commit_publication(
        self,
        command: RecommendationPublicationCommand,
        *,
        actor: AuthenticatedActor,
        store: RecommendationStorePort,
        portfolio_store: PortfolioStorePort,
        workflow_store: ActionItemStorePort,
        now: datetime,
        clock: Callable[[], datetime],
    ) -> RecommendationView:
        """Map owner participants already fenced/bound by the concrete transaction."""
        self._authorize_owner(actor)
        if actor.actor_id != command.actor_id or sorted(command.versions) != sorted(
            self._versions
        ):
            raise ValueError("input_digest_conflict")
        job = self._publication_job(command)
        frozen = store.load_job_input(job)
        if (
            RecommendationService.admission_digest(frozen, command.versions)
            != command.input_digest
        ):
            raise ValueError("input_digest_conflict")
        current = self.current_bindings(actor, frozen, now=now)
        if RecommendationService.expiry_reasons(frozen.bindings, current, now=now):
            raise ValueError("superseded_inputs")
        expected_portfolio = next(
            (
                bound.version
                for bound in frozen.bindings
                if bound.owner_domain == "portfolio"
                and bound.record_id == actor.actor_id
            ),
            None,
        )
        if expected_portfolio is None:
            raise ValueError("input_validity_unavailable")
        record, risk = self.plan_publication(
            actor=actor,
            recommendation_id=command.input_id,
            version=1,
            inputs=frozen,
            current=current,
            expected_portfolio_version=expected_portfolio,
            raw_candidate=command.raw_candidate,
            raw_critic=command.raw_critic,
            provenance=command.versions,
            now=now,
        )
        actual_policies = {
            "minimum_return_policy": self._minimum_return_policy_version,
            "risk_policy": risk.exposure.policy_version,
            "cost_profile_policy": risk.cost.policy_version,
            "sizing_policy": risk.sizing.policy_version,
        }
        trace = dict(record.calculation_trace)
        if "return_policy" in trace:
            actual_policies["return_policy"] = trace["return_policy"]
        if any(
            dict(command.versions).get(key) != value
            for key, value in actual_policies.items()
        ):
            raise ValueError("publication_rejected")
        portfolio_store.append_recommendation_snapshot(actor.actor_id, risk)
        store.append_record(record)
        if record.direction in {"buy", "hold"}:
            company = self._research.get_company(record.inputs.company_id)
            if company is None:
                raise LookupError("resource_unavailable")
            workflow = WorkflowService(
                workflow_store,
                clock=lambda: now.isoformat(),
                id_generator=lambda: "recommendation:"
                + record.recommendation_id
                + ":"
                + str(record.version),
            )
            workflow.create(
                CreateActionItemCommand(
                    WorkflowActorContext(actor.actor_id, True, True, True),
                    ActionSourceRef(
                        "recommendation",
                        record.recommendation_id,
                        record.version,
                        actor.actor_id,
                        company.company_id,
                        company.ticker,
                        company.name,
                        WorkflowService.RECOMMENDATION_RULE_VERSION,
                        record.direction,
                    ),
                    "請審查投資建議並記錄 Owner 決策。",
                    None,
                    "recommendation-publication:"
                    + record.recommendation_id
                    + ":"
                    + str(record.version),
                )
            )
        if RecommendationService.expiry_reasons(frozen.bindings, current, now=clock()):
            raise ValueError("superseded_inputs")
        store.finish_job(job)
        return RecommendationView(
            record.recommendation_id,
            record.version,
            None,
            "valid",
            ("accept", "reject", "defer")
            if record.direction in {"buy", "hold"}
            else (),
            record.reasons,
        )

    @staticmethod
    def process_one(
        *,
        store: RecommendationStorePort,
        provider: Callable[[InvestmentAnalysisRequest], str],
        critic: Callable[[InvestmentAnalysisRequest], str],
        transactions: RecommendationTransactionPort,
        versions: tuple[tuple[str, str], ...],
        clock: Callable[[], datetime],
    ) -> bool:
        job = store.claim_job()
        if job is None:
            return False
        stage = "input"
        try:
            frozen = store.load_job_input(job)
            if (
                sorted(job.versions) != sorted(versions)
                or frozen.actor.actor_id != job.actor_id
                or frozen.thesis_id != job.thesis_id
                or frozen.cycle != job.cycle
                or RecommendationService.admission_digest(frozen, job.versions)
                != job.input_digest
            ):
                raise ValueError("input_digest_conflict")
            admitted = dict(job.versions)
            context = dict(frozen.analysis_context)
            source_context = (
                ("thesis", context["thesis"]),
                ("conditions", context["conditions"]),
                ("valuation", context["valuation"]),
                (
                    "sources",
                    RecommendationFlow._canonical(
                        [asdict(source) for source in frozen.sources]
                    ),
                ),
            )
            request = InvestmentAnalysisRequest(
                job.input_id,
                source_context,
                None,
                None,
                admitted["candidate_schema"],
                admitted["prompt"],
                admitted["model"],
            )
            stage = "provider"
            raw_candidate = provider(request)
            candidate = RecommendationService.validate_candidate(
                raw_candidate, sources=frozen.sources, now=clock()
            )
            stage = "lease"
            job = store.renew_job(job)
            stage = "critic"
            raw_critic = critic(
                replace(
                    request,
                    candidate_text=raw_candidate,
                    candidate_digest=candidate.digest,
                    schema_version=admitted["critic_schema"],
                    prompt_version=admitted["critic_prompt"],
                    model_version=admitted["critic_model"],
                )
            )
            if not RecommendationService.validate_critic(
                raw_critic, candidate=candidate
            ):
                raise ValueError("critic_rejected")
            stage = "lease"
            job = store.renew_job(job)
            stage = "publication"
            transactions.publish(
                RecommendationPublicationCommand(
                    job.job_id,
                    job.input_id,
                    job.input_digest,
                    job.actor_id,
                    job.thesis_id,
                    job.cycle,
                    job.lease_token,
                    job.lease_expires_at,
                    job.attempt,
                    job.versions,
                    raw_candidate,
                    raw_critic,
                    clock(),
                )
            )
        except (ValueError, PermissionError, LookupError, RuntimeError) as error:
            code = str(error)
            if code == "lease_unavailable":
                return True
            if code == "invalid_output":
                code = "invalid_critic" if stage == "critic" else "invalid_candidate"
            known = {
                "provider_transport_failure",
                "critic_transport_failure",
                "provider_unavailable",
                "invalid_candidate",
                "invalid_candidate_sources",
                "invalid_critic",
                "critic_rejected",
                "superseded_inputs",
                "resource_unavailable",
                "input_digest_conflict",
                "input_too_large",
                "publication_rejected",
            }
            if code not in known:
                # Unknown database/runtime failures are not content failures. Let the lease
                # recover; redact unknown errors only from the untrusted provider boundary.
                if stage not in {"provider", "critic"}:
                    raise
                code = "provider_unavailable"
            try:
                store.fail_job(
                    job,
                    error_code=code,
                    transient=code
                    in {"provider_transport_failure", "critic_transport_failure"},
                )
            except ValueError as lease_error:
                if str(lease_error) != "lease_unavailable":
                    raise
        return True

    @staticmethod
    def _canonical(value: Any) -> str:
        def encode(item):
            if isinstance(item, datetime):
                if item.utcoffset() is None:
                    raise ValueError("input_validity_unavailable")
                return item.astimezone(timezone.utc).isoformat()
            if isinstance(item, date):
                return item.isoformat()
            if isinstance(item, Decimal):
                if not item.is_finite():
                    raise ValueError("input_validity_unavailable")
                sign, digits, exponent = item.as_tuple()
                digits = list(digits)
                if not any(digits):
                    return "0e0"
                while digits[-1] == 0:
                    digits.pop()
                    exponent += 1
                return (
                    ("-" if sign else "")
                    + "".join(str(digit) for digit in digits)
                    + "e"
                    + str(exponent)
                )
            if isinstance(item, Enum):
                return item.value
            raise ValueError("input_validity_unavailable")

        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=encode,
        )

    @classmethod
    def _binding(
        cls,
        owner: str,
        key: str,
        version: int,
        value: Any,
        valid_until: datetime | None = None,
    ) -> BoundRecommendationInput:
        return BoundRecommendationInput(
            owner,
            key,
            version,
            hashlib.sha256(cls._canonical(value).encode()).hexdigest(),
            valid_until,
        )

    @staticmethod
    def _authorize_owner(actor: AuthenticatedActor) -> None:
        if actor.role is not Role.OWNER or not actor.actor_id:
            raise PermissionError("resource_unavailable")

    @classmethod
    def _thesis_binding(cls, thesis: ThesisRecord) -> BoundRecommendationInput:
        return cls._binding(
            "thesis",
            "cycle:" + thesis.thesis_id,
            thesis.cycle,
            {
                "company": thesis.company_id,
                "cycle": thesis.cycle,
                "status": thesis.status,
                "narrative": thesis.narrative,
                "conditions": [asdict(item) for item in thesis.conditions],
                "evidence": [asdict(item) for item in thesis.evidence_refs],
            },
        )

    @classmethod
    def _valuation_binding(cls, thesis: ThesisRecord) -> BoundRecommendationInput:
        if not thesis.valuation_snapshots:
            raise LookupError("resource_unavailable")
        valuation = max(thesis.valuation_snapshots, key=lambda item: item.version)
        return cls._binding(
            "thesis",
            "valuation:" + thesis.thesis_id,
            valuation.version,
            asdict(valuation),
            valuation.draft.validity.expires_at,
        )

    def _runtime_binding(self) -> BoundRecommendationInput:
        return self._binding(
            "runtime",
            "recommendation-policy",
            1,
            {
                "versions": dict(self._versions),
                "minimum_return": self._minimum_return,
                "minimum_return_policy": self._minimum_return_policy_version,
            },
        )

    def _portfolio_binding(
        self, actor: AuthenticatedActor, thesis: ThesisRecord, now: datetime
    ) -> BoundRecommendationInput:
        current = self._portfolio.get(PortfolioActorContext(actor.actor_id, True))
        if current.cost_profile is None:
            raise ValueError("portfolio_prerequisites_missing")
        if not thesis.valuation_snapshots:
            raise LookupError("resource_unavailable")
        valuation = max(thesis.valuation_snapshots, key=lambda item: item.version)
        company = self._research.get_company(thesis.company_id)
        if company is None:
            raise LookupError("resource_unavailable")
        with localcontext() as context:
            context.prec = max(
                28,
                len(valuation.draft.quantity.as_tuple().digits)
                + len(valuation.draft.buy_price.as_tuple().digits),
            )
            base_amount = valuation.draft.quantity * valuation.draft.buy_price
        risk = self._portfolio.prepare_recommendation_snapshot(
            PortfolioActorContext(actor.actor_id, True),
            snapshot_id="binding-only",
            expected_version=current.version,
            cost_profile_version=current.cost_profile.version,
            security_id=company.ticker,
            base_amount=base_amount,
            buy_price=valuation.draft.buy_price,
            raw_ceiling=Decimal(0),
            now=now,
        )
        return self._binding(
            "portfolio",
            actor.actor_id,
            current.version,
            {
                "portfolio": asdict(risk.portfolio),
                "cash_as_of": risk.cash_as_of,
                "cost": asdict(risk.cost),
                "target": asdict(risk.target),
            },
        )

    def prepare_inputs(
        self,
        *,
        actor: AuthenticatedActor,
        thesis_id: str,
        expected_thesis_version: int,
        valuation_id: str,
        expected_valuation_version: int,
        expected_portfolio_version: int,
        benchmark_source: str,
        source_selection_reason: str,
        portfolio_snapshot_id: str,
        now: datetime,
    ) -> RecommendationInputSnapshot:
        """Resolve owner data only; the caller must lock and atomically admit this plan."""
        self._authorize_owner(actor)
        if any(
            type(value) is not int or value < 1
            for value in (
                expected_thesis_version,
                expected_valuation_version,
                expected_portfolio_version,
            )
        ):
            raise ValueError("invalid_admission_intent")
        if self._source_queries is None:
            raise ValueError("recommendation_queries_unavailable")
        thesis = self._thesis.get(ThesisActorContext(actor.actor_id, True), thesis_id)
        if thesis.version != expected_thesis_version:
            raise ValueError("version_conflict")
        if thesis.status is not ThesisStatus.ACTIVE or not any(
            item.active for item in thesis.conditions
        ):
            raise ValueError("active_thesis_required")
        if not thesis.valuation_snapshots:
            raise ValueError("published_valuation_required")
        valuation = max(thesis.valuation_snapshots, key=lambda item: item.version)
        if (valuation.valuation_id, valuation.version) != (
            valuation_id,
            expected_valuation_version,
        ):
            raise ValueError("valuation_version_conflict")
        if valuation.draft.benchmark_source != benchmark_source:
            raise ValueError("valuation_source_selection_conflict")
        if now >= valuation.draft.validity.expires_at:
            raise ValueError("forecast_expired")
        company = self._research.get_company(thesis.company_id)
        if company is None:
            raise LookupError("resource_unavailable")
        portfolio_binding = self._portfolio_binding(actor, thesis, now)
        if portfolio_binding.version != expected_portfolio_version:
            raise ValueError("portfolio_version_conflict")
        bindings = [
            self._thesis_binding(thesis),
            self._valuation_binding(thesis),
            portfolio_binding,
            self._runtime_binding(),
            self._binding(
                "research",
                "company:" + company.company_id,
                company.version,
                {
                    "id": company.company_id,
                    "ticker": company.ticker,
                    "name": company.name,
                },
            ),
        ]
        financial_refs = []
        if valuation.draft.forecast_source is not None:
            financial_refs.append(valuation.draft.forecast_source)
        for benchmark in (valuation.draft.company_history, valuation.draft.peer_group):
            if benchmark is not None:
                financial_refs.extend(item.source for item in benchmark.valid_samples)
        if any(not reference.fact_id for reference in financial_refs):
            raise ValueError("valuation_source_invalid")
        source_values = {}
        evidence_sources = {}
        research_actor = ResearchActorContext(actor.actor_id, False, True)
        for reference in dict.fromkeys((*thesis.evidence_refs, *financial_refs)):
            if reference.record_type != "evidence":
                raise ValueError("research_reference_invalid")
            if reference.record_id not in evidence_sources:
                evidence_sources[reference.record_id] = self._source_queries.get_source(
                    research_actor, reference.record_id
                )
            source = evidence_sources[reference.record_id]
            if (source.evidence.version, source.evidence.company_id) != (
                reference.version,
                reference.company_id,
            ):
                raise ValueError("research_version_conflict")
            mapped_source = RecommendationSource(
                source.snapshot_id,
                source.publisher,
                source.excerpt,
                source.canonical_url,
                source.published_at,
                source.observed_at,
                source.retrieved_at,
                source.source_category,
                source.lineage,
            )
            if (
                source.snapshot_id in source_values
                and source_values[source.snapshot_id] != mapped_source
            ):
                raise ValueError("invalid_candidate_sources")
            source_values[source.snapshot_id] = mapped_source
            value = {
                key: item
                for key, item in asdict(source).items()
                if not key.startswith("stage")
            }
            bindings.append(
                self._binding(
                    "research",
                    "evidence:" + reference.record_id,
                    source.evidence.version,
                    value,
                )
            )
            bindings.append(
                self._binding(
                    "research",
                    "stage:" + reference.record_id,
                    source.stage_version or 1,
                    {
                        "version": source.stage_version,
                        "stage": source.stage,
                        "source": source.stage_source_id,
                        "digest": source.stage_digest,
                    },
                )
            )
        for reference in dict.fromkeys(financial_refs):
            fact, digest = self._source_queries.get_fact_binding(
                research_actor, reference.record_id, reference.fact_id
            )
            if (fact.version, fact.company_id) != (
                reference.version,
                reference.company_id,
            ):
                raise ValueError("research_version_conflict")
            bindings.append(
                self._binding(
                    "research",
                    "fact:"
                    + json.dumps(
                        [reference.record_id, reference.fact_id], separators=(",", ":")
                    ),
                    fact.version,
                    digest,
                )
            )
        unique = {(item.owner_domain, item.record_id): item for item in bindings}
        context = (
            ("thesis", thesis.narrative),
            (
                "conditions",
                self._canonical(
                    [asdict(item) for item in thesis.conditions if item.active]
                ),
            ),
            ("thesis_record_version", str(thesis.version)),
            (
                "valuation",
                self._canonical(
                    {
                        "id": valuation.valuation_id,
                        "version": valuation.version,
                        "company_id": company.company_id,
                        "ticker": company.ticker,
                        "company_name": company.name,
                        "method": valuation.draft.method,
                        "source": valuation.draft.benchmark_source,
                        "variant": valuation.draft.benchmark_variant,
                        "target_date": valuation.draft.validity.target_date,
                        "forecast": valuation.draft.forecast,
                        "distribution": None
                        if valuation.draft.distribution is None
                        else asdict(valuation.draft.distribution),
                    }
                ),
            ),
        )
        frozen = RecommendationInputSnapshot(
            RecommendationActor(actor.actor_id, True),
            thesis_id,
            thesis.cycle,
            tuple(unique[key] for key in sorted(unique)),
            tuple(source_values[key] for key in sorted(source_values)),
            valuation_id,
            portfolio_snapshot_id,
            source_selection_reason,
            (),
            thesis.company_id,
            benchmark_source,
            now,
            context,
        )
        RecommendationService.admission_digest(frozen, self._versions)
        return frozen

    def current_bindings(
        self,
        actor: AuthenticatedActor,
        inputs: RecommendationInputSnapshot,
        *,
        now: datetime,
    ) -> tuple[BoundRecommendationInput, ...]:
        """Read current owner projections; known absence differs from a failed query."""
        self._authorize_owner(actor)
        if actor.actor_id != inputs.actor.actor_id or self._source_queries is None:
            raise PermissionError("resource_unavailable")
        thesis = self._thesis.get(
            ThesisActorContext(actor.actor_id, True), inputs.thesis_id
        )
        research_actor = ResearchActorContext(actor.actor_id, False, True)
        result = []
        sources = {}
        for bound in inputs.bindings:
            try:
                if (
                    bound.owner_domain == "thesis"
                    and bound.record_id == "cycle:" + inputs.thesis_id
                ):
                    current = self._thesis_binding(thesis)
                elif (
                    bound.owner_domain == "thesis"
                    and bound.record_id == "valuation:" + inputs.thesis_id
                ):
                    current = self._valuation_binding(thesis)
                elif (
                    bound.owner_domain == "portfolio"
                    and bound.record_id == actor.actor_id
                ):
                    current = self._portfolio_binding(actor, thesis, now)
                elif (
                    bound.owner_domain == "runtime"
                    and bound.record_id == "recommendation-policy"
                ):
                    current = self._runtime_binding()
                elif bound.owner_domain == "research":
                    kind, identifier = bound.record_id.split(":", 1)
                    if kind == "company":
                        company = self._research.get_company(identifier)
                        if company is None:
                            raise LookupError("resource_unavailable")
                        current = self._binding(
                            "research",
                            bound.record_id,
                            company.version,
                            {
                                "id": company.company_id,
                                "ticker": company.ticker,
                                "name": company.name,
                            },
                        )
                    elif kind == "fact":
                        evidence_id, fact_id = json.loads(identifier)
                        fact, digest = self._source_queries.get_fact_binding(
                            research_actor, evidence_id, fact_id
                        )
                        current = self._binding(
                            "research", bound.record_id, fact.version, digest
                        )
                    elif kind in ("evidence", "stage"):
                        if identifier not in sources:
                            sources[identifier] = self._source_queries.get_source(
                                research_actor, identifier
                            )
                        source = sources[identifier]
                        if kind == "evidence":
                            current = self._binding(
                                "research",
                                bound.record_id,
                                source.evidence.version,
                                {
                                    key: item
                                    for key, item in asdict(source).items()
                                    if not key.startswith("stage")
                                },
                            )
                        else:
                            current = self._binding(
                                "research",
                                bound.record_id,
                                source.stage_version or 1,
                                {
                                    "version": source.stage_version,
                                    "stage": source.stage,
                                    "source": source.stage_source_id,
                                    "digest": source.stage_digest,
                                },
                            )
                    else:
                        raise ValueError("input_validity_unavailable")
                else:
                    raise ValueError("input_validity_unavailable")
            except LookupError:
                current = self._binding(
                    bound.owner_domain,
                    bound.record_id,
                    bound.version,
                    {"unavailable": "missing_current_record"},
                )
            except ValueError as error:
                if str(error) not in {
                    "official_security_invalid",
                    "official_security_missing",
                    "portfolio_prerequisites_missing",
                    "cost_profile_not_effective",
                    "invalid_cash",
                }:
                    raise
                current = self._binding(
                    bound.owner_domain,
                    bound.record_id,
                    bound.version,
                    {"unavailable": str(error)},
                )
            result.append(current)
        return tuple(result)

    def plan_publication(
        self,
        *,
        actor: AuthenticatedActor,
        recommendation_id: str,
        version: int,
        inputs: RecommendationInputSnapshot,
        current: tuple[BoundRecommendationInput, ...],
        expected_portfolio_version: int,
        raw_candidate: str,
        raw_critic: str,
        provenance: tuple[tuple[str, str], ...],
        now: datetime,
    ) -> tuple[RecommendationRecord, PortfolioRecommendationSnapshot]:
        if actor.role is not Role.OWNER or actor.actor_id != inputs.actor.actor_id:
            raise ValueError("resource_unavailable")
        thesis = self._thesis.get(
            ThesisActorContext(actor.actor_id, True), inputs.thesis_id
        )
        if thesis.company_id != inputs.company_id:
            raise ValueError("resource_unavailable")
        if thesis.cycle != inputs.cycle or thesis.status is not ThesisStatus.ACTIVE:
            raise ValueError("superseded_inputs")
        company = self._research.get_company(thesis.company_id)
        if (
            company is None
            or company.company_id != thesis.company_id
            or not company.ticker
        ):
            raise ValueError("resource_unavailable")
        valuation = next(
            (
                item
                for item in thesis.valuation_snapshots
                if item.valuation_id == inputs.valuation_id
            ),
            None,
        )
        if valuation is None:
            raise ValueError("resource_unavailable")
        if valuation.draft.benchmark_source != inputs.benchmark_source:
            raise ValueError("valuation_source_selection_conflict")
        candidate = RecommendationService.validate_candidate(
            raw_candidate, sources=inputs.sources, now=now
        )
        if not RecommendationService.validate_critic(raw_critic, candidate=candidate):
            raise ValueError("critic_rejected")
        if not inputs.portfolio_snapshot_id:
            raise ValueError("portfolio_snapshot_unavailable")
        with localcontext() as context:
            context.prec = max(
                28,
                len(valuation.draft.quantity.as_tuple().digits)
                + len(valuation.draft.buy_price.as_tuple().digits),
            )
            base_amount = valuation.draft.quantity * valuation.draft.buy_price
        risk = self._portfolio.prepare_recommendation_snapshot(
            PortfolioActorContext(actor.actor_id, True),
            snapshot_id=inputs.portfolio_snapshot_id,
            expected_version=expected_portfolio_version,
            cost_profile_version=valuation.draft.cost_profile_version,
            security_id=company.ticker,
            base_amount=base_amount,
            buy_price=valuation.draft.buy_price,
            raw_ceiling=candidate.raw_dca_ceiling,
            now=now,
        )
        reasons = list(inputs.gate_reasons)
        reasons.extend(risk.exposure.reasons)
        result = None
        if candidate.direction == "buy" and risk.sizing.multiplier > 0:
            try:
                result = final_size_valuation_return(
                    valuation,
                    multiplier=risk.sizing.multiplier,
                    cost_profile_version=risk.cost.version,
                    buy_rate=risk.cost.buy_rate,
                    minimum_buy_fee=risk.cost.minimum_buy_fee,
                    sell_rate=risk.cost.sell_rate,
                    minimum_sell_fee=risk.cost.minimum_sell_fee,
                    tax_rate=risk.cost.tax_rate,
                    now=now,
                )
            except ValuationAbstained as error:
                reasons.append(str(error))
        elif candidate.direction == "buy":
            reasons.extend(risk.sizing.reasons)
        if now >= valuation.draft.validity.expires_at:
            reasons.append("forecast_expired")
        trace = (
            ("valuation_id", valuation.valuation_id),
            ("portfolio_snapshot_id", risk.snapshot_id),
            ("portfolio_version", str(risk.portfolio.version)),
            ("cost_profile_version", str(risk.cost.version)),
            ("sizing_policy", risk.sizing.policy_version),
            ("selected_multiplier", str(risk.sizing.multiplier)),
            ("base_amount", str(risk.base_amount)),
            ("buy_price", str(risk.buy_price)),
        )
        if result is not None:
            trace += (
                ("purchase_outflow", str(result.purchase_outflow)),
                ("terminal_inflow", str(result.terminal_inflow)),
                ("annualized_return", str(result.annualized_return)),
                ("return_policy", result.policy_version),
            )
        authoritative = (
            ("minimum_return_policy", self._minimum_return_policy_version),
            ("risk_policy", risk.exposure.policy_version),
            ("cost_profile_policy", risk.cost.policy_version),
        )
        versions = (
            tuple(
                (key, value)
                for key, value in provenance
                if key not in dict(authoritative)
            )
            + authoritative
        )
        plan = RecommendationService.plan_publication(
            actor=RecommendationActor(actor.actor_id, True),
            recommendation_id=recommendation_id,
            version=version,
            inputs=replace(inputs, gate_reasons=tuple(dict.fromkeys(reasons))),
            current=current,
            raw_candidate=raw_candidate,
            raw_critic=raw_critic,
            selected_multiplier=risk.sizing.multiplier,
            annualized_return=None if result is None else result.annualized_return,
            minimum_return=self._minimum_return,
            calculation_trace=trace,
            provenance=versions,
            now=now,
        )
        # Publication reasons include the final calculation, but the admitted
        # evidence snapshot must retain its original digest and values.
        return replace(plan, inputs=inputs), risk


@dataclass(frozen=True, slots=True)
class CreateCompanyCommand:
    actor: AuthenticatedActor
    ticker: str
    name: str


@dataclass(frozen=True, slots=True)
class ListCompaniesQuery:
    actor: AuthenticatedActor


@dataclass(frozen=True, slots=True)
class ThesisLifecycleRequest:
    actor: AuthenticatedActor
    operation: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ThesisLifecycleResult:
    operation: str
    record: dict[str, Any]


class ThesisResearchQueryPort(Protocol):
    def get_company(self, company_id: str) -> Any | None: ...
    def get_record(self, evidence_id: str) -> Any | None: ...
    def get_source_snapshot_id(self, evidence_id: str) -> str | None: ...
    def get_valuation_fact(self, evidence_id: str, fact_id: str) -> Any | None: ...


class ThesisConfirmationPort(Protocol):
    def preview(
        self,
        actor_id: str,
        action_type: str,
        target_id: str,
        target_version: int,
        payload: dict[str, Any],
        impact_summary: dict[str, Any],
    ) -> tuple[str, Any]: ...

    def confirm(
        self,
        token: str,
        actor_id: str,
        action_type: str,
        target_version: int,
        payload: dict[str, Any],
        reason: str,
    ) -> Any: ...


class ThesisConfirmedTransitionPort(Protocol):
    def execute(
        self,
        *,
        actor: AuthenticatedActor,
        thesis_id: str,
        expected_version: int,
        target: ThesisStatus,
        reason: str,
        idempotency_key: str,
        challenge_token: str,
        now: datetime,
    ) -> ThesisRecord: ...


class ThesisLifecycleFlow:
    """L0 mapping for Research references, Access capability and Thesis commands."""

    def __init__(
        self,
        service: ThesisService,
        research: ThesisResearchQueryPort,
        *,
        confirmations: ThesisConfirmationPort | None = None,
        confirmed_transitions: ThesisConfirmedTransitionPort | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._service = service
        self._research = research
        self._confirmations = confirmations
        self._confirmed_transitions = confirmed_transitions
        self._clock = clock

    @staticmethod
    def _actor(actor: AuthenticatedActor) -> ThesisActorContext:
        if actor.role not in {Role.OWNER, Role.LEARNER}:
            raise PermissionError("resource_unavailable")
        return ThesisActorContext(actor.actor_id, True)

    def _company(
        self, company_id: str, version: int | None = None
    ) -> ThesisResearchReference:
        company = self._research.get_company(company_id)
        if company is None:
            raise LookupError("resource_unavailable")
        if version is not None and company.version != version:
            raise ValueError("research_version_conflict")
        return ThesisResearchReference(
            "company", company.company_id, company.version, company.company_id
        )

    def _evidence(
        self, company_id: str, values: list[dict[str, Any]]
    ) -> tuple[ThesisResearchReference, ...]:
        references = []
        for value in values:
            record = self._research.get_record(str(value.get("record_id", "")))
            if (
                record is None
                or record.company_id != company_id
                or record.version != int(value.get("version", 0))
            ):
                raise ValueError("research_version_conflict")
            references.append(
                ThesisResearchReference(
                    "evidence", record.evidence_id, record.version, record.company_id
                )
            )
        return tuple(references)

    @staticmethod
    def _response(record: ThesisRecord) -> dict[str, Any]:
        def reference(value: ThesisResearchReference) -> dict[str, Any]:
            return {
                "record_type": value.record_type,
                "record_id": value.record_id,
                "version": value.version,
                "company_id": value.company_id,
            }

        def valuation(value: ValuationDraft) -> dict[str, Any]:
            def normalize(item: Any) -> Any:
                if isinstance(item, Decimal):
                    return str(item)
                if isinstance(item, (date, datetime)):
                    return item.isoformat()
                if isinstance(item, Enum):
                    return item.value
                if isinstance(item, dict):
                    return {key: normalize(child) for key, child in item.items()}
                if isinstance(item, (list, tuple)):
                    return [normalize(child) for child in item]
                return item

            return normalize(asdict(value))

        return {
            "thesis_id": record.thesis_id,
            "version": record.version,
            "owner_user_id": record.owner_user_id,
            "company_id": record.company_id,
            "company_version": record.company_version,
            "title": record.title,
            "narrative": record.narrative,
            "status": record.status.value,
            "cycle": record.cycle,
            "reflection_pending": record.reflection_pending,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "conditions": [
                {
                    "condition_id": value.condition_id,
                    "version": value.version,
                    "summary": value.summary,
                    "active": value.active,
                }
                for value in record.conditions
            ],
            "evidence_refs": [reference(value) for value in record.evidence_refs],
            "outcome": None
            if record.outcome is None
            else {
                "outcome_id": record.outcome.outcome_id,
                "version": record.outcome.version,
                "cycle": record.outcome.cycle,
                "observed_at": record.outcome.observed_at.isoformat(),
                "result": record.outcome.result,
                "evidence_refs": [
                    reference(value) for value in record.outcome.evidence_refs
                ],
            },
            "reflection": None
            if record.reflection is None
            else {
                "reflection_id": record.reflection.reflection_id,
                "version": record.reflection.version,
                "cycle": record.reflection.cycle,
                "original_assumption": record.reflection.original_assumption,
                "judgment_errors": record.reflection.judgment_errors,
                "missing_evidence": record.reflection.missing_evidence,
                "improvement": record.reflection.improvement,
            },
            "reflection_draft": None
            if record.reflection_draft is None
            else {
                "revision": record.reflection_draft.revision,
                "cycle": record.reflection_draft.cycle,
                "original_assumption": record.reflection_draft.original_assumption,
                "judgment_errors": record.reflection_draft.judgment_errors,
                "missing_evidence": record.reflection_draft.missing_evidence,
                "improvement": record.reflection_draft.improvement,
                "saved_at": record.reflection_draft.saved_at.isoformat(),
            },
            "valuation_draft": None
            if record.valuation_draft is None
            else valuation(record.valuation_draft),
            "valuation_snapshots": [
                {
                    "valuation_id": value.valuation_id,
                    "version": value.version,
                    "draft_version": value.draft_version,
                    "draft": valuation(value.draft),
                    "published_at": value.published_at.isoformat(),
                    "reason": value.reason,
                    "policy_version": value.policy_version,
                }
                for value in record.valuation_snapshots
            ],
            "policy_version": record.policy_version,
        }

    def create(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        company = self._company(
            str(body.get("company_id", "")), int(body.get("company_version", 0))
        )
        return self._response(
            self._service.create(
                CreateThesisCommand(
                    self._actor(actor),
                    company,
                    str(body.get("title", "")),
                    str(body.get("narrative", "")),
                    tuple(
                        str(value) for value in body.get("invalidation_conditions", [])
                    ),
                    self._evidence(company.company_id, body.get("evidence_refs", [])),
                    str(body.get("reason", "")),
                    str(body.get("idempotency_key", "")),
                ),
                now=self._clock(),
            )
        )

    def list_for_company(
        self, actor: AuthenticatedActor, company_id: str
    ) -> list[dict[str, Any]]:
        self._company(company_id)
        return [
            self._response(value)
            for value in self._service.list_for_company(self._actor(actor), company_id)
        ]

    def get(self, actor: AuthenticatedActor, thesis_id: str) -> dict[str, Any]:
        return self._response(self._service.get(self._actor(actor), thesis_id))

    def save(
        self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        current = self._service.get(self._actor(actor), thesis_id)
        return self._response(
            self._service.save(
                SaveThesisCommand(
                    self._actor(actor),
                    thesis_id,
                    int(body.get("expected_version", 0)),
                    str(body.get("title", "")),
                    str(body.get("narrative", "")),
                    tuple(
                        str(value) for value in body.get("invalidation_conditions", [])
                    ),
                    self._evidence(current.company_id, body.get("evidence_refs", [])),
                    str(body.get("reason", "")),
                    str(body.get("idempotency_key", "")),
                ),
                now=self._clock(),
            )
        )

    def preview_transition(
        self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        thesis_actor = self._actor(actor)
        target = ThesisStatus(str(body.get("target_status", "")))
        expected_version = int(body.get("expected_version", 0))
        preview = self._service.preview_transition(
            thesis_actor, thesis_id, expected_version, target
        )
        response: dict[str, Any] = {
            "thesis_id": preview.thesis_id,
            "target_version": preview.target_version,
            "from_status": preview.from_status.value,
            "to_status": preview.to_status.value,
            "consequences": list(preview.consequences),
            "requires_confirmation": self._service.requires_confirmation(
                preview.from_status, preview.to_status
            ),
        }
        if response["requires_confirmation"]:
            if self._confirmations is None:
                raise LookupError("resource_unavailable")
            payload = {"thesis_id": thesis_id, "target_status": target.value}
            impact = {
                "subject": thesis_id,
                "action_label": "Change Thesis lifecycle state",
                "before": {
                    "status": preview.from_status.value,
                    "version": str(expected_version),
                },
                "after": {"status": target.value, "version": str(expected_version + 1)},
                "consequences": list(preview.consequences),
                "confirmation_verb": "CHANGE THESIS",
            }
            token, challenge = self._confirmations.preview(
                actor.actor_id,
                "transition_personal_thesis",
                thesis_id,
                expected_version,
                payload,
                impact,
            )
            response.update(
                {
                    "challenge_token": token,
                    "challenge_expires_at": challenge.expires_at.isoformat(),
                    "impact_summary": impact,
                }
            )
        return response

    def transition(
        self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        thesis_actor = self._actor(actor)
        current = self._service.get(thesis_actor, thesis_id)
        target = ThesisStatus(str(body.get("target_status", "")))
        confirmation_id = None
        if self._service.requires_confirmation(current.status, target):
            if self._confirmed_transitions is None:
                raise LookupError("resource_unavailable")
            return self._response(
                self._confirmed_transitions.execute(
                    actor=actor,
                    thesis_id=thesis_id,
                    expected_version=int(body.get("expected_version", 0)),
                    target=target,
                    reason=str(body.get("reason", "")),
                    idempotency_key=str(body.get("idempotency_key", "")),
                    challenge_token=str(body.get("challenge_token", "")),
                    now=self._clock(),
                )
            )
        return self._response(
            self._service.transition(
                TransitionThesisCommand(
                    thesis_actor,
                    thesis_id,
                    int(body.get("expected_version", 0)),
                    target,
                    str(body.get("reason", "")),
                    str(body.get("idempotency_key", "")),
                    confirmation_id,
                ),
                now=self._clock(),
            )
        )

    def save_outcome(
        self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        current = self._service.get(self._actor(actor), thesis_id)
        observed_at = datetime.fromisoformat(str(body.get("observed_at", "")))
        return self._response(
            self._service.save_outcome(
                SaveOutcomeCommand(
                    self._actor(actor),
                    thesis_id,
                    int(body.get("expected_version", 0)),
                    observed_at,
                    str(body.get("result", "")),
                    self._evidence(current.company_id, body.get("evidence_refs", [])),
                    str(body.get("reason", "")),
                    str(body.get("idempotency_key", "")),
                ),
                now=self._clock(),
            )
        )

    def autosave_reflection(
        self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._response(
            self._service.save_reflection_draft(
                SaveReflectionDraftCommand(
                    self._actor(actor),
                    thesis_id,
                    int(body.get("expected_draft_version", 0)),
                    str(body.get("field", "")),
                    str(body.get("text", "")),
                    str(body.get("idempotency_key", "")),
                ),
                now=self._clock(),
            )
        )

    def complete_reflection(
        self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._response(
            self._service.complete_reflection(
                CompleteReflectionCommand(
                    self._actor(actor),
                    thesis_id,
                    int(body.get("expected_version", 0)),
                    str(body.get("original_assumption", "")),
                    str(body.get("judgment_errors", "")),
                    str(body.get("missing_evidence", "")),
                    str(body.get("improvement", "")),
                    str(body.get("reason", "")),
                    str(body.get("idempotency_key", "")),
                ),
                now=self._clock(),
            )
        )


class ValuationConfirmedPublicationPort(Protocol):
    def execute(
        self,
        *,
        actor: AuthenticatedActor,
        thesis_id: str,
        expected_thesis_version: int,
        expected_draft_version: int,
        reason: str,
        idempotency_key: str,
        challenge_token: str,
        binding_payload: dict[str, Any],
        now: datetime,
    ) -> ThesisRecord: ...


class ValuationFlow:
    """Owner-only L0 mapping of Portfolio costs into Thesis-owned valuation commands."""

    def __init__(
        self,
        thesis: ThesisService,
        portfolio: PortfolioService,
        research: ThesisResearchQueryPort,
        *,
        confirmations: ThesisConfirmationPort | None = None,
        confirmed_publications: ValuationConfirmedPublicationPort | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._thesis = thesis
        self._portfolio = portfolio
        self._research = research
        self._confirmations = confirmations
        self._confirmed_publications = confirmed_publications
        self._clock = clock

    @staticmethod
    def _actors(
        actor: AuthenticatedActor,
    ) -> tuple[ThesisActorContext, PortfolioActorContext]:
        if actor.role is not Role.OWNER:
            raise PermissionError("resource_unavailable")
        return ThesisActorContext(actor.actor_id, True), PortfolioActorContext(
            actor.actor_id, True
        )

    def _publication_binding(
        self,
        thesis_actor: ThesisActorContext,
        portfolio_actor: PortfolioActorContext,
        record: ThesisRecord,
    ) -> dict[str, Any]:
        draft = record.valuation_draft
        if draft is None:
            raise ValueError("valuation_draft_conflict")
        portfolio = self._portfolio.get(portfolio_actor)
        if draft.method is ValuationMethod.ABSTAIN:
            if draft.cost_profile_version != 0:
                raise ValueError("cost_profile_version_conflict")
        elif (
            portfolio.cost_profile is None
            or portfolio.cost_profile.version != draft.cost_profile_version
        ):
            raise ValueError("cost_profile_version_conflict")
        references: dict[tuple[str, str], ThesisResearchReference] = {}
        if draft.forecast_source is not None:
            references[
                (draft.forecast_source.record_id, str(draft.forecast_source.fact_id))
            ] = draft.forecast_source
        for benchmark in (draft.company_history, draft.peer_group):
            if benchmark is not None:
                for sample in benchmark.valid_samples:
                    references[
                        (sample.source.record_id, str(sample.source.fact_id))
                    ] = sample.source
        sources: list[dict[str, Any]] = []
        for (record_id, fact_id), reference in sorted(references.items()):
            evidence = self._research.get_record(record_id)
            snapshot_id = self._research.get_source_snapshot_id(record_id)
            fact = self._research.get_valuation_fact(record_id, fact_id)
            if (
                evidence is None
                or evidence.version != reference.version
                or evidence.company_id != reference.company_id
                or getattr(evidence.status, "value", evidence.status) != "succeeded"
                or snapshot_id is None
                or fact is None
                or fact.fact_id != fact_id
                or fact.evidence_version != reference.version
                or fact.source_snapshot_id != snapshot_id
                or fact.company_id != reference.company_id
            ):
                raise ValueError("valuation_source_invalid")
            sources.append(
                {
                    "record_id": record_id,
                    "version": reference.version,
                    "company_id": reference.company_id,
                    "source_snapshot_id": snapshot_id,
                    "fact_id": fact_id,
                    "fact_policy_version": fact.policy_version,
                }
            )
        return {
            "thesis_id": record.thesis_id,
            "draft_version": draft.version,
            "cost_profile_version": draft.cost_profile_version,
            "research_sources": sources,
        }

    def save(
        self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        thesis_actor, portfolio_actor = self._actors(actor)
        method = ValuationMethod(str(body["method"]))
        portfolio = self._portfolio.get(portfolio_actor)
        profile = portfolio.cost_profile
        if method is not ValuationMethod.ABSTAIN and profile is None:
            raise ValueError("cost_profile_required")

        def reference(
            value: dict[str, Any], company_id: str
        ) -> ThesisResearchReference:
            record_id = str(value["record_id"])
            version = int(value["version"])
            record = self._research.get_record(record_id)
            if (
                record is None
                or record.version != version
                or record.company_id != company_id
                or getattr(record.status, "value", record.status) != "succeeded"
                or self._research.get_source_snapshot_id(record_id) is None
            ):
                raise ValueError("valuation_source_invalid")
            return ThesisResearchReference("evidence", record_id, version, company_id)

        def source_fact(
            value: dict[str, Any], company_id: str, fact_kind: str
        ) -> tuple[ThesisResearchReference, Any]:
            source = reference(value, company_id)
            fact_id = str(value["fact_id"])
            fact = self._research.get_valuation_fact(source.record_id, fact_id)
            snapshot_id = self._research.get_source_snapshot_id(source.record_id)
            if (
                fact is None
                or fact.fact_id != fact_id
                or fact.evidence_id != source.record_id
                or fact.evidence_version != source.version
                or fact.source_snapshot_id != snapshot_id
                or fact.company_id != company_id
                or fact.method != method.value
                or fact.fact_kind != fact_kind
            ):
                raise ValueError("valuation_source_invalid")
            return ThesisResearchReference(
                source.record_type,
                source.record_id,
                source.version,
                source.company_id,
                fact_id,
            ), fact

        current = self._thesis.get(thesis_actor, thesis_id)
        basis_date = date.fromisoformat(str(body["basis_date"]))
        horizon_months = int(body["horizon_months"])
        target_date = add_calendar_months_clamped(basis_date, horizon_months)
        company_samples_list: list[ValuationSample] = []
        for value in body.get("company_history_samples", []):
            source, fact = source_fact(
                value["source"], current.company_id, "history_multiple"
            )
            company_samples_list.append(
                ValuationSample(
                    fact.fact_id,
                    current.company_id,
                    fact.observed_on,
                    fact.value,
                    fact.denominator,
                    source,
                )
            )
        company_samples = tuple(company_samples_list)
        peer_members: list[PeerValuationMember] = []
        for value in body.get("peer_members", []):
            company_id = str(value["company_id"])
            company = self._research.get_company(company_id)
            listed = (
                company is not None
                and str(company.ticker).isdigit()
                and 4 <= len(str(company.ticker)) <= 6
            )
            source, fact = source_fact(value["source"], company_id, "peer_multiple")
            sample = ValuationSample(
                fact.fact_id,
                company_id,
                fact.observed_on,
                fact.value,
                fact.denominator,
                source,
            )
            peer_members.append(
                PeerValuationMember(
                    company_id,
                    str(value["inclusion_reason"]),
                    method,
                    listed,
                    True,
                    sample,
                )
            )
        forecast_source_value = body.get("forecast_source")
        forecast_fact = None
        if forecast_source_value is None:
            forecast_source = None
        else:
            forecast_source, forecast_fact = source_fact(
                forecast_source_value, current.company_id, "forecast"
            )
            if forecast_fact.target_date != target_date:
                raise ValueError("forecast_target_date_mismatch")
        profile_values = (
            profile
            or type(
                "NoCostProfile",
                (),
                {
                    "buy_rate": Decimal(0),
                    "minimum_buy_fee": Decimal(0),
                    "sell_rate": Decimal(0),
                    "minimum_sell_fee": Decimal(0),
                    "tax_rate": Decimal(0),
                    "version": 0,
                },
            )()
        )
        record = self._thesis.save_valuation_draft(
            SaveValuationDraftCommand(
                thesis_actor,
                thesis_id,
                int(body["expected_thesis_version"]),
                int(body["expected_draft_version"]),
                method,
                str(body["benchmark_source"]),
                str(body["benchmark_variant"]),
                tuple(value.company_id for value in peer_members),
                (),
                basis_date,
                horizon_months,
                Decimal(0) if forecast_fact is None else forecast_fact.value,
                Decimal(str(body.get("quantity") or 0)),
                Decimal(str(body.get("buy_price") or 0)),
                Decimal(str(body.get("cash_dividend") or 0)),
                profile_values.buy_rate,
                profile_values.minimum_buy_fee,
                profile_values.sell_rate,
                profile_values.minimum_sell_fee,
                profile_values.tax_rate,
                profile_values.version,
                str(body["reason"]),
                str(body["idempotency_key"]),
                company_samples,
                tuple(peer_members),
                str(body["source_selection_reason"]),
                forecast_source,
                None if forecast_fact is None else forecast_fact.confirmed_at,
                None if forecast_fact is None else forecast_fact.next_report_time,
                None if forecast_fact is None else forecast_fact.material_event_time,
                True,
            ),
            now=self._clock(),
        )
        return ThesisLifecycleFlow._response(record)

    def preview_publication(
        self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        thesis_actor, portfolio_actor = self._actors(actor)
        record = self._thesis.get(thesis_actor, thesis_id)
        expected_version = int(body["expected_thesis_version"])
        expected_draft = int(body["expected_draft_version"])
        if record.version != expected_version:
            raise ValueError("version_conflict")
        if (
            record.valuation_draft is None
            or record.valuation_draft.version != expected_draft
        ):
            raise ValueError("valuation_draft_conflict")
        if self._clock() >= record.valuation_draft.validity.expires_at:
            raise ValueError("forecast_expired")
        if self._confirmations is None:
            raise LookupError("resource_unavailable")
        payload = self._publication_binding(thesis_actor, portfolio_actor, record)
        impact = {
            "subject": thesis_id,
            "action_label": "發布不可變估值快照",
            "before": {
                "thesis_version": str(expected_version),
                "draft_version": str(expected_draft),
            },
            "after": {
                "target_price": None
                if record.valuation_draft.result is None
                else str(record.valuation_draft.result.target_price),
                "outcome": "abstain"
                if record.valuation_draft.result is None
                else "valued",
            },
            "consequences": ["估值方法、來源、成本版本與計算 trace 將不可變保存"],
            "confirmation_verb": "發布估值",
        }
        token, challenge = self._confirmations.preview(
            actor.actor_id,
            "publish_thesis_valuation",
            thesis_id,
            expected_version,
            payload,
            impact,
        )
        return {
            "target_version": expected_version,
            "draft_version": expected_draft,
            "challenge_token": token,
            "challenge_expires_at": challenge.expires_at.isoformat(),
            "impact_summary": impact,
        }

    def publish(
        self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        thesis_actor, portfolio_actor = self._actors(actor)
        if self._confirmed_publications is None:
            raise LookupError("resource_unavailable")
        current = self._thesis.get(thesis_actor, thesis_id)
        binding_payload = self._publication_binding(
            thesis_actor, portfolio_actor, current
        )
        record = self._confirmed_publications.execute(
            actor=actor,
            thesis_id=thesis_id,
            expected_thesis_version=int(body["expected_thesis_version"]),
            expected_draft_version=int(body["expected_draft_version"]),
            reason=str(body["reason"]),
            idempotency_key=str(body["idempotency_key"]),
            challenge_token=str(body["challenge_token"]),
            binding_payload=binding_payload,
            now=self._clock(),
        )
        return ThesisLifecycleFlow._response(record)


class PortfolioConfirmedTradePort(Protocol):
    def execute(
        self,
        *,
        actor: AuthenticatedActor,
        preview: TradePreview,
        reason: str,
        idempotency_key: str,
        challenge_token: str,
        now: datetime,
    ) -> PortfolioRecord: ...

    def execute_correction(
        self,
        *,
        actor: AuthenticatedActor,
        preview: Any,
        reason: str,
        idempotency_key: str,
        challenge_token: str,
        now: datetime,
    ) -> PortfolioRecord: ...

    def execute_company_action(
        self,
        *,
        actor: AuthenticatedActor,
        preview: Any,
        reason: str,
        idempotency_key: str,
        challenge_token: str,
        now: datetime,
    ) -> PortfolioRecord: ...


class PortfolioFlow:
    """Owner-only L0 mapping for Cost Profile, cash, holdings, exposure and Trades."""

    def __init__(
        self,
        service: PortfolioService,
        *,
        thesis: ThesisService | None = None,
        confirmations: ThesisConfirmationPort | None = None,
        confirmed_trades: PortfolioConfirmedTradePort | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._service = service
        self._thesis = thesis
        self._confirmations = confirmations
        self._confirmed_trades = confirmed_trades
        self._clock = clock

    @staticmethod
    def _actor(actor: AuthenticatedActor) -> PortfolioActorContext:
        if actor.role is not Role.OWNER:
            raise PermissionError("resource_unavailable")
        return PortfolioActorContext(actor.actor_id, True)

    @staticmethod
    def _response(record: PortfolioRecord) -> dict[str, Any]:
        exposure = None
        if (
            record.cash_as_of is not None
            and record.cash
            + sum(value.quantity * value.official_close for value in record.holdings)
            > 0
        ):
            exposure = aggregate_exposure(
                PortfolioSnapshot(record.version, record.cash, record.holdings)
            )
        return {
            "version": record.version,
            "cost_profile": None
            if record.cost_profile is None
            else {
                "version": record.cost_profile.version,
                "buy_rate": str(record.cost_profile.buy_rate),
                "minimum_buy_fee": str(record.cost_profile.minimum_buy_fee),
                "sell_rate": str(record.cost_profile.sell_rate),
                "minimum_sell_fee": str(record.cost_profile.minimum_sell_fee),
                "tax_rate": str(record.cost_profile.tax_rate),
                "effective_at": record.cost_profile.effective_at.isoformat(),
                "policy_version": record.cost_profile.policy_version,
            },
            "cash": str(record.cash),
            "cash_as_of": None
            if record.cash_as_of is None
            else record.cash_as_of.isoformat(),
            "holdings": [
                {
                    "bucket_id": value.bucket_id,
                    "security_id": value.security_id,
                    "quantity": str(value.quantity),
                    "official_close": str(value.official_close),
                    "official_industry": value.official_industry,
                    "themes": list(value.themes),
                    "price_date": value.price_date.isoformat(),
                    "price_source": value.price_source,
                    "industry_source": value.industry_source,
                    "classification_effective_at": value.classification_effective_at.isoformat(),
                    "theme_snapshot_version": value.theme_snapshot_version,
                    "theme_source": value.theme_source,
                    "theme_effective_at": value.theme_effective_at.isoformat(),
                }
                for value in record.holdings
            ],
            "trades": [
                {
                    "trade_id": value.trade_id,
                    "fingerprint": value.fingerprint,
                    "security_id": value.trade.security_id,
                    "side": value.trade.side.value,
                    "quantity": value.trade.quantity,
                    "price": str(value.trade.price),
                    "confirmed_at": value.confirmed_at.isoformat(),
                    "reason": value.reason,
                }
                for value in record.trades
            ],
            "corrections": [
                {
                    "correction_id": value.correction_id,
                    "original_trade_id": value.original_trade_id,
                    "confirmed_at": value.confirmed_at.isoformat(),
                    "reason": value.reason,
                    "policy_version": value.policy_version,
                }
                for value in record.corrections
            ],
            "company_actions": [
                {
                    "action_id": value.action_id,
                    "security_id": value.security_id,
                    "action_kind": value.action_kind,
                    "pre_action_shares": value.pre_action_shares,
                    "confirmed_post_action_shares": value.confirmed_post_action_shares,
                    "cash_in_lieu": str(value.cash_in_lieu),
                    "allocation": {
                        "shares": value.allocation.shares,
                        "cash": {
                            key: str(amount)
                            for key, amount in value.allocation.cash.items()
                        },
                        "remainder_order": list(value.allocation.remainder_order),
                        "policy_version": value.allocation.policy_version,
                    },
                    "confirmed_at": value.confirmed_at.isoformat(),
                    "reason": value.reason,
                    "policy_version": value.policy_version,
                }
                for value in record.company_actions
            ],
            "exposure": (
                {
                    "nav": str(record.cash),
                    "security_exposure": {},
                    "industry_exposure": {},
                    "theme_exposure": {},
                    "feasible": False,
                    "reasons": ["investable_cash_missing"],
                    "policy_version": "exposure-policy-v1",
                }
                if exposure is None
                else {
                    "nav": str(exposure.nav),
                    "security_exposure": {
                        key: str(value)
                        for key, value in exposure.security_exposure.items()
                    },
                    "industry_exposure": {
                        key: str(value)
                        for key, value in exposure.industry_exposure.items()
                    },
                    "theme_exposure": {
                        key: str(value)
                        for key, value in exposure.theme_exposure.items()
                    },
                    "feasible": exposure.feasible,
                    "reasons": list(exposure.reasons),
                    "policy_version": exposure.policy_version,
                }
            ),
            "updated_at": record.updated_at.isoformat(),
        }

    def get(self, actor: AuthenticatedActor) -> dict[str, Any]:
        return self._response(self._service.get(self._actor(actor)))

    def save_cost_profile(
        self, actor: AuthenticatedActor, body: dict[str, Any]
    ) -> dict[str, Any]:
        from decimal import Decimal

        return self._response(
            self._service.save_cost_profile(
                SaveCostProfileCommand(
                    self._actor(actor),
                    int(body["expected_version"]),
                    Decimal(str(body["buy_rate"])),
                    Decimal(str(body["minimum_buy_fee"])),
                    Decimal(str(body["sell_rate"])),
                    Decimal(str(body["minimum_sell_fee"])),
                    Decimal(str(body["tax_rate"])),
                    datetime.fromisoformat(str(body["effective_at"])),
                    str(body["reason"]),
                    str(body["idempotency_key"]),
                ),
                now=self._clock(),
            )
        )

    def save_cash(
        self, actor: AuthenticatedActor, body: dict[str, Any]
    ) -> dict[str, Any]:
        from decimal import Decimal

        return self._response(
            self._service.save_investable_cash(
                SaveInvestableCashCommand(
                    self._actor(actor),
                    int(body["expected_version"]),
                    Decimal(str(body["cash"])),
                    datetime.fromisoformat(str(body["as_of"])),
                    str(body["reason"]),
                    str(body["idempotency_key"]),
                ),
                now=self._clock(),
            )
        )

    def preview_csv(self, actor: AuthenticatedActor, content: str) -> dict[str, Any]:
        self._actor(actor)
        preview = parse_canonical_csv(content)
        return {
            "trades": [
                {
                    "source_kind": value.source_kind,
                    "source_row_id": value.source_row_id,
                    "broker_reference": value.broker_reference,
                    "security_id": value.security_id,
                    "side": value.side.value,
                    "quantity": value.quantity,
                    "price": str(value.price),
                    "fees": str(value.fees),
                    "tax": str(value.tax),
                    "executed_at": value.executed_at.isoformat(),
                }
                for value in preview.trades
            ],
            "issues": [
                {"row_number": value.row_number, "code": value.code}
                for value in preview.issues
            ],
            "policy_version": preview.policy_version,
        }

    def _preview(self, actor: AuthenticatedActor, body: dict[str, Any]) -> TradePreview:
        from decimal import Decimal

        current = self._service.get(self._actor(actor))
        security_id = str(body["security_id"])
        available = {
            item.bucket_id: int(item.quantity)
            for item in current.holdings
            if item.security_id == security_id
        }
        trade = CanonicalTrade(
            str(body["source_kind"]),
            str(body["source_row_id"]),
            body.get("broker_reference"),
            security_id,
            TradeSide(str(body["side"])),
            int(body["quantity"]),
            Decimal(str(body["price"])),
            Decimal(str(body["fees"])),
            Decimal(str(body["tax"])),
            datetime.fromisoformat(str(body["executed_at"])),
        )
        allocation_values = tuple(
            TradeAllocation(str(value["bucket_id"]), int(value["quantity"]))
            for value in body["allocations"]
        )
        allowed = {"independent"}
        for allocation in allocation_values:
            if allocation.bucket_id == "independent":
                continue
            if self._thesis is None:
                raise ValueError("inactive_allocation_bucket")
            thesis = self._thesis.get(
                ThesisActorContext(actor.actor_id, True),
                allocation.bucket_id,
            )
            if (
                thesis.status is not ThesisStatus.ACTIVE
                or thesis.company_id != security_id
            ):
                raise ValueError("inactive_allocation_bucket")
            allowed.add(allocation.bucket_id)
        return self._service.preview_trade(
            PreviewTradeCommand(
                self._actor(actor),
                int(body["expected_version"]),
                trade,
                allocation_values,
                available,
                frozenset(allowed),
            ),
            now=self._clock(),
        )

    @staticmethod
    def _trade_response(preview: TradePreview) -> dict[str, Any]:
        return {
            "target_version": preview.expected_portfolio_version,
            "fingerprint": preview.fingerprint,
            "preview_digest": preview.preview_digest,
            "post_cash": str(preview.post_portfolio.cash),
            "nav": str(preview.exposure.nav),
            "feasible": preview.exposure.feasible,
            "reasons": list(preview.exposure.reasons),
            "policy_version": preview.policy_version,
        }

    def preview_trade(
        self, actor: AuthenticatedActor, body: dict[str, Any]
    ) -> dict[str, Any]:
        preview = self._preview(actor, body)
        if self._confirmations is None:
            raise LookupError("resource_unavailable")
        payload = {
            "fingerprint": preview.fingerprint,
            "preview_digest": preview.preview_digest,
        }
        impact = {
            "subject": preview.trade.security_id,
            "action_label": "確認交易與桶分配",
            "before": {"portfolio_version": str(preview.expected_portfolio_version)},
            "after": {
                "cash": str(preview.post_portfolio.cash),
                "nav": str(preview.exposure.nav),
            },
            "consequences": ["交易、分配、持股、曝險與稽核將一併保存"],
            "confirmation_verb": "確認交易",
        }
        token, challenge = self._confirmations.preview(
            actor.actor_id,
            "confirm_portfolio_trade",
            actor.actor_id,
            preview.expected_portfolio_version,
            payload,
            impact,
        )
        return {
            **self._trade_response(preview),
            "challenge_token": token,
            "challenge_expires_at": challenge.expires_at.isoformat(),
            "impact_summary": impact,
        }

    def confirm_trade(
        self, actor: AuthenticatedActor, body: dict[str, Any]
    ) -> dict[str, Any]:
        if self._confirmed_trades is None:
            raise LookupError("resource_unavailable")
        preview = self._preview(actor, body)
        return self._response(
            self._confirmed_trades.execute(
                actor=actor,
                preview=preview,
                reason=str(body["reason"]),
                idempotency_key=str(body["idempotency_key"]),
                challenge_token=str(body["challenge_token"]),
                now=self._clock(),
            )
        )

    def preview_correction(
        self, actor: AuthenticatedActor, body: dict[str, Any]
    ) -> dict[str, Any]:
        preview = self._service.preview_correction(
            self._actor(actor),
            expected_version=int(body["expected_version"]),
            original_trade_id=str(body["original_trade_id"]),
            now=self._clock(),
        )
        if self._confirmations is None:
            raise LookupError("resource_unavailable")
        payload = {
            "original_trade_id": preview.original_trade_id,
            "preview_digest": preview.preview_digest,
        }
        impact = {
            "subject": preview.original_trade_id,
            "action_label": "追加交易反向更正",
            "before": {"portfolio_version": str(preview.expected_portfolio_version)},
            "after": {"cash": str(preview.post_portfolio.cash)},
            "consequences": ["原交易保持不可變，另追加反向更正、持股與稽核"],
            "confirmation_verb": "確認更正",
        }
        token, challenge = self._confirmations.preview(
            actor.actor_id,
            "correct_portfolio_trade",
            actor.actor_id,
            preview.expected_portfolio_version,
            payload,
            impact,
        )
        return {
            "target_version": preview.expected_portfolio_version,
            "original_trade_id": preview.original_trade_id,
            "preview_digest": preview.preview_digest,
            "post_cash": str(preview.post_portfolio.cash),
            "challenge_token": token,
            "challenge_expires_at": challenge.expires_at.isoformat(),
            "impact_summary": impact,
        }

    def confirm_correction(
        self, actor: AuthenticatedActor, body: dict[str, Any]
    ) -> dict[str, Any]:
        if self._confirmed_trades is None:
            raise LookupError("resource_unavailable")
        preview = self._service.preview_correction(
            self._actor(actor),
            expected_version=int(body["expected_version"]),
            original_trade_id=str(body["original_trade_id"]),
            now=self._clock(),
        )
        return self._response(
            self._confirmed_trades.execute_correction(
                actor=actor,
                preview=preview,
                reason=str(body["reason"]),
                idempotency_key=str(body["idempotency_key"]),
                challenge_token=str(body["challenge_token"]),
                now=self._clock(),
            )
        )

    def preview_company_action(
        self, actor: AuthenticatedActor, body: dict[str, Any]
    ) -> dict[str, Any]:
        preview = self._service.preview_company_action(
            self._actor(actor),
            expected_version=int(body["expected_version"]),
            security_id=str(body["security_id"]),
            action_kind=str(body["action_kind"]),
            confirmed_post_action_shares=int(body["confirmed_post_action_shares"]),
            cash_in_lieu=Decimal(str(body["cash_in_lieu"])),
            now=self._clock(),
        )
        if self._confirmations is None:
            raise LookupError("resource_unavailable")
        payload = {
            "preview_digest": preview.preview_digest,
            "security_id": preview.security_id,
        }
        impact = {
            "subject": preview.security_id,
            "action_label": "依確認總股數分配公司行動",
            "before": {"portfolio_version": str(preview.expected_portfolio_version)},
            "after": {
                "shares": str(preview.confirmed_post_action_shares),
                "cash": str(preview.post_portfolio.cash),
            },
            "consequences": ["按各桶持股與 ALG-0014 最大餘數法追加不可變紀錄"],
            "confirmation_verb": "確認公司行動",
        }
        token, challenge = self._confirmations.preview(
            actor.actor_id,
            "confirm_portfolio_company_action",
            actor.actor_id,
            preview.expected_portfolio_version,
            payload,
            impact,
        )
        return {
            "target_version": preview.expected_portfolio_version,
            "preview_digest": preview.preview_digest,
            "allocation": {
                "shares": preview.allocation.shares,
                "cash": {
                    key: str(value) for key, value in preview.allocation.cash.items()
                },
                "remainder_order": list(preview.allocation.remainder_order),
            },
            "post_cash": str(preview.post_portfolio.cash),
            "challenge_token": token,
            "challenge_expires_at": challenge.expires_at.isoformat(),
            "impact_summary": impact,
        }

    def confirm_company_action(
        self, actor: AuthenticatedActor, body: dict[str, Any]
    ) -> dict[str, Any]:
        if self._confirmed_trades is None:
            raise LookupError("resource_unavailable")
        preview = self._service.preview_company_action(
            self._actor(actor),
            expected_version=int(body["expected_version"]),
            security_id=str(body["security_id"]),
            action_kind=str(body["action_kind"]),
            confirmed_post_action_shares=int(body["confirmed_post_action_shares"]),
            cash_in_lieu=Decimal(str(body["cash_in_lieu"])),
            now=self._clock(),
        )
        return self._response(
            self._confirmed_trades.execute_company_action(
                actor=actor,
                preview=preview,
                reason=str(body["reason"]),
                idempotency_key=str(body["idempotency_key"]),
                challenge_token=str(body["challenge_token"]),
                now=self._clock(),
            )
        )
