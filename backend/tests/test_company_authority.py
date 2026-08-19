from __future__ import annotations

import asyncio

import httpx

from thesis_trace.api import EvidenceApi, create_fastapi_app
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.platform.in_memory import InMemoryEvidenceStore


def owner() -> AuthenticatedActor:
    return AuthenticatedActor("owner-1", Role.OWNER, 1)


def test_company_is_created_listed_and_required_by_evidence_admission() -> None:
    store = InMemoryEvidenceStore()
    api = EvidenceApi(flow=EvidenceIntakeFlow(store=store, id_generator=iter(["ev-1"]).__next__))
    company = api.create_company(owner(), {"ticker": "2330", "name": "台積電"})

    assert company == {"company_id": "2330", "ticker": "2330", "name": "台積電", "version": 1}
    assert api.list_companies(owner()) == [company]
    assert api.submit_evidence(owner(), {"company_id": "missing", "company_version": 1,
        "url": "https://example.com/a", "idempotency_key": "missing"}) == {"error": "company_not_found"}


def test_fastapi_openapi_has_typed_company_and_evidence_schemas() -> None:
    store = InMemoryEvidenceStore()
    api = EvidenceApi(flow=EvidenceIntakeFlow(store=store, id_generator=lambda: "ev-1"))

    async def actor_provider() -> AuthenticatedActor:
        return owner()

    document = create_fastapi_app(api, actor_provider).openapi()
    submit = document["paths"]["/api/evidence"]["post"]
    create = document["paths"]["/api/companies"]["post"]
    assert submit["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("EvidenceSubmissionBody")
    assert submit["responses"]["202"]["content"]["application/json"]["schema"]["$ref"].endswith("EvidenceResponse")
    assert create["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith("CompanyResponse")
