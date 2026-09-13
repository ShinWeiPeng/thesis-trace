from dataclasses import replace
from datetime import timedelta
import hashlib
import os
import uuid

import pytest

from thesis_trace.adapters.postgres_recommendation.adapter import (
    PostgresRecommendationStore,
)
from thesis_trace.modules.access.contracts import Role, SecurityContext
from thesis_trace.modules.recommendation.service import RecommendationService
from thesis_trace.platform.postgres import bootstrap_schema
from thesis_trace.platform.database import create_database_engine, database_connection
from test_recommendation_publication import plan as publish, NOW

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL required",
)


def fixture():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    owner = str(uuid.uuid4())
    record = publish()
    record = replace(
        record,
        recommendation_id=str(uuid.uuid4()),
        inputs=replace(
            record.inputs, actor=replace(record.inputs.actor, actor_id=owner)
        ),
    )
    store = PostgresRecommendationStore(
        lambda: url,
        security_context_provider=lambda: SecurityContext(
            owner, Role.OWNER, "recommendation-store-test"
        ),
    )
    return url, owner, store, record


def decision(record, *, previous=None, status="deferred"):
    return RecommendationService.plan_decision(
        actor=record.inputs.actor,
        owner_id=record.inputs.actor.actor_id,
        recommendation_id=record.recommendation_id,
        recommendation_version=record.version,
        previous=previous,
        expected_sequence=previous.sequence if previous else 0,
        bound=record.inputs.bindings,
        current=record.inputs.bindings,
        target_status=status,
        reason="Review this specific version",
        now=NOW,
        defer_until=NOW + timedelta(days=1),
    )


def test_record_replay_and_sequenced_decision_history():
    url, owner, store, record = fixture()
    assert store.append_record(record) == record
    assert store.append_record(record) == record
    assert store.get_record(owner, record.recommendation_id, record.version) == record
    assert (
        store.get_record(str(uuid.uuid4()), record.recommendation_id, record.version)
        is None
    )
    deferred = decision(record)
    digest = hashlib.sha256(b"defer-command").hexdigest()
    assert (
        store.append_decision(
            deferred,
            expected_sequence=0,
            idempotency_key="defer-1",
            command_digest=digest,
        )
        == deferred
    )
    assert (
        store.append_decision(
            deferred,
            expected_sequence=0,
            idempotency_key="defer-1",
            command_digest=digest,
        )
        == deferred
    )
    accepted = decision(record, previous=deferred, status="accepted")
    assert (
        store.append_decision(
            accepted,
            expected_sequence=1,
            idempotency_key="accept-1",
            command_digest=hashlib.sha256(b"accept-command").hexdigest(),
        )
        == accepted
    )
    assert store.decision_history(owner, record.recommendation_id, record.version) == (
        deferred,
        accepted,
    )
    assert store.get_record(owner, record.recommendation_id, record.version) == record


def test_decision_conflicts_leave_no_partial_history_receipt_or_audit():
    url, owner, store, record = fixture()
    store.append_record(record)
    deferred = decision(record)
    digest = hashlib.sha256(b"original-command").hexdigest()
    store.append_decision(
        deferred,
        expected_sequence=0,
        idempotency_key="command-1",
        command_digest=digest,
    )
    with pytest.raises(ValueError, match="idempotency_conflict"):
        store.append_decision(
            deferred,
            expected_sequence=0,
            idempotency_key="command-1",
            command_digest=hashlib.sha256(b"different-command").hexdigest(),
        )
    with pytest.raises(ValueError, match="version_conflict"):
        store.append_decision(
            deferred,
            expected_sequence=0,
            idempotency_key="stale-command",
            command_digest=digest,
        )
    assert store.decision_history(owner, record.recommendation_id, record.version) == (
        deferred,
    )
    with psycopg.connect(url) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM recommendation.receipts WHERE owner_user_id=%s",
                (owner,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM recommendation.audit_events WHERE owner_user_id=%s",
                (owner,),
            ).fetchone()[0]
            == 2
        )


def test_outer_transaction_rolls_back_record_decision_receipt_and_audit():
    url, owner, store, record = fixture()
    engine = create_database_engine(lambda: url)
    with pytest.raises(ValueError, match="rollback-test"):
        with database_connection(engine) as connection:
            connection.exec_driver_sql(
                "SELECT set_config('app.user_id',%s,true)", (owner,)
            )
            connection.exec_driver_sql("SELECT set_config('app.role','owner',true)")
            bound = store.for_transaction(connection)
            bound.append_record(record)
            bound.append_decision(
                decision(record),
                expected_sequence=0,
                idempotency_key="rolled-back",
                command_digest=hashlib.sha256(b"rollback").hexdigest(),
            )
            raise ValueError("rollback-test")
    assert store.get_record(owner, record.recommendation_id, record.version) is None
    with psycopg.connect(url) as connection:
        for table in (
            "records",
            "input_bindings",
            "sources",
            "claims",
            "decisions",
            "receipts",
            "audit_events",
        ):
            assert (
                connection.execute(
                    f"SELECT count(*) FROM recommendation.{table} WHERE owner_user_id=%s",
                    (owner,),
                ).fetchone()[0]
                == 0
            )
    engine.dispose()


def test_real_rls_and_immutable_record_child_sets():
    url, owner, store, record = fixture()
    store.append_record(record)
    for table in ("records", "input_bindings", "sources", "claims", "audit_events"):
        with pytest.raises(psycopg.Error, match="immutable_recommendation_history"):
            with psycopg.connect(url) as connection:
                connection.execute(
                    f"DELETE FROM recommendation.{table} WHERE owner_user_id=%s",
                    (owner,),
                )
    with pytest.raises(psycopg.Error, match="recommendation_record_incomplete"):
        with psycopg.connect(url) as connection:
            connection.execute(
                "INSERT INTO recommendation.claims(owner_user_id,recommendation_id,version,ordinal,claim_text,supporting_snapshot_ids) VALUES(%s,%s,1,999,'Late claim',ARRAY['snapshot-1'])",
                (owner, record.recommendation_id),
            )
    role_name = "rec_rls_" + uuid.uuid4().hex
    with pytest.raises(ValueError, match="rollback-role"):
        with psycopg.connect(url) as connection:
            connection.execute(
                f"CREATE ROLE {role_name} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            connection.execute(f"GRANT USAGE ON SCHEMA recommendation TO {role_name}")
            connection.execute(
                f"GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA recommendation TO {role_name}"
            )
            connection.execute(f"SET LOCAL ROLE {role_name}")
            connection.execute("SELECT set_config('app.user_id',%s,true)", (owner,))
            connection.execute("SELECT set_config('app.role','owner',true)")
            assert (
                connection.execute(
                    "SELECT count(*) FROM recommendation.records"
                ).fetchone()[0]
                == 1
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with connection.transaction():
                    connection.execute(
                        "INSERT INTO recommendation.claims(owner_user_id,recommendation_id,version,ordinal,claim_text,supporting_snapshot_ids) VALUES(%s,%s,1,99,'Forged',ARRAY['snapshot-1'])",
                        (str(uuid.uuid4()), record.recommendation_id),
                    )
            connection.execute(
                "SELECT set_config('app.user_id',%s,true)", (str(uuid.uuid4()),)
            )
            for table in (
                "records",
                "input_bindings",
                "sources",
                "claims",
                "decisions",
                "receipts",
                "audit_events",
            ):
                assert (
                    connection.execute(
                        f"SELECT count(*) FROM recommendation.{table}"
                    ).fetchone()[0]
                    == 0
                )
            raise ValueError("rollback-role")


def test_concurrent_decisions_have_one_sequence_winner():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    url, owner, store, record = fixture()
    store.append_record(record)
    barrier = Barrier(2)

    def submit(status):
        planned = decision(record, status=status)
        barrier.wait(timeout=10)
        try:
            return store.append_decision(
                planned,
                expected_sequence=0,
                idempotency_key=status,
                command_digest=hashlib.sha256(status.encode()).hexdigest(),
            )
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, ("accepted", "rejected")))
    assert sum(result == "version_conflict" for result in results) == 1
    history = store.decision_history(owner, record.recommendation_id, record.version)
    assert len(history) == 1 and history[0].sequence == 1
    assert history[0].status in ("accepted", "rejected")
    with pytest.raises(ValueError, match="invalid_transition"):
        store.append_decision(
            replace(history[0], sequence=2, status="expired"),
            expected_sequence=1,
            idempotency_key="late-expiry",
            command_digest=hashlib.sha256(b"late").hexdigest(),
        )
