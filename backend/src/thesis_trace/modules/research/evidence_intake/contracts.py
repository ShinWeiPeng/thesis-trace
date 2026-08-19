from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class CompanyRecord:
    company_id: str
    ticker: str
    name: str
    version: int


@dataclass(frozen=True, slots=True)
class EvidenceAccepted:
    evidence_id: str
    version: int


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    accepted: EvidenceAccepted | None = None
    rejection_code: str | None = None

    @property
    def evidence_id(self) -> str:
        if self.accepted is None:
            raise AttributeError("submission was not accepted")
        return self.accepted.evidence_id

    @property
    def version(self) -> int:
        if self.accepted is None:
            raise AttributeError("submission was not accepted")
        return self.accepted.version


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    version: int
    company_id: str
    company_version: int
    url: str
    status: EvidenceStatus


@dataclass(frozen=True, slots=True)
class EvidenceStatusSnapshot:
    evidence_id: str
    version: int
    status: EvidenceStatus


@dataclass(frozen=True, slots=True)
class EvidenceAuditFact:
    actor_id: str
    action: str
    subject_id: str
    subject_version: int


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    evidence_id: str
    evidence_version: int
    url: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class LeasedCollectionJob:
    job_id: str
    evidence_id: str
    evidence_version: int
    url: str
    idempotency_key: str
    lease_token: str
    attempt: int
