from __future__ import annotations

from dataclasses import dataclass

from thesis_trace.modules.access.contracts import AuthenticatedActor


@dataclass(frozen=True, slots=True)
class SubmitEvidenceRequest:
    actor: AuthenticatedActor
    company_id: str
    company_version: int
    url: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CreateCompanyCommand:
    actor: AuthenticatedActor
    ticker: str
    name: str


@dataclass(frozen=True, slots=True)
class ListCompaniesQuery:
    actor: AuthenticatedActor
