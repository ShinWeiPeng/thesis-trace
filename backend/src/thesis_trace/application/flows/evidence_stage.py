from __future__ import annotations

from dataclasses import dataclass

from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research import (
    ResearchActorContext,
    ResearchStageConfirmationRequest,
    ResearchStageFacade,
    ResearchStageQuery,
    ResearchStageResult,
)


@dataclass(frozen=True, slots=True)
class ConfirmEvidenceStageRequest:
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
class QueryEvidenceStageRequest:
    evidence_id: str


@dataclass(frozen=True, slots=True)
class EvidenceStageFactsResult:
    source_confirmation: str
    product_established: bool
    commercialization_established: bool
    identifiable_revenue: bool
    identifiable_profit_or_cash_flow: bool
    consecutive_financial_quarters: int


@dataclass(frozen=True, slots=True)
class EvidenceStageGateResult:
    gate: str
    passed: bool
    code: str


@dataclass(frozen=True, slots=True)
class EvidenceStageResult:
    evidence_id: str
    version: int
    source_snapshot_id: str
    actor_id: str
    confirmed_at: str
    reason: str
    facts: EvidenceStageFactsResult
    stage: str
    gate_trace: tuple[EvidenceStageGateResult, ...]
    policy_version: str


class EvidenceStageFlow:
    """L0 mapping from authenticated Access actors into Research capabilities."""

    def __init__(self, *, research: ResearchStageFacade) -> None:
        self._research = research

    @staticmethod
    def _research_actor(actor: AuthenticatedActor) -> ResearchActorContext:
        return ResearchActorContext(
            actor_id=actor.actor_id,
            may_confirm_evidence_stage=actor.role is Role.OWNER,
            may_read_evidence_stage=actor.role in {Role.OWNER, Role.LEARNER},
        )

    @staticmethod
    def _result(record: ResearchStageResult) -> EvidenceStageResult:
        return EvidenceStageResult(
            evidence_id=record.evidence_id,
            version=record.version,
            source_snapshot_id=record.source_snapshot_id,
            actor_id=record.actor_id,
            confirmed_at=record.confirmed_at,
            reason=record.reason,
            facts=EvidenceStageFactsResult(
                source_confirmation=record.facts.source_confirmation,
                product_established=record.facts.product_established,
                commercialization_established=record.facts.commercialization_established,
                identifiable_revenue=record.facts.identifiable_revenue,
                identifiable_profit_or_cash_flow=record.facts.identifiable_profit_or_cash_flow,
                consecutive_financial_quarters=record.facts.consecutive_financial_quarters,
            ),
            stage=record.stage,
            gate_trace=tuple(
                EvidenceStageGateResult(item.gate, item.passed, item.code)
                for item in record.gate_trace
            ),
            policy_version=record.policy_version,
        )

    def confirm(
        self, actor: AuthenticatedActor, request: ConfirmEvidenceStageRequest
    ) -> EvidenceStageResult:
        record = self._research.confirm(
            self._research_actor(actor),
            ResearchStageConfirmationRequest(
                evidence_id=request.evidence_id,
                source_snapshot_id=request.source_snapshot_id,
                expected_version=request.expected_version,
                source_confirmation=request.source_confirmation,
                product_established=request.product_established,
                commercialization_established=request.commercialization_established,
                identifiable_revenue=request.identifiable_revenue,
                identifiable_profit_or_cash_flow=request.identifiable_profit_or_cash_flow,
                consecutive_financial_quarters=request.consecutive_financial_quarters,
                reason=request.reason,
                idempotency_key=request.idempotency_key,
            ),
        )
        return self._result(record)

    def get_stage(
        self, actor: AuthenticatedActor, request: QueryEvidenceStageRequest
    ) -> EvidenceStageResult:
        return self._result(
            self._research.get_stage(
                self._research_actor(actor), ResearchStageQuery(request.evidence_id)
            )
        )
