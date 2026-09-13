from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BoundRecommendationInput:
    owner_domain: str
    record_id: str
    version: int
    digest: str
    valid_until: datetime | None


@dataclass(frozen=True, slots=True)
class RecommendationActor:
    actor_id: str
    may_manage: bool


@dataclass(frozen=True, slots=True)
class OwnerDecision:
    recommendation_id: str
    recommendation_version: int
    sequence: int
    status: str
    reason: str
    actor_id: str
    recorded_at: datetime
    defer_until: datetime | None
    policy_version: str
    input_checks: tuple[tuple[str, str], ...] = ()
    confirmation_id: str | None = None


@dataclass(frozen=True, slots=True)
class RecommendationSource:
    snapshot_id: str
    publisher: str
    excerpt: str
    canonical_url: str
    published_at: datetime | None
    observed_at: datetime | None
    retrieved_at: datetime
    source_category: str | None = None
    lineage: str | None = None


@dataclass(frozen=True, slots=True)
class RecommendationCandidate:
    direction: str
    raw_dca_ceiling: Decimal
    claims: tuple[tuple[str, tuple[str, ...]], ...]
    schema_version: str
    digest: str


@dataclass(frozen=True, slots=True)
class RecommendationInputSnapshot:
    actor: RecommendationActor
    thesis_id: str
    cycle: int
    bindings: tuple[BoundRecommendationInput, ...]
    sources: tuple[RecommendationSource, ...]
    valuation_id: str
    portfolio_snapshot_id: str | None
    source_selection_reason: str
    gate_reasons: tuple[str, ...]
    company_id: str
    benchmark_source: str
    admitted_at: datetime
    analysis_context: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RecommendationRecord:
    recommendation_id: str
    version: int
    inputs: RecommendationInputSnapshot
    candidate: RecommendationCandidate
    final_multiplier: Decimal
    published_at: datetime
    policy_version: str
    direction: str
    reasons: tuple[str, ...]
    annualized_return: Decimal | None
    minimum_return: Decimal | None
    calculation_trace: tuple[tuple[str, str], ...]
    provenance: tuple[tuple[str, str], ...]
    critic_evidence: str


@dataclass(frozen=True, slots=True)
class RecommendationJob:
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
