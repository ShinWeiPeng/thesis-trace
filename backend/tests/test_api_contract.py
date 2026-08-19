from __future__ import annotations

from thesis_trace.api import AccessApi, EvidenceApi
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.access.account_administration.contracts import AccountSummary
from thesis_trace.modules.access.orchestration import AccountActionService
from thesis_trace.modules.access.confirmation_challenge.service import ConfirmationService
from thesis_trace.platform.in_memory import InMemoryEvidenceStore
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
