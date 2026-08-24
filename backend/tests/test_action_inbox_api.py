from __future__ import annotations

import asyncio

import httpx

from thesis_trace.api import EvidenceApi, create_fastapi_app
from thesis_trace.application.flows.anomaly_assessment import ActionInboxResult, ActionItemResult
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.platform.in_memory import InMemoryEvidenceStore


def item(version: int = 1, status: str = "pending") -> ActionItemResult:
    return ActionItemResult(
        "item-1", version, "anomaly_review", "anomaly_assessment", "assessment-1", 2,
        "company-1", "TT", "Thesis Trace", "Review", status, "high", "high", None,
        False, ("workflow.shadow-anomaly-review-v1",), "action-priority-v1", "Shadow review",
        "2026-08-24T00:00:00+00:00", "2026-08-24T00:00:00+00:00", None, None, None,
        ("in_progress", "deferred", "completed", "dismissed"),
    )


class ActionFlowStub:
    def create(self, _actor, request):
        assert request.assessment_id == "assessment-1"
        return item()

    def query(self, _actor, request):
        assert request.search == "TT"
        return ActionInboxResult(1, 0, 0, 1, 1, (item(),), None, "2026-08-24T00:00:00+00:00")

    def get(self, _actor, request):
        assert request.item_id == "item-1"
        return item()

    def transition(self, _actor, request):
        assert request.target_status == "completed"
        return item(2, "completed")


def test_action_http_contract_and_authority_fields() -> None:
    async def actor_provider() -> AuthenticatedActor:
        return AuthenticatedActor("owner-1", Role.OWNER, 1)

    api = EvidenceApi(
        flow=EvidenceIntakeFlow(store=InMemoryEvidenceStore(), id_generator=lambda: "unused"),
        action_inbox_flow=ActionFlowStub(),
    )
    app = create_fastapi_app(api, actor_provider)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/action-items/anomaly-reviews", json={
                "assessment_id": "assessment-1", "expected_assessment_version": 2,
                "reason": "Review", "due_at": None, "idempotency_key": "create-1",
            })
            injected = await client.post("/api/action-items/anomaly-reviews", json={
                "assessment_id": "assessment-1", "expected_assessment_version": 2,
                "reason": "Review", "due_at": None, "idempotency_key": "create-2",
                "assignee_user_id": "attacker", "effective_priority": "low",
            })
            page = await client.get("/api/action-items?search=TT")
            detail = await client.get("/api/action-items/item-1")
            transitioned = await client.post("/api/action-items/item-1/transitions", json={
                "expected_version": 1, "target_status": "completed", "reason": "Reviewed",
                "defer_until": None, "idempotency_key": "transition-1",
            })
            return created, injected, page, detail, transitioned

    created, injected, page, detail, transitioned = asyncio.run(exercise())
    assert created.status_code == 201
    assert injected.status_code == 422
    assert page.status_code == detail.status_code == transitioned.status_code == 200
    assert page.json()["summary"]["urgent"] == page.json()["total_count"] == 1
    assert transitioned.json()["status"] == "completed"
    create_schema = app.openapi()["components"]["schemas"]["ActionItemCreateBody"]
    assert create_schema["additionalProperties"] is False
    assert "assignee_user_id" not in create_schema["properties"]
    assert "priority" not in create_schema["properties"]
