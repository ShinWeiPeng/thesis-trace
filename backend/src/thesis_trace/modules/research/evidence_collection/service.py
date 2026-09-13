from __future__ import annotations

from hashlib import sha256

from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot
from thesis_trace.modules.research.evidence_collection.ports import CollectionStorePort, SourceFetchPort
from thesis_trace.modules.research.evidence_intake.contracts import EvidenceStatus


class EvidenceCollector:
    def __init__(
        self,
        *,
        store: CollectionStorePort,
        source_fetcher: SourceFetchPort,
    ) -> None:
        self._store = store
        self._source_fetcher = source_fetcher

    def run_once(self) -> bool:
        job = self._store.claim_collection_job()
        if job is None:
            return False
        try:
            fetched = self._source_fetcher.fetch(job.url)
        except Exception as error:
            code = getattr(error, "failure_code", "source_unavailable")
            retryable = bool(getattr(error, "retryable", True))
            self._store.fail_collection(job, job.lease_token, code, retryable=retryable)
            return True
        snapshot = CollectedSourceSnapshot(
            canonical_url=fetched.canonical_url,
            publisher=fetched.publisher,
            content_hash=sha256(fetched.content).hexdigest(),
            retrieved_at=fetched.retrieved_at,
            normalization_policy_version=fetched.normalization_policy_version,
            published_at=fetched.published_at,
            observed_at=fetched.observed_at,
            excerpt=fetched.excerpt,
            source_category=fetched.source_category,
            lineage=fetched.lineage,
        )
        self._store.complete_collection(job.evidence_id, snapshot, job.lease_token)
        return True
