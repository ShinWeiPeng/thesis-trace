from datetime import datetime, timezone
from types import SimpleNamespace

import asyncio
import httpx
import pytest

from thesis_trace.api import EvidenceApi, create_fastapi_app
from thesis_trace.application.contracts import (
    RecommendationRequestPage,
    RecommendationRequestView,
)
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role


def app(flow):
    async def actor():
        return AuthenticatedActor("owner", Role.OWNER, 4)

    return create_fastapi_app(EvidenceApi(flow=None, recommendation_flow=flow), actor)


def send(app, method, path, **kwargs):
    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(request())


def test_generated_http_contract_maps_server_identity_not_body_authority():
    calls = []
    result = RecommendationRequestView(
        "request",
        "thesis",
        "pending",
        None,
        datetime(2026, 9, 5, tzinfo=timezone.utc),
        None,
    )

    def request(actor, company, command):
        calls.append((actor, company, command))
        return result

    client = app(SimpleNamespace(request_recommendation=request))
    body = {
        "thesis_id": "thesis",
        "expected_thesis_version": 2,
        "valuation_id": "valuation",
        "expected_valuation_version": 1,
        "expected_portfolio_version": 3,
        "benchmark_source": "company_history",
        "source_selection_reason": "Reviewed history",
        "idempotency_key": "request-key",
    }
    response = send(
        client, "POST", "/api/companies/company/recommendation-requests", json=body
    )
    assert response.status_code == 202 and response.json()["status"] == "pending"
    assert calls[0][2].actor_id == "owner" and calls[0][2].identity_version == 4
    for change in (
        {"actor_id": "other"},
        {"expected_thesis_version": True},
        {"expected_portfolio_version": "3"},
    ):
        assert (
            send(
                client,
                "POST",
                "/api/companies/company/recommendation-requests",
                json=body | change,
            ).status_code
            == 422
        )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error,status,detail",
    [
        (PermissionError("resource_unavailable"), 404, "resource_unavailable"),
        (PermissionError("challenge_invalid"), 409, "challenge_invalid"),
        (ValueError("version_conflict"), 409, "version_conflict"),
        (
            RuntimeError("connection contained private credentials"),
            503,
            "recommendation_unavailable",
        ),
    ],
)
def test_http_error_recovery_is_explicit_and_redacted(error, status, detail):
    def fail(*args, **kwargs):
        raise error

    client = app(SimpleNamespace(request_status=fail))
    response = send(client, "GET", "/api/recommendation-requests/request")
    assert response.status_code == status and response.json() == {"detail": detail}


def test_public_confirm_contract_cannot_request_system_expiry():
    client = app(SimpleNamespace())
    response = send(
        client,
        "POST",
        "/api/recommendations/record/decisions",
        json={
            "version": 1,
            "expected_sequence": 0,
            "target_status": "expired",
            "reason": "",
            "defer_until": None,
            "idempotency_key": "forged",
        },
    )
    assert response.status_code == 422


def test_read_models_are_in_openapi_with_structured_sources_risk_and_history():
    schema = send(app(SimpleNamespace()), "GET", "/openapi.json").json()
    detail = schema["components"]["schemas"]["RecommendationDetailView"]["properties"]
    assert set(detail) >= {
        "view",
        "sources",
        "risk",
        "decisions",
        "next_decision_sequence",
    }
    assert detail["sources"]["items"]["$ref"].endswith("RecommendationSourceView")
