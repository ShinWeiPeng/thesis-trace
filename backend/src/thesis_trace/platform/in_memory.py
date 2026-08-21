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
from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    EvidenceStageRecord,
    StageEvaluation,
    confirmation_matches,
)


class InMemoryEvidenceStore:
    """Deterministic test adapter implementing the atomic admission boundary."""

    def __init__(self) -> None:
        self.records: dict[str, EvidenceRecord] = {}
        self.companies: dict[str, CompanyRecord] = {}
        self.audit_events: list[EvidenceAuditFact] = []
        self.collection_jobs: list[CollectionRequest] = []
        self.source_snapshots: dict[str, CollectedSourceSnapshot] = {}
        self._accepted_by_key: dict[str, EvidenceAccepted] = {}
        self.stage_records: dict[str, EvidenceStageRecord] = {}
        self._stage_by_idempotency_key: dict[str, EvidenceStageRecord] = {}

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

    def get_source_snapshot_id(self, evidence_id: str) -> str | None:
        return evidence_id if evidence_id in self.source_snapshots else None

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

    def commit_confirmation(
        self,
        *,
        command: ConfirmDimensionFactsCommand,
        evaluation: StageEvaluation,
        confirmed_at: str,
        policy_version: str,
    ) -> EvidenceStageRecord:
        replay = self._stage_by_idempotency_key.get(command.idempotency_key)
        if replay is not None:
            if not confirmation_matches(replay, command, evaluation, policy_version):
                raise ValueError("idempotency_conflict")
            return replay
        evidence = self.records.get(command.evidence_id)
        if evidence is None or evidence.status is not EvidenceStatus.SUCCEEDED:
            raise LookupError("resource_unavailable")
        if command.source_snapshot_id != command.evidence_id or command.evidence_id not in self.source_snapshots:
            raise LookupError("resource_unavailable")
        current = self.stage_records.get(command.evidence_id)
        current_version = 0 if current is None else current.version
        if command.expected_version != current_version:
            raise ValueError("version_conflict")
        record = EvidenceStageRecord(
            evidence_id=command.evidence_id,
            version=current_version + 1,
            source_snapshot_id=command.source_snapshot_id,
            actor_id=command.actor.actor_id,
            confirmed_at=confirmed_at,
            reason=command.reason,
            facts=command.facts,
            evaluation=evaluation,
            policy_version=policy_version,
        )
        self.stage_records[command.evidence_id] = record
        self._stage_by_idempotency_key[command.idempotency_key] = record
        return record

    def get_stage(self, evidence_id: str) -> EvidenceStageRecord | None:
        return self.stage_records.get(evidence_id)
