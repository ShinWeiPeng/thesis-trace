from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping

@dataclass(frozen=True, slots=True)
class ConfirmationChallenge:
    challenge_id: str; actor_id: str; action_type: str; target_id: str; target_version: int; payload_digest: str; impact_summary: Mapping[str, Any]; expires_at: datetime; consumed_at: datetime | None = None
    def matches(self, actor_id, action_type, target_version, payload_digest, now): return self.consumed_at is None and now < self.expires_at and (self.actor_id,self.action_type,self.target_version,self.payload_digest)==(actor_id,action_type,target_version,payload_digest)
    def consumed(self, when): return replace(self, consumed_at=when)
