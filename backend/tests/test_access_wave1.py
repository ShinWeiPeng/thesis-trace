from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from thesis_trace.modules.access.contracts import Role
from thesis_trace.modules.access.identity_registry.contracts import AccessAccount, ProviderIdentity, ProviderIdentityMapping, VerifiedPrincipal
from thesis_trace.modules.access.identity_registry.service import IdentityRegistry
from thesis_trace.modules.access.session_management.contracts import SessionProfile
from thesis_trace.modules.access.session_management.service import SessionService
from thesis_trace.modules.access.recovery_policy import RecoveryPolicyConfiguration
from thesis_trace.modules.access.confirmation_challenge.service import ConfirmationService


class MemoryAccessRepository:
    def __init__(self):
        self.mappings = {}
        self.accounts = {}
        self.sessions = {}
        self.challenges = {}
        self.audit = []

    def find_mapping(self, identity): return self.mappings.get(identity)
    def get_account(self, user_id): return self.accounts.get(user_id)
    def save_session(self, session, token_digest): self.sessions[token_digest] = session
    def save_recovery_session(self, session, token_digest, reason, policy_version):
        self.sessions[token_digest] = session
        self.audit.append((session.user_id, "emergency_authenticated", reason))
    def get_session(self, token_digest): return self.sessions.get(token_digest)
    def revoke_session(self, session_id, when):
        for key, value in list(self.sessions.items()):
            if value.session_id == session_id: self.sessions[key] = value.revoked(when)
    def revoke_recovery_sessions(self, actor_id, reason, policy_version, when):
        count = 0
        for key, value in list(self.sessions.items()):
            if value.recovery and value.revoked_at is None:
                self.sessions[key] = value.revoked(when); count += 1
        self.audit.append((actor_id, "emergency_disabled", reason))
        return count
    def save_challenge(self, challenge, token_digest): self.challenges[token_digest] = challenge
    def consume_challenge(self, token_digest, actor_id, action_type, target_version, payload_digest, reason, now):
        challenge = self.challenges.get(token_digest)
        if not challenge or not challenge.matches(actor_id, action_type, target_version, payload_digest, now) or not reason.strip(): return None
        self.challenges[token_digest] = challenge.consumed(now)
        self.audit.append((actor_id, action_type, reason))
        return challenge


def test_same_email_never_merges_distinct_provider_identities() -> None:
    repo = MemoryAccessRepository()
    google = ProviderIdentity("google-idp", "google", "subject-1")
    recovery = ProviderIdentity("cloudflare-idp", "cloudflare", "subject-1")
    repo.accounts["owner"] = AccessAccount("owner", Role.OWNER, "active", 1)
    repo.mappings[google] = ProviderIdentityMapping(google, "owner", True, 1)
    repo.mappings[recovery] = ProviderIdentityMapping(recovery, "owner", True, 1)
    registry = IdentityRegistry(repo)
    now = datetime.now(timezone.utc)
    assert registry.resolve(VerifiedPrincipal(google, True, now + timedelta(hours=1))).user_id == "owner"
    assert registry.resolve(VerifiedPrincipal(recovery, True, now + timedelta(hours=1))).user_id == "owner"
    with pytest.raises(PermissionError):
        registry.resolve(VerifiedPrincipal(ProviderIdentity("other", "google", "subject-1"), True, now + timedelta(hours=1)))


def test_session_expiry_logout_and_identity_version_invalidation() -> None:
    repo = MemoryAccessRepository(); now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    account = AccessAccount("owner", Role.OWNER, "active", 2)
    identity = ProviderIdentity("google", "google", "sub")
    service = SessionService(repo, clock=lambda: now, token_factory=lambda: "opaque")
    token, session, profile = service.bootstrap(account, VerifiedPrincipal(identity, True, now + timedelta(hours=12)), recovery=False)
    assert session.expires_at == now + timedelta(hours=8)
    assert repo.get_session(hashlib.sha256(token.encode()).hexdigest()) is not None
    service.revoke(token, account)
    with pytest.raises(PermissionError): service.validate(token, account)
    recovery_identity = ProviderIdentity("cloudflare", "cloudflare", "sub")
    service._recovery_policy = RecoveryPolicyConfiguration(recovery_identity, "v1", True)
    recovery_token, recovery_session, _ = service.bootstrap(
        account, VerifiedPrincipal(recovery_identity, True, now + timedelta(hours=2)),
        recovery=True, recovery_reason="lost primary identity",
    )
    assert recovery_session.expires_at == now + timedelta(minutes=30)
    with pytest.raises(PermissionError): service.validate(recovery_token, AccessAccount("owner", Role.OWNER, "active", 3))


def test_confirmation_is_five_minute_actor_payload_version_bound_and_single_use() -> None:
    repo = MemoryAccessRepository(); now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    service = ConfirmationService(repo, clock=lambda: now, token_factory=lambda: "challenge-token")
    payload = {"role": "admin"}
    token, challenge = service.preview("owner", "change_role", "user-2", 4, payload, "Make user-2 Admin")
    assert token not in repr(challenge) and not hasattr(challenge, "token")
    assert challenge.expires_at == now + timedelta(minutes=5)
    assert service.confirm(token, "owner", "change_role", 4, payload, "approved") is not None
    with pytest.raises(PermissionError): service.confirm(token, "owner", "change_role", 4, payload, "approved")
    token2, _ = service.preview("owner", "change_role", "user-2", 4, payload, "Make user-2 Admin")
    with pytest.raises(PermissionError): service.confirm(token2, "other", "change_role", 4, payload, "approved")
    with pytest.raises(ValueError): service.confirm(token2, "owner", "change_role", 4, payload, "   ")


def test_recovery_requires_cloudflare_provider_owner_and_nonblank_reason() -> None:
    repo = MemoryAccessRepository(); now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    cloudflare_identity = ProviderIdentity("cf", "cloudflare", "sub")
    service = SessionService(repo, recovery_policy=RecoveryPolicyConfiguration(cloudflare_identity, "v1", True), clock=lambda: now, token_factory=lambda: "recovery")
    owner = AccessAccount("owner", Role.OWNER, "active", 1)
    learner = AccessAccount("learner", Role.LEARNER, "active", 1)
    google = VerifiedPrincipal(ProviderIdentity("google", "google", "sub"), True, now + timedelta(hours=1))
    cloudflare = VerifiedPrincipal(cloudflare_identity, True, now + timedelta(hours=1))
    with pytest.raises(PermissionError): service.bootstrap(owner, google, recovery=True, recovery_reason="safe")
    with pytest.raises(PermissionError): service.bootstrap(learner, cloudflare, recovery=True, recovery_reason="safe")
    with pytest.raises(PermissionError): service.bootstrap(owner, cloudflare, recovery=True, recovery_reason="  ")
    wrong_cloudflare = VerifiedPrincipal(ProviderIdentity("other", "cloudflare", "sub"), True, now + timedelta(hours=1))
    with pytest.raises(PermissionError): service.bootstrap(owner, wrong_cloudflare, recovery=True, recovery_reason="safe")
    disabled = SessionService(repo, recovery_policy=RecoveryPolicyConfiguration(cloudflare_identity, "v1", False), clock=lambda: now)
    with pytest.raises(PermissionError): disabled.bootstrap(owner, cloudflare, recovery=True, recovery_reason="safe")


def test_disabling_recovery_policy_immediately_invalidates_existing_recovery_cookie() -> None:
    repo = MemoryAccessRepository(); now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    identity = ProviderIdentity("cf", "cloudflare", "owner")
    owner = AccessAccount("owner", Role.OWNER, "active", 1)
    enabled = SessionService(
        repo,
        recovery_policy=RecoveryPolicyConfiguration(identity, "v2", True),
        clock=lambda: now,
        token_factory=lambda: "existing-recovery-cookie",
    )
    token, _session, _profile = enabled.bootstrap(
        owner,
        VerifiedPrincipal(identity, True, now + timedelta(hours=1)),
        recovery=True,
        recovery_reason="primary unavailable",
    )

    disabled = SessionService(
        repo,
        recovery_policy=RecoveryPolicyConfiguration(identity, "v3", False),
        clock=lambda: now,
    )
    with pytest.raises(PermissionError):
        disabled.validate(token, owner)


def test_repair_seam_revokes_all_recovery_sessions_and_audits_disable() -> None:
    repo = MemoryAccessRepository(); now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    identity = ProviderIdentity("cf", "cloudflare", "owner")
    owner = AccessAccount("owner", Role.OWNER, "active", 1)
    service = SessionService(repo, recovery_policy=RecoveryPolicyConfiguration(identity, "v2", True), clock=lambda: now,
                             token_factory=iter(("one", "two")).__next__)
    principal = VerifiedPrincipal(identity, True, now + timedelta(hours=1))
    service.bootstrap(owner, principal, recovery=True, recovery_reason="repair")
    service.bootstrap(owner, principal, recovery=True, recovery_reason="repair")
    assert service.disable_recovery(owner, "primary identity repaired") == 2
    assert repo.audit[-1] == ("owner", "emergency_disabled", "primary identity repaired")
