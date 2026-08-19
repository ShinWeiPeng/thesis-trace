from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from hashlib import sha256
import json
import uuid
from typing import Any, Callable, Iterator

from thesis_trace.modules.access.account_administration.contracts import AccountSummary
from thesis_trace.modules.access.confirmation_challenge.contracts import ConfirmationChallenge
from thesis_trace.modules.access.contracts import Role, SecurityContext
from thesis_trace.modules.access.identity_registry.contracts import AccessAccount, ProviderIdentity, ProviderIdentityMapping
from thesis_trace.modules.access.session_management.contracts import AccessSession
from thesis_trace.platform.postgres import DatabaseUrlProvider, _redacted_connection


class PostgresAccessAdapter:
    """Access persistence and transaction-local PostgreSQL security context."""

    def __init__(self, database_url_provider: DatabaseUrlProvider, *, recovery_fault_hook: Callable[[], None] | None = None) -> None:
        self._provider = database_url_provider
        self._recovery_fault_hook = recovery_fault_hook

    @contextmanager
    def transaction(self, context: SecurityContext) -> Iterator[Any]:
        with _redacted_connection(self._provider) as connection:
            with connection.transaction():
                connection.execute("SELECT set_config('app.user_id',%s,true)", (context.user_id,))
                connection.execute("SELECT set_config('app.role',%s,true)", (context.role.value,))
                connection.execute("SELECT set_config('app.request_id',%s,true)", (context.ownership_scope,))
                yield connection

    def find_mapping(self, identity: ProviderIdentity) -> ProviderIdentityMapping | None:
        with _redacted_connection(self._provider) as connection:
            row = connection.execute(
                "SELECT user_id::text,enabled,version FROM access.identities WHERE provider_id=%s AND provider_type=%s AND provider_subject=%s",
                (identity.provider_id, identity.provider_type, identity.subject),
            ).fetchone()
        return None if row is None else ProviderIdentityMapping(identity, str(row[0]), bool(row[1]), int(row[2]))

    def get_account(self, user_id: str) -> AccessAccount | None:
        with _redacted_connection(self._provider) as connection:
            row = connection.execute("SELECT user_id::text,role,status,identity_version FROM access.users WHERE user_id=%s", (user_id,)).fetchone()
        return None if row is None else AccessAccount(str(row[0]), Role(row[1]), str(row[2]), int(row[3]))

    def list_account_summaries(self) -> list[AccountSummary]:
        with _redacted_connection(self._provider) as connection:
            rows = connection.execute(
                """SELECT u.user_id::text,u.role,u.status,coalesce(min(i.provider_type),'unlinked'),u.identity_version
                   FROM access.users u LEFT JOIN access.identities i USING(user_id)
                   GROUP BY u.user_id ORDER BY u.created_at,u.user_id"""
            ).fetchall()
        return [AccountSummary(str(r[0]), Role(r[1]), str(r[2]), str(r[3]), int(r[4])) for r in rows]

    def create_account(self, *, role: Role, provider_identity: ProviderIdentity, email_fact: str) -> AccessAccount:
        user_id, identity_id = uuid.uuid4(), uuid.uuid4()
        with _redacted_connection(self._provider) as connection:
            with connection.transaction():
                connection.execute("INSERT INTO access.users(user_id,role,status) VALUES(%s,%s,'active')", (user_id, role.value))
                connection.execute(
                    """INSERT INTO access.identities(identity_id,user_id,provider_id,provider_type,provider_subject,email_fact)
                       VALUES(%s,%s,%s,%s,%s,%s)""",
                    (identity_id, user_id, provider_identity.provider_id, provider_identity.provider_type, provider_identity.subject, email_fact),
                )
        return AccessAccount(str(user_id), role, "active", 1)

    def save_session(self, session: AccessSession, token_digest: str) -> None:
        with _redacted_connection(self._provider) as connection:
            identity = connection.execute(
                """SELECT identity_id FROM access.identities WHERE user_id=%s AND provider_id=%s
                   AND provider_type=%s AND provider_subject=%s AND enabled""",
                (session.user_id, session.provider_identity.provider_id, session.provider_identity.provider_type, session.provider_identity.subject),
            ).fetchone()
            if identity is None:
                raise PermissionError("resource_unavailable")
            connection.execute(
                """INSERT INTO access.sessions(session_id,user_id,identity_id,token_digest,recovery,jwt_expires_at,expires_at,identity_version,recovery_policy_version)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (session.session_id, session.user_id, identity[0], token_digest, session.recovery, session.expires_at, session.expires_at, session.identity_version, session.recovery_policy_version),
            )

    def save_recovery_session(self, session: AccessSession, token_digest: str, reason: str, policy_version: str) -> None:
        if session.provider_identity.provider_type != "cloudflare" or not reason.strip():
            raise PermissionError("resource_unavailable")
        event_id = uuid.uuid5(uuid.NAMESPACE_URL, f"access-recovery:{session.session_id}")
        with _redacted_connection(self._provider) as connection:
            with connection.transaction():
                identity = connection.execute(
                    """SELECT i.identity_id FROM access.identities i JOIN access.users u USING(user_id)
                       WHERE i.user_id=%s AND i.provider_id=%s AND i.provider_type='cloudflare'
                         AND i.provider_subject=%s AND i.enabled AND u.role='owner' AND u.status='active'""",
                    (session.user_id, session.provider_identity.provider_id, session.provider_identity.subject),
                ).fetchone()
                if identity is None:
                    raise PermissionError("resource_unavailable")
                connection.execute(
                    """INSERT INTO access.sessions(session_id,user_id,identity_id,token_digest,recovery,jwt_expires_at,expires_at,identity_version,recovery_policy_version)
                       VALUES(%s,%s,%s,%s,true,%s,%s,%s,%s)""",
                    (session.session_id, session.user_id, identity[0], token_digest, session.expires_at, session.expires_at, session.identity_version, policy_version),
                )
                if self._recovery_fault_hook is not None:
                    self._recovery_fault_hook()
                connection.execute(
                    """INSERT INTO access.security_audit_events(event_id,actor_user_id,subject_id,action,reason,metadata)
                       VALUES(%s,%s,%s,'emergency_authenticated',%s,%s::jsonb)""",
                    (uuid.uuid4(), session.user_id, session.session_id, reason,
                     json.dumps({"outbox_event_id": str(event_id), "provider_id": session.provider_identity.provider_id,
                                 "provider_type": session.provider_identity.provider_type, "provider_subject": session.provider_identity.subject,
                                 "policy_version": policy_version})),
                )
                connection.execute(
                    """INSERT INTO access.workflow_outbox(event_id,event_type,payload)
                       VALUES(%s,'workflow.safety_item.requested',%s::jsonb)""",
                    (event_id, json.dumps({"request_type": "disable_recovery_access", "actor_id": session.user_id,
                                           "session_id": session.session_id, "reason": reason,
                                           "provider_id": session.provider_identity.provider_id,
                                           "provider_type": session.provider_identity.provider_type,
                                           "provider_subject": session.provider_identity.subject,
                                           "policy_version": policy_version})),
                )

    def revoke_recovery_sessions(self, actor_id: str, reason: str, policy_version: str, when: datetime) -> int:
        event_id = uuid.uuid4()
        with _redacted_connection(self._provider) as connection:
            with connection.transaction():
                rows = connection.execute(
                    "UPDATE access.sessions SET revoked_at=%s WHERE recovery AND revoked_at IS NULL RETURNING session_id",
                    (when,),
                ).fetchall()
                connection.execute(
                    """INSERT INTO access.security_audit_events(event_id,actor_user_id,subject_id,action,reason,metadata)
                       VALUES(%s,%s,'recovery-policy','emergency_disabled',%s,%s::jsonb)""",
                    (uuid.uuid4(), actor_id, reason, json.dumps({"policy_version": policy_version, "revoked_sessions": len(rows)})),
                )
                connection.execute(
                    """INSERT INTO access.workflow_outbox(event_id,event_type,payload)
                       VALUES(%s,'access.emergency_disabled',%s::jsonb)""",
                    (event_id, json.dumps({"actor_id": actor_id, "policy_version": policy_version, "revoked_sessions": len(rows)})),
                )
        return len(rows)

    def get_session(self, token_digest: str) -> AccessSession | None:
        with _redacted_connection(self._provider) as connection:
            row = connection.execute(
                """SELECT s.session_id::text,s.user_id::text,i.provider_id,i.provider_type,i.provider_subject,
                          s.expires_at,s.recovery,s.revoked_at,s.identity_version,s.recovery_policy_version
                   FROM access.sessions s JOIN access.identities i USING(identity_id) WHERE token_digest=%s""",
                (token_digest,),
            ).fetchone()
        if row is None:
            return None
        return AccessSession(str(row[0]), str(row[1]), ProviderIdentity(str(row[2]), str(row[3]), str(row[4])), row[5], bool(row[6]), row[7], int(row[8]), None if row[9] is None else str(row[9]))

    def revoke_session(self, session_id: str, when: datetime) -> None:
        with _redacted_connection(self._provider) as connection:
            connection.execute("UPDATE access.sessions SET revoked_at=%s WHERE session_id=%s AND revoked_at IS NULL", (when, session_id))

    def save_challenge(self, challenge: ConfirmationChallenge, token_digest: str) -> None:
        with _redacted_connection(self._provider) as connection:
            connection.execute(
                """INSERT INTO access.confirmation_challenges
                   (challenge_id,actor_user_id,action_type,target_id,target_version,payload_digest,impact_summary,token_digest,issued_at,expires_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (challenge.challenge_id, challenge.actor_id, challenge.action_type, challenge.target_id, challenge.target_version,
                 challenge.payload_digest, json.dumps(challenge.impact_summary, sort_keys=True, separators=(",", ":")), token_digest,
                 challenge.expires_at - timedelta(minutes=5), challenge.expires_at),
            )

    def consume_challenge(self, token_digest: str, actor_id: str, action_type: str, target_version: int,
                          payload_digest: str, reason: str, now: datetime) -> ConfirmationChallenge | None:
        if not reason.strip():
            return None
        with _redacted_connection(self._provider) as connection:
            with connection.transaction():
                row = connection.execute(
                    """UPDATE access.confirmation_challenges SET consumed_at=%s
                       WHERE token_digest=%s AND actor_user_id=%s AND action_type=%s AND target_version=%s
                         AND payload_digest=%s AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>%s
                       RETURNING challenge_id::text,actor_user_id::text,action_type,target_id,target_version,payload_digest,impact_summary,expires_at,consumed_at""",
                    (now, token_digest, actor_id, action_type, target_version, payload_digest, now),
                ).fetchone()
                if row is None:
                    return None
                connection.execute(
                    """INSERT INTO access.security_audit_events(event_id,actor_user_id,subject_id,action,reason,metadata)
                       VALUES(%s,%s,%s,%s,%s,%s::jsonb)""",
                    (uuid.uuid4(), actor_id, str(row[3]), action_type, reason,
                     json.dumps({"challenge_id": row[0], "payload_digest": payload_digest})),
                )
        return ConfirmationChallenge(str(row[0]), str(row[1]), str(row[2]), str(row[3]), int(row[4]), str(row[5]), json.loads(row[6]), row[7], row[8])

    def execute_confirmed_account_action(self, *, token: str, actor_id: str, action_type: str,
                                         target_version: int, payload: dict[str, Any], reason: str,
                                         now: datetime) -> str:
        """Consume, mutate, and audit an account action in one transaction."""
        if not reason.strip():
            raise ValueError("reason_required")
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        token_digest = sha256(token.encode()).hexdigest()
        with _redacted_connection(self._provider) as connection:
            with connection.transaction():
                row = connection.execute(
                    """SELECT challenge_id::text,target_id FROM access.confirmation_challenges
                       WHERE token_digest=%s AND actor_user_id=%s AND action_type=%s AND target_version=%s
                         AND payload_digest=%s AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>%s
                       FOR UPDATE""",
                    (token_digest, actor_id, action_type, target_version, digest, now),
                ).fetchone()
                if row is None:
                    raise PermissionError("resource_unavailable")
                if action_type == "change_role":
                    role = Role(str(payload.get("role", "")))
                    changed = connection.execute(
                        """UPDATE access.users SET role=%s,identity_version=identity_version+1
                           WHERE user_id=%s AND identity_version=%s RETURNING user_id""",
                        (role.value, row[1], target_version),
                    ).fetchone()
                elif action_type == "change_status":
                    status = str(payload.get("status", ""))
                    if status not in {"active", "disabled"}:
                        raise ValueError("resource_unavailable")
                    changed = connection.execute(
                        """UPDATE access.users SET status=%s,identity_version=identity_version+1,
                                  disabled_at=CASE WHEN %s='disabled' THEN %s ELSE NULL END
                           WHERE user_id=%s AND identity_version=%s RETURNING user_id""",
                        (status, status, now, row[1], target_version),
                    ).fetchone()
                elif action_type == "add_identity":
                    changed = connection.execute(
                        "UPDATE access.users SET identity_version=identity_version+1 WHERE user_id=%s AND identity_version=%s RETURNING user_id",
                        (row[1], target_version),
                    ).fetchone()
                    if changed is not None:
                        connection.execute(
                            """INSERT INTO access.identities(identity_id,user_id,provider_id,provider_type,provider_subject,email_fact)
                               VALUES(%s,%s,%s,%s,%s,%s)""",
                            (uuid.uuid4(), row[1], payload["provider_id"], payload["provider_type"], payload["provider_subject"], payload["email_fact"]),
                        )
                elif action_type in {"disable_identity", "replace_identity"}:
                    prefix = "old_" if action_type == "replace_identity" else ""
                    disabled = connection.execute(
                        """UPDATE access.identities SET enabled=false,version=version+1 WHERE user_id=%s AND enabled
                           AND provider_id=%s AND provider_type=%s AND provider_subject=%s RETURNING identity_id""",
                        (row[1], payload[f"{prefix}provider_id"], payload[f"{prefix}provider_type"], payload[f"{prefix}provider_subject"]),
                    ).fetchone()
                    changed = None if disabled is None else connection.execute(
                        "UPDATE access.users SET identity_version=identity_version+1 WHERE user_id=%s AND identity_version=%s RETURNING user_id",
                        (row[1], target_version),
                    ).fetchone()
                    if changed is not None and action_type == "replace_identity":
                        connection.execute(
                            """INSERT INTO access.identities(identity_id,user_id,provider_id,provider_type,provider_subject,email_fact)
                               VALUES(%s,%s,%s,%s,%s,%s)""",
                            (uuid.uuid4(), row[1], payload["provider_id"], payload["provider_type"], payload["provider_subject"], payload["email_fact"]),
                        )
                else:
                    raise ValueError("resource_unavailable")
                if changed is None:
                    raise PermissionError("resource_unavailable")
                connection.execute("UPDATE access.confirmation_challenges SET consumed_at=%s,result_id=%s WHERE challenge_id=%s", (now, row[1], row[0]))
                connection.execute(
                    """INSERT INTO access.security_audit_events(event_id,actor_user_id,subject_id,action,reason,metadata)
                       VALUES(%s,%s,%s,%s,%s,%s::jsonb)""",
                    (uuid.uuid4(), actor_id, row[1], action_type, reason,
                     json.dumps({"challenge_id": row[0], "payload_digest": digest})),
                )
        return str(row[0])

    def execute_confirmed_action(self, *, token: str, actor_id: str, action_type: str,
                                 target_version: int, payload: dict[str, Any], reason: str,
                                 now: datetime) -> tuple[str, AccountSummary | None]:
        if action_type == "create_account":
            account = self.execute_confirmed_account_creation(
                token=token, actor_id=actor_id, payload=payload, reason=reason, now=now,
            )
            return self._challenge_id_for_result(account.user_id), AccountSummary(
                account.user_id, account.role, account.status, str(payload["provider_type"]), account.version,
            )
        challenge_id = self.execute_confirmed_account_action(
            token=token, actor_id=actor_id, action_type=action_type, target_version=target_version,
            payload=payload, reason=reason, now=now,
        )
        result = next((item for item in self.list_account_summaries() if item.user_id == self._challenge_result(challenge_id)), None)
        return challenge_id, result

    def _challenge_result(self, challenge_id: str) -> str:
        with _redacted_connection(self._provider) as connection:
            row = connection.execute("SELECT result_id FROM access.confirmation_challenges WHERE challenge_id=%s", (challenge_id,)).fetchone()
        if row is None or row[0] is None:
            raise PermissionError("resource_unavailable")
        return str(row[0])

    def _challenge_id_for_result(self, result_id: str) -> str:
        with _redacted_connection(self._provider) as connection:
            row = connection.execute("SELECT challenge_id::text FROM access.confirmation_challenges WHERE result_id=%s ORDER BY consumed_at DESC LIMIT 1", (result_id,)).fetchone()
        if row is None:
            raise PermissionError("resource_unavailable")
        return str(row[0])

    def execute_confirmed_account_creation(self, *, token: str, actor_id: str, payload: dict[str, Any],
                                           reason: str, now: datetime) -> AccessAccount:
        if not reason.strip():
            raise ValueError("reason_required")
        normalized = {**payload, "role": Role(payload["role"]).value}
        digest = sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        with _redacted_connection(self._provider) as connection:
            with connection.transaction():
                challenge = connection.execute(
                    """SELECT challenge_id::text FROM access.confirmation_challenges
                       WHERE token_digest=%s AND actor_user_id=%s AND action_type='create_account'
                         AND target_version=1 AND payload_digest=%s AND consumed_at IS NULL
                         AND revoked_at IS NULL AND expires_at>%s FOR UPDATE""",
                    (sha256(token.encode()).hexdigest(), actor_id, digest, now),
                ).fetchone()
                if challenge is None:
                    raise PermissionError("resource_unavailable")
                user_id, identity_id = uuid.uuid4(), uuid.uuid4()
                connection.execute("INSERT INTO access.users(user_id,role,status) VALUES(%s,%s,'active')", (user_id, normalized["role"]))
                connection.execute(
                    """INSERT INTO access.identities(identity_id,user_id,provider_id,provider_type,provider_subject,email_fact)
                       VALUES(%s,%s,%s,%s,%s,%s)""",
                    (identity_id, user_id, normalized["provider_id"], normalized["provider_type"],
                     normalized["provider_subject"], normalized["email_fact"]),
                )
                connection.execute("UPDATE access.confirmation_challenges SET consumed_at=%s,result_id=%s WHERE challenge_id=%s", (now, user_id, challenge[0]))
                connection.execute(
                    """INSERT INTO access.security_audit_events(event_id,actor_user_id,subject_id,action,reason,metadata)
                       VALUES(%s,%s,%s,'create_account',%s,%s::jsonb)""",
                    (uuid.uuid4(), actor_id, user_id, reason, json.dumps({"challenge_id": challenge[0], "payload_digest": digest})),
                )
        return AccessAccount(str(user_id), Role(normalized["role"]), "active", 1)

    def record_recovery_first_use(self, *, actor_id: str, session_id: str) -> bool:
        event_id = uuid.uuid5(uuid.NAMESPACE_URL, f"access-recovery:{session_id}")
        with _redacted_connection(self._provider) as connection:
            with connection.transaction():
                inserted = connection.execute(
                    """INSERT INTO access.workflow_outbox(event_id,event_type,payload)
                       VALUES(%s,'access.emergency_authenticated',%s::jsonb)
                       ON CONFLICT(event_id) DO NOTHING RETURNING event_id""",
                    (event_id, json.dumps({"actor_id": actor_id, "session_id": session_id})),
                ).fetchone()
                if inserted is None:
                    return False
                connection.execute(
                    """INSERT INTO access.security_audit_events(event_id,actor_user_id,subject_id,action,reason,metadata)
                       VALUES(%s,%s,%s,'emergency_authenticated','recovery_first_use',%s::jsonb)""",
                    (uuid.uuid4(), actor_id, session_id, json.dumps({"outbox_event_id": str(event_id)})),
                )
        return True
