"""Research-domain parent mappings and public orchestration facade."""

from __future__ import annotations

from dataclasses import dataclass

from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    DimensionFacts,
    EvidenceStageRecord,
    SourceConfirmation,
    StageActorContext,
)
from thesis_trace.modules.research.evidence_stage.service import EvidenceStageService


@dataclass(frozen=True, slots=True)
class ResearchActorContext:
    actor_id: str
    may_confirm_evidence_stage: bool
    may_read_evidence_stage: bool


@dataclass(frozen=True, slots=True)
class ResearchStageConfirmationRequest:
    evidence_id: str
    source_snapshot_id: str
    expected_version: int
    source_confirmation: str
    product_established: bool
    commercialization_established: bool
    identifiable_revenue: bool
    identifiable_profit_or_cash_flow: bool
    consecutive_financial_quarters: int
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResearchStageQuery:
    evidence_id: str


@dataclass(frozen=True, slots=True)
class ResearchStageFacts:
    source_confirmation: str
    product_established: bool
    commercialization_established: bool
    identifiable_revenue: bool
    identifiable_profit_or_cash_flow: bool
    consecutive_financial_quarters: int


@dataclass(frozen=True, slots=True)
class ResearchStageGate:
    gate: str
    passed: bool
    code: str


@dataclass(frozen=True, slots=True)
class ResearchStageResult:
    evidence_id: str
    version: int
    source_snapshot_id: str
    actor_id: str
    confirmed_at: str
    reason: str
    facts: ResearchStageFacts
    stage: str
    gate_trace: tuple[ResearchStageGate, ...]
    policy_version: str


class ResearchStageFacade:
    """Map Research-parent primitives into the Evidence Stage child boundary."""

    def __init__(self, service: EvidenceStageService) -> None:
        self._service = service

    @staticmethod
    def _stage_actor(actor: ResearchActorContext) -> StageActorContext:
        return StageActorContext(
            actor_id=actor.actor_id,
            may_confirm=actor.may_confirm_evidence_stage,
            may_read=actor.may_read_evidence_stage,
        )

    @staticmethod
    def _result(record: EvidenceStageRecord) -> ResearchStageResult:
        return ResearchStageResult(
            evidence_id=record.evidence_id,
            version=record.version,
            source_snapshot_id=record.source_snapshot_id,
            actor_id=record.actor_id,
            confirmed_at=record.confirmed_at,
            reason=record.reason,
            facts=ResearchStageFacts(
                source_confirmation=record.facts.source_confirmation.value,
                product_established=record.facts.product_established,
                commercialization_established=record.facts.commercialization_established,
                identifiable_revenue=record.facts.identifiable_revenue,
                identifiable_profit_or_cash_flow=record.facts.identifiable_profit_or_cash_flow,
                consecutive_financial_quarters=record.facts.consecutive_financial_quarters,
            ),
            stage=record.evaluation.stage.value,
            gate_trace=tuple(
                ResearchStageGate(item.gate.value, item.passed, item.code)
                for item in record.evaluation.gate_trace
            ),
            policy_version=record.policy_version,
        )

    def confirm(
        self,
        actor: ResearchActorContext,
        request: ResearchStageConfirmationRequest,
    ) -> ResearchStageResult:
        record = self._service.confirm(
            ConfirmDimensionFactsCommand(
                actor=self._stage_actor(actor),
                evidence_id=request.evidence_id,
                source_snapshot_id=request.source_snapshot_id,
                expected_version=request.expected_version,
                facts=DimensionFacts(
                    source_confirmation=SourceConfirmation(request.source_confirmation),
                    product_established=request.product_established,
                    commercialization_established=request.commercialization_established,
                    identifiable_revenue=request.identifiable_revenue,
                    identifiable_profit_or_cash_flow=request.identifiable_profit_or_cash_flow,
                    consecutive_financial_quarters=request.consecutive_financial_quarters,
                ),
                reason=request.reason,
                idempotency_key=request.idempotency_key,
            )
        )
        return self._result(record)

    def get_stage(
        self, actor: ResearchActorContext, query: ResearchStageQuery
    ) -> ResearchStageResult:
        return self._result(
            self._service.get_stage(self._stage_actor(actor), query.evidence_id)
        )
