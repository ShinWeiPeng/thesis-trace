from __future__ import annotations

from thesis_trace.modules.research.evidence_intake.contracts import (
    CollectionRequest,
    EvidenceAccepted,
    CompanyRecord,
    EvidenceAuditFact,
    EvidenceRecord,
    EvidenceStatus,
    LeasedCollectionJob,
)
import uuid
from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot


class InMemoryEvidenceStore:
    """Deterministic test adapter implementing the atomic admission boundary."""

    def __init__(self) -> None:
        self.records: dict[str, EvidenceRecord] = {}
        self.companies: dict[str, CompanyRecord] = {}
        self.audit_events: list[EvidenceAuditFact] = []
        self.collection_jobs: list[CollectionRequest] = []
        self.source_snapshots: dict[str, CollectedSourceSnapshot] = {}
        self._accepted_by_key: dict[str, EvidenceAccepted] = {}

    def create_company(self, ticker: str, name: str) -> CompanyRecord:
        ticker = ticker.strip()
        name = name.strip()
        if not ticker or not name:
            raise ValueError("invalid_company")
        if ticker in self.companies:
            raise ValueError("company_exists")
        company = CompanyRecord(ticker, ticker, name, 1)
        self.companies[ticker] = company
        return company

    def list_companies(self) -> list[CompanyRecord]:
        return sorted(self.companies.values(), key=lambda item: item.ticker)

    def get_company(self, company_id: str) -> CompanyRecord | None:
        return self.companies.get(company_id)

    def find_accepted(self, idempotency_key: str) -> EvidenceAccepted | None:
        return self._accepted_by_key.get(idempotency_key)

    def commit_admission(
        self,
        *,
        idempotency_key: str,
        record: EvidenceRecord,
        audit: EvidenceAuditFact,
        job: CollectionRequest,
        accepted: EvidenceAccepted,
    ) -> None:
        if idempotency_key in self._accepted_by_key:
            return
        if record.evidence_id in self.records:
            raise ValueError("duplicate evidence id")
        self.records[record.evidence_id] = record
        self.audit_events.append(audit)
        self.collection_jobs.append(job)
        self._accepted_by_key[idempotency_key] = accepted

    def get_record(self, evidence_id: str) -> EvidenceRecord | None:
        return self.records.get(evidence_id)

    def claim_collection_job(self) -> LeasedCollectionJob | None:
        if not self.collection_jobs:
            return None
        job = self.collection_jobs.pop(0)
        self.transition(job.evidence_id, EvidenceStatus.PROCESSING)
        return LeasedCollectionJob(
            job_id=str(uuid.uuid4()), evidence_id=job.evidence_id,
            evidence_version=job.evidence_version, url=job.url,
            idempotency_key=job.idempotency_key, lease_token=str(uuid.uuid4()), attempt=1,
        )

    def transition(self, evidence_id: str, status: EvidenceStatus) -> None:
        current = self.records[evidence_id]
        self.records[evidence_id] = EvidenceRecord(
            evidence_id=current.evidence_id,
            version=current.version + 1,
            company_id=current.company_id,
            company_version=current.company_version,
            url=current.url,
            status=status,
        )

    def complete_collection(
        self,
        evidence_id: str,
        snapshot: CollectedSourceSnapshot,
        lease_token: str | None = None,
    ) -> bool:
        self.source_snapshots[evidence_id] = snapshot
        self.transition(evidence_id, EvidenceStatus.SUCCEEDED)
        return True

    def fail_collection(self, job: LeasedCollectionJob, lease_token: str,
                        failure_code: str, *, retryable: bool) -> bool:
        if lease_token != job.lease_token:
            return False
        status = EvidenceStatus.RETRYING if retryable else EvidenceStatus.FAILED
        self.transition(job.evidence_id, status)
        return True
