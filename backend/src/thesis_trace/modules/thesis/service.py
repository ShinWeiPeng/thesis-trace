from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import uuid
from collections.abc import Callable

from thesis_trace.modules.thesis.contracts import (
    CompleteReflectionCommand,
    CreateThesisCommand,
    InvalidationCondition,
    ReflectionDraftRevision,
    SaveOutcomeCommand,
    SaveReflectionDraftCommand,
    SaveThesisCommand,
    SaveValuationDraftCommand,
    ThesisActorContext,
    ThesisInvalidationProjection,
    ThesisOutcome,
    ThesisRecord,
    ThesisReflection,
    ThesisStatus,
    ThesisTransitionPreview,
    TransitionThesisCommand,
    PublishValuationCommand,
    ValuationDraft,
    ValuationMethod,
    ValuationSnapshot,
)
from thesis_trace.modules.thesis.ports import ThesisStorePort
from thesis_trace.modules.thesis.valuation import (
    annualized_net_return,
    company_history_benchmark,
    company_history_distribution,
    evaluate_validity,
    peer_group_benchmark,
    peer_group_distribution,
    ValuationAbstained,
)


POLICY_VERSION = "thesis-lifecycle-v1"
_DIRECT = {
    (ThesisStatus.DRAFT, ThesisStatus.ACTIVE),
    (ThesisStatus.ACTIVE, ThesisStatus.PAUSED),
    (ThesisStatus.PAUSED, ThesisStatus.ACTIVE),
}
_CONSEQUENTIAL = {
    (ThesisStatus.DRAFT, ThesisStatus.INVALIDATED),
    (ThesisStatus.ACTIVE, ThesisStatus.INVALIDATED),
    (ThesisStatus.PAUSED, ThesisStatus.INVALIDATED),
    (ThesisStatus.ACTIVE, ThesisStatus.CLOSED),
    (ThesisStatus.PAUSED, ThesisStatus.CLOSED),
    (ThesisStatus.INVALIDATED, ThesisStatus.CLOSED),
    (ThesisStatus.INVALIDATED, ThesisStatus.ACTIVE),
    (ThesisStatus.CLOSED, ThesisStatus.ACTIVE),
}
_REFLECTION_FIELDS = {
    "original_assumption",
    "judgment_errors",
    "missing_evidence",
    "improvement",
}


def _json_default(value):
    if isinstance(value, (date, datetime, Enum)):
        return value.isoformat() if isinstance(value, (date, datetime)) else value.value
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def _digest(command: object) -> str:
    body = json.dumps(
        asdict(command),
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(body.encode()).hexdigest()


def _required(value: str, code: str = "invalid_request") -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(code)
    return normalized


class ThesisService:
    def __init__(
        self,
        store: ThesisStorePort,
        *,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._store = store
        self._id_factory = id_factory

    def with_store(self, store: ThesisStorePort) -> ThesisService:
        """Bind the same policies and deterministic factory to a request-scoped store."""
        return ThesisService(store, id_factory=self._id_factory)

    @staticmethod
    def _authorize(actor: ThesisActorContext) -> None:
        if not actor.may_manage_personal_thesis or not actor.actor_id:
            raise PermissionError("resource_unavailable")

    def get(self, actor: ThesisActorContext, thesis_id: str) -> ThesisRecord:
        self._authorize(actor)
        record = self._store.get(actor.actor_id, thesis_id)
        if record is None:
            raise LookupError("resource_unavailable")
        return record

    @staticmethod
    def requires_confirmation(from_status: ThesisStatus, target: ThesisStatus) -> bool:
        return (from_status, target) in _CONSEQUENTIAL

    def list_for_company(
        self, actor: ThesisActorContext, company_id: str
    ) -> list[ThesisRecord]:
        self._authorize(actor)
        return self._store.list_for_company(actor.actor_id, company_id)

    def create(self, command: CreateThesisCommand, *, now: datetime) -> ThesisRecord:
        self._authorize(command.actor)
        if (
            command.company.record_type != "company"
            or command.company.record_id != command.company.company_id
            or command.company.version < 1
        ):
            raise ValueError("invalid_request")
        title, narrative, reason = (
            _required(command.title),
            _required(command.narrative),
            _required(command.reason, "reason_required"),
        )
        thesis_id = self._id_factory()
        conditions = self._conditions(thesis_id, command.invalidation_conditions)
        self._validate_evidence(command.company.record_id, command.evidence_refs)
        record = ThesisRecord(
            thesis_id=thesis_id,
            version=1,
            owner_user_id=command.actor.actor_id,
            company_id=command.company.record_id,
            company_version=command.company.version,
            title=title,
            narrative=narrative,
            status=ThesisStatus.DRAFT,
            cycle=1,
            reflection_pending=False,
            created_at=now,
            updated_at=now,
            conditions=conditions,
            evidence_refs=command.evidence_refs,
            outcome=None,
            reflection=None,
            reflection_draft=None,
            policy_version=POLICY_VERSION,
        )
        return self._store.commit(
            actor_id=command.actor.actor_id,
            idempotency_key=_required(command.idempotency_key),
            command_digest=_digest(command),
            expected_version=0,
            record=record,
            action="created",
            reason=reason,
        )

    def save(self, command: SaveThesisCommand, *, now: datetime) -> ThesisRecord:
        current = self._owned(command.actor, command.thesis_id)
        if current.version != command.expected_version:
            raise ValueError("version_conflict")
        self._validate_evidence(current.company_id, command.evidence_refs)
        record = replace(
            current,
            version=current.version + 1,
            title=_required(command.title),
            narrative=_required(command.narrative),
            conditions=self._conditions(
                current.thesis_id, command.invalidation_conditions
            ),
            evidence_refs=command.evidence_refs,
            updated_at=now,
        )
        return self._commit(
            command, record, "saved", _required(command.reason, "reason_required")
        )

    def preview_transition(
        self,
        actor: ThesisActorContext,
        thesis_id: str,
        expected_version: int,
        target: ThesisStatus,
    ) -> ThesisTransitionPreview:
        current = self._owned(actor, thesis_id)
        if current.version != expected_version:
            raise ValueError("version_conflict")
        self._validate_transition(current, target)
        consequences = (
            ("Starts a new immutable lifecycle cycle",)
            if current.status in {ThesisStatus.INVALIDATED, ThesisStatus.CLOSED}
            and target is ThesisStatus.ACTIVE
            else ("Changes the canonical Thesis lifecycle state",)
        )
        return ThesisTransitionPreview(
            thesis_id, expected_version, current.status, target, consequences
        )

    def transition(
        self, command: TransitionThesisCommand, *, now: datetime
    ) -> ThesisRecord:
        current = self._owned(command.actor, command.thesis_id)
        if current.version != command.expected_version:
            raise ValueError("version_conflict")
        self._validate_transition(current, command.target)
        if (
            current.status,
            command.target,
        ) in _CONSEQUENTIAL and not command.confirmation_id:
            raise PermissionError("confirmation_required")
        cycle = (
            current.cycle + 1
            if current.status in {ThesisStatus.INVALIDATED, ThesisStatus.CLOSED}
            and command.target is ThesisStatus.ACTIVE
            else current.cycle
        )
        record = replace(
            current,
            version=current.version + 1,
            status=command.target,
            cycle=cycle,
            reflection_pending=command.target is ThesisStatus.INVALIDATED,
            outcome=None if cycle != current.cycle else current.outcome,
            reflection=None if cycle != current.cycle else current.reflection,
            reflection_draft=None
            if cycle != current.cycle
            else current.reflection_draft,
            updated_at=now,
        )
        return self._commit(
            command,
            record,
            f"transitioned:{current.status.value}->{command.target.value}",
            _required(command.reason, "reason_required"),
        )

    def save_outcome(
        self, command: SaveOutcomeCommand, *, now: datetime
    ) -> ThesisRecord:
        current = self._owned(command.actor, command.thesis_id)
        if current.version != command.expected_version:
            raise ValueError("version_conflict")
        self._validate_evidence(current.company_id, command.evidence_refs)
        version = 1 if current.outcome is None else current.outcome.version + 1
        outcome = ThesisOutcome(
            f"{current.thesis_id}:outcome:{current.cycle}",
            version,
            current.cycle,
            command.observed_at,
            _required(command.result),
            command.evidence_refs,
        )
        record = replace(
            current, version=current.version + 1, outcome=outcome, updated_at=now
        )
        return self._commit(
            command,
            record,
            "outcome_saved",
            _required(command.reason, "reason_required"),
        )

    def save_reflection_draft(
        self, command: SaveReflectionDraftCommand, *, now: datetime
    ) -> ThesisRecord:
        current = self._owned(command.actor, command.thesis_id)
        if command.field not in _REFLECTION_FIELDS:
            raise ValueError("invalid_request")
        latest = current.reflection_draft
        version = 0 if latest is None else latest.revision
        if version != command.expected_draft_version:
            raise ValueError("version_conflict")
        values = {
            "original_assumption": "" if latest is None else latest.original_assumption,
            "judgment_errors": "" if latest is None else latest.judgment_errors,
            "missing_evidence": "" if latest is None else latest.missing_evidence,
            "improvement": "" if latest is None else latest.improvement,
        }
        values[command.field] = command.text
        draft = ReflectionDraftRevision(
            revision=version + 1,
            cycle=current.cycle,
            saved_at=now,
            **values,
        )
        record = replace(
            current, version=current.version + 1, reflection_draft=draft, updated_at=now
        )
        return self._store.commit(
            actor_id=command.actor.actor_id,
            idempotency_key=_required(command.idempotency_key),
            command_digest=_digest(command),
            expected_version=current.version,
            record=record,
            action="reflection_draft_saved",
            reason="autosave",
        )

    def complete_reflection(
        self, command: CompleteReflectionCommand, *, now: datetime
    ) -> ThesisRecord:
        current = self._owned(command.actor, command.thesis_id)
        if current.version != command.expected_version:
            raise ValueError("version_conflict")
        version = 1 if current.reflection is None else current.reflection.version + 1
        reflection = ThesisReflection(
            f"{current.thesis_id}:reflection:{current.cycle}",
            version,
            current.cycle,
            _required(command.original_assumption),
            _required(command.judgment_errors),
            _required(command.missing_evidence),
            _required(command.improvement),
        )
        record = replace(
            current,
            version=current.version + 1,
            reflection=reflection,
            reflection_pending=False,
            updated_at=now,
        )
        return self._commit(
            command,
            record,
            "reflection_completed",
            _required(command.reason, "reason_required"),
        )

    def save_valuation_draft(
        self, command: SaveValuationDraftCommand, *, now: datetime
    ) -> ThesisRecord:
        current = self._owned(command.actor, command.thesis_id)
        if current.version != command.expected_thesis_version:
            raise ValueError("version_conflict")
        current_draft_version = (
            0 if current.valuation_draft is None else current.valuation_draft.version
        )
        if current_draft_version != command.expected_draft_version:
            raise ValueError("valuation_draft_conflict")
        if not command.method_confirmed:
            raise ValueError("valuation_method_unconfirmed")
        if command.benchmark_variant not in {"median", "p75"}:
            raise ValueError("invalid_benchmark_variant")
        validity = evaluate_validity(
            basis_date=command.basis_date,
            horizon_months=command.horizon_months,
            saved_at=now,
            evaluation_time=now,
            next_report_time=command.next_report_time,
            material_event_time=command.material_event_time,
        )
        selection_reason = _required(
            command.source_selection_reason, "source_selection_reason_required"
        )
        company_history = None
        peer_group = None
        abstentions: list[str] = []
        if command.method is ValuationMethod.ABSTAIN:
            if command.benchmark_source != "abstain":
                raise ValueError("invalid_benchmark_source")
            distribution = None
            result = None
        else:
            if command.cost_profile_version < 1:
                raise ValueError("cost_profile_required")
            if (
                command.forecast_source is None
                or command.forecast_source.record_type != "evidence"
            ):
                raise ValueError("forecast_source_required")
            if (
                command.forecast_confirmed_at is None
                or command.forecast_confirmed_at.tzinfo is None
            ):
                raise ValueError("forecast_unconfirmed")
            try:
                company_history = company_history_benchmark(
                    method=command.method,
                    target_company_id=current.company_id,
                    samples=command.company_history_samples,
                )
            except ValuationAbstained as error:
                abstentions.append(f"company_history:{error}")
            try:
                peer_group = peer_group_benchmark(
                    method=command.method,
                    target_company_id=current.company_id,
                    members=command.peer_members,
                )
            except ValuationAbstained as error:
                abstentions.append(f"peer_group:{error}")
            selected = (
                company_history
                if command.benchmark_source == "company_history"
                else peer_group
                if command.benchmark_source == "peer_group"
                else None
            )
            if selected is None:
                raise ValueError("selected_benchmark_abstained")
            distribution = selected.distribution
            multiple = (
                distribution.median
                if command.benchmark_variant == "median"
                else distribution.p75
            )
            result = annualized_net_return(
                forecast=command.forecast,
                multiple=multiple,
                quantity=command.quantity,
                buy_price=command.buy_price,
                cash_dividend=command.cash_dividend,
                buy_rate=command.buy_rate,
                minimum_buy_fee=command.minimum_buy_fee,
                sell_rate=command.sell_rate,
                minimum_sell_fee=command.minimum_sell_fee,
                tax_rate=command.tax_rate,
                holding_days=(validity.target_date - command.basis_date).days,
            )
        difference_median = None
        difference_p75 = None
        if company_history is not None and peer_group is not None:
            difference_median = (
                company_history.distribution.median - peer_group.distribution.median
            )
            difference_p75 = (
                company_history.distribution.p75 - peer_group.distribution.p75
            )
        draft = ValuationDraft(
            current_draft_version + 1,
            command.method,
            command.benchmark_source,
            command.benchmark_variant,
            command.peer_company_ids,
            distribution,
            validity,
            result,
            command.forecast,
            command.quantity,
            command.buy_price,
            command.cash_dividend,
            command.cost_profile_version,
            now,
            company_history,
            peer_group,
            difference_median,
            difference_p75,
            tuple(abstentions),
            selection_reason,
            command.forecast_source,
            command.forecast_confirmed_at,
            command.next_report_time,
            command.material_event_time,
            command.peer_members,
            basis_date=command.basis_date,
            horizon_months=command.horizon_months,
        )
        record = replace(
            current, version=current.version + 1, valuation_draft=draft, updated_at=now
        )
        return self._store.commit(
            actor_id=command.actor.actor_id,
            idempotency_key=_required(command.idempotency_key),
            command_digest=_digest(command),
            expected_version=command.expected_thesis_version,
            record=record,
            action="valuation_draft_saved",
            reason=_required(command.reason, "reason_required"),
        )

    def publish_valuation(
        self, command: PublishValuationCommand, *, now: datetime
    ) -> ThesisRecord:
        current = self._owned(command.actor, command.thesis_id)
        if current.version != command.expected_thesis_version:
            raise ValueError("version_conflict")
        if (
            current.valuation_draft is None
            or current.valuation_draft.version != command.expected_draft_version
        ):
            raise ValueError("valuation_draft_conflict")
        if now >= current.valuation_draft.validity.expires_at:
            raise ValueError("forecast_expired")
        if not command.confirmation_id:
            raise PermissionError("confirmation_required")
        snapshot = ValuationSnapshot(
            f"{current.thesis_id}:valuation:{len(current.valuation_snapshots) + 1}",
            len(current.valuation_snapshots) + 1,
            current.valuation_draft.version,
            current.valuation_draft,
            now,
            _required(command.reason, "reason_required"),
        )
        record = replace(
            current,
            version=current.version + 1,
            valuation_snapshots=current.valuation_snapshots + (snapshot,),
            updated_at=now,
        )
        return self._store.commit(
            actor_id=command.actor.actor_id,
            idempotency_key=_required(command.idempotency_key),
            command_digest=_digest(command),
            expected_version=command.expected_thesis_version,
            record=record,
            action="valuation_published",
            reason=snapshot.reason,
        )

    def invalidation_projection(
        self,
        actor: ThesisActorContext,
        thesis_id: str,
        thesis_version: int,
        condition_id: str,
        condition_version: int,
    ) -> ThesisInvalidationProjection:
        current = self._owned(actor, thesis_id)
        if current.version != thesis_version:
            raise ValueError("version_conflict")
        condition = next(
            (
                item
                for item in current.conditions
                if item.condition_id == condition_id
                and item.version == condition_version
                and item.active
            ),
            None,
        )
        if condition is None:
            raise LookupError("resource_unavailable")
        return ThesisInvalidationProjection(
            current.thesis_id,
            current.version,
            condition.condition_id,
            condition.version,
            condition.summary,
        )

    def _owned(self, actor: ThesisActorContext, thesis_id: str) -> ThesisRecord:
        self._authorize(actor)
        record = self._store.get(actor.actor_id, thesis_id)
        if record is None:
            raise PermissionError("resource_unavailable")
        return record

    @staticmethod
    def _conditions(
        thesis_id: str, values: tuple[str, ...]
    ) -> tuple[InvalidationCondition, ...]:
        normalized = tuple(_required(value) for value in values)
        if not normalized:
            raise ValueError("invalidation_condition_required")
        return tuple(
            InvalidationCondition(
                str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL, f"{thesis_id}:condition:{index}:{value}"
                    )
                ),
                1,
                value,
            )
            for index, value in enumerate(normalized)
        )

    @staticmethod
    def _validate_evidence(company_id: str, refs) -> None:
        if any(
            item.record_type != "evidence"
            or item.company_id != company_id
            or item.version < 1
            for item in refs
        ):
            raise ValueError("invalid_evidence_reference")

    @staticmethod
    def _validate_transition(current: ThesisRecord, target: ThesisStatus) -> None:
        edge = (current.status, target)
        if edge not in _DIRECT | _CONSEQUENTIAL:
            raise ValueError("invalid_transition")
        if target is ThesisStatus.ACTIVE and (
            not current.title.strip()
            or not current.narrative.strip()
            or not any(
                item.active and item.summary.strip() for item in current.conditions
            )
        ):
            raise ValueError("activation_prerequisites_missing")
        if target is ThesisStatus.CLOSED and (
            current.outcome is None or current.reflection is None
        ):
            raise ValueError("close_prerequisites_missing")

    def _commit(
        self, command, record: ThesisRecord, action: str, reason: str
    ) -> ThesisRecord:
        return self._store.commit(
            actor_id=command.actor.actor_id,
            idempotency_key=_required(command.idempotency_key),
            command_digest=_digest(command),
            expected_version=command.expected_version,
            record=record,
            action=action,
            reason=reason,
        )
