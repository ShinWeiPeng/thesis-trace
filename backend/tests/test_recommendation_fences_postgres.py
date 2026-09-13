from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
import os
import time
import uuid

import pytest
import psycopg

from thesis_trace.adapters.postgres_portfolio.adapter import PostgresPortfolioStore
from thesis_trace.adapters.postgres_thesis.adapter import PostgresThesisStore
from thesis_trace.modules.access.contracts import Role, SecurityContext
from thesis_trace.modules.portfolio.contracts import (
    PortfolioActorContext,
    SaveInvestableCashCommand,
    SaveCostProfileCommand,
)
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.modules.research.evidence_intake.contracts import EvidenceStatus
from thesis_trace.platform.database import create_database_engine, database_connection
from thesis_trace.platform.postgres import (
    PostgresEvidenceStore,
    bootstrap_schema,
    database_security_context,
)
from test_portfolio_domain import NOW, MemoryPortfolioStore
from test_thesis_domain import MemoryThesisStore, create
from thesis_trace.modules.thesis.service import ThesisService


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL required",
)


def verify_fence(make_operations):
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    owner = str(uuid.uuid4())
    application_name = "wave7-fence-" + owner
    writer_url = psycopg.conninfo.make_conninfo(url, application_name=application_name)
    context = SecurityContext(owner, Role.OWNER, "fence-test")
    lock, write = make_operations(url, writer_url, context)
    engine = create_database_engine(lambda: url)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with database_connection(engine) as connection:
                connection.exec_driver_sql(
                    "SELECT set_config('app.user_id',%s,true)", (owner,)
                )
                connection.exec_driver_sql("SELECT set_config('app.role','owner',true)")
                lock(connection)
                future = executor.submit(write)
                deadline = time.monotonic() + 3
                blocked = False
                with psycopg.connect(url, autocommit=True) as observer:
                    while time.monotonic() < deadline:
                        blocked = observer.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name=%s AND wait_event='advisory')",
                            (application_name,),
                        ).fetchone()[0]
                        if blocked or future.done():
                            break
                        time.sleep(0.01)
                assert blocked, (
                    "real competing writer must wait on the same advisory fence"
                )
                assert not future.done()
            future.result(timeout=3)
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["cash", "official"])
def test_portfolio_cash_and_official_inputs_share_the_owner_fence(operation):
    def operations(url, writer_url, context):
        reader = PostgresPortfolioStore(
            lambda: url, security_context_provider=lambda: context
        )
        writer = PostgresPortfolioStore(
            lambda: writer_url, security_context_provider=lambda: context
        )
        if operation == "cash":
            PortfolioService(writer).save_cost_profile(
                SaveCostProfileCommand(
                    PortfolioActorContext(context.user_id, True),
                    0,
                    Decimal(0),
                    Decimal(20),
                    Decimal(0),
                    Decimal(20),
                    Decimal("0.003"),
                    NOW,
                    "Fence costs",
                    str(uuid.uuid4()),
                ),
                now=NOW,
            )

        def lock(connection):
            reader.for_transaction(connection).lock_recommendation_inputs(
                context.user_id
            )

        def write():
            if operation == "official":
                writer.save_official_security(
                    context.user_id, MemoryPortfolioStore().official["2330"]
                )
            else:
                PortfolioService(writer).save_investable_cash(
                    SaveInvestableCashCommand(
                        PortfolioActorContext(context.user_id, True),
                        1,
                        Decimal(1000),
                        NOW,
                        "Test fenced cash",
                        str(uuid.uuid4()),
                    ),
                    now=NOW,
                )

        return lock, write

    verify_fence(operations)


def test_thesis_commit_uses_the_exact_owner_and_thesis_fence():
    def operations(url, writer_url, context):
        reader = PostgresThesisStore(
            lambda: url, security_context_provider=lambda: context
        )
        writer = PostgresThesisStore(
            lambda: writer_url, security_context_provider=lambda: context
        )
        record = replace(
            create(ThesisService(MemoryThesisStore())),
            owner_user_id=context.user_id,
            thesis_id=str(uuid.uuid4()),
        )
        return (
            lambda connection: reader.for_transaction(
                connection
            ).lock_recommendation_inputs(context.user_id, record.thesis_id),
            lambda: writer.commit(
                actor_id=context.user_id,
                idempotency_key=str(uuid.uuid4()),
                command_digest="fixture",
                expected_version=0,
                record=record,
                action="create_thesis",
                reason="Fence test",
            ),
        )

    verify_fence(operations)


def test_research_transition_uses_the_exact_evidence_fence():
    def operations(url, writer_url, context):
        reader = PostgresEvidenceStore(lambda: url)
        writer = PostgresEvidenceStore(lambda: writer_url)
        evidence_id = str(uuid.uuid4())

        def write():
            with database_security_context(context):
                writer.transition(evidence_id, EvidenceStatus.FAILED)

        return lambda connection: reader.for_transaction(
            connection
        ).lock_recommendation_inputs((evidence_id,)), write

    verify_fence(operations)
