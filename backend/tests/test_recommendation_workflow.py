from dataclasses import replace
from itertools import count

import pytest

from thesis_trace.modules.workflow.contracts import (
    ActionItemStatus,
    ActionSourceRef,
    CreateActionItemCommand,
    TransitionActionItemCommand,
    WorkflowActorContext,
)
from thesis_trace.modules.workflow.service import WorkflowService
from test_workflow_domain import MemoryActionItemStore


NOW = "2026-09-05T12:00:00+00:00"
LATER = "2026-09-06T12:00:00+00:00"


class RecommendationTaskStore(MemoryActionItemStore):
    def get_by_source(self, actor_id, source_domain, record_id, source_version):
        return next(
            (
                item
                for item in self.items.values()
                if item.assignee_user_id == actor_id
                and item.source_domain == source_domain
                and item.source_record_id == record_id
                and item.source_version == source_version
            ),
            None,
        )


def actor():
    return WorkflowActorContext("owner-1", True, True, True)


def publication(*, version=1, direction="buy"):
    return CreateActionItemCommand(
        actor(),
        ActionSourceRef(
            "recommendation",
            "rec-1",
            version,
            "owner-1",
            "2330",
            "2330",
            "Test company",
            "workflow.recommendation-decision-v1",
            direction,
        ),
        "Review this published Recommendation",
        None,
        f"publication-{version}",
    )


def service():
    ids = count(1)
    return WorkflowService(
        RecommendationTaskStore(),
        clock=lambda: NOW,
        id_generator=lambda: f"item-{next(ids)}",
    )


def transition(item, target, *, defer_until=None):
    return TransitionActionItemCommand(
        actor(),
        item.item_id,
        item.version,
        target,
        "Task-only operation",
        defer_until,
        f"task-{item.version}",
        NOW,
        False,
    )


@pytest.mark.parametrize("direction", ["buy", "hold"])
def test_actionable_recommendation_materializes_one_normal_unlocked_owner_task(
    direction,
):
    subject = service()
    first = subject.create(publication(direction=direction))
    replay = subject.create(publication(direction=direction))
    assert first.item_id == replay.item_id
    assert first.item_type.value == "recommendation_decision"
    assert first.priority.system_priority.value == "normal"
    assert first.priority.safety_locked is False
    assert first.priority.rule_ids == ("workflow.recommendation-decision-v1",)
    assert first.assignee_user_id == "owner-1"


def test_task_dismissal_does_not_recreate_the_same_recommendation_but_new_version_is_distinct():
    subject = service()
    first = subject.create(publication())
    dismissed = subject.transition(transition(first, ActionItemStatus.DISMISSED))
    replay = subject.create(publication())
    next_version = subject.create(publication(version=2))
    assert replay.item_id == dismissed.item_id
    assert replay.status is ActionItemStatus.DISMISSED
    assert next_version.item_id != dismissed.item_id
    assert next_version.source_version == 2


def test_inbox_cannot_complete_a_recommendation_task_without_the_domain_decision():
    subject = service()
    item = subject.create(publication())
    assert ActionItemStatus.COMPLETED not in item.allowed_transitions
    with pytest.raises(ValueError, match="invalid_transition"):
        subject.transition(transition(item, ActionItemStatus.COMPLETED))
    with pytest.raises(ValueError, match="invalid_transition"):
        subject.transition(
            replace(
                transition(item, ActionItemStatus.COMPLETED), underlying_resolved=True
            )
        )


@pytest.mark.parametrize("direction", ["abstain", "failed", "exit", "would_be_hard"])
def test_nonactionable_or_shadow_hard_output_does_not_become_a_decision_task(direction):
    with pytest.raises(ValueError, match="invalid_source"):
        service().create(publication(direction=direction))


def reconcile(subject, status, **changes):
    arguments = dict(
        actor=actor(),
        source_record_id="rec-1",
        source_version=1,
        decision_sequence=1,
        decision_status=status,
        reason="Domain decision",
        server_time=NOW,
        defer_until=None,
    )
    arguments.update(changes)
    return subject.reconcile_recommendation(**arguments)


@pytest.mark.parametrize("status", ["accepted", "rejected", "expired"])
def test_domain_terminal_decision_resolves_linked_open_task_and_retries_without_duplicate_history(
    status,
):
    subject = service()
    first = subject.create(publication())
    completed = reconcile(subject, status)
    retried = reconcile(subject, status)
    assert completed.item_id == first.item_id
    assert completed.status is ActionItemStatus.COMPLETED
    assert completed.version == 2
    assert retried == completed


def test_domain_defer_updates_open_reminder_without_reopening_a_dismissed_task():
    subject = service()
    subject.create(publication())
    deferred = reconcile(subject, "deferred", defer_until=LATER)
    assert deferred.status is ActionItemStatus.DEFERRED
    assert deferred.defer_until == LATER
    repeated = reconcile(
        subject,
        "deferred",
        decision_sequence=2,
        defer_until="2026-09-07T12:00:00+00:00",
    )
    assert repeated.version == 3
    dismissed = subject.transition(transition(repeated, ActionItemStatus.DISMISSED))
    assert reconcile(subject, "accepted", decision_sequence=3) == dismissed
