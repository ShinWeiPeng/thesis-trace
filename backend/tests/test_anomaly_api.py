from __future__ import annotations

import asyncio

import httpx

from thesis_trace.api import EvidenceApi, create_fastapi_app
from thesis_trace.application.flows.anomaly_assessment import AnomalyAssessmentFlow
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research import ResearchAnomalyFacade
from thesis_trace.modules.research.anomaly_assessment.service import AnomalyAssessmentService
from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot
from thesis_trace.modules.research.evidence_intake.contracts import EvidenceRecord, EvidenceStatus
from thesis_trace.platform.in_memory import InMemoryEvidenceStore


def _build() -> tuple[object, list[AuthenticatedActor]]:
    store = InMemoryEvidenceStore()
    store.records["evidence-1"] = EvidenceRecord(
        "evidence-1", 3, "2330", 1, "https://example.com/disclosure", EvidenceStatus.SUCCEEDED
    )
    store.source_snapshots["evidence-1"] = CollectedSourceSnapshot(
        canonical_url="https://example.com/disclosure",
        publisher="TWSE",
        content_hash="snapshot-content",
        retrieved_at="2026-08-21T09:00:00+00:00",
        normalization_policy_version="url-normalization-v1",
        source_category="A",
    )
    actor = [AuthenticatedActor("owner-1", Role.OWNER, 1)]

    async def actor_provider() -> AuthenticatedActor:
        return actor[0]

    anomaly_flow = AnomalyAssessmentFlow(
        research=ResearchAnomalyFacade(
            AnomalyAssessmentService(
                store=store, clock=lambda: "2026-08-21T10:00:00+00:00"
            )
        )
    )
    api = EvidenceApi(
        flow=EvidenceIntakeFlow(store=store, id_generator=iter([]).__next__),
        anomaly_flow=anomaly_flow,
    )
    return create_fastapi_app(api, actor_provider), actor


def _request_body() -> dict[str, object]:
    return {
        "expected_evidence_version": 3,
        "sources": [{"source_snapshot_id": "evidence-1"}],
        "reason": "check the immutable disclosure",
        "idempotency_key": "anomaly-api-1",
    }


def test_owner_requests_pending_assessment_and_role_safe_query_returns_server_projection() -> None:
    app, actor = _build()

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/evidence/evidence-1/anomaly-assessments", json=_request_body()
            )
            assessment_id = created.json()["assessment_id"]
            actor[0] = AuthenticatedActor("learner-1", Role.LEARNER, 1)
            learner = await client.get(f"/api/anomaly-assessments/{assessment_id}")
            actor[0] = AuthenticatedActor("admin-1", Role.ADMIN, 1)
            admin = await client.get(f"/api/anomaly-assessments/{assessment_id}")
            return created, learner, admin

    created, learner, admin = asyncio.run(exercise())

    assert created.status_code == 202
    assert created.json() == {
        "assessment_id": "assessment-1",
        "version": 1,
        "evidence_id": "evidence-1",
        "evidence_version": 3,
        "source_snapshot_ids": ["evidence-1"],
        "status": "pending",
        "requested_at": "2026-08-21T10:00:00+00:00",
        "trace": None,
        "failure_code": None,
    }
    assert learner.status_code == 200
    assert learner.json() == created.json()
    assert admin.status_code == 404


def test_non_owner_cannot_admit_and_wire_schema_forbids_policy_authority() -> None:
    app, actor = _build()
    actor[0] = AuthenticatedActor("learner-1", Role.LEARNER, 1)

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            denied = await client.post(
                "/api/evidence/evidence-1/anomaly-assessments", json=_request_body()
            )
            injected = await client.post(
                "/api/evidence/evidence-1/anomaly-assessments",
                json={**_request_body(), "anomaly_class": "would_be_hard"},
            )
            source_body = _request_body()
            source_body["sources"][0]["authoritative_first_party"] = True
            injected_source_authority = await client.post(
                "/api/evidence/evidence-1/anomaly-assessments", json=source_body,
            )
            return denied, injected, injected_source_authority

    denied, injected, injected_source_authority = asyncio.run(exercise())

    assert denied.status_code == 403
    assert injected.status_code == 422
    assert injected_source_authority.status_code == 422
    schema = app.openapi()["components"]["schemas"]["AnomalyAssessmentRequestBody"]
    assert schema["additionalProperties"] is False
    assert "anomaly_class" not in schema["properties"]
    assert "clue_score" not in schema["properties"]
    assert "hard" not in schema["properties"]
