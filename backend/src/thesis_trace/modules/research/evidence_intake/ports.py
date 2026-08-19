from __future__ import annotations

from typing import Protocol

from thesis_trace.modules.research.evidence_intake.contracts import (
    CollectionRequest,
    EvidenceAccepted,
    EvidenceAuditFact,
    EvidenceRecord,
    CompanyRecord,
)


class EvidenceIntakeUnitOfWorkPort(Protocol):
    def create_company(self, ticker: str, name: str) -> CompanyRecord: ...

    def list_companies(self) -> list[CompanyRecord]: ...

    def get_company(self, company_id: str) -> CompanyRecord | None: ...

    def find_accepted(self, idempotency_key: str) -> EvidenceAccepted | None: ...

    def commit_admission(
        self,
        *,
        idempotency_key: str,
        record: EvidenceRecord,
        audit: EvidenceAuditFact,
        job: CollectionRequest,
        accepted: EvidenceAccepted,
    ) -> None: ...

    def get_record(self, evidence_id: str) -> EvidenceRecord | None: ...
