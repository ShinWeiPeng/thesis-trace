from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceStage(str, Enum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"
    E4 = "E4"
    E5 = "E5"
    E6 = "E6"


class SourceConfirmation(str, Enum):
    UNVERIFIED = "unverified"
    OFFICIAL = "official"
    TWO_INDEPENDENT_CREDIBLE = "two_independent_credible"


@dataclass(frozen=True, slots=True)
class DimensionFacts:
    source_confirmation: SourceConfirmation
    product_established: bool
    commercialization_established: bool
    identifiable_revenue: bool
    identifiable_profit_or_cash_flow: bool
    consecutive_financial_quarters: int


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: EvidenceStage
    passed: bool
    code: str


@dataclass(frozen=True, slots=True)
class StageEvaluation:
    stage: EvidenceStage
    gate_trace: tuple[GateResult, ...]
    abstention_code: str | None = None


@dataclass(frozen=True, slots=True)
class StageActorContext:
    actor_id: str
    may_confirm: bool
    may_read: bool


@dataclass(frozen=True, slots=True)
class ConfirmDimensionFactsCommand:
    actor: StageActorContext
    evidence_id: str
    source_snapshot_id: str
    expected_version: int
    facts: DimensionFacts
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class EvidenceStageRecord:
    evidence_id: str
    version: int
    source_snapshot_id: str
    actor_id: str
    confirmed_at: str
    reason: str
    facts: DimensionFacts
    evaluation: StageEvaluation
    policy_version: str


def confirmation_matches(
    record: EvidenceStageRecord,
    command: ConfirmDimensionFactsCommand,
    evaluation: StageEvaluation,
    policy_version: str,
) -> bool:
    """Return whether an idempotent replay is exactly the committed command."""
    return (
        record.evidence_id == command.evidence_id
        and record.source_snapshot_id == command.source_snapshot_id
        and record.actor_id == command.actor.actor_id
        and record.version - 1 == command.expected_version
        and record.reason == command.reason
        and record.facts == command.facts
        and record.evaluation == evaluation
        and record.policy_version == policy_version
    )
