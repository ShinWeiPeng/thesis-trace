from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib

import httpx

from thesis_trace.api import AccessApi, EvidenceApi, create_fastapi_app
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.bootstrap.application import create_authenticated_actor_dependency
from thesis_trace.modules.access.confirmation_challenge.service import ConfirmationService
from thesis_trace.modules.access.orchestration import AccountActionService
from thesis_trace.modules.access.contracts import Role
from thesis_trace.modules.access.identity_registry.contracts import AccessAccount, ProviderIdentity, ProviderIdentityMapping, VerifiedPrincipal
from thesis_trace.modules.access.identity_registry.service import IdentityRegistry
from thesis_trace.modules.access.session_management.service import SessionService
from thesis_trace.platform.in_memory import InMemoryEvidenceStore


class MemoryAccessRepository:
    def __init__(self, role: Role) -> None:
        self.account = AccessAccount("user-1234", role, "active", 1)
        self.identity = ProviderIdentity("google-idp", "google", "subject")
        self.sessions = {}
        self.challenges = {}

    def find_mapping(self, identity):
        return ProviderIdentityMapping(identity, self.account.user_id, True, 1) if identity == self.identity else None
    def get_account(self, user_id): return self.account if user_id == self.account.user_id else None
    def save_session(self, session, token_digest): self.sessions[token_digest] = session
    def save_recovery_session(self, session, token_digest, reason, policy_version): raise AssertionError("not recovery")
    def get_session(self, digest): return self.sessions.get(digest)
    def revoke_session(self, session_id, when):
        for digest, session in list(self.sessions.items()):
            if session.session_id == session_id: self.sessions[digest] = session.revoked(when)
    def list_account_summaries(self): return []
    def save_challenge(self, challenge, digest): self.challenges[digest] = challenge
    def consume_challenge(self, *args): return None


class IdentityAdapter:
    def __init__(self, principal): self.principal, self.calls = principal, 0
    def verify(self, token):
        assert token == "valid-jwt"
        self.calls += 1
        return self.principal


def build(role: Role):
    now = datetime.now(timezone.utc)
    repository = MemoryAccessRepository(role)
    principal = VerifiedPrincipal(repository.identity, True, now + timedelta(hours=2))
    identity_adapter = IdentityAdapter(principal)
    sessions = SessionService(repository, token_factory=lambda: "opaque-session")
    dependency = create_authenticated_actor_dependency(identity_adapter, IdentityRegistry(repository), sessions)
    evidence_store = InMemoryEvidenceStore()
    api = EvidenceApi(flow=EvidenceIntakeFlow(store=evidence_store, id_generator=lambda: "id"))
    app = create_fastapi_app(api, dependency, AccessApi(repository, sessions, AccountActionService(repository, ConfirmationService(repository))))
    return app, identity_adapter, repository


def test_first_valid_request_issues_strict_bounded_cookie_and_logout_revokes_it() -> None:
    app, identity_adapter, repository = build(Role.OWNER)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            first = await client.get("/api/session", headers={"Cf-Access-Jwt-Assertion": "valid-jwt"})
            second = await client.get("/api/session", headers={"Cf-Access-Jwt-Assertion": "valid-jwt"})
            logout = await client.delete("/api/session", headers={"Cf-Access-Jwt-Assertion": "valid-jwt"})
            return first, second, logout

    first, second, logout = asyncio.run(scenario())
    cookie = first.headers["set-cookie"].lower()
    assert first.status_code == second.status_code == 200
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert first.json()["kind"] == "owner" and first.json()["is_recovery_session"] is False
    assert identity_adapter.calls == 3  # JWT + full identity are repeated for every request.
    assert logout.status_code == 204 and "max-age=0" in logout.headers["set-cookie"].lower()
    assert repository.sessions[hashlib.sha256(b"opaque-session").hexdigest()].revoked_at is not None


def test_learner_response_excludes_owner_fields_and_denial_is_stable_problem() -> None:
    app, _, _ = build(Role.LEARNER)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            profile = await client.get("/api/session", headers={"Cf-Access-Jwt-Assertion": "valid-jwt"})
            denied = await client.get("/api/admin/accounts", headers={"Cf-Access-Jwt-Assertion": "valid-jwt"})
            return profile, denied

    profile, denied = asyncio.run(scenario())
    assert profile.json()["kind"] == "learner"
    assert "recovery_task_url" not in profile.json()
    assert denied.status_code == 404 and denied.json() == {"code": "resource_unavailable"}


def test_confirmation_rejects_client_summary_and_stale_target_with_problem_envelopes() -> None:
    app, _, _ = build(Role.OWNER)
    request = {"action_type": "change_role", "target_id": "missing", "target_version": 2, "payload": {"role": "admin"}}

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            stale = await client.post("/api/confirmation-challenges", json=request, headers={"Cf-Access-Jwt-Assertion": "valid-jwt"})
            injected = await client.post("/api/confirmation-challenges", json={**request, "impact_summary": "trust me"}, headers={"Cf-Access-Jwt-Assertion": "valid-jwt"})
            return stale, injected

    stale, injected = asyncio.run(scenario())
    assert stale.status_code == 404 and stale.json() == {"code": "resource_unavailable"}
    assert injected.status_code == 422 and injected.json() == {"code": "invalid_request"}
