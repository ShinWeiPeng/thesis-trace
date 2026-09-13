from __future__ import annotations

from collections.abc import Callable

from thesis_trace.application.contracts import CreateCompanyCommand, ListCompaniesQuery, SubmitEvidenceRequest
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research.evidence_intake.contracts import (
    EvidenceAccepted,
    EvidenceAuditFact,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceStatusSnapshot,
    SubmissionResult,
    CollectionRequest,
)
from thesis_trace.modules.research.evidence_intake.ports import EvidenceIntakeUnitOfWorkPort


class EvidenceIntakeFlow:
    def __init__(
        self,
        *,
        store: EvidenceIntakeUnitOfWorkPort,
        id_generator: Callable[[], str],
    ) -> None:
        self._store = store
        self._id_generator = id_generator

    def submit(self, request: SubmitEvidenceRequest) -> SubmissionResult:
        if request.actor.role is not Role.OWNER:
            return SubmissionResult(rejection_code="forbidden")
        if not _is_admissible_url(request.url):
            return SubmissionResult(rejection_code="invalid_url")
        if not request.company_id or request.company_version < 1 or not request.idempotency_key:
            return SubmissionResult(rejection_code="invalid")
        company = self._store.get_company(request.company_id)
        if company is None:
            return SubmissionResult(rejection_code="company_not_found")
        if company.version != request.company_version:
            return SubmissionResult(rejection_code="company_version_conflict")

        replay = self._store.find_accepted(request.idempotency_key)
        if replay is not None:
            return SubmissionResult(accepted=replay)

        evidence_id = self._id_generator()
        record = EvidenceRecord(
            evidence_id=evidence_id,
            version=1,
            company_id=request.company_id,
            company_version=request.company_version,
            url=request.url,
            status=EvidenceStatus.RECEIVED,
        )
        accepted = EvidenceAccepted(evidence_id=evidence_id, version=1)
        self._store.commit_admission(
            idempotency_key=request.idempotency_key,
            record=record,
            audit=EvidenceAuditFact(
                actor_id=request.actor.actor_id,
                action="evidence.received",
                subject_id=evidence_id,
                subject_version=1,
            ),
            job=CollectionRequest(
                evidence_id=evidence_id,
                evidence_version=1,
                url=request.url,
                idempotency_key=f"collect:{evidence_id}:1",
            ),
            accepted=accepted,
        )
        return SubmissionResult(accepted=accepted)

    def create_company(self, command: CreateCompanyCommand):
        if command.actor.role is not Role.OWNER:
            raise PermissionError("forbidden")
        return self._store.create_company(command.ticker, command.name)

    def list_companies(self, query: ListCompaniesQuery):
        if query.actor.role is not Role.OWNER:
            raise PermissionError("forbidden")
        return self._store.list_companies()

    def get_status(self, actor: AuthenticatedActor, evidence_id: str) -> EvidenceStatusSnapshot:
        if actor.role is not Role.OWNER:
            raise PermissionError("forbidden")
        record = self._store.get_record(evidence_id)
        if record is None:
            raise LookupError("not_found")
        return EvidenceStatusSnapshot(
            evidence_id=record.evidence_id,
            version=record.version,
            status=record.status,
            source_snapshot_id=self._store.get_source_snapshot_id(evidence_id),
        )


def _is_admissible_url(value: str) -> bool:
    from urllib.parse import urlsplit

    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname)
