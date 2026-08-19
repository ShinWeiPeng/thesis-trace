from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime
from thesis_trace.modules.access.contracts import Role
from thesis_trace.modules.access.identity_registry.contracts import ProviderIdentity

@dataclass(frozen=True, slots=True)
class AccessSession:
    session_id: str
    user_id: str
    provider_identity: ProviderIdentity
    expires_at: datetime
    recovery: bool
    revoked_at: datetime | None
    identity_version: int
    recovery_policy_version: str | None = None
    def revoked(self, when: datetime) -> "AccessSession": return replace(self, revoked_at=when)

@dataclass(frozen=True, slots=True)
class SessionProfile:
    user_id: str
    role: Role
    capabilities: frozenset[str]
    session_expires_at: datetime
    recovery: bool
