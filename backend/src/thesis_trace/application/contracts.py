from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Protocol

from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
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
from thesis_trace.modules.thesis.valuation import add_calendar_months_clamped
from thesis_trace.modules.portfolio.contracts import (
    CanonicalTrade,
    ConfirmTradeCommand,
    ConfirmTradeCorrectionCommand,
    ConfirmCompanyActionCommand,
    PortfolioActorContext,
    PortfolioRecord,
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
from thesis_trace.modules.portfolio.trades import parse_canonical_csv


@dataclass(frozen=True, slots=True)
class SubmitEvidenceRequest:
    actor: AuthenticatedActor
    company_id: str
    company_version: int
    url: str
    idempotency_key: str


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
        self, actor_id: str, action_type: str, target_id: str, target_version: int,
        payload: dict[str, Any], impact_summary: dict[str, Any],
    ) -> tuple[str, Any]: ...

    def confirm(
        self, token: str, actor_id: str, action_type: str, target_version: int,
        payload: dict[str, Any], reason: str,
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

    def _company(self, company_id: str, version: int | None = None) -> ThesisResearchReference:
        company = self._research.get_company(company_id)
        if company is None:
            raise LookupError("resource_unavailable")
        if version is not None and company.version != version:
            raise ValueError("research_version_conflict")
        return ThesisResearchReference("company", company.company_id, company.version, company.company_id)

    def _evidence(self, company_id: str, values: list[dict[str, Any]]) -> tuple[ThesisResearchReference, ...]:
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
                ThesisResearchReference("evidence", record.evidence_id, record.version, record.company_id)
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
            "outcome": None if record.outcome is None else {
                "outcome_id": record.outcome.outcome_id,
                "version": record.outcome.version,
                "cycle": record.outcome.cycle,
                "observed_at": record.outcome.observed_at.isoformat(),
                "result": record.outcome.result,
                "evidence_refs": [reference(value) for value in record.outcome.evidence_refs],
            },
            "reflection": None if record.reflection is None else {
                "reflection_id": record.reflection.reflection_id,
                "version": record.reflection.version,
                "cycle": record.reflection.cycle,
                "original_assumption": record.reflection.original_assumption,
                "judgment_errors": record.reflection.judgment_errors,
                "missing_evidence": record.reflection.missing_evidence,
                "improvement": record.reflection.improvement,
            },
            "reflection_draft": None if record.reflection_draft is None else {
                "revision": record.reflection_draft.revision,
                "cycle": record.reflection_draft.cycle,
                "original_assumption": record.reflection_draft.original_assumption,
                "judgment_errors": record.reflection_draft.judgment_errors,
                "missing_evidence": record.reflection_draft.missing_evidence,
                "improvement": record.reflection_draft.improvement,
                "saved_at": record.reflection_draft.saved_at.isoformat(),
            },
            "valuation_draft": None if record.valuation_draft is None else valuation(record.valuation_draft),
            "valuation_snapshots": [{
                "valuation_id": value.valuation_id, "version": value.version,
                "draft_version": value.draft_version, "draft": valuation(value.draft),
                "published_at": value.published_at.isoformat(), "reason": value.reason,
                "policy_version": value.policy_version,
            } for value in record.valuation_snapshots],
            "policy_version": record.policy_version,
        }

    def create(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        company = self._company(str(body.get("company_id", "")), int(body.get("company_version", 0)))
        return self._response(self._service.create(CreateThesisCommand(
            self._actor(actor),
            company,
            str(body.get("title", "")),
            str(body.get("narrative", "")),
            tuple(str(value) for value in body.get("invalidation_conditions", [])),
            self._evidence(company.company_id, body.get("evidence_refs", [])),
            str(body.get("reason", "")),
            str(body.get("idempotency_key", "")),
        ), now=self._clock()))

    def list_for_company(self, actor: AuthenticatedActor, company_id: str) -> list[dict[str, Any]]:
        self._company(company_id)
        return [self._response(value) for value in self._service.list_for_company(self._actor(actor), company_id)]

    def get(self, actor: AuthenticatedActor, thesis_id: str) -> dict[str, Any]:
        return self._response(self._service.get(self._actor(actor), thesis_id))

    def save(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        current = self._service.get(self._actor(actor), thesis_id)
        return self._response(self._service.save(SaveThesisCommand(
            self._actor(actor), thesis_id, int(body.get("expected_version", 0)),
            str(body.get("title", "")), str(body.get("narrative", "")),
            tuple(str(value) for value in body.get("invalidation_conditions", [])),
            self._evidence(current.company_id, body.get("evidence_refs", [])),
            str(body.get("reason", "")), str(body.get("idempotency_key", "")),
        ), now=self._clock()))

    def preview_transition(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        thesis_actor = self._actor(actor)
        target = ThesisStatus(str(body.get("target_status", "")))
        expected_version = int(body.get("expected_version", 0))
        preview = self._service.preview_transition(thesis_actor, thesis_id, expected_version, target)
        response: dict[str, Any] = {
            "thesis_id": preview.thesis_id,
            "target_version": preview.target_version,
            "from_status": preview.from_status.value,
            "to_status": preview.to_status.value,
            "consequences": list(preview.consequences),
            "requires_confirmation": self._service.requires_confirmation(preview.from_status, preview.to_status),
        }
        if response["requires_confirmation"]:
            if self._confirmations is None:
                raise LookupError("resource_unavailable")
            payload = {"thesis_id": thesis_id, "target_status": target.value}
            impact = {
                "subject": thesis_id,
                "action_label": "Change Thesis lifecycle state",
                "before": {"status": preview.from_status.value, "version": str(expected_version)},
                "after": {"status": target.value, "version": str(expected_version + 1)},
                "consequences": list(preview.consequences),
                "confirmation_verb": "CHANGE THESIS",
            }
            token, challenge = self._confirmations.preview(
                actor.actor_id, "transition_personal_thesis", thesis_id,
                expected_version, payload, impact,
            )
            response.update({
                "challenge_token": token,
                "challenge_expires_at": challenge.expires_at.isoformat(),
                "impact_summary": impact,
            })
        return response

    def transition(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        thesis_actor = self._actor(actor)
        current = self._service.get(thesis_actor, thesis_id)
        target = ThesisStatus(str(body.get("target_status", "")))
        confirmation_id = None
        if self._service.requires_confirmation(current.status, target):
            if self._confirmed_transitions is None:
                raise LookupError("resource_unavailable")
            return self._response(self._confirmed_transitions.execute(
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
        return self._response(self._service.transition(TransitionThesisCommand(
            thesis_actor, thesis_id, int(body.get("expected_version", 0)), target,
            str(body.get("reason", "")), str(body.get("idempotency_key", "")), confirmation_id,
        ), now=self._clock()))

    def save_outcome(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        current = self._service.get(self._actor(actor), thesis_id)
        observed_at = datetime.fromisoformat(str(body.get("observed_at", "")))
        return self._response(self._service.save_outcome(SaveOutcomeCommand(
            self._actor(actor), thesis_id, int(body.get("expected_version", 0)), observed_at,
            str(body.get("result", "")), self._evidence(current.company_id, body.get("evidence_refs", [])),
            str(body.get("reason", "")), str(body.get("idempotency_key", "")),
        ), now=self._clock()))

    def autosave_reflection(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._response(self._service.save_reflection_draft(SaveReflectionDraftCommand(
            self._actor(actor), thesis_id, int(body.get("expected_draft_version", 0)),
            str(body.get("field", "")), str(body.get("text", "")),
            str(body.get("idempotency_key", "")),
        ), now=self._clock()))

    def complete_reflection(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._response(self._service.complete_reflection(CompleteReflectionCommand(
            self._actor(actor), thesis_id, int(body.get("expected_version", 0)),
            str(body.get("original_assumption", "")), str(body.get("judgment_errors", "")),
            str(body.get("missing_evidence", "")), str(body.get("improvement", "")),
            str(body.get("reason", "")), str(body.get("idempotency_key", "")),
        ), now=self._clock()))


class ValuationConfirmedPublicationPort(Protocol):
    def execute(
        self, *, actor: AuthenticatedActor, thesis_id: str, expected_thesis_version: int,
        expected_draft_version: int, reason: str, idempotency_key: str,
        challenge_token: str, binding_payload: dict[str, Any], now: datetime,
    ) -> ThesisRecord: ...


class ValuationFlow:
    """Owner-only L0 mapping of Portfolio costs into Thesis-owned valuation commands."""

    def __init__(
        self, thesis: ThesisService, portfolio: PortfolioService, research: ThesisResearchQueryPort, *,
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
    def _actors(actor: AuthenticatedActor) -> tuple[ThesisActorContext, PortfolioActorContext]:
        if actor.role is not Role.OWNER:
            raise PermissionError("resource_unavailable")
        return ThesisActorContext(actor.actor_id, True), PortfolioActorContext(actor.actor_id, True)

    def _publication_binding(
        self, thesis_actor: ThesisActorContext, portfolio_actor: PortfolioActorContext, record: ThesisRecord,
    ) -> dict[str, Any]:
        draft = record.valuation_draft
        if draft is None:
            raise ValueError("valuation_draft_conflict")
        portfolio = self._portfolio.get(portfolio_actor)
        if draft.method is ValuationMethod.ABSTAIN:
            if draft.cost_profile_version != 0:
                raise ValueError("cost_profile_version_conflict")
        elif portfolio.cost_profile is None or portfolio.cost_profile.version != draft.cost_profile_version:
            raise ValueError("cost_profile_version_conflict")
        references: dict[tuple[str, str], ThesisResearchReference] = {}
        if draft.forecast_source is not None:
            references[(draft.forecast_source.record_id, str(draft.forecast_source.fact_id))] = draft.forecast_source
        for benchmark in (draft.company_history, draft.peer_group):
            if benchmark is not None:
                for sample in benchmark.valid_samples:
                    references[(sample.source.record_id, str(sample.source.fact_id))] = sample.source
        sources: list[dict[str, Any]] = []
        for (record_id, fact_id), reference in sorted(references.items()):
            evidence = self._research.get_record(record_id)
            snapshot_id = self._research.get_source_snapshot_id(record_id)
            fact = self._research.get_valuation_fact(record_id, fact_id)
            if (
                evidence is None or evidence.version != reference.version
                or evidence.company_id != reference.company_id
                or getattr(evidence.status, "value", evidence.status) != "succeeded"
                or snapshot_id is None or fact is None or fact.fact_id != fact_id
                or fact.evidence_version != reference.version or fact.source_snapshot_id != snapshot_id
                or fact.company_id != reference.company_id
            ):
                raise ValueError("valuation_source_invalid")
            sources.append({
                "record_id": record_id, "version": reference.version,
                "company_id": reference.company_id, "source_snapshot_id": snapshot_id,
                "fact_id": fact_id, "fact_policy_version": fact.policy_version,
            })
        return {
            "thesis_id": record.thesis_id,
            "draft_version": draft.version,
            "cost_profile_version": draft.cost_profile_version,
            "research_sources": sources,
        }

    def save(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        thesis_actor, portfolio_actor = self._actors(actor)
        method = ValuationMethod(str(body["method"]))
        portfolio = self._portfolio.get(portfolio_actor)
        profile = portfolio.cost_profile
        if method is not ValuationMethod.ABSTAIN and profile is None:
            raise ValueError("cost_profile_required")
        def reference(value: dict[str, Any], company_id: str) -> ThesisResearchReference:
            record_id = str(value["record_id"])
            version = int(value["version"])
            record = self._research.get_record(record_id)
            if (
                record is None or record.version != version or record.company_id != company_id
                or getattr(record.status, "value", record.status) != "succeeded"
                or self._research.get_source_snapshot_id(record_id) is None
            ):
                raise ValueError("valuation_source_invalid")
            return ThesisResearchReference("evidence", record_id, version, company_id)

        def source_fact(value: dict[str, Any], company_id: str, fact_kind: str) -> tuple[ThesisResearchReference, Any]:
            source = reference(value, company_id)
            fact_id = str(value["fact_id"])
            fact = self._research.get_valuation_fact(source.record_id, fact_id)
            snapshot_id = self._research.get_source_snapshot_id(source.record_id)
            if (
                fact is None or fact.fact_id != fact_id or fact.evidence_id != source.record_id
                or fact.evidence_version != source.version or fact.source_snapshot_id != snapshot_id
                or fact.company_id != company_id or fact.method != method.value
                or fact.fact_kind != fact_kind
            ):
                raise ValueError("valuation_source_invalid")
            return ThesisResearchReference(
                source.record_type, source.record_id, source.version, source.company_id, fact_id,
            ), fact

        current = self._thesis.get(thesis_actor, thesis_id)
        basis_date = date.fromisoformat(str(body["basis_date"]))
        horizon_months = int(body["horizon_months"])
        target_date = add_calendar_months_clamped(basis_date, horizon_months)
        company_samples_list: list[ValuationSample] = []
        for value in body.get("company_history_samples", []):
            source, fact = source_fact(value["source"], current.company_id, "history_multiple")
            company_samples_list.append(ValuationSample(
                fact.fact_id, current.company_id, fact.observed_on, fact.value,
                fact.denominator, source,
            ))
        company_samples = tuple(company_samples_list)
        peer_members: list[PeerValuationMember] = []
        for value in body.get("peer_members", []):
            company_id = str(value["company_id"])
            company = self._research.get_company(company_id)
            listed = company is not None and str(company.ticker).isdigit() and 4 <= len(str(company.ticker)) <= 6
            source, fact = source_fact(value["source"], company_id, "peer_multiple")
            sample = ValuationSample(
                fact.fact_id, company_id, fact.observed_on, fact.value, fact.denominator, source,
            )
            peer_members.append(PeerValuationMember(
                company_id, str(value["inclusion_reason"]), method, listed, True, sample,
            ))
        forecast_source_value = body.get("forecast_source")
        forecast_fact = None
        if forecast_source_value is None:
            forecast_source = None
        else:
            forecast_source, forecast_fact = source_fact(forecast_source_value, current.company_id, "forecast")
            if forecast_fact.target_date != target_date:
                raise ValueError("forecast_target_date_mismatch")
        profile_values = profile or type("NoCostProfile", (), {
            "buy_rate": Decimal(0), "minimum_buy_fee": Decimal(0),
            "sell_rate": Decimal(0), "minimum_sell_fee": Decimal(0),
            "tax_rate": Decimal(0), "version": 0,
        })()
        record = self._thesis.save_valuation_draft(SaveValuationDraftCommand(
            thesis_actor, thesis_id, int(body["expected_thesis_version"]),
            int(body["expected_draft_version"]), method,
            str(body["benchmark_source"]), str(body["benchmark_variant"]),
            tuple(value.company_id for value in peer_members), (),
            basis_date, horizon_months,
            Decimal(0) if forecast_fact is None else forecast_fact.value,
            Decimal(str(body.get("quantity") or 0)),
            Decimal(str(body.get("buy_price") or 0)), Decimal(str(body.get("cash_dividend") or 0)),
            profile_values.buy_rate, profile_values.minimum_buy_fee, profile_values.sell_rate,
            profile_values.minimum_sell_fee, profile_values.tax_rate, profile_values.version,
            str(body["reason"]), str(body["idempotency_key"]),
            company_samples, tuple(peer_members), str(body["source_selection_reason"]),
            forecast_source,
            None if forecast_fact is None else forecast_fact.confirmed_at,
            None if forecast_fact is None else forecast_fact.next_report_time,
            None if forecast_fact is None else forecast_fact.material_event_time,
            True,
        ), now=self._clock())
        return ThesisLifecycleFlow._response(record)

    def preview_publication(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        thesis_actor, portfolio_actor = self._actors(actor)
        record = self._thesis.get(thesis_actor, thesis_id)
        expected_version = int(body["expected_thesis_version"])
        expected_draft = int(body["expected_draft_version"])
        if record.version != expected_version:
            raise ValueError("version_conflict")
        if record.valuation_draft is None or record.valuation_draft.version != expected_draft:
            raise ValueError("valuation_draft_conflict")
        if self._clock() >= record.valuation_draft.validity.expires_at:
            raise ValueError("forecast_expired")
        if self._confirmations is None:
            raise LookupError("resource_unavailable")
        payload = self._publication_binding(thesis_actor, portfolio_actor, record)
        impact = {
            "subject": thesis_id, "action_label": "發布不可變估值快照",
            "before": {"thesis_version": str(expected_version), "draft_version": str(expected_draft)},
            "after": {
                "target_price": None if record.valuation_draft.result is None
                else str(record.valuation_draft.result.target_price),
                "outcome": "abstain" if record.valuation_draft.result is None else "valued",
            },
            "consequences": ["估值方法、來源、成本版本與計算 trace 將不可變保存"],
            "confirmation_verb": "發布估值",
        }
        token, challenge = self._confirmations.preview(
            actor.actor_id, "publish_thesis_valuation", thesis_id, expected_version, payload, impact,
        )
        return {
            "target_version": expected_version, "draft_version": expected_draft,
            "challenge_token": token, "challenge_expires_at": challenge.expires_at.isoformat(),
            "impact_summary": impact,
        }

    def publish(self, actor: AuthenticatedActor, thesis_id: str, body: dict[str, Any]) -> dict[str, Any]:
        thesis_actor, portfolio_actor = self._actors(actor)
        if self._confirmed_publications is None:
            raise LookupError("resource_unavailable")
        current = self._thesis.get(thesis_actor, thesis_id)
        binding_payload = self._publication_binding(thesis_actor, portfolio_actor, current)
        record = self._confirmed_publications.execute(
            actor=actor, thesis_id=thesis_id,
            expected_thesis_version=int(body["expected_thesis_version"]),
            expected_draft_version=int(body["expected_draft_version"]),
            reason=str(body["reason"]), idempotency_key=str(body["idempotency_key"]),
            challenge_token=str(body["challenge_token"]), binding_payload=binding_payload,
            now=self._clock(),
        )
        return ThesisLifecycleFlow._response(record)


class PortfolioConfirmedTradePort(Protocol):
    def execute(
        self, *, actor: AuthenticatedActor, preview: TradePreview, reason: str,
        idempotency_key: str, challenge_token: str, now: datetime,
    ) -> PortfolioRecord: ...

    def execute_correction(
        self, *, actor: AuthenticatedActor, preview: Any, reason: str,
        idempotency_key: str, challenge_token: str, now: datetime,
    ) -> PortfolioRecord: ...

    def execute_company_action(
        self, *, actor: AuthenticatedActor, preview: Any, reason: str,
        idempotency_key: str, challenge_token: str, now: datetime,
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
        if record.cash_as_of is not None and record.cash + sum(
            value.quantity * value.official_close for value in record.holdings
        ) > 0:
            exposure = aggregate_exposure(PortfolioSnapshot(record.version, record.cash, record.holdings))
        return {
            "version": record.version,
            "cost_profile": None if record.cost_profile is None else {
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
            "cash_as_of": None if record.cash_as_of is None else record.cash_as_of.isoformat(),
            "holdings": [{
                "bucket_id": value.bucket_id, "security_id": value.security_id,
                "quantity": str(value.quantity), "official_close": str(value.official_close),
                "official_industry": value.official_industry, "themes": list(value.themes),
                "price_date": value.price_date.isoformat(), "price_source": value.price_source,
                "industry_source": value.industry_source,
                "classification_effective_at": value.classification_effective_at.isoformat(),
                "theme_snapshot_version": value.theme_snapshot_version,
                "theme_source": value.theme_source,
                "theme_effective_at": value.theme_effective_at.isoformat(),
            } for value in record.holdings],
            "trades": [{
                "trade_id": value.trade_id, "fingerprint": value.fingerprint,
                "security_id": value.trade.security_id, "side": value.trade.side.value,
                "quantity": value.trade.quantity, "price": str(value.trade.price),
                "confirmed_at": value.confirmed_at.isoformat(), "reason": value.reason,
            } for value in record.trades],
            "corrections": [{
                "correction_id": value.correction_id,
                "original_trade_id": value.original_trade_id,
                "confirmed_at": value.confirmed_at.isoformat(), "reason": value.reason,
                "policy_version": value.policy_version,
            } for value in record.corrections],
            "company_actions": [{
                "action_id": value.action_id, "security_id": value.security_id,
                "action_kind": value.action_kind,
                "pre_action_shares": value.pre_action_shares,
                "confirmed_post_action_shares": value.confirmed_post_action_shares,
                "cash_in_lieu": str(value.cash_in_lieu),
                "allocation": {
                    "shares": value.allocation.shares,
                    "cash": {key: str(amount) for key, amount in value.allocation.cash.items()},
                    "remainder_order": list(value.allocation.remainder_order),
                    "policy_version": value.allocation.policy_version,
                },
                "confirmed_at": value.confirmed_at.isoformat(), "reason": value.reason,
                "policy_version": value.policy_version,
            } for value in record.company_actions],
            "exposure": ({
                "nav": str(record.cash), "security_exposure": {}, "industry_exposure": {},
                "theme_exposure": {}, "feasible": False,
                "reasons": ["investable_cash_missing"], "policy_version": "exposure-policy-v1",
            } if exposure is None else {
                "nav": str(exposure.nav),
                "security_exposure": {key: str(value) for key, value in exposure.security_exposure.items()},
                "industry_exposure": {key: str(value) for key, value in exposure.industry_exposure.items()},
                "theme_exposure": {key: str(value) for key, value in exposure.theme_exposure.items()},
                "feasible": exposure.feasible, "reasons": list(exposure.reasons),
                "policy_version": exposure.policy_version,
            }),
            "updated_at": record.updated_at.isoformat(),
        }

    def get(self, actor: AuthenticatedActor) -> dict[str, Any]:
        return self._response(self._service.get(self._actor(actor)))

    def save_cost_profile(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        from decimal import Decimal
        return self._response(self._service.save_cost_profile(SaveCostProfileCommand(
            self._actor(actor), int(body["expected_version"]), Decimal(str(body["buy_rate"])),
            Decimal(str(body["minimum_buy_fee"])), Decimal(str(body["sell_rate"])),
            Decimal(str(body["minimum_sell_fee"])), Decimal(str(body["tax_rate"])),
            datetime.fromisoformat(str(body["effective_at"])), str(body["reason"]),
            str(body["idempotency_key"]),
        ), now=self._clock()))

    def save_cash(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        from decimal import Decimal
        return self._response(self._service.save_investable_cash(SaveInvestableCashCommand(
            self._actor(actor), int(body["expected_version"]), Decimal(str(body["cash"])),
            datetime.fromisoformat(str(body["as_of"])), str(body["reason"]),
            str(body["idempotency_key"]),
        ), now=self._clock()))

    def preview_csv(self, actor: AuthenticatedActor, content: str) -> dict[str, Any]:
        self._actor(actor)
        preview = parse_canonical_csv(content)
        return {
            "trades": [{
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
            } for value in preview.trades],
            "issues": [{"row_number": value.row_number, "code": value.code} for value in preview.issues],
            "policy_version": preview.policy_version,
        }

    def _preview(self, actor: AuthenticatedActor, body: dict[str, Any]) -> TradePreview:
        from decimal import Decimal
        current = self._service.get(self._actor(actor))
        security_id = str(body["security_id"])
        available = {
            item.bucket_id: int(item.quantity)
            for item in current.holdings if item.security_id == security_id
        }
        trade = CanonicalTrade(
            str(body["source_kind"]), str(body["source_row_id"]), body.get("broker_reference"),
            security_id, TradeSide(str(body["side"])), int(body["quantity"]),
            Decimal(str(body["price"])), Decimal(str(body["fees"])), Decimal(str(body["tax"])),
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
                ThesisActorContext(actor.actor_id, True), allocation.bucket_id,
            )
            if thesis.status is not ThesisStatus.ACTIVE or thesis.company_id != security_id:
                raise ValueError("inactive_allocation_bucket")
            allowed.add(allocation.bucket_id)
        return self._service.preview_trade(PreviewTradeCommand(
            self._actor(actor), int(body["expected_version"]), trade,
            allocation_values, available, frozenset(allowed),
        ), now=self._clock())

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

    def preview_trade(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        preview = self._preview(actor, body)
        if self._confirmations is None:
            raise LookupError("resource_unavailable")
        payload = {"fingerprint": preview.fingerprint, "preview_digest": preview.preview_digest}
        impact = {
            "subject": preview.trade.security_id, "action_label": "確認交易與桶分配",
            "before": {"portfolio_version": str(preview.expected_portfolio_version)},
            "after": {"cash": str(preview.post_portfolio.cash), "nav": str(preview.exposure.nav)},
            "consequences": ["交易、分配、持股、曝險與稽核將一併保存"],
            "confirmation_verb": "確認交易",
        }
        token, challenge = self._confirmations.preview(
            actor.actor_id, "confirm_portfolio_trade", actor.actor_id,
            preview.expected_portfolio_version, payload, impact,
        )
        return {**self._trade_response(preview), "challenge_token": token,
                "challenge_expires_at": challenge.expires_at.isoformat(), "impact_summary": impact}

    def confirm_trade(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        if self._confirmed_trades is None:
            raise LookupError("resource_unavailable")
        preview = self._preview(actor, body)
        return self._response(self._confirmed_trades.execute(
            actor=actor, preview=preview, reason=str(body["reason"]),
            idempotency_key=str(body["idempotency_key"]),
            challenge_token=str(body["challenge_token"]), now=self._clock(),
        ))

    def preview_correction(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        preview = self._service.preview_correction(
            self._actor(actor), expected_version=int(body["expected_version"]),
            original_trade_id=str(body["original_trade_id"]), now=self._clock(),
        )
        if self._confirmations is None:
            raise LookupError("resource_unavailable")
        payload = {"original_trade_id": preview.original_trade_id, "preview_digest": preview.preview_digest}
        impact = {
            "subject": preview.original_trade_id, "action_label": "追加交易反向更正",
            "before": {"portfolio_version": str(preview.expected_portfolio_version)},
            "after": {"cash": str(preview.post_portfolio.cash)},
            "consequences": ["原交易保持不可變，另追加反向更正、持股與稽核"],
            "confirmation_verb": "確認更正",
        }
        token, challenge = self._confirmations.preview(
            actor.actor_id, "correct_portfolio_trade", actor.actor_id,
            preview.expected_portfolio_version, payload, impact,
        )
        return {
            "target_version": preview.expected_portfolio_version,
            "original_trade_id": preview.original_trade_id,
            "preview_digest": preview.preview_digest,
            "post_cash": str(preview.post_portfolio.cash),
            "challenge_token": token, "challenge_expires_at": challenge.expires_at.isoformat(),
            "impact_summary": impact,
        }

    def confirm_correction(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        if self._confirmed_trades is None:
            raise LookupError("resource_unavailable")
        preview = self._service.preview_correction(
            self._actor(actor), expected_version=int(body["expected_version"]),
            original_trade_id=str(body["original_trade_id"]), now=self._clock(),
        )
        return self._response(self._confirmed_trades.execute_correction(
            actor=actor, preview=preview, reason=str(body["reason"]),
            idempotency_key=str(body["idempotency_key"]),
            challenge_token=str(body["challenge_token"]), now=self._clock(),
        ))

    def preview_company_action(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        preview = self._service.preview_company_action(
            self._actor(actor), expected_version=int(body["expected_version"]),
            security_id=str(body["security_id"]), action_kind=str(body["action_kind"]),
            confirmed_post_action_shares=int(body["confirmed_post_action_shares"]),
            cash_in_lieu=Decimal(str(body["cash_in_lieu"])), now=self._clock(),
        )
        if self._confirmations is None:
            raise LookupError("resource_unavailable")
        payload = {"preview_digest": preview.preview_digest, "security_id": preview.security_id}
        impact = {
            "subject": preview.security_id, "action_label": "依確認總股數分配公司行動",
            "before": {"portfolio_version": str(preview.expected_portfolio_version)},
            "after": {"shares": str(preview.confirmed_post_action_shares), "cash": str(preview.post_portfolio.cash)},
            "consequences": ["按各桶持股與 ALG-0014 最大餘數法追加不可變紀錄"],
            "confirmation_verb": "確認公司行動",
        }
        token, challenge = self._confirmations.preview(
            actor.actor_id, "confirm_portfolio_company_action", actor.actor_id,
            preview.expected_portfolio_version, payload, impact,
        )
        return {
            "target_version": preview.expected_portfolio_version,
            "preview_digest": preview.preview_digest,
            "allocation": {"shares": preview.allocation.shares, "cash": {key: str(value) for key, value in preview.allocation.cash.items()}, "remainder_order": list(preview.allocation.remainder_order)},
            "post_cash": str(preview.post_portfolio.cash),
            "challenge_token": token, "challenge_expires_at": challenge.expires_at.isoformat(),
            "impact_summary": impact,
        }

    def confirm_company_action(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        if self._confirmed_trades is None:
            raise LookupError("resource_unavailable")
        preview = self._service.preview_company_action(
            self._actor(actor), expected_version=int(body["expected_version"]),
            security_id=str(body["security_id"]), action_kind=str(body["action_kind"]),
            confirmed_post_action_shares=int(body["confirmed_post_action_shares"]),
            cash_in_lieu=Decimal(str(body["cash_in_lieu"])), now=self._clock(),
        )
        return self._response(self._confirmed_trades.execute_company_action(
            actor=actor, preview=preview, reason=str(body["reason"]),
            idempotency_key=str(body["idempotency_key"]),
            challenge_token=str(body["challenge_token"]), now=self._clock(),
        ))
