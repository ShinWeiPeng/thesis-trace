from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


URL_NORMALIZATION_POLICY_V1 = "url-normalization-v1"


@dataclass(frozen=True, slots=True)
class FetchedSource:
    canonical_url: str
    publisher: str
    content: bytes
    retrieved_at: str
    normalization_policy_version: str = URL_NORMALIZATION_POLICY_V1
    published_at: str | None = None
    observed_at: str | None = None
    excerpt: str | None = None
    source_category: str = "C"
    lineage: str | None = None


@dataclass(frozen=True, slots=True)
class CollectedSourceSnapshot:
    canonical_url: str
    publisher: str
    content_hash: str
    retrieved_at: str
    normalization_policy_version: str = URL_NORMALIZATION_POLICY_V1
    published_at: str | None = None
    observed_at: str | None = None
    excerpt: str | None = None
    source_category: str = "C"
    lineage: str | None = None


@dataclass(frozen=True, slots=True)
class ValuationSourceFact:
    """A server-ingested valuation fact bound to one immutable source snapshot."""

    fact_id: str
    evidence_id: str
    evidence_version: int
    source_snapshot_id: str
    company_id: str
    method: str
    fact_kind: str
    observed_on: date
    value: Decimal
    denominator: Decimal | None = None
    confirmed_at: datetime | None = None
    next_report_time: datetime | None = None
    material_event_time: datetime | None = None
    policy_version: str = "valuation-source-fact-v1"
    target_date: date | None = None
