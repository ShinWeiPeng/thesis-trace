import os
import uuid
from dataclasses import replace
from itertools import count

import pytest

from thesis_trace.adapters.postgres_workflow.adapter import PostgresWorkflowStore
from thesis_trace.modules.access.contracts import Role, SecurityContext
from thesis_trace.modules.workflow.contracts import ActionItemStatus
from thesis_trace.modules.workflow.service import WorkflowService
from thesis_trace.platform.postgres import bootstrap_schema
from thesis_trace.platform.database import create_database_engine, database_connection
from test_recommendation_workflow import NOW, actor, publication, reconcile, transition


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL required",
)


def test_recommendation_source_task_round_trip_and_terminal_preservation():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    context = SecurityContext(actor().actor_id, Role.OWNER, "wave7-workflow-test")
    store = PostgresWorkflowStore(
        lambda: url, security_context_provider=lambda: context
    )
    store.delete_all_for_test()
    ids = count(1)
    subject = WorkflowService(
        store, clock=lambda: NOW, id_generator=lambda: f"wave7-item-{next(ids)}"
    )
    first = subject.create(publication())
    assert (
        store.get_by_source(actor().actor_id, "recommendation", "rec-1", 1).item_id
        == first.item_id
    )
    assert store.get_by_source("foreign-owner", "recommendation", "rec-1", 1) is None
    assert store.get_by_source(actor().actor_id, "recommendation", "rec-1", 2) is None
    dismissed = subject.transition(transition(first, ActionItemStatus.DISMISSED))
    assert reconcile(subject, "accepted") == dismissed
    assert (
        subject.create(replace(publication(), idempotency_key="replayed-publication"))
        == dismissed
    )


def test_outer_transaction_failure_rolls_back_task_decision_receipt_and_audit():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    context = SecurityContext(actor().actor_id, Role.OWNER, "wave7-atomic-test")
    store = PostgresWorkflowStore(
        lambda: url, security_context_provider=lambda: context
    )
    store.delete_all_for_test()
    subject = WorkflowService(
        store, clock=lambda: NOW, id_generator=lambda: "rollback-item"
    )
    first = subject.create(publication())
    engine = create_database_engine(lambda: url)
    try:
        with pytest.raises(ValueError, match="injected_participant_failure"):
            with database_connection(engine) as connection:
                connection.exec_driver_sql(
                    "SELECT set_config('app.user_id',%s,true),set_config('app.role','owner',true)",
                    (actor().actor_id,),
                )
                bound = WorkflowService(
                    store.for_transaction(connection),
                    clock=lambda: NOW,
                    id_generator=lambda: "unused",
                )
                assert reconcile(bound, "accepted").status is ActionItemStatus.COMPLETED
                raise ValueError("injected_participant_failure")
        assert subject.get(actor(), first.item_id).status is ActionItemStatus.PENDING
        assert store.count_audit_events(first.item_id) == 1
        completed = reconcile(subject, "accepted")
        assert completed.status is ActionItemStatus.COMPLETED
        assert completed.version == 2
    finally:
        engine.dispose()


def test_bound_store_requires_active_matching_owner_context():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    context = SecurityContext(actor().actor_id, Role.OWNER, "wave7-context-test")
    store = PostgresWorkflowStore(
        lambda: url, security_context_provider=lambda: context
    )
    engine = create_database_engine(lambda: url)
    try:
        with engine.connect() as connection:
            with pytest.raises(ValueError, match="active_transaction_required"):
                store.for_transaction(connection)
            with connection.begin():
                connection.exec_driver_sql(
                    "SELECT set_config('app.user_id','foreign-owner',true),set_config('app.role','owner',true)"
                )
                bound = store.for_transaction(connection)
                with pytest.raises(
                    PermissionError, match="transaction_context_mismatch"
                ):
                    bound.get_by_source(actor().actor_id, "recommendation", "rec-1", 1)
            with pytest.raises(ValueError, match="active_transaction_required"):
                bound.get_by_source(actor().actor_id, "recommendation", "rec-1", 1)
    finally:
        engine.dispose()


def test_recommendation_task_lookup_enforces_real_nobypassrls_isolation():
    from psycopg.errors import InsufficientPrivilege

    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    owner = SecurityContext(actor().actor_id, Role.OWNER, "wave7-rls-test")
    foreign = SecurityContext("foreign-owner", Role.OWNER, "wave7-rls-test")
    store = PostgresWorkflowStore(lambda: url, security_context_provider=lambda: owner)
    store.delete_all_for_test()
    WorkflowService(store, clock=lambda: NOW, id_generator=lambda: "rls-item").create(
        publication()
    )
    engine = create_database_engine(lambda: url)
    # Role DDL and grants are deliberately rolled back with this isolated test.
    role_name = f"wave7_rls_{uuid.uuid4().hex}"
    try:
        with pytest.raises(ValueError, match="rollback_test_role"):
            with database_connection(engine) as connection:
                connection.exec_driver_sql(
                    f'CREATE ROLE "{role_name}" NOLOGIN NOSUPERUSER NOBYPASSRLS'
                )
                connection.exec_driver_sql(
                    f'GRANT USAGE ON SCHEMA workflow TO "{role_name}"'
                )
                connection.exec_driver_sql(
                    f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA workflow TO "{role_name}"'
                )
                connection.exec_driver_sql(f'SET LOCAL ROLE "{role_name}"')
                assert connection.exec_driver_sql(
                    "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).one() == (False, False)
                connection.exec_driver_sql(
                    "SELECT set_config('app.user_id',%s,true),set_config('app.role','owner',true)",
                    (actor().actor_id,),
                )
                assert (
                    store.for_transaction(connection)
                    .get_by_source(actor().actor_id, "recommendation", "rec-1", 1)
                    .item_id
                    == "rls-item"
                )
                connection.exec_driver_sql(
                    "SELECT set_config('app.user_id','foreign-owner',true)"
                )
                foreign_store = PostgresWorkflowStore(
                    lambda: url, security_context_provider=lambda: foreign
                ).for_transaction(connection)
                assert (
                    foreign_store.get_by_source(
                        actor().actor_id, "recommendation", "rec-1", 1
                    )
                    is None
                )
                # Supplying the real owner's lookup ID cannot bypass row policy.
                assert (
                    connection.exec_driver_sql(
                        "SELECT count(*) FROM workflow.action_items"
                    ).scalar_one()
                    == 0
                )
                with pytest.raises(InsufficientPrivilege):
                    with connection.begin_nested():
                        foreign_bound = WorkflowService(
                            foreign_store,
                            clock=lambda: NOW,
                            id_generator=lambda: "forged-owner-item",
                        )
                        foreign_bound.create(
                            replace(
                                publication(version=2), idempotency_key="forged-owner"
                            )
                        )
                raise ValueError("rollback_test_role")
    finally:
        engine.dispose()
