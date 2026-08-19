from __future__ import annotations
from dataclasses import dataclass
from thesis_trace.modules.access.contracts import Role
@dataclass(frozen=True, slots=True)
class AccountSummary:
    user_id: str; role: Role; status: str; masked_identity: str; version: int
