from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class ThesisStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    INVALIDATED = "invalidated"
    CLOSED = "closed"


class ValuationMethod(StrEnum):
    PE = "pe"
    PB = "pb"
    ABSTAIN = "abstain"


class ValuationCoverage(StrEnum):
    LIMITED_HISTORY = "limited_history"
    STANDARD_HISTORY = "standard_history"


@dataclass(frozen=True, slots=True)
class ValuationDistribution:
    median: Decimal
    p75: Decimal
    coverage: ValuationCoverage
    sample_count: int
    sorted_samples: tuple[Decimal, ...] = ()
    p75_position: Decimal = Decimal(0)
    p75_lower_index: int = 0
    p75_upper_index: int = 0
    p75_interpolation_fraction: Decimal = Decimal(0)
    policy_version: str = "valuation-benchmark-v1"


@dataclass(frozen=True, slots=True)
class ValuationSample:
    sample_id: str
    company_id: str
    observed_on: date
    multiple: Decimal
    denominator: Decimal
    source: ThesisResearchReference


@dataclass(frozen=True, slots=True)
class PeerValuationMember:
    company_id: str
    inclusion_reason: str
    method: ValuationMethod
    taiwan_listed: bool
    owner_confirmed: bool
    sample: ValuationSample


@dataclass(frozen=True, slots=True)
class ValuationBenchmarkSnapshot:
    source: str
    distribution: ValuationDistribution
    valid_samples: tuple[ValuationSample, ...]
    exclusions: tuple[str, ...]
    data_start: date
    data_end: date
    policy_version: str = "valuation-benchmark-snapshot-v1"


@dataclass(frozen=True, slots=True)
class ValuationValidity:
    target_date: date
    expires_at: datetime
    expiry_causes: tuple[str, ...]
    policy_version: str = "valuation-validity-v1"


@dataclass(frozen=True, slots=True)
class ValuationReturn:
    target_price: Decimal
    purchase_outflow: Decimal
    terminal_inflow: Decimal
    annualized_return: Decimal
    tax_disclaimer: str
    policy_version: str = "valuation-return-v1"


@dataclass(frozen=True, slots=True)
class ValuationDraft:
    version: int
    method: ValuationMethod
    benchmark_source: str
    benchmark_variant: str
    peer_company_ids: tuple[str, ...]
    distribution: ValuationDistribution | None
    validity: ValuationValidity
    result: ValuationReturn | None
    forecast: Decimal | None
    quantity: Decimal
    buy_price: Decimal
    cash_dividend: Decimal
    cost_profile_version: int
    saved_at: datetime
    company_history: ValuationBenchmarkSnapshot | None = None
    peer_group: ValuationBenchmarkSnapshot | None = None
    benchmark_difference_median: Decimal | None = None
    benchmark_difference_p75: Decimal | None = None
    benchmark_abstentions: tuple[str, ...] = ()
    source_selection_reason: str = ""
    forecast_source: ThesisResearchReference | None = None
    forecast_confirmed_at: datetime | None = None
    next_report_time: datetime | None = None
    material_event_time: datetime | None = None
    peer_members: tuple[PeerValuationMember, ...] = ()
    policy_version: str = "valuation-draft-v1"


@dataclass(frozen=True, slots=True)
class ValuationSnapshot:
    valuation_id: str
    version: int
    draft_version: int
    draft: ValuationDraft
    published_at: datetime
    reason: str
    policy_version: str = "valuation-publication-v1"


@dataclass(frozen=True, slots=True)
class ThesisActorContext:
    actor_id: str
    may_manage_personal_thesis: bool


@dataclass(frozen=True, slots=True)
class ThesisResearchReference:
    record_type: str
    record_id: str
    version: int
    company_id: str
    fact_id: str | None = None


@dataclass(frozen=True, slots=True)
class InvalidationCondition:
    condition_id: str
    version: int
    summary: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class ThesisOutcome:
    outcome_id: str
    version: int
    cycle: int
    observed_at: datetime
    result: str
    evidence_refs: tuple[ThesisResearchReference, ...]


@dataclass(frozen=True, slots=True)
class ReflectionDraftRevision:
    revision: int
    cycle: int
    original_assumption: str
    judgment_errors: str
    missing_evidence: str
    improvement: str
    saved_at: datetime


@dataclass(frozen=True, slots=True)
class ThesisReflection:
    reflection_id: str
    version: int
    cycle: int
    original_assumption: str
    judgment_errors: str
    missing_evidence: str
    improvement: str


@dataclass(frozen=True, slots=True)
class ThesisRecord:
    thesis_id: str
    version: int
    owner_user_id: str
    company_id: str
    company_version: int
    title: str
    narrative: str
    status: ThesisStatus
    cycle: int
    reflection_pending: bool
    created_at: datetime
    updated_at: datetime
    conditions: tuple[InvalidationCondition, ...]
    evidence_refs: tuple[ThesisResearchReference, ...]
    outcome: ThesisOutcome | None
    reflection: ThesisReflection | None
    reflection_draft: ReflectionDraftRevision | None
    valuation_draft: ValuationDraft | None = None
    valuation_snapshots: tuple[ValuationSnapshot, ...] = ()
    policy_version: str = "thesis-lifecycle-v1"


@dataclass(frozen=True, slots=True)
class CreateThesisCommand:
    actor: ThesisActorContext
    company: ThesisResearchReference
    title: str
    narrative: str
    invalidation_conditions: tuple[str, ...]
    evidence_refs: tuple[ThesisResearchReference, ...]
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SaveThesisCommand:
    actor: ThesisActorContext
    thesis_id: str
    expected_version: int
    title: str
    narrative: str
    invalidation_conditions: tuple[str, ...]
    evidence_refs: tuple[ThesisResearchReference, ...]
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class TransitionThesisCommand:
    actor: ThesisActorContext
    thesis_id: str
    expected_version: int
    target: ThesisStatus
    reason: str
    idempotency_key: str
    confirmation_id: str | None = None


@dataclass(frozen=True, slots=True)
class SaveOutcomeCommand:
    actor: ThesisActorContext
    thesis_id: str
    expected_version: int
    observed_at: datetime
    result: str
    evidence_refs: tuple[ThesisResearchReference, ...]
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SaveReflectionDraftCommand:
    actor: ThesisActorContext
    thesis_id: str
    expected_draft_version: int
    field: str
    text: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CompleteReflectionCommand:
    actor: ThesisActorContext
    thesis_id: str
    expected_version: int
    original_assumption: str
    judgment_errors: str
    missing_evidence: str
    improvement: str
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SaveValuationDraftCommand:
    actor: ThesisActorContext
    thesis_id: str
    expected_thesis_version: int
    expected_draft_version: int
    method: ValuationMethod
    benchmark_source: str
    benchmark_variant: str
    peer_company_ids: tuple[str, ...]
    samples: tuple[Decimal, ...]
    basis_date: date
    horizon_months: int
    forecast: Decimal
    quantity: Decimal
    buy_price: Decimal
    cash_dividend: Decimal
    buy_rate: Decimal
    minimum_buy_fee: Decimal
    sell_rate: Decimal
    minimum_sell_fee: Decimal
    tax_rate: Decimal
    cost_profile_version: int
    reason: str
    idempotency_key: str
    company_history_samples: tuple[ValuationSample, ...] = ()
    peer_members: tuple[PeerValuationMember, ...] = ()
    source_selection_reason: str = ""
    forecast_source: ThesisResearchReference | None = None
    forecast_confirmed_at: datetime | None = None
    next_report_time: datetime | None = None
    material_event_time: datetime | None = None
    method_confirmed: bool = False


@dataclass(frozen=True, slots=True)
class PublishValuationCommand:
    actor: ThesisActorContext
    thesis_id: str
    expected_thesis_version: int
    expected_draft_version: int
    confirmation_id: str
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ThesisInvalidationProjection:
    thesis_id: str
    thesis_version: int
    condition_id: str
    condition_version: int
    condition_summary: str


@dataclass(frozen=True, slots=True)
class ThesisTransitionPreview:
    thesis_id: str
    target_version: int
    from_status: ThesisStatus
    to_status: ThesisStatus
    consequences: tuple[str, ...]
