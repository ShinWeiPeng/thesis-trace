from __future__ import annotations

from typing import Protocol

from thesis_trace.modules.research.evidence_collection.contracts import (
    CollectedSourceSnapshot,
    FetchedSource,
)
from thesis_trace.modules.research.evidence_intake.contracts import EvidenceStatus, LeasedCollectionJob


class SourceFetchPort(Protocol):
    def fetch(self, url: str) -> FetchedSource: ...


class CollectionStorePort(Protocol):
    def claim_collection_job(self) -> LeasedCollectionJob | None: ...

    def transition(self, evidence_id: str, status: EvidenceStatus) -> None: ...

    def complete_collection(
        self,
        evidence_id: str,
        snapshot: CollectedSourceSnapshot,
        lease_token: str | None = None,
    ) -> bool | None: ...

    def fail_collection(
        self,
        job: LeasedCollectionJob,
        lease_token: str,
        failure_code: str,
        *,
        retryable: bool,
    ) -> bool: ...
