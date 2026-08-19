from __future__ import annotations
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json, secrets, uuid
from thesis_trace.modules.access.confirmation_challenge.contracts import ConfirmationChallenge
from thesis_trace.modules.access.confirmation_challenge.ports import ChallengeRepositoryPort

def payload_digest(payload) -> str: return sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode()).hexdigest()
class ConfirmationService:
    def __init__(self, repository: ChallengeRepositoryPort, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32)) -> None: self._repository,self._clock,self._token_factory=repository,clock,token_factory
    def preview(self, actor_id, action_type, target_id, target_version, payload, impact_summary):
        token=self._token_factory(); now=self._clock(); challenge=ConfirmationChallenge(str(uuid.uuid4()),actor_id,action_type,target_id,target_version,payload_digest(payload),impact_summary,now+timedelta(minutes=5))
        self._repository.save_challenge(challenge,sha256(token.encode()).hexdigest()); return token,challenge
    def confirm(self, token, actor_id, action_type, target_version, payload, reason):
        if not reason.strip(): raise ValueError("reason_required")
        result=self._repository.consume_challenge(sha256(token.encode()).hexdigest(),actor_id,action_type,target_version,payload_digest(payload),reason,self._clock())
        if result is None: raise PermissionError("challenge_invalid")
        return result
