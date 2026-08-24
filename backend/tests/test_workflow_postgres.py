from __future__ import annotations

import os

import psycopg
import pytest

from thesis_trace.adapters.postgres_workflow.adapter import PostgresWorkflowStore
from thesis_trace.modules.access.contracts import Role, SecurityContext
from thesis_trace.modules.workflow.contracts import (
    ActionInboxQuery,
    ActionItemStatus,
    ActionSourceRef,
    CreateActionItemCommand,
    TransitionActionItemCommand,
    WorkflowActorContext,
)
from thesis_trace.modules.workflow.service import WorkflowService
from thesis_trace.platform.postgres import bootstrap_schema


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="set THESIS_TRACE_TEST_DATABASE_URL for PostgreSQL integration evidence",
)


@pytest.fixture()
def workflow() -> tuple[WorkflowService, PostgresWorkflowStore]:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    context = SecurityContext("00000000-0000-0000-0000-000000000001", Role.OWNER, "workflow-test")
    store = PostgresWorkflowStore(lambda: url, security_context_provider=lambda: context, cursor_key=b"test-key")
    store.delete_all_for_test()
    service = WorkflowService(
        store,
        clock=lambda: "2026-08-24T00:00:00+00:00",
        id_generator=iter(("item-1", "item-2", "item-3", "item-4")).__next__,
    )
    return service, store


def actor() -> WorkflowActorContext:
    return WorkflowActorContext(
        "00000000-0000-0000-0000-000000000001", True, True, True
    )


def source(record_id: str, company_id: str) -> ActionSourceRef:
    return ActionSourceRef(
        "anomaly_assessment", record_id, 1, actor().actor_id,
        company_id, company_id.upper(), f"Company {company_id}",
        "manual-anomaly-review-v1", "would_be_hard",
    )


def test_postgres_create_query_transition_and_audit_are_consistent(
    workflow: tuple[WorkflowService, PostgresWorkflowStore],
) -> None:
    service, store = workflow
    first = service.create(CreateActionItemCommand(actor(), source("assessment-1", "aaa"), "Review A", None, "create-1"))
    second = service.create(CreateActionItemCommand(actor(), source("assessment-2", "bbb"), "Review B", None, "create-2"))

    page = service.query(ActionInboxQuery(actor(), page_size=1))
    assert page.summary.urgent == page.summary.all_open == page.total_count == 2
    assert len(page.items) == 1
    assert page.next_cursor is not None
    next_page = service.query(ActionInboxQuery(actor(), page_size=1, cursor=page.next_cursor))
    assert {page.items[0].item_id, next_page.items[0].item_id} == {first.item_id, second.item_id}

    completed = service.transition(TransitionActionItemCommand(
        actor(), first.item_id, first.version, ActionItemStatus.COMPLETED,
        "Reviewed", None, "transition-1", "2026-08-24T00:01:00+00:00", False,
    ))
    assert completed.version == 2
    assert completed.status is ActionItemStatus.COMPLETED
    assert completed.reason == "Review A"
    assert store.count_audit_events(first.item_id) == 2
    assert store.count_priority_evaluations(first.item_id) == 1

    replay = service.transition(TransitionActionItemCommand(
        actor(), first.item_id, first.version, ActionItemStatus.COMPLETED,
        "Reviewed", None, "transition-1", "2026-08-24T00:01:00+00:00", False,
    ))
    assert replay == completed
    assert store.count_audit_events(first.item_id) == 2
    with pytest.raises(ValueError, match="version_conflict"):
        service.transition(TransitionActionItemCommand(
            actor(), first.item_id, first.version, ActionItemStatus.COMPLETED,
            "Reviewed", None, "transition-stale", "2026-08-24T00:02:00+00:00", False,
        ))
    assert store.count_audit_events(first.item_id) == 2

    version_only = service.create(CreateActionItemCommand(
        actor(), ActionSourceRef(
            "anomaly_assessment", "assessment-1", 2, actor().actor_id,
            "aaa", "AAA", "Company aaa", "manual-anomaly-review-v1", "would_be_hard",
        ), "Version only", None, "create-version-only",
    ))
    assert version_only.item_id == first.item_id

    recurrence = service.create(CreateActionItemCommand(
        actor(), ActionSourceRef(
            "anomaly_assessment", "assessment-1", 3, actor().actor_id,
            "aaa", "AAA", "Company aaa", "manual-anomaly-review-v1", "human_review",
        ), "Material recurrence", None, "create-recurrence",
    ))
    assert recurrence.item_id != first.item_id
    assert recurrence.recurrence_of == first.item_id

    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    with psycopg.connect(url) as connection:
        connection.execute(
            "UPDATE workflow.action_items SET system_priority='critical',effective_priority='critical' WHERE item_id=%s",
            (second.item_id,),
        )
    urgent = service.query(ActionInboxQuery(actor(), priority="urgent", open_only=True))
    assert {candidate.priority.effective_priority.value for candidate in urgent.items} == {"critical", "high"}

    open_page = service.query(ActionInboxQuery(actor(), open_only=True))
    assert open_page.summary.all_open == open_page.total_count == 2


def test_workflow_rls_hides_other_assignees(
    workflow: tuple[WorkflowService, PostgresWorkflowStore],
) -> None:
    service, _store = workflow
    item = service.create(CreateActionItemCommand(actor(), source("assessment-rls", "aaa"), "Review", None, "create-rls"))
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    role_name = "thesis_trace_workflow_rls_integration"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role_name}') "
            f"THEN CREATE ROLE {role_name} NOLOGIN NOBYPASSRLS; END IF; END $$"
        )
        connection.execute(f"GRANT USAGE ON SCHEMA workflow TO {role_name}")
        connection.execute(f"GRANT SELECT ON workflow.action_items TO {role_name}")
        connection.execute(f"SET ROLE {role_name}")
        with connection.transaction():
            connection.execute("SELECT set_config('app.user_id',%s,true)", (actor().actor_id,))
            assert connection.execute("SELECT item_id FROM workflow.action_items").fetchone()[0] == item.item_id
        with connection.transaction():
            connection.execute("SELECT set_config('app.user_id','00000000-0000-0000-0000-000000000099',true)")
            assert connection.execute("SELECT count(*) FROM workflow.action_items").fetchone()[0] == 0
        connection.execute("RESET ROLE")
