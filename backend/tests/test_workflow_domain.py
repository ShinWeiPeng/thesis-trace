from __future__ import annotations

from dataclasses import replace

import pytest

from thesis_trace.modules.workflow.contracts import (
    ActionInboxPage,
    ActionInboxQuery,
    ActionInboxSummary,
    ActionItem,
    ActionItemStatus,
    ActionPriority,
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
        self.material: dict[tuple[str, str, str], tuple[str, str]] = {}
        self.transition_receipts: dict[str, tuple[str, str]] = {}

    def create(
        self, item: ActionItem, *, fingerprint: str, material_fingerprint: str,
        creation_rule_version: str, trigger_kind: str, idempotency_key: str,
        command_digest: str,
    ) -> ActionItem:
        del trigger_kind, idempotency_key, command_digest
        existing_id = self.fingerprints.get(fingerprint)
        if existing_id is not None:
            return self.items[existing_id]
        key = (creation_rule_version, item.source_domain, item.source_record_id)
        prior = self.material.get(key)
        if prior is not None and prior[0] == material_fingerprint:
            return self.items[prior[1]]
        terminal = next((candidate for candidate in reversed(tuple(self.items.values()))
                         if candidate.source_domain == item.source_domain
                         and candidate.source_record_id == item.source_record_id
                         and candidate.status in {ActionItemStatus.COMPLETED, ActionItemStatus.DISMISSED}), None)
        if terminal is not None:
            item = replace(item, recurrence_of=terminal.item_id)
        self.items[item.item_id] = item
        self.fingerprints[fingerprint] = item.item_id
        self.material[key] = (material_fingerprint, item.item_id)
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
        expected_version: int,
        target_status: ActionItemStatus,
        reason: str,
        defer_until: str | None,
        idempotency_key: str,
        command_digest: str,
        occurred_at: str,
    ) -> ActionItem:
        del reason
        receipt = self.transition_receipts.get(idempotency_key)
        if receipt is not None:
            if receipt[0] != command_digest:
                raise ValueError("idempotency_conflict")
            return self.items[receipt[1]]
        if self.items[current.item_id].version != expected_version:
            raise ValueError("version_conflict")
        updated = replace(
            current,
            version=current.version + 1,
            status=target_status,
            updated_at=occurred_at,
            defer_until=defer_until,
        )
        self.items[current.item_id] = updated
        self.transition_receipts[idempotency_key] = (command_digest, current.item_id)
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


def test_transition_exact_retry_replays_and_preserves_creation_reason() -> None:
    store = MemoryActionItemStore()
    service = WorkflowService(store, clock=lambda: "2026-08-24T10:00:00+00:00", id_generator=lambda: "item-1")
    item = service.create(CreateActionItemCommand(owner(), source(), "Original reason", None, "create-1"))
    command = TransitionActionItemCommand(
        owner(), item.item_id, item.version, ActionItemStatus.COMPLETED,
        "Resolution reason", None, "transition-1", "2026-08-24T10:01:00+00:00", False,
    )

    first = service.transition(command)
    replay = service.transition(command)

    assert replay == first
    assert replay.version == 2
    assert replay.reason == "Original reason"

    with pytest.raises(ValueError, match="version_conflict"):
        service.transition(replace(command, idempotency_key="transition-stale"))
    assert store.items[item.item_id].version == 2


def test_material_change_after_terminal_creates_linked_recurrence() -> None:
    store = MemoryActionItemStore()
    service = WorkflowService(
        store, clock=lambda: "2026-08-24T10:00:00+00:00",
        id_generator=iter(("item-1", "item-2", "item-3")).__next__,
    )
    first = service.create(CreateActionItemCommand(owner(), source(), "Review", None, "create-1"))
    service.transition(TransitionActionItemCommand(
        owner(), first.item_id, first.version, ActionItemStatus.COMPLETED,
        "Resolved", None, "transition-1", "2026-08-24T10:01:00+00:00", False,
    ))

    version_only = service.create(CreateActionItemCommand(owner(), source(3), "Review again", None, "create-2"))
    material = service.create(CreateActionItemCommand(
        owner(), replace(source(4), required_handling="human_review"), "New material route", None, "create-3",
    ))

    assert version_only.item_id == first.item_id
    assert material.item_id == "item-3"
    assert material.recurrence_of == first.item_id


def test_rejects_naive_due_and_defer_times() -> None:
    service = WorkflowService(MemoryActionItemStore(), clock=lambda: "2026-08-24T10:00:00+00:00", id_generator=lambda: "item-1")
    with pytest.raises(ValueError, match="invalid_due_at"):
        service.create(CreateActionItemCommand(owner(), source(), "Review", "2026-08-25T10:00:00", "create-1"))


def test_safety_lock_rejects_defer_dismiss_and_unverified_completion() -> None:
    store = MemoryActionItemStore()
    service = WorkflowService(store, clock=lambda: "2026-08-24T10:00:00+00:00", id_generator=lambda: "item-1")
    item = service.create(CreateActionItemCommand(owner(), source(), "Safety review", None, "create-1"))
    locked = replace(item, priority=replace(
        item.priority, effective_priority=ActionPriority.CRITICAL,
        safety_floor=ActionPriority.CRITICAL, safety_locked=True,
    ))
    store.items[item.item_id] = locked

    for target, defer_until in (
        (ActionItemStatus.DEFERRED, "2026-08-25T10:00:00+00:00"),
        (ActionItemStatus.DISMISSED, None),
        (ActionItemStatus.COMPLETED, None),
    ):
        with pytest.raises(ValueError, match="invalid_transition"):
            service.transition(TransitionActionItemCommand(
                owner(), item.item_id, item.version, target, "Not resolved", defer_until,
                f"transition-{target.value}", "2026-08-24T10:01:00+00:00", False,
            ))

    completed = service.transition(TransitionActionItemCommand(
        owner(), item.item_id, item.version, ActionItemStatus.COMPLETED, "Underlying condition resolved",
        None, "transition-resolved", "2026-08-24T10:02:00+00:00", True,
    ))
    assert completed.status is ActionItemStatus.COMPLETED
