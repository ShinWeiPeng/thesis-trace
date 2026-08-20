from __future__ import annotations

from dataclasses import dataclass


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
