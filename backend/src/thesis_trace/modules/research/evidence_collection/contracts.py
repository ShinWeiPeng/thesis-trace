from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FetchedSource:
    canonical_url: str
    publisher: str
    content: bytes
    retrieved_at: str
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
    published_at: str | None = None
    observed_at: str | None = None
    excerpt: str | None = None
    source_category: str = "C"
    lineage: str | None = None
