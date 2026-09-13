from __future__ import annotations

from collections.abc import Callable

from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    DimensionFacts,
    EvidenceStage,
    EvidenceStageRecord,
    GateResult,
    SourceConfirmation,
    StageActorContext,
    StageEvaluation,
)
from thesis_trace.modules.research.evidence_stage.ports import EvidenceStageStorePort


E_STAGE_POLICY_VERSION = "e-stage-v1"


def derive_stage(facts: DimensionFacts) -> StageEvaluation:
    """Derive the highest sequentially satisfied E-stage with a complete trace."""
    if facts.consecutive_financial_quarters < 0:
        return StageEvaluation(
            stage=EvidenceStage.E0,
            gate_trace=(),
            abstention_code="invalid_consecutive_financial_quarters",
        )
    predicates = (
        facts.source_confirmation is not SourceConfirmation.UNVERIFIED,
        facts.product_established,
        facts.commercialization_established,
        facts.identifiable_revenue,
        facts.identifiable_profit_or_cash_flow,
        facts.consecutive_financial_quarters >= 2,
    )
    gates = tuple(EvidenceStage(f"E{index}") for index in range(1, 7))
    trace: list[GateResult] = []
    prerequisites_passed = True
    highest = EvidenceStage.E0
    for gate, predicate in zip(gates, predicates, strict=True):
        passed = prerequisites_passed and predicate
        code = "passed" if passed else ("predicate_unmet" if prerequisites_passed else "prerequisite_unmet")
        trace.append(GateResult(gate=gate, passed=passed, code=code))
        if passed:
            highest = gate
        prerequisites_passed = passed
    return StageEvaluation(stage=highest, gate_trace=tuple(trace))


class EvidenceStageService:
    def __init__(self, *, store: EvidenceStageStorePort, clock: Callable[[], str]) -> None:
        self._store = store
        self._clock = clock

    def confirm(self, command: ConfirmDimensionFactsCommand) -> EvidenceStageRecord:
        if not command.actor.may_confirm:
            raise PermissionError("forbidden")
        if command.facts.source_confirmation is SourceConfirmation.TWO_INDEPENDENT_CREDIBLE:
            raise ValueError("insufficient_independent_sources")
        reason = command.reason.strip()
        if not reason:
            raise ValueError("invalid_reason")
        evaluation = derive_stage(command.facts)
        if evaluation.abstention_code is not None:
            raise ValueError(evaluation.abstention_code)
        normalized = ConfirmDimensionFactsCommand(
            actor=command.actor,
            evidence_id=command.evidence_id,
            source_snapshot_id=command.source_snapshot_id,
            expected_version=command.expected_version,
            facts=command.facts,
            reason=reason,
            idempotency_key=command.idempotency_key,
        )
        return self._store.commit_confirmation(
            command=normalized,
            evaluation=evaluation,
            confirmed_at=self._clock(),
            policy_version=E_STAGE_POLICY_VERSION,
        )

    def get_stage(self, actor: StageActorContext, evidence_id: str) -> EvidenceStageRecord:
        if not actor.may_read:
            raise PermissionError("resource_unavailable")
        record = self._store.get_stage(evidence_id)
        if record is None:
            raise LookupError("resource_unavailable")
        return record
