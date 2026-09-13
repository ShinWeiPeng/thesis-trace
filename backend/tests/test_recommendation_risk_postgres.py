from dataclasses import replace
from decimal import Decimal
import os
import uuid

import pytest

from thesis_trace.adapters.postgres_portfolio.adapter import PostgresPortfolioStore
from thesis_trace.modules.access.contracts import Role, SecurityContext
from thesis_trace.platform.postgres import bootstrap_schema
from thesis_trace.platform.database import create_database_engine, database_connection
from test_recommendation_portfolio import prepare
from test_portfolio_domain import MemoryPortfolioStore, configured
from thesis_trace.modules.portfolio.service import PortfolioService

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL required",
)


def fixture():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    actor_id = str(uuid.uuid4())
    store = PostgresPortfolioStore(
        lambda: url,
        security_context_provider=lambda: SecurityContext(
            actor_id, Role.OWNER, "risk-test"
        ),
    )
    memory = MemoryPortfolioStore()
    service = PortfolioService(memory)
    current = configured(service)
    from test_portfolio_domain import holding

    memory.record = replace(
        current,
        holdings=(
            holding(quantity="0.1"),
            replace(holding(quantity="0.2"), bucket_id="another"),
        ),
    )
    snapshot = prepare(service, current.version, snapshot_id=str(uuid.uuid4()))
    return url, actor_id, store, snapshot


def test_frozen_risk_roundtrip_uses_only_immutable_owner_rows():
    url, actor, store, snapshot = fixture()
    store.append_recommendation_snapshot(actor, snapshot)
    assert store.get_recommendation_snapshot(actor, snapshot.snapshot_id) == snapshot
    assert (
        store.get(actor) is None
    )  # Snapshot persistence does not fabricate current cash/holdings.
    assert (
        store.get_recommendation_snapshot(str(uuid.uuid4()), snapshot.snapshot_id)
        is None
    )
    assert store.get_recommendation_snapshot(actor, "absent") is None
    loaded = store.get_recommendation_snapshot(actor, snapshot.snapshot_id)
    loaded.exposure.security_exposure["2330"] = Decimal(999)
    assert store.get_recommendation_snapshot(actor, snapshot.snapshot_id) == snapshot


def test_outer_transaction_rolls_back_all_snapshot_rows():
    url, actor, store, snapshot = fixture()
    engine = create_database_engine(lambda: url)
    with pytest.raises(ValueError, match="rollback-test"):
        with database_connection(engine) as connection:
            connection.exec_driver_sql(
                "SELECT set_config('app.user_id',%s,true)", (actor,)
            )
            connection.exec_driver_sql("SELECT set_config('app.role','owner',true)")
            bound = store.for_transaction(connection)
            bound.append_recommendation_snapshot(actor, snapshot)
            assert (
                bound.get_recommendation_snapshot(actor, snapshot.snapshot_id)
                == snapshot
            )
            raise ValueError("rollback-test")
    assert store.get_recommendation_snapshot(actor, snapshot.snapshot_id) is None
    with psycopg.connect(url) as connection:
        for table in (
            "recommendation_snapshots",
            "recommendation_holdings",
            "recommendation_exposures",
        ):
            assert (
                connection.execute(
                    f"SELECT count(*) FROM portfolio.{table} WHERE snapshot_id=%s",
                    (snapshot.snapshot_id,),
                ).fetchone()[0]
                == 0
            )
    engine.dispose()


def test_snapshot_rows_and_child_sets_are_immutable():
    url, actor, store, snapshot = fixture()
    store.append_recommendation_snapshot(actor, snapshot)
    for operation in (
        "UPDATE portfolio.recommendation_snapshots SET cash=0 WHERE snapshot_id=%s",
        "DELETE FROM portfolio.recommendation_holdings WHERE snapshot_id=%s",
        "UPDATE portfolio.recommendation_exposures SET ratio=0 WHERE snapshot_id=%s",
    ):
        with pytest.raises(psycopg.Error):
            with psycopg.connect(url) as connection:
                connection.execute(operation, (snapshot.snapshot_id,))
    with pytest.raises(psycopg.Error, match="recommendation_snapshot_incomplete"):
        with psycopg.connect(url) as connection:
            connection.execute(
                "INSERT INTO portfolio.recommendation_exposures(owner_user_id,snapshot_id,kind,exposure_key,ratio) VALUES(%s,%s,'theme','forged-later',0)",
                (actor, snapshot.snapshot_id),
            )
    assert store.get_recommendation_snapshot(actor, snapshot.snapshot_id) == snapshot


def test_forced_rls_blocks_foreign_reads_and_writes_for_real_non_bypass_role():
    url, actor, store, snapshot = fixture()
    store.append_recommendation_snapshot(actor, snapshot)
    role_name = "risk_rls_" + uuid.uuid4().hex
    with pytest.raises(ValueError, match="rollback-role"):
        with psycopg.connect(url) as connection:
            connection.execute(
                f"CREATE ROLE {role_name} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            connection.execute(f"GRANT USAGE ON SCHEMA portfolio TO {role_name}")
            connection.execute(
                f"GRANT SELECT, INSERT ON portfolio.recommendation_snapshots,portfolio.recommendation_holdings,portfolio.recommendation_exposures TO {role_name}"
            )
            connection.execute(f"SET LOCAL ROLE {role_name}")
            connection.execute("SELECT set_config('app.user_id',%s,true)", (actor,))
            connection.execute("SELECT set_config('app.role','owner',true)")
            for table in (
                "recommendation_snapshots",
                "recommendation_holdings",
                "recommendation_exposures",
            ):
                assert (
                    connection.execute(
                        f"SELECT count(*) FROM portfolio.{table} WHERE snapshot_id=%s",
                        (snapshot.snapshot_id,),
                    ).fetchone()[0]
                    > 0
                )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with connection.transaction():
                    connection.execute(
                        "INSERT INTO portfolio.recommendation_exposures(owner_user_id,snapshot_id,kind,exposure_key,ratio) VALUES(%s,%s,'theme','forged',0)",
                        (str(uuid.uuid4()), snapshot.snapshot_id),
                    )
            connection.execute(
                "SELECT set_config('app.user_id',%s,true)", (str(uuid.uuid4()),)
            )
            for table in (
                "recommendation_snapshots",
                "recommendation_holdings",
                "recommendation_exposures",
            ):
                assert (
                    connection.execute(
                        f"SELECT count(*) FROM portfolio.{table}"
                    ).fetchone()[0]
                    == 0
                )
            connection.execute("SELECT set_config('app.user_id',%s,true)", (actor,))
            connection.execute("SELECT set_config('app.role','admin',true)")
            assert (
                connection.execute(
                    "SELECT count(*) FROM portfolio.recommendation_snapshots"
                ).fetchone()[0]
                == 0
            )
            raise ValueError("rollback-role")


def test_bound_store_requires_active_matching_transaction_context():
    url, actor, store, snapshot = fixture()
    engine = create_database_engine(lambda: url)
    with engine.connect() as connection:
        with pytest.raises(ValueError, match="active_transaction_required"):
            store.for_transaction(connection).append_recommendation_snapshot(
                actor, snapshot
            )
    with database_connection(engine) as connection:
        connection.exec_driver_sql(
            "SELECT set_config('app.user_id','another-owner',true)"
        )
        connection.exec_driver_sql("SELECT set_config('app.role','owner',true)")
        with pytest.raises(PermissionError, match="transaction_context_mismatch"):
            store.for_transaction(connection).append_recommendation_snapshot(
                actor, snapshot
            )
    engine.dispose()
