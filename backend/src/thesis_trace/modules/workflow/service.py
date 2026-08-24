from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from typing import Callable

from .contracts import (
    ActionInboxPage,
    ActionInboxQuery,
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ActionPriority,
    ActionPriorityEvaluation,
    CreateActionItemCommand,
    TransitionActionItemCommand,
)
from .ports import ActionItemStorePort


_TERMINAL = {ActionItemStatus.COMPLETED, ActionItemStatus.DISMISSED}
_NON_SAFETY_TRANSITIONS = {
    ActionItemStatus.PENDING: (
        ActionItemStatus.IN_PROGRESS,
        ActionItemStatus.DEFERRED,
        ActionItemStatus.COMPLETED,
        ActionItemStatus.DISMISSED,
    ),
    ActionItemStatus.IN_PROGRESS: (
        ActionItemStatus.PENDING,
        ActionItemStatus.DEFERRED,
        ActionItemStatus.COMPLETED,
        ActionItemStatus.DISMISSED,
    ),
    ActionItemStatus.DEFERRED: (
        ActionItemStatus.PENDING,
        ActionItemStatus.IN_PROGRESS,
        ActionItemStatus.COMPLETED,
        ActionItemStatus.DISMISSED,
    ),
    ActionItemStatus.COMPLETED: (),
    ActionItemStatus.DISMISSED: (),
}


def _digest(parts: tuple[object, ...]) -> str:
    canonical = "".join(f"{len(str(part).encode())}:{part}" for part in parts)
    return sha256(canonical.encode()).hexdigest()


def _aware_datetime(value: str, error_code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(error_code) from error
    if parsed.utcoffset() is None:
        raise ValueError(error_code)
    return parsed


class WorkflowService:
    POLICY_VERSION = "action-priority-v1"
    CREATION_RULE_VERSION = "manual-anomaly-review-v1"

    def __init__(
        self,
        store: ActionItemStorePort,
        *,
        clock: Callable[[], str],
        id_generator: Callable[[], str],
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_generator = id_generator

    @staticmethod
    def _priority(required_handling: str) -> ActionPriorityEvaluation:
        if required_handling not in {"would_be_hard", "human_review"}:
            raise ValueError("invalid_source")
        return ActionPriorityEvaluation(
            system_priority=ActionPriority.HIGH,
            effective_priority=ActionPriority.HIGH,
            safety_floor=None,
            safety_locked=False,
            rule_ids=("workflow.shadow-anomaly-review-v1",),
            policy_version=WorkflowService.POLICY_VERSION,
            reason="Shadow anomaly requires Owner review; formal Hard is not active.",
        )

    @staticmethod
    def _allowed(item: ActionItem) -> tuple[ActionItemStatus, ...]:
        if item.status in _TERMINAL:
            return ()
        if item.priority.safety_locked:
            if item.status is ActionItemStatus.PENDING:
                return (ActionItemStatus.IN_PROGRESS,)
            if item.status is ActionItemStatus.IN_PROGRESS:
                return (ActionItemStatus.PENDING,)
            return ()
        return _NON_SAFETY_TRANSITIONS[item.status]

    @classmethod
    def _project(cls, item: ActionItem) -> ActionItem:
        return replace(item, allowed_transitions=cls._allowed(item))

    def create(self, command: CreateActionItemCommand) -> ActionItem:
        source = command.source
        if not command.actor.may_create or command.actor.actor_id != source.source_owner_id:
            raise PermissionError("forbidden")
        if (
            source.source_domain != "anomaly_assessment"
            or source.trigger_kind != self.CREATION_RULE_VERSION
            or source.source_version < 1
            or not command.reason.strip()
            or not command.idempotency_key.strip()
        ):
            raise ValueError("invalid_source")
        if command.due_at is not None:
            _aware_datetime(command.due_at, "invalid_due_at")
        priority = self._priority(source.required_handling)
        fingerprint = _digest((
            self.CREATION_RULE_VERSION,
            source.source_domain,
            source.source_record_id,
            source.source_version,
            source.trigger_kind,
            source.required_handling,
        ))
        material_fingerprint = _digest((
            self.CREATION_RULE_VERSION,
            source.source_domain,
            source.source_record_id,
            source.trigger_kind,
            source.required_handling,
        ))
        command_digest = _digest((fingerprint, command.reason.strip(), command.due_at or ""))
        now = self._clock()
        item = ActionItem(
            item_id=self._id_generator(),
            version=1,
            item_type=ActionItemType.ANOMALY_REVIEW,
            source_domain=source.source_domain,
            source_record_id=source.source_record_id,
            source_version=source.source_version,
            company_id=source.company_id,
            company_ticker=source.company_ticker,
            company_name=source.company_name,
            assignee_user_id=source.source_owner_id,
            reason=command.reason.strip(),
            status=ActionItemStatus.PENDING,
            priority=priority,
            created_at=now,
            updated_at=now,
            due_at=command.due_at,
            defer_until=None,
            recurrence_of=None,
        )
        return self._project(self._store.create(
            item,
            fingerprint=fingerprint,
            material_fingerprint=material_fingerprint,
            creation_rule_version=self.CREATION_RULE_VERSION,
            trigger_kind=source.trigger_kind,
            idempotency_key=command.idempotency_key,
            command_digest=command_digest,
        ))

    def get(self, actor, item_id: str) -> ActionItem:
        if not actor.may_read:
            raise PermissionError("forbidden")
        return self._project(self._store.get(actor.actor_id, item_id))

    def query(self, query: ActionInboxQuery) -> ActionInboxPage:
        if not query.actor.may_read:
            raise PermissionError("forbidden")
        if query.page_size < 1 or query.page_size > 100:
            raise ValueError("invalid_query")
        if query.item_type is not None and query.item_type not in {value.value for value in ActionItemType}:
            raise ValueError("invalid_query")
        if query.status is not None and query.status not in {value.value for value in ActionItemStatus}:
            raise ValueError("invalid_query")
        if query.priority is not None and query.priority not in ({value.value for value in ActionPriority} | {"urgent"}):
            raise ValueError("invalid_query")
        for value in (query.created_from, query.created_to, query.due_from, query.due_to):
            if value is not None:
                _aware_datetime(value, "invalid_query")
        page = self._store.query(query)
        return replace(page, items=tuple(self._project(item) for item in page.items))

    def transition(self, command: TransitionActionItemCommand) -> ActionItem:
        if not command.actor.may_transition:
            raise PermissionError("forbidden")
        if not command.reason.strip() or not command.idempotency_key.strip():
            raise ValueError("invalid_transition")
        server_time = _aware_datetime(command.server_time, "invalid_transition")
        parsed_defer_until = None
        if command.defer_until is not None:
            parsed_defer_until = _aware_datetime(command.defer_until, "invalid_transition")
        command_digest = _digest((
            command.item_id,
            command.expected_version,
            command.target_status.value,
            command.reason.strip(),
            command.defer_until or "",
            command.underlying_resolved,
        ))
        current = self._store.get(command.actor.actor_id, command.item_id)
        # Preserve exact retry replay: a stale expected version must reach the
        # store receipt check before optimistic concurrency is rejected.
        if current.version == command.expected_version:
            allowed = self._allowed(current)
            if command.target_status not in allowed:
                if not (
                    current.priority.safety_locked
                    and command.target_status is ActionItemStatus.COMPLETED
                    and command.underlying_resolved
                    and current.status in {ActionItemStatus.PENDING, ActionItemStatus.IN_PROGRESS}
                ):
                    raise ValueError("invalid_transition")
            if command.target_status is ActionItemStatus.DEFERRED:
                if parsed_defer_until is None or parsed_defer_until <= server_time:
                    raise ValueError("invalid_transition")
            elif parsed_defer_until is not None:
                raise ValueError("invalid_transition")
        updated = self._store.transition(
            current,
            expected_version=command.expected_version,
            target_status=command.target_status,
            reason=command.reason.strip(),
            defer_until=command.defer_until,
            idempotency_key=command.idempotency_key,
            command_digest=command_digest,
            occurred_at=command.server_time,
        )
        return self._project(updated)
