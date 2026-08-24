from __future__ import annotations

from dataclasses import replace

import pytest

from thesis_trace.modules.workflow.contracts import (
    ActionInboxPage,
    ActionInboxQuery,
    ActionInboxSummary,
    ActionItem,
    ActionItemStatus,
    ActionSourceRef,
    CreateActionItemCommand,
    TransitionActionItemCommand,
    WorkflowActorContext,
)
from thesis_trace.modules.workflow.service import WorkflowService


class MemoryActionItemStore:
    def __init__(self) -> None:
        self.items: dict[str, ActionItem] = {}
        self.fingerprints: dict[str, str] = {}

    def create(self, item: ActionItem, *, fingerprint: str, idempotency_key: str, command_digest: str) -> ActionItem:
        del idempotency_key, command_digest
        existing_id = self.fingerprints.get(fingerprint)
        if existing_id is not None:
            return self.items[existing_id]
        self.items[item.item_id] = item
        self.fingerprints[fingerprint] = item.item_id
        return item

    def get(self, actor_id: str, item_id: str) -> ActionItem:
        item = self.items[item_id]
        if item.assignee_user_id != actor_id:
            raise LookupError("resource_unavailable")
        return item

    def query(self, query: ActionInboxQuery) -> ActionInboxPage:
        items = tuple(item for item in self.items.values() if item.assignee_user_id == query.actor.actor_id)
        return ActionInboxPage(
            summary=ActionInboxSummary(urgent=len(items), due_today=0, deferred=0, all_open=len(items)),
            total_count=len(items),
            items=items,
            next_cursor=None,
            as_of="2026-08-24T10:00:00+00:00",
        )

    def transition(
        self,
        current: ActionItem,
        *,
        target_status: ActionItemStatus,
        reason: str,
        defer_until: str | None,
        idempotency_key: str,
        command_digest: str,
        occurred_at: str,
    ) -> ActionItem:
        del reason, idempotency_key, command_digest
        updated = replace(
            current,
            version=current.version + 1,
            status=target_status,
            updated_at=occurred_at,
            defer_until=defer_until,
        )
        self.items[current.item_id] = updated
        return updated


def owner() -> WorkflowActorContext:
    return WorkflowActorContext("owner-1", may_create=True, may_read=True, may_transition=True)


def source(version: int = 2) -> ActionSourceRef:
    return ActionSourceRef(
        source_domain="anomaly_assessment",
        source_record_id="assessment-1",
        source_version=version,
        source_owner_id="owner-1",
        company_id="company-1",
        company_ticker="TT",
        company_name="Thesis Trace",
        trigger_kind="manual-anomaly-review-v1",
        required_handling="would_be_hard",
    )


def test_shadow_anomaly_review_is_high_unlocked_and_deduplicated() -> None:
    store = MemoryActionItemStore()
    service = WorkflowService(
        store,
        clock=lambda: "2026-08-24T10:00:00+00:00",
        id_generator=iter(("item-1", "item-2")).__next__,
    )
    command = CreateActionItemCommand(owner(), source(), "Review the shadow anomaly", None, "retry-1")

    first = service.create(command)
    retried = service.create(replace(command, idempotency_key="retry-2"))

    assert first.item_id == retried.item_id == "item-1"
    assert first.status is ActionItemStatus.PENDING
    assert first.priority.system_priority.value == "high"
    assert first.priority.effective_priority.value == "high"
    assert first.priority.rule_ids == ("workflow.shadow-anomaly-review-v1",)
    assert first.priority.safety_locked is False
    assert first.priority.safety_floor is None
    assert first.assignee_user_id == "owner-1"


def test_terminal_item_cannot_reopen() -> None:
    store = MemoryActionItemStore()
    service = WorkflowService(
        store,
        clock=lambda: "2026-08-24T10:00:00+00:00",
        id_generator=lambda: "item-1",
    )
    item = service.create(CreateActionItemCommand(owner(), source(), "Review", None, "create-1"))
    completed = service.transition(
        TransitionActionItemCommand(
            owner(), item.item_id, item.version, ActionItemStatus.COMPLETED,
            "Reviewed and resolved", None, "transition-1", "2026-08-24T10:01:00+00:00", False,
        )
    )

    with pytest.raises(ValueError, match="invalid_transition"):
        service.transition(
            TransitionActionItemCommand(
                owner(), completed.item_id, completed.version, ActionItemStatus.PENDING,
                "Reopen", None, "transition-2", "2026-08-24T10:02:00+00:00", False,
            )
        )
