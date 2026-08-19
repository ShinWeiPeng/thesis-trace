from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    LEARNER = "learner"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    actor_id: str
    role: Role
    identity_version: int


@dataclass(frozen=True, slots=True)
class SecurityContext:
    user_id: str
    role: Role
    ownership_scope: str
