from __future__ import annotations
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets, uuid
from thesis_trace.modules.access.contracts import Role
from thesis_trace.modules.access.identity_registry.contracts import AccessAccount, VerifiedPrincipal
from thesis_trace.modules.access.recovery_policy import RecoveryPolicyConfiguration
from thesis_trace.modules.access.session_management.contracts import AccessSession, SessionProfile
from thesis_trace.modules.access.session_management.ports import SessionRepositoryPort

_CAPABILITIES = {Role.OWNER: frozenset({"research","account_admin","consequential_action"}), Role.LEARNER: frozenset({"shared_evidence","own_thesis"}), Role.ADMIN: frozenset({"operations","account_admin"})}
class SessionService:
    def __init__(self, repository: SessionRepositoryPort, *, recovery_policy: RecoveryPolicyConfiguration | None = None, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32)) -> None:
        self._repository, self._recovery_policy, self._clock, self._token_factory = repository, recovery_policy, clock, token_factory
    def bootstrap(self, account: AccessAccount, principal: VerifiedPrincipal, *, recovery: bool, recovery_reason: str | None = None):
        now = self._clock()
        if account.status != "active" or not principal.mfa_assured or principal.token_expires_at <= now or (recovery and account.role is not Role.OWNER): raise PermissionError("access_denied")
        expires = min(principal.token_expires_at, now + (timedelta(minutes=30) if recovery else timedelta(hours=8)))
        policy_version = self._recovery_policy.policy_version if recovery and self._recovery_policy is not None else None
        token = self._token_factory(); session = AccessSession(str(uuid.uuid4()), account.user_id, principal.identity, expires, recovery, None, account.version, policy_version)
        token_digest = sha256(token.encode()).hexdigest()
        if recovery:
            policy = self._recovery_policy
            if (policy is None or not policy.enabled or principal.identity != policy.approved_identity
                    or principal.identity.provider_type != "cloudflare" or not (recovery_reason or "").strip()):
                raise PermissionError("access_denied")
            self._repository.save_recovery_session(session, token_digest, recovery_reason.strip(), policy.policy_version)
        else:
            self._repository.save_session(session, token_digest)
        return token, session, SessionProfile(account.user_id, account.role, _CAPABILITIES[account.role], expires, recovery)
    def validate(self, token: str, account: AccessAccount) -> AccessSession:
        session = self._repository.get_session(sha256(token.encode()).hexdigest())
        recovery_invalid = session is not None and session.recovery and (
            self._recovery_policy is None
            or not self._recovery_policy.enabled
            or session.provider_identity != self._recovery_policy.approved_identity
            or session.recovery_policy_version != self._recovery_policy.policy_version
        )
        if session is None or recovery_invalid or session.revoked_at is not None or session.expires_at <= self._clock() or session.user_id != account.user_id or session.identity_version != account.version or account.status != "active": raise PermissionError("access_denied")
        return session
    def revoke(self, token: str, account: AccessAccount) -> None:
        session = self.validate(token, account); self._repository.revoke_session(session.session_id, self._clock())
    def disable_recovery(self, actor: AccessAccount, reason: str) -> int:
        if actor.role is not Role.OWNER or not reason.strip() or self._recovery_policy is None:
            raise PermissionError("access_denied")
        return self._repository.revoke_recovery_sessions(actor.user_id, reason.strip(), self._recovery_policy.policy_version, self._clock())
