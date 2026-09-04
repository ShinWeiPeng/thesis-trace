from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

httpx = pytest.importorskip("httpx")

from thesis_trace.api import EvidenceApi, create_fastapi_app
from thesis_trace.application.contracts import ThesisLifecycleFlow
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research.evidence_intake.contracts import CompanyRecord
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.platform.in_memory import InMemoryEvidenceStore
from test_thesis_domain import MemoryThesisStore


class ResearchStub:
    def get_company(self, company_id: str):
        return CompanyRecord("company-1", "TT", "Thesis Trace", 1) if company_id == "company-1" else None

    def get_record(self, _evidence_id: str):
        return None


def test_thesis_http_contract_uses_server_versions_and_rejects_authority_injection() -> None:
    async def actor_provider() -> AuthenticatedActor:
        return AuthenticatedActor("owner-1", Role.OWNER, 1)

    thesis_flow = ThesisLifecycleFlow(
        ThesisService(MemoryThesisStore(), id_factory=lambda: "thesis-1"),
        ResearchStub(),
        clock=lambda: datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc),
    )
    api = EvidenceApi(
        flow=EvidenceIntakeFlow(store=InMemoryEvidenceStore(), id_generator=lambda: "unused"),
        thesis_flow=thesis_flow,
    )
    app = create_fastapi_app(api, actor_provider)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/companies/company-1/theses", json={
                "company_version": 1,
                "title": "AI server demand",
                "narrative": "Demand supports durable cash flow.",
                "invalidation_conditions": ["Server revenue declines"],
                "evidence_refs": [],
                "reason": "Create thesis",
                "idempotency_key": "create-1",
            })
            injected = await client.post("/api/companies/company-1/theses", json={
                "company_version": 1,
                "title": "Injected",
                "narrative": "Injected",
                "invalidation_conditions": ["Injected"],
                "evidence_refs": [],
                "reason": "Create thesis",
                "idempotency_key": "create-2",
                "owner_user_id": "attacker",
                "status": "active",
            })
            listed = await client.get("/api/companies/company-1/theses")
            transitioned = await client.post("/api/theses/thesis-1/transitions", json={
                "expected_version": 1,
                "target_status": "active",
                "reason": "Publish",
                "idempotency_key": "activate-1",
            })
            stale = await client.post("/api/theses/thesis-1/transitions", json={
                "expected_version": 1,
                "target_status": "paused",
                "reason": "Stale",
                "idempotency_key": "pause-stale",
            })
            return created, injected, listed, transitioned, stale

    created, injected, listed, transitioned, stale = asyncio.run(exercise())
    assert created.status_code == 201
    assert created.json()["owner_user_id"] == "owner-1"
    assert injected.status_code == 422
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert transitioned.status_code == 200 and transitioned.json()["status"] == "active"
    assert stale.status_code == 409 and stale.json()["detail"] == "version_conflict"
    schema = app.openapi()["components"]["schemas"]["ThesisCreateBody"]
    assert schema["additionalProperties"] is False
    assert "owner_user_id" not in schema["properties"]
    assert "status" not in schema["properties"]
    valuation_schema = app.openapi()["components"]["schemas"]["ValuationDraftSaveBody"]
    assert valuation_schema["additionalProperties"] is False
    for client_authority_field in (
        "forecast", "forecast_confirmed_at", "next_report_time", "material_event_time",
    ):
        assert client_authority_field not in valuation_schema["properties"]
    source_schema = app.openapi()["components"]["schemas"]["ValuationSourceReferenceBody"]
    assert set(source_schema["required"]) == {"record_id", "version", "fact_id"}
