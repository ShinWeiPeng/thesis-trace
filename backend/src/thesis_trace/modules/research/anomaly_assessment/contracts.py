from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class ClueRoute(str, Enum):
    SAVE_ONLY = "save_only"
    WATCH_DAILY = "watch_daily"
    HUMAN_REVIEW = "human_review"


class AnomalyClass(str, Enum):
    SOFT = "soft"
    WOULD_BE_HARD = "would_be_hard"


class AssessmentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class SourceCharacteristicSnapshot:
    source_snapshot_id: str
    publisher_identity: str
    authoritative_first_party: bool = False
    formal_record: bool = False
    editorial_responsibility: bool = False
    attributed_author: bool = False
    verifiable_primary_evidence: bool = False
    underlying_evidence_id: str | None = None
    canonical_url: str | None = None
    excerpt: str | None = None
    retrieved_at: str | None = None
    published_at: str | None = None
    observed_at: str | None = None


@dataclass(frozen=True, slots=True)
class ClueFeatureVector:
    timeliness: int
    traceability: int
    specificity: int
    corroboration: int
    invalidation_relevance: int


@dataclass(frozen=True, slots=True)
class DecisionGate:
    gate: str
    passed: bool
    code: str


@dataclass(frozen=True, slots=True)
class AnomalyDecisionTrace:
    anomaly_class: AnomalyClass
    source_tiers: tuple[SourceTier, ...]
    clue_score: int | None
    clue_route: ClueRoute | None
    gates: tuple[DecisionGate, ...]
    policy_version: str

    @property
    def failure_codes(self) -> tuple[str, ...]:
        return tuple(gate.gate for gate in self.gates if not gate.passed)


@dataclass(frozen=True, slots=True)
class RequestAssessmentCommand:
    actor_id: str
    may_request: bool
    evidence_id: str
    expected_evidence_version: int
    sources: tuple[SourceCharacteristicSnapshot, ...]
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class EvaluateAssessmentCommand:
    assessment_id: str
    lease_token: str
    expected_assessment_version: int
    sources: tuple[SourceCharacteristicSnapshot, ...]
    direct_supporting_snapshot_ids: tuple[str, ...]
    predeclared_invalidation_matches: bool
    critic_passed: bool
    clue_features: ClueFeatureVector | None = None
    has_source_conflict: bool = False
    newer_authoritative_refutation: bool = False
    price_or_volume_only: bool = False
    novel_unsupported_event: bool = False


@dataclass(frozen=True, slots=True)
class AnomalyAnalysisJob:
    job_id: str
    assessment_id: str
    assessment_version: int
    evidence_id: str
    evidence_version: int
    lease_token: str | None
    attempt: int
    build_version: str
    policy_version: str
    candidate_schema_version: str
    candidate_prompt_version: str
    provider_model_version: str
    critic_schema_version: str
    critic_prompt_version: str
    critic_model_version: str


@dataclass(frozen=True, slots=True)
class AnomalyAnalysisVersions:
    build_version: str
    candidate_schema_version: str
    candidate_prompt_version: str
    provider_model_version: str
    critic_schema_version: str
    critic_prompt_version: str
    critic_model_version: str


@dataclass(frozen=True, slots=True)
class AnomalyAssessmentRecord:
    assessment_id: str
    version: int
    evidence_id: str
    evidence_version: int
    actor_id: str
    source_snapshot_ids: tuple[str, ...]
    status: AssessmentStatus
    reason: str
    requested_at: str
    trace: AnomalyDecisionTrace | None = None
    failure_code: str | None = None
    company_id: str = ""
    company_ticker: str = ""
    company_name: str = ""
