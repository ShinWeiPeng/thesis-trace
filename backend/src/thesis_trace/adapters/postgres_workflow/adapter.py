from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import uuid
from typing import Any, Callable, Iterator

from thesis_trace.modules.access.contracts import SecurityContext
from thesis_trace.modules.workflow.contracts import (
    ActionInboxPage,
    ActionInboxQuery,
    ActionInboxSummary,
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ActionPriority,
    ActionPriorityEvaluation,
)
from thesis_trace.platform.postgres import DatabaseUrlProvider, _psycopg


_OPEN_STATUSES = ("pending", "in_progress", "deferred")
_PRIORITY_SQL = "CASE effective_priority WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'normal' THEN 2 ELSE 1 END"


class PostgresWorkflowStore:
    """RLS-scoped, append-audited storage for an assignee's action inbox."""

    def __init__(
        self,
        database_url_provider: DatabaseUrlProvider,
        *,
        security_context_provider: Callable[[], SecurityContext | None],
        cursor_key: bytes | None = None,
    ) -> None:
        self._database_url_provider = database_url_provider
        self._security_context_provider = security_context_provider
        self._cursor_key = cursor_key or secrets.token_bytes(32)

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        context = self._security_context_provider()
        if context is None:
            raise PermissionError("missing_security_context")
        with _psycopg().connect(self._database_url_provider()) as connection:
            connection.execute("SELECT set_config('app.user_id',%s,true)", (context.user_id,))
            connection.execute("SELECT set_config('app.role',%s,true)", (context.role.value,))
            connection.execute("SELECT set_config('app.request_id',%s,true)", (context.ownership_scope,))
            yield connection

    @staticmethod
    def _priority(row: dict[str, Any]) -> ActionPriorityEvaluation:
        floor = row.get("safety_floor")
        return ActionPriorityEvaluation(
            system_priority=ActionPriority(row["system_priority"]),
            effective_priority=ActionPriority(row["effective_priority"]),
            safety_floor=ActionPriority(floor) if floor else None,
            safety_locked=bool(row["safety_locked"]),
            rule_ids=tuple(row["priority_rule_ids"]),
            policy_version=row["priority_policy_version"],
            reason=row["priority_reason"],
        )

    @classmethod
    def _item(cls, row: dict[str, Any]) -> ActionItem:
        def iso(value: Any) -> str | None:
            return value.isoformat() if isinstance(value, datetime) else value

        return ActionItem(
            item_id=row["item_id"],
            version=int(row["version"]),
            item_type=ActionItemType(row["item_type"]),
            source_domain=row["source_domain"],
            source_record_id=row["source_record_id"],
            source_version=int(row["source_version"]),
            company_id=row["company_id"],
            company_ticker=row["company_ticker"],
            company_name=row["company_name"],
            assignee_user_id=row["assignee_user_id"],
            reason=row["reason"],
            status=ActionItemStatus(row["status"]),
            priority=cls._priority(row),
            created_at=iso(row["created_at"]),
            updated_at=iso(row["updated_at"]),
            due_at=iso(row.get("due_at")),
            defer_until=iso(row.get("defer_until")),
            recurrence_of=row.get("recurrence_of"),
        )

    @staticmethod
    def _row(cursor: Any) -> dict[str, Any]:
        values = cursor.fetchone()
        if values is None:
            raise LookupError("action_item_not_found")
        return dict(zip((column.name for column in cursor.description), values, strict=True))

    @staticmethod
    def _lock_key(value: str) -> int:
        raw = hashlib.sha256(value.encode()).digest()[:8]
        return int.from_bytes(raw, "big", signed=True)

    def create(
        self,
        item: ActionItem,
        *,
        fingerprint: str,
        material_fingerprint: str,
        creation_rule_version: str,
        trigger_kind: str,
        idempotency_key: str,
        command_digest: str,
    ) -> ActionItem:
        with self._connection() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (
                self._lock_key(f"{item.assignee_user_id}:{idempotency_key}"),
            ))
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (
                self._lock_key(f"{creation_rule_version}:{item.source_domain}:{item.source_record_id}"),
            ))
            receipt = connection.execute(
                "SELECT command_digest,item_id FROM workflow.creation_receipts WHERE actor_user_id=%s AND idempotency_key=%s",
                (item.assignee_user_id, idempotency_key),
            ).fetchone()
            if receipt:
                if receipt[0] != command_digest:
                    raise ValueError("idempotency_conflict")
                return self._get(connection, item.assignee_user_id, receipt[1])

            prior = connection.execute(
                """SELECT item_id,material_fingerprint FROM workflow.action_items
                WHERE assignee_user_id=%s AND creation_rule_version=%s
                  AND source_domain=%s AND source_record_id=%s
                ORDER BY created_at DESC,item_id DESC LIMIT 1""",
                (item.assignee_user_id, creation_rule_version, item.source_domain, item.source_record_id),
            ).fetchone()
            if prior and prior[1] == material_fingerprint:
                connection.execute(
                    "INSERT INTO workflow.creation_receipts(actor_user_id,idempotency_key,command_digest,item_id) VALUES(%s,%s,%s,%s)",
                    (item.assignee_user_id, idempotency_key, command_digest, prior[0]),
                )
                return self._get(connection, item.assignee_user_id, prior[0])
            terminal = connection.execute(
                """SELECT item_id FROM workflow.action_items
                WHERE assignee_user_id=%s AND creation_rule_version=%s
                  AND source_domain=%s AND source_record_id=%s
                  AND status IN ('completed','dismissed')
                ORDER BY updated_at DESC,item_id DESC LIMIT 1""",
                (item.assignee_user_id, creation_rule_version, item.source_domain, item.source_record_id),
            ).fetchone()
            recurrence_of = terminal[0] if terminal else None
            inserted = connection.execute(
                """
                INSERT INTO workflow.action_items(
                  item_id,version,item_type,source_domain,source_record_id,source_version,
                  trigger_fingerprint,material_fingerprint,creation_rule_version,trigger_kind,
                  company_id,company_ticker,company_name,assignee_user_id,
                  reason,status,system_priority,effective_priority,safety_floor,safety_locked,
                  priority_rule_ids,priority_policy_version,priority_reason,created_at,updated_at,
                  due_at,defer_until,recurrence_of
                ) VALUES(
                  %s,%s,%s,%s,%s,
                  %s,%s,%s,%s,%s,
                  %s,%s,%s,%s,%s,
                  %s,%s,%s,%s,%s,
                  %s::jsonb,%s,%s,
                  %s::timestamptz,%s::timestamptz,%s::timestamptz,%s::timestamptz,%s
                ) ON CONFLICT(trigger_fingerprint) DO NOTHING RETURNING item_id
                """,
                (
                    item.item_id, item.version, item.item_type.value, item.source_domain,
                    item.source_record_id, item.source_version, fingerprint, material_fingerprint,
                    creation_rule_version, trigger_kind, item.company_id,
                    item.company_ticker, item.company_name, item.assignee_user_id, item.reason,
                    item.status.value, item.priority.system_priority.value,
                    item.priority.effective_priority.value,
                    item.priority.safety_floor.value if item.priority.safety_floor else None,
                    item.priority.safety_locked, json.dumps(item.priority.rule_ids),
                    item.priority.policy_version, item.priority.reason, item.created_at,
                    item.updated_at, item.due_at, item.defer_until, recurrence_of,
                ),
            ).fetchone()
            created = inserted is not None
            item_id = inserted[0] if created else connection.execute(
                "SELECT item_id FROM workflow.action_items WHERE trigger_fingerprint=%s",
                (fingerprint,),
            ).fetchone()[0]
            if created:
                connection.execute(
                    """INSERT INTO workflow.action_priority_evaluations(
                    item_id,evaluation_version,system_priority,effective_priority,safety_floor,
                    safety_locked,rule_ids,policy_version,reason,evaluated_at)
                    VALUES(%s,1,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::timestamptz)""",
                    (item_id, item.priority.system_priority.value, item.priority.effective_priority.value,
                     item.priority.safety_floor.value if item.priority.safety_floor else None,
                     item.priority.safety_locked, json.dumps(item.priority.rule_ids),
                     item.priority.policy_version, item.priority.reason, item.created_at),
                )
                connection.execute(
                    """INSERT INTO workflow.audit_events(
                    event_id,item_id,item_version,actor_user_id,action,from_status,to_status,reason,occurred_at)
                    VALUES(%s,%s,1,%s,'created',NULL,%s,%s,%s::timestamptz)""",
                    (uuid.uuid4(), item_id, item.assignee_user_id, item.status.value, item.reason, item.created_at),
                )
            connection.execute(
                "INSERT INTO workflow.creation_receipts(actor_user_id,idempotency_key,command_digest,item_id) VALUES(%s,%s,%s,%s)",
                (item.assignee_user_id, idempotency_key, command_digest, item_id),
            )
            return self._get(connection, item.assignee_user_id, item_id)

    def _get(self, connection: Any, actor_id: str, item_id: str) -> ActionItem:
        cursor = connection.execute(
            "SELECT * FROM workflow.action_items WHERE item_id=%s AND assignee_user_id=%s",
            (item_id, actor_id),
        )
        return self._item(self._row(cursor))

    def get(self, actor_id: str, item_id: str) -> ActionItem:
        with self._connection() as connection:
            return self._get(connection, actor_id, item_id)

    def _encode_cursor(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self._cursor_key, body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(body + signature).decode().rstrip("=")

    def _decode_cursor(self, value: str) -> dict[str, Any]:
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
            body, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(signature, hmac.new(self._cursor_key, body, hashlib.sha256).digest()):
                raise ValueError
            decoded = json.loads(body)
            if not isinstance(decoded, dict):
                raise ValueError
            return decoded
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid_cursor") from error

    @staticmethod
    def _query_binding(query: ActionInboxQuery) -> str:
        return hashlib.sha256(json.dumps({
            "schema": "action-inbox-query-v1",
            "actor": query.actor.actor_id, "search": query.search, "company": query.company_id,
            "type": query.item_type, "status": query.status, "priority": query.priority,
            "created_from": query.created_from, "created_to": query.created_to,
            "due_from": query.due_from, "due_to": query.due_to,
            "open": query.open_only, "sort": query.sort, "direction": query.direction,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def query(self, query: ActionInboxQuery) -> ActionInboxPage:
        binding = self._query_binding(query)
        if query.cursor:
            cursor = self._decode_cursor(query.cursor)
            required = {
                "v", "binding", "as_of", "primary", "primary_null",
                "due", "due_null", "created", "item_id",
            }
            if not required.issubset(cursor) or cursor.get("v") != 1 or cursor.get("binding") != binding:
                raise ValueError("invalid_cursor")
            as_of = cursor["as_of"]
        else:
            as_of = datetime.now(timezone.utc).isoformat()
            cursor = None
        if query.sort not in {"effective_priority", "due_at", "created_at", "updated_at"} or query.direction not in {"asc", "desc"}:
            raise ValueError("invalid_query")
        sort_expression, primary_cast = {
            "effective_priority": (_PRIORITY_SQL, "int"),
            "due_at": ("due_at", "timestamptz"),
            "created_at": ("created_at", "timestamptz"),
            "updated_at": ("updated_at", "timestamptz"),
        }[query.sort]
        direction = query.direction.upper()
        order_sql = (
            f"({sort_expression} IS NULL) ASC, {sort_expression} {direction} NULLS LAST, "
            "(due_at IS NULL) ASC, due_at ASC NULLS LAST, created_at ASC, item_id ASC"
        )
        anchor_sql = "TRUE"
        last_primary = last_due = last_created = last_item_id = None
        last_primary_null = last_due_null = False
        if cursor is not None:
            last_primary = cursor["primary"]
            last_primary_null = bool(cursor["primary_null"])
            last_due = cursor["due"]
            last_due_null = bool(cursor["due_null"])
            last_created = cursor["created"]
            last_item_id = cursor["item_id"]
            comparator = ">" if direction == "ASC" else "<"
            anchor_sql = f"""
              (({sort_expression} IS NULL)::int > %(last_primary_null)s::int)
              OR (({sort_expression} IS NULL)=%(last_primary_null)s AND (
                ({sort_expression} IS NOT NULL AND {sort_expression} {comparator} %(last_primary)s::{primary_cast})
                OR ({sort_expression} IS NOT DISTINCT FROM %(last_primary)s::{primary_cast} AND (
                  ((due_at IS NULL)::int > %(last_due_null)s::int)
                  OR ((due_at IS NULL)=%(last_due_null)s AND (
                    (due_at IS NOT NULL AND due_at > %(last_due)s::timestamptz)
                    OR (due_at IS NOT DISTINCT FROM %(last_due)s::timestamptz AND (
                      created_at > %(last_created)s::timestamptz
                      OR (created_at=%(last_created)s::timestamptz AND item_id>%(last_item_id)s)
                    ))
                  ))
                ))
              ))
            """
        with self._connection() as connection:
            row = connection.execute(
                f"""
                WITH filtered AS (
                  SELECT * FROM workflow.action_items
                  WHERE assignee_user_id=%(actor)s AND created_at <= %(as_of)s::timestamptz
                    AND (NOT %(open_only)s OR status = ANY(%(open_statuses)s))
                    AND (%(search)s::text IS NULL OR company_ticker ILIKE '%%'||%(search)s::text||'%%' OR company_name ILIKE '%%'||%(search)s::text||'%%' OR reason ILIKE '%%'||%(search)s::text||'%%')
                    AND (%(company_id)s::text IS NULL OR company_id=%(company_id)s::text)
                    AND (%(item_type)s::text IS NULL OR item_type=%(item_type)s::text)
                    AND (%(status)s::text IS NULL OR status=%(status)s::text)
                    AND (%(priority)s::text IS NULL
                      OR (%(priority)s::text='urgent' AND effective_priority IN ('critical','high'))
                      OR effective_priority=%(priority)s::text)
                    AND (%(created_from)s::text IS NULL OR created_at >= %(created_from)s::timestamptz)
                    AND (%(created_to)s::text IS NULL OR created_at <= %(created_to)s::timestamptz)
                    AND (%(due_from)s::text IS NULL OR due_at >= %(due_from)s::timestamptz)
                    AND (%(due_to)s::text IS NULL OR due_at <= %(due_to)s::timestamptz)
                ), page AS (
                  SELECT *, row_number() OVER (ORDER BY {order_sql}) AS page_order
                  FROM filtered WHERE {anchor_sql}
                  ORDER BY {order_sql} LIMIT %(limit)s
                ), summary AS (
                  SELECT count(*)::int AS total_count,
                    count(*) FILTER (WHERE effective_priority IN ('critical','high') AND status=ANY(%(open_statuses)s))::int AS urgent,
                    count(*) FILTER (WHERE due_at::date=(%(as_of)s::timestamptz)::date AND status=ANY(%(open_statuses)s))::int AS due_today,
                    count(*) FILTER (WHERE status='deferred')::int AS deferred,
                    count(*) FILTER (WHERE status=ANY(%(open_statuses)s))::int AS all_open
                  FROM filtered
                )
                SELECT summary.*,
                  COALESCE(jsonb_agg(to_jsonb(page)-'trigger_fingerprint'-'page_order' ORDER BY page.page_order)
                    FILTER (WHERE page.item_id IS NOT NULL),'[]'::jsonb) AS items
                FROM summary LEFT JOIN page ON true GROUP BY summary.total_count,summary.urgent,summary.due_today,summary.deferred,summary.all_open
                """,
                {
                    "actor": query.actor.actor_id, "as_of": as_of, "open_only": query.open_only,
                    "open_statuses": list(_OPEN_STATUSES), "search": query.search,
                    "company_id": query.company_id, "item_type": query.item_type,
                    "status": query.status, "priority": query.priority,
                    "created_from": query.created_from, "created_to": query.created_to,
                    "due_from": query.due_from, "due_to": query.due_to,
                    "limit": query.page_size + 1, "last_primary": last_primary,
                    "last_primary_null": last_primary_null, "last_due": last_due,
                    "last_due_null": last_due_null, "last_created": last_created,
                    "last_item_id": last_item_id,
                },
            ).fetchone()
        total_count, urgent, due_today, deferred, all_open, rows = row
        next_cursor = None
        if len(rows) > query.page_size:
            rows = rows[:query.page_size]
            last = rows[-1]
            primary = (
                {"critical": 4, "high": 3, "normal": 2, "low": 1}[last["effective_priority"]]
                if query.sort == "effective_priority" else last[query.sort]
            )
            next_cursor = self._encode_cursor({
                "v": 1, "binding": binding, "as_of": as_of,
                "primary": primary, "primary_null": primary is None,
                "due": last["due_at"], "due_null": last["due_at"] is None,
                "created": last["created_at"], "item_id": last["item_id"],
            })
        return ActionInboxPage(
            summary=ActionInboxSummary(urgent, due_today, deferred, all_open),
            total_count=total_count,
            items=tuple(self._item(value) for value in rows),
            next_cursor=next_cursor,
            as_of=as_of,
        )

    def transition(
        self,
        current: ActionItem,
        *,
        expected_version: int,
        target_status: ActionItemStatus,
        reason: str,
        defer_until: str | None,
        idempotency_key: str,
        command_digest: str,
        occurred_at: str,
    ) -> ActionItem:
        with self._connection() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (
                self._lock_key(f"{current.assignee_user_id}:{idempotency_key}"),
            ))
            receipt = connection.execute(
                "SELECT command_digest,item_id FROM workflow.transition_receipts WHERE actor_user_id=%s AND idempotency_key=%s",
                (current.assignee_user_id, idempotency_key),
            ).fetchone()
            if receipt:
                if receipt[0] != command_digest:
                    raise ValueError("idempotency_conflict")
                return self._get(connection, current.assignee_user_id, receipt[1])
            locked = connection.execute(
                "SELECT version,status FROM workflow.action_items WHERE item_id=%s AND assignee_user_id=%s FOR UPDATE",
                (current.item_id, current.assignee_user_id),
            ).fetchone()
            if locked is None:
                raise LookupError("action_item_not_found")
            if locked[0] != expected_version:
                raise ValueError("version_conflict")
            new_version = expected_version + 1
            connection.execute(
                """UPDATE workflow.action_items SET version=%s,status=%s,
                defer_until=%s::timestamptz,updated_at=%s::timestamptz WHERE item_id=%s""",
                (new_version, target_status.value, defer_until, occurred_at, current.item_id),
            )
            connection.execute(
                """INSERT INTO workflow.audit_events(
                event_id,item_id,item_version,actor_user_id,action,from_status,to_status,reason,occurred_at)
                VALUES(%s,%s,%s,%s,'transitioned',%s,%s,%s,%s::timestamptz)""",
                (uuid.uuid4(), current.item_id, new_version, current.assignee_user_id,
                 current.status.value, target_status.value, reason, occurred_at),
            )
            connection.execute(
                """INSERT INTO workflow.transition_receipts(
                actor_user_id,idempotency_key,command_digest,item_id,item_version) VALUES(%s,%s,%s,%s,%s)""",
                (current.assignee_user_id, idempotency_key, command_digest, current.item_id, new_version),
            )
            return self._get(connection, current.assignee_user_id, current.item_id)

    def delete_all_for_test(self) -> None:
        with self._connection() as connection:
            connection.execute(
                "TRUNCATE workflow.transition_receipts,workflow.creation_receipts,"
                "workflow.audit_events,workflow.action_priority_evaluations,workflow.action_items"
            )

    def count_audit_events(self, item_id: str) -> int:
        with self._connection() as connection:
            return connection.execute(
                "SELECT count(*) FROM workflow.audit_events WHERE item_id=%s", (item_id,)
            ).fetchone()[0]

    def count_priority_evaluations(self, item_id: str) -> int:
        with self._connection() as connection:
            return connection.execute(
                "SELECT count(*) FROM workflow.action_priority_evaluations WHERE item_id=%s", (item_id,)
            ).fetchone()[0]
