from dataclasses import replace
import hashlib
import os
import uuid

import pytest

from thesis_trace.adapters.postgres_recommendation.adapter import (
    PostgresRecommendationStore,
)
from thesis_trace.modules.access.contracts import Role, SecurityContext
from thesis_trace.platform.postgres import bootstrap_schema
from thesis_trace.platform.database import create_database_engine, database_connection
from test_recommendation_publication import inputs
from test_recommendation_admission import versions

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL required",
)


def fixture():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    owner = str(uuid.uuid4())
    store = PostgresRecommendationStore(
        lambda: url,
        security_context_provider=lambda: SecurityContext(
            owner, Role.OWNER, "job-test"
        ),
    )
    frozen = inputs()
    return (
        url,
        owner,
        store,
        replace(frozen, actor=replace(frozen.actor, actor_id=owner)),
    )


def admit(store, frozen, *, key="request-1"):
    return store.admit(
        inputs=frozen,
        input_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        versions=versions(),
        idempotency_key=key,
        command_digest=hashlib.sha256(key.encode()).hexdigest(),
    )


def test_admission_replay_claim_and_fenced_completion():
    url, owner, store, frozen = fixture()
    input_id = admit(store, frozen)
    assert admit(store, frozen) == input_id
    assert store.get_input(owner, input_id) == (frozen, versions())
    job = store.claim_job()
    assert job is not None and job.actor_id == owner and job.input_id == input_id
    assert job.attempt == 1 and job.versions == versions()
    renewed = store.renew_job(job)
    assert (
        renewed.lease_token == job.lease_token
        and renewed.lease_expires_at >= job.lease_expires_at
    )
    with pytest.raises(ValueError, match="lease_unavailable"):
        store.finish_job(replace(job, lease_token=str(uuid.uuid4())))
    store.finish_job(renewed)
    assert store.job_status(owner, input_id) == ("succeeded", None)
    with pytest.raises(ValueError, match="lease_unavailable"):
        store.finish_job(renewed)


def test_owner_bound_claim_cannot_take_another_owners_older_job_even_with_test_superuser():
    _url, first_owner, first_store, first_inputs = fixture()
    _url, second_owner, second_store, second_inputs = fixture()
    first_id = admit(first_store, first_inputs)
    second_id = admit(second_store, second_inputs)
    claimed = second_store.claim_job()
    try:
        assert claimed.actor_id == second_owner and claimed.input_id == second_id
    finally:
        second_store.finish_job(claimed)
    first_claimed = first_store.claim_job()
    assert first_claimed.actor_id == first_owner and first_claimed.input_id == first_id
    with pytest.raises(ValueError, match="lease_unavailable"):
        second_store.finish_job(first_claimed)
    first_store.finish_job(first_claimed)


def expire(url, job):
    with psycopg.connect(url) as connection:
        connection.execute(
            "UPDATE recommendation.jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE job_id=%s",
            (job.job_id,),
        )


def test_expired_claim_reclaims_same_inputs_and_never_attempts_a_fourth_time():
    url, owner, store, frozen = fixture()
    input_id = admit(store, frozen)
    first = store.claim_job()
    assert store.load_job_input(first) == frozen
    expire(url, first)
    with pytest.raises(ValueError, match="lease_unavailable"):
        store.renew_job(first)
    second = store.claim_job()
    assert (
        second.job_id == first.job_id
        and second.attempt == 2
        and second.lease_token != first.lease_token
    )
    assert store.load_job_input(second) == frozen
    with pytest.raises(ValueError, match="lease_unavailable"):
        store.finish_job(first)
    expire(url, second)
    third = store.claim_job()
    assert third.attempt == 3
    expire(url, third)
    assert store.claim_job() is None
    assert store.job_status(owner, input_id) == ("dead_letter", "lease_exhausted")


def test_transport_backoff_and_schema_failure_are_distinct():
    url, owner, store, frozen = fixture()
    input_id = admit(store, frozen)
    first = store.claim_job()
    store.fail_job(first, error_code="provider_transport_failure", transient=True)
    assert store.job_status(owner, input_id) == (
        "retrying",
        "provider_transport_failure",
    )
    assert store.claim_job() is None
    with psycopg.connect(url) as connection:
        delay = connection.execute(
            "SELECT extract(epoch FROM available_at-updated_at) FROM recommendation.jobs WHERE job_id=%s",
            (first.job_id,),
        ).fetchone()[0]
        assert 59 <= delay <= 61
        connection.execute(
            "UPDATE recommendation.jobs SET available_at=clock_timestamp()-interval '1 second' WHERE job_id=%s",
            (first.job_id,),
        )
    second = store.claim_job()
    store.fail_job(second, error_code="critic_transport_failure", transient=True)
    with psycopg.connect(url) as connection:
        delay = connection.execute(
            "SELECT extract(epoch FROM available_at-updated_at) FROM recommendation.jobs WHERE job_id=%s",
            (first.job_id,),
        ).fetchone()[0]
        assert 239 <= delay <= 241
        connection.execute(
            "UPDATE recommendation.jobs SET available_at=clock_timestamp()-interval '1 second' WHERE job_id=%s",
            (first.job_id,),
        )
    third = store.claim_job()
    store.fail_job(third, error_code="provider_transport_failure", transient=True)
    assert store.job_status(owner, input_id) == (
        "dead_letter",
        "provider_transport_failure",
    )
    another = admit(store, frozen, key="schema-case")
    job = store.claim_job()
    store.fail_job(job, error_code="invalid_candidate", transient=True)
    assert store.job_status(owner, another) == ("failed", "invalid_candidate")
    assert store.claim_job() is None


def test_simultaneous_claims_serialize_one_owner_thesis_cycle():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    url, owner, store, frozen = fixture()
    admit(store, frozen, key="first")
    admit(store, frozen, key="second")
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=10)
        return store.claim_job()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result()
            for future in (executor.submit(claim), executor.submit(claim))
        ]
    assert sum(result is None for result in results) == 1
    first = next(result for result in results if result is not None)
    # Another subject is still eligible while the first stream has a durable lease.
    different = admit(
        store, replace(frozen, thesis_id="independent-thesis"), key="third"
    )
    independent = store.claim_job()
    assert independent.input_id == different
    store.finish_job(independent)
    store.finish_job(first)
    second = store.claim_job()
    assert second.input_id != first.input_id and second.thesis_id == first.thesis_id
    store.finish_job(second)


def test_global_capacity_rejects_atomically_without_partial_input():
    url, owner, store, frozen = fixture()
    engine = create_database_engine(lambda: url)
    with pytest.raises(ValueError, match="rollback-capacity-test"):
        with database_connection(engine) as connection:
            connection.exec_driver_sql(
                "SELECT set_config('app.user_id',%s,true)", (owner,)
            )
            connection.exec_driver_sql("SELECT set_config('app.role','owner',true)")
            bound = store.for_transaction(connection)
            before = connection.exec_driver_sql(
                "SELECT live_count FROM recommendation.queue_capacity"
            ).scalar_one()
            for index in range(1000 - before):
                admit(bound, frozen, key=f"capacity-{index}")
            connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
            connection.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")
            # All 1000 live jobs are real, complete admissions; no fake counter seeding.
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM recommendation.jobs WHERE state IN ('pending','processing','retrying')"
                ).scalar_one()
                == 1000
            )
            with pytest.raises(ValueError, match="recommendation_queue_full"):
                with connection.begin_nested():
                    admit(bound, frozen, key="overloaded")
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM recommendation.admissions WHERE owner_user_id=%s",
                    (owner,),
                ).scalar_one()
                == 1000 - before
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT live_count FROM recommendation.queue_capacity"
                ).scalar_one()
                == 1000
            )
            raise ValueError("rollback-capacity-test")
    with psycopg.connect(url) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM recommendation.admissions WHERE owner_user_id=%s",
                (owner,),
            ).fetchone()[0]
            == 0
        )
    engine.dispose()


def test_api_cannot_claim_or_touch_capacity_but_worker_can_claim_across_owners():
    import sqlalchemy as sa

    url, owner, store, frozen = fixture()
    engine = create_database_engine(lambda: url)
    api_role = "queue_api_" + uuid.uuid4().hex
    with pytest.raises(ValueError, match="rollback-role-test"):
        with database_connection(engine) as connection:
            connection.exec_driver_sql(
                f"CREATE ROLE {api_role} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            if not connection.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='thesis_trace_ai_worker')"
            ).scalar_one():
                connection.exec_driver_sql(
                    "CREATE ROLE thesis_trace_ai_worker NOLOGIN NOSUPERUSER NOBYPASSRLS"
                )
            for role in (api_role, "thesis_trace_ai_worker"):
                connection.exec_driver_sql(
                    f"GRANT USAGE ON SCHEMA recommendation TO {role}"
                )
                connection.exec_driver_sql(
                    f"GRANT SELECT,INSERT ON recommendation.admissions,recommendation.admission_bindings,recommendation.admission_sources,recommendation.jobs,recommendation.admission_events TO {role}"
                )
            connection.exec_driver_sql(
                "GRANT UPDATE ON recommendation.jobs TO thesis_trace_ai_worker"
            )
            connection.exec_driver_sql(f"SET LOCAL ROLE {api_role}")
            connection.exec_driver_sql(
                "SELECT set_config('app.user_id',%s,true)", (owner,)
            )
            connection.exec_driver_sql("SELECT set_config('app.role','owner',true)")
            first_id = admit(store.for_transaction(connection), frozen)
            for sql in (
                "SELECT live_count FROM recommendation.queue_capacity",
                "UPDATE recommendation.queue_capacity SET live_count=0",
            ):
                with pytest.raises(sa.exc.ProgrammingError) as error:
                    with connection.begin_nested():
                        connection.exec_driver_sql(sql)
                assert error.value.orig.sqlstate == "42501"
            with pytest.raises(sa.exc.ProgrammingError) as error:
                with connection.begin_nested():
                    store.for_transaction(connection).claim_job()
            assert error.value.orig.sqlstate == "42501"
            other_owner = str(uuid.uuid4())
            other = PostgresRecommendationStore(
                lambda: url,
                security_context_provider=lambda: SecurityContext(
                    other_owner, Role.OWNER, "job-test"
                ),
            )
            connection.exec_driver_sql(
                "SELECT set_config('app.user_id',%s,true)", (other_owner,)
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM recommendation.admissions"
                ).scalar_one()
                == 0
            )
            second_id = admit(
                other.for_transaction(connection),
                replace(frozen, actor=replace(frozen.actor, actor_id=other_owner)),
            )
            connection.exec_driver_sql("SET LOCAL ROLE thesis_trace_ai_worker")
            # Control only these two fixture jobs; do not assume an otherwise empty queue.
            connection.exec_driver_sql(
                "UPDATE recommendation.jobs SET available_at=TIMESTAMPTZ '2000-01-01 UTC' WHERE input_id=%s",
                (first_id,),
            )
            connection.exec_driver_sql(
                "UPDATE recommendation.jobs SET available_at=TIMESTAMPTZ '2000-01-02 UTC' WHERE input_id=%s",
                (second_id,),
            )
            assert connection.exec_driver_sql(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).one() == (False, False)
            worker = PostgresRecommendationStore(
                lambda: url, security_context_provider=lambda: None
            ).for_transaction(connection)
            job = worker.claim_job()
            assert job.actor_id == owner and job.input_id == first_id
            assert worker.load_job_input(job) == frozen
            worker.finish_job(job)
            next_job = worker.claim_job()
            assert next_job.actor_id == other_owner
            worker.finish_job(next_job)
            connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
            raise ValueError("rollback-role-test")
    engine.dispose()
