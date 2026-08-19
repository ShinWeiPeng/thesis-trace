from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from thesis_trace.modules.access.contracts import Role

@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    provider_id: str
    provider_type: str
    subject: str

@dataclass(frozen=True, slots=True)
class VerifiedPrincipal:
    identity: ProviderIdentity
    mfa_assured: bool
    token_expires_at: datetime

@dataclass(frozen=True, slots=True)
class AccessAccount:
    user_id: str
    role: Role
    status: str
    version: int

@dataclass(frozen=True, slots=True)
class ProviderIdentityMapping:
    identity: ProviderIdentity
    user_id: str
    enabled: bool
    version: int
