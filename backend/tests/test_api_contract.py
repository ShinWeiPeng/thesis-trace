from __future__ import annotations

from thesis_trace.api import AccessApi, EvidenceApi
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.application.flows.evidence_stage import EvidenceStageFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.access.account_administration.contracts import AccountSummary
from thesis_trace.modules.access.orchestration import AccountActionService
from thesis_trace.modules.access.confirmation_challenge.service import ConfirmationService
from thesis_trace.platform.in_memory import InMemoryEvidenceStore
from thesis_trace.modules.research import ResearchStageFacade
from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot
from thesis_trace.modules.research.evidence_intake.contracts import EvidenceRecord, EvidenceStatus
from thesis_trace.modules.research.evidence_stage.service import EvidenceStageService
from thesis_trace.api import create_fastapi_app
from types import SimpleNamespace


def owner() -> AuthenticatedActor:
    return AuthenticatedActor(actor_id="owner-1", role=Role.OWNER, identity_version=1)


def test_recovery_profile_does_not_invent_workflow_task_url() -> None:
    profile = AccessApi.profile_for(
        SimpleNamespace(role=Role.OWNER, user_id="owner-1"),
        SimpleNamespace(expires_at="soon", recovery=True),
    )
    assert "recovery_task_url" not in profile


def build_api() -> EvidenceApi:
    store = InMemoryEvidenceStore()
    store.create_company("2330", "台積電")
    return EvidenceApi(
        flow=EvidenceIntakeFlow(
            store=store,
            id_generator=iter(["evidence-1"]).__next__,
        )
    )


def test_fastapi_contract_accepts_and_returns_server_record() -> None:
    import asyncio

    import httpx

    api = build_api()

    async def actor_provider() -> AuthenticatedActor:
        return owner()

    app = create_fastapi_app(api, actor_provider)

    async def submit() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/evidence",
                json={
                    "company_id": "2330",
                    "company_version": 1,
                    "url": "https://example.com/disclosure/1",
                    "idempotency_key": "request-fastapi-1",
                },
            )

    response = asyncio.run(submit())

    assert response.status_code == 202
    assert response.json() == {
        "evidence_id": "evidence-1",
        "version": 1,
        "status": "received",
    }


def test_api_returns_server_record_version_and_status() -> None:
    actor = AuthenticatedActor(actor_id="owner-1", role=Role.OWNER, identity_version=1)
    store = InMemoryEvidenceStore()
    store.create_company("2330", "台積電")
    api = EvidenceApi(
        flow=EvidenceIntakeFlow(
            store=store,
            id_generator=iter(["evidence-1"]).__next__,
        )
    )

    accepted = api.submit_evidence(
        actor,
        {
            "company_id": "2330",
            "company_version": 1,
            "url": "https://example.com/disclosure/1",
            "idempotency_key": "request-1",
        },
    )
    status = api.get_evidence(actor, accepted["evidence_id"])

    assert accepted == {"evidence_id": "evidence-1", "version": 1, "status": "received"}
    assert status == {"evidence_id": "evidence-1", "version": 1, "status": "received"}


def test_owner_confirms_facts_and_api_returns_server_derived_stage() -> None:
    import asyncio

    import httpx

    store = InMemoryEvidenceStore()
    store.records["evidence-1"] = EvidenceRecord(
        "evidence-1", 3, "2330", 1, "https://example.com/disclosure", EvidenceStatus.SUCCEEDED
    )
    store.source_snapshots["evidence-1"] = CollectedSourceSnapshot(
        canonical_url="https://example.com/disclosure",
        publisher="Example Exchange",
        content_hash="abc123",
        retrieved_at="2026-08-20T10:00:00+00:00",
        normalization_policy_version="url-normalization-v1",
    )
    intake_flow = EvidenceIntakeFlow(store=store, id_generator=iter([]).__next__)
    stage_flow = EvidenceStageFlow(
        research=ResearchStageFacade(
            EvidenceStageService(store=store, clock=lambda: "2026-08-20T12:00:00+00:00")
        )
    )

    current_actor = [owner()]

    async def actor_provider() -> AuthenticatedActor:
        return current_actor[0]

    app = create_fastapi_app(EvidenceApi(flow=intake_flow, stage_flow=stage_flow), actor_provider)

    async def confirm() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/evidence/evidence-1/stage-confirmations",
                json={
                    "source_snapshot_id": "evidence-1",
                    "expected_version": 0,
                    "facts": {
                        "source_confirmation": "official",
                        "product_established": True,
                        "commercialization_established": True,
                        "identifiable_revenue": False,
                        "identifiable_profit_or_cash_flow": False,
                        "consecutive_financial_quarters": 0,
                    },
                    "reason": "reviewed immutable source",
                    "idempotency_key": "api-stage-1",
                },
            )

    response = asyncio.run(confirm())

    assert response.status_code == 201
    body = response.json()
    assert body["stage"] == "E3"
    assert body["version"] == 1
    assert [item["gate"] for item in body["gate_trace"]] == ["E1", "E2", "E3", "E4", "E5", "E6"]
    assert body["source_snapshot_id"] == "evidence-1"
    assert "stage" not in app.openapi()["components"]["schemas"]["EvidenceStageConfirmationBody"]["properties"]

    async def stage_request(
        method: str, *, extra: dict | None = None, source_confirmation: str = "official"
    ) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            if method == "GET":
                return await client.get("/api/evidence/evidence-1/stage")
            request_body = {
                "source_snapshot_id": "evidence-1", "expected_version": 1,
                "facts": {
                    "source_confirmation": source_confirmation, "product_established": True,
                    "commercialization_established": True, "identifiable_revenue": False,
                    "identifiable_profit_or_cash_flow": False, "consecutive_financial_quarters": 0,
                },
                "reason": "learner must not confirm", "idempotency_key": "api-stage-denied",
                **(extra or {}),
            }
            return await client.post("/api/evidence/evidence-1/stage-confirmations", json=request_body)

    current_actor[0] = AuthenticatedActor("learner-1", Role.LEARNER, 1)
    assert asyncio.run(stage_request("GET")).json()["stage"] == "E3"
    assert asyncio.run(stage_request("POST")).status_code == 403
    current_actor[0] = AuthenticatedActor("admin-1", Role.ADMIN, 1)
    assert asyncio.run(stage_request("GET")).status_code == 404
    current_actor[0] = owner()
    invalid = asyncio.run(stage_request("POST", extra={"stage": "E6"}))
    assert invalid.status_code == 422
    unsupported_two_source = asyncio.run(
        stage_request("POST", source_confirmation="two_independent_credible")
    )
    assert unsupported_two_source.status_code == 422


def test_access_openapi_exports_all_typed_vertical_slice_routes() -> None:
    class StubAccessApi:
        def session_profile(self, actor, token): raise NotImplementedError
        def logout(self, actor, token): raise NotImplementedError
        def list_accounts(self, actor): raise NotImplementedError
        def get_account(self, actor, user_id): raise NotImplementedError
        def create_account(self, actor, body): raise NotImplementedError
        def preview_confirmation(self, actor, body): raise NotImplementedError
        def confirm_action(self, actor, body): raise NotImplementedError

    async def actor_provider() -> AuthenticatedActor:
        return owner()

    schema = create_fastapi_app(build_api(), actor_provider, StubAccessApi()).openapi()
    expected = {
        ("/api/session", "get"),
        ("/api/session", "delete"),
        ("/api/admin/accounts", "get"),
        ("/api/admin/accounts", "post"),
        ("/api/admin/accounts/{user_id}", "get"),
        ("/api/confirmation-challenges", "post"),
        ("/api/confirmed-actions", "post"),
    }
    assert expected <= {(path, method) for path, methods in schema["paths"].items() for method in methods}
    for path, method in expected:
        assert "responses" in schema["paths"][path][method]
    session_schema = schema["paths"]["/api/session"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert session_schema["discriminator"]["propertyName"] == "kind"
    assert set(session_schema["discriminator"]["mapping"]) == {"owner", "learner", "admin"}
    challenge_body = schema["components"]["schemas"]["ConfirmationChallengeBody"]
    assert "impact_summary" not in challenge_body["properties"]
    assert "confirmation_verb" not in challenge_body["properties"]
    assert challenge_body["additionalProperties"] is False


def test_confirmation_summary_is_server_derived_from_current_account_snapshot() -> None:
    class Repository:
        def __init__(self): self.saved = None
        def list_account_summaries(self):
            return [AccountSummary("user-5678", Role.LEARNER, "active", "google", 3)]
        def save_challenge(self, challenge, digest): self.saved = challenge

    repository = Repository()
    access = AccessApi(repository, sessions=None, account_actions=AccountActionService(repository, ConfirmationService(repository, token_factory=lambda: "challenge")))
    response = access.preview_confirmation(owner(), {
        "action_type": "change_role", "target_id": "user-5678", "target_version": 3,
        "payload": {"role": "admin"},
    })
    summary = response["impact_summary"]
    assert response["target_version"] == 3
    assert summary["before"] == {"role": "learner", "status": "active", "identity_provider": "google"}
    assert summary["after"] == {"role": "admin", "status": "active", "identity_provider": "google"}
    assert summary["confirmation_verb"] == "CHANGE ROLE"
    assert repository.saved.impact_summary == summary


def test_confirmation_rejects_absent_stale_or_unknown_account_action_without_disclosure() -> None:
    class Repository:
        def list_account_summaries(self):
            return [AccountSummary("user-5678", Role.LEARNER, "active", "google", 3)]
        def save_challenge(self, challenge, digest): raise AssertionError("must not persist")

    repository = Repository()
    access = AccessApi(repository, sessions=None, account_actions=AccountActionService(repository, ConfirmationService(repository)))
    for request in (
        {"action_type": "change_role", "target_id": "missing", "target_version": 3, "payload": {"role": "admin"}},
        {"action_type": "change_role", "target_id": "user-5678", "target_version": 2, "payload": {"role": "admin"}},
        {"action_type": "delete_account", "target_id": "user-5678", "target_version": 3, "payload": {}},
    ):
        try:
            access.preview_confirmation(owner(), request)
        except LookupError as error:
            assert str(error) == "resource_unavailable"
        else:
            raise AssertionError("request must be rejected")
