from dataclasses import replace
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import uuid
import runpy
from pathlib import Path

import pytest
import psycopg

from thesis_trace.adapters.postgres_access.adapter import PostgresAccessAdapter
from thesis_trace.adapters.postgres_atomic.adapter import (
    PostgresRecommendationTransaction,
)
from thesis_trace.adapters.postgres_portfolio.adapter import PostgresPortfolioStore
from thesis_trace.adapters.postgres_recommendation.adapter import (
    PostgresRecommendationStore,
)
from thesis_trace.adapters.postgres_thesis.adapter import PostgresThesisStore
from thesis_trace.adapters.postgres_workflow.adapter import PostgresWorkflowStore
from thesis_trace.application.contracts import (
    RecommendationFlow,
    RecommendationPublicationCommand,
)
from thesis_trace.modules.access.contracts import (
    AuthenticatedActor,
    Role,
    SecurityContext,
)
from thesis_trace.modules.portfolio.contracts import (
    PortfolioActorContext,
    SaveCostProfileCommand,
    SaveInvestableCashCommand,
)
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.modules.research import ResearchRecommendationFacade
from thesis_trace.modules.research.evidence_collection.contracts import (
    ValuationSourceFact,
)
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.platform.postgres import (
    PostgresEvidenceStore,
    bootstrap_schema,
    database_security_context,
)
from thesis_trace.platform.database import create_database_engine, database_connection
from thesis_trace.platform.database import PostgresUnavailable
from test_recommendation_bindings import setup
from test_recommendation_admission import versions
from test_recommendation_publication import evidence
from test_portfolio_domain import NOW, MemoryPortfolioStore


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL required",
)


@pytest.fixture
def context():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    actor_id = str(uuid.uuid4())
    security = SecurityContext(actor_id, Role.OWNER, "atomic-recommendation-test")
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO access.users(user_id,role,status) VALUES(%s,'owner','active')",
            (actor_id,),
        )
    try:
        yield url, security
    finally:
        with psycopg.connect(url) as connection:
            connection.execute(
                "UPDATE recommendation.jobs SET state='failed',error_code='resource_unavailable',lease_token=NULL,lease_expires_at=NULL WHERE owner_user_id=%s AND state IN ('pending','processing','retrying')",
                (actor_id,),
            )
            connection.execute(
                "UPDATE access.users SET status='disabled' WHERE user_id=%s",
                (actor_id,),
            )


def prepare(context, *, cash=Decimal(20000)):
    url, security = context
    owner = security.user_id
    thesis_id, evidence_id, snapshot_id = (str(uuid.uuid4()) for _ in range(3))
    research = PostgresEvidenceStore(lambda: url)
    portfolio = PostgresPortfolioStore(
        lambda: url, security_context_provider=lambda: security
    )
    theses = PostgresThesisStore(
        lambda: url, security_context_provider=lambda: security
    )
    recommendations = PostgresRecommendationStore(
        lambda: url, security_context_provider=lambda: security
    )
    workflow = PostgresWorkflowStore(
        lambda: url, security_context_provider=lambda: security
    )
    portfolio_service = PortfolioService(portfolio)
    actor = PortfolioActorContext(owner, True)
    portfolio_service.save_cost_profile(
        SaveCostProfileCommand(
            actor,
            0,
            Decimal(0),
            Decimal(20),
            Decimal(0),
            Decimal(20),
            Decimal("0.003"),
            NOW,
            "Fixture costs",
            str(uuid.uuid4()),
        ),
        now=NOW,
    )
    portfolio_service.save_investable_cash(
        SaveInvestableCashCommand(
            actor, 1, cash, NOW, "Fixture cash", str(uuid.uuid4())
        ),
        now=NOW,
    )
    portfolio.save_official_security(owner, MemoryPortfolioStore().official["2330"])
    _, memory_theses, _, _ = setup()
    template = memory_theses.records["thesis-1"]
    with database_security_context(security):
        company = research.create_company("fixture-" + thesis_id, "Publication fixture")
        # The parent company ticker is the security key; use a matching official snapshot.
        portfolio.save_official_security(
            owner,
            replace(
                MemoryPortfolioStore().official["2330"], security_id=company.ticker
            ),
        )
        with psycopg.connect(url) as connection:
            source_url = "https://example.test/" + evidence_id
            connection.execute(
                "INSERT INTO research.evidence_intakes(evidence_id,version,company_id,company_version,submitted_url,status) VALUES(%s,1,%s,1,%s,'succeeded')",
                (evidence_id, company.company_id, source_url),
            )
            connection.execute(
                "INSERT INTO research.source_snapshots(snapshot_id,canonical_url,normalization_policy_version,publisher,content_hash,retrieved_at,published_at,excerpt,source_category,lineage) VALUES(%s,%s,'url-normalization-v1','Official publisher',%s,%s,%s,'Exact saved excerpt','A','underlying-report')",
                (snapshot_id, source_url, evidence_id, NOW, NOW),
            )
            connection.execute(
                "INSERT INTO research.canonical_sources(source_id,normalization_policy_version,canonical_url) VALUES(%s,'url-normalization-v1',%s)",
                (snapshot_id, source_url),
            )
            connection.execute(
                "INSERT INTO research.source_observations(evidence_id,snapshot_id,submitted_url,source_id) VALUES(%s,%s,%s,%s)",
                (evidence_id, snapshot_id, source_url, snapshot_id),
            )
        valuation = template.valuation_snapshots[0]

        def ref(value):
            return replace(
                value, record_id=evidence_id, version=1, company_id=company.company_id
            )

        draft = replace(
            valuation.draft,
            forecast_source=ref(valuation.draft.forecast_source),
            company_history=replace(
                valuation.draft.company_history,
                valid_samples=tuple(
                    replace(sample, source=ref(sample.source))
                    for sample in valuation.draft.company_history.valid_samples
                ),
            ),
        )
        valuation = replace(
            valuation, valuation_id=thesis_id + ":valuation:1", draft=draft
        )
        record = replace(
            template,
            owner_user_id=owner,
            company_id=company.company_id,
            thesis_id=thesis_id,
            evidence_refs=(),
            valuation_draft=draft,
            valuation_snapshots=(valuation,),
        )
        theses.commit(
            actor_id=owner,
            idempotency_key=str(uuid.uuid4()),
            command_digest="fixture",
            expected_version=0,
            record=record,
            action="create_thesis",
            reason="Real publication fixture",
        )
        facts = [
            ValuationSourceFact(
                sample.source.fact_id,
                evidence_id,
                1,
                snapshot_id,
                company.company_id,
                "pe",
                "history_multiple",
                sample.observed_on,
                sample.multiple,
                Decimal(1),
            )
            for sample in draft.company_history.valid_samples
        ]
        facts.append(
            ValuationSourceFact(
                draft.forecast_source.fact_id,
                evidence_id,
                1,
                snapshot_id,
                company.company_id,
                "pe",
                "forecast",
                NOW.date(),
                draft.forecast,
                confirmed_at=NOW,
                target_date=draft.validity.target_date,
            )
        )
        research.save_valuation_facts(evidence_id, tuple(facts))
        flow = RecommendationFlow(
            ThesisService(theses),
            portfolio_service,
            research,
            minimum_return=Decimal("0.05"),
            minimum_return_policy_version="local-acceptance-minimum-return-v1",
            source_queries=ResearchRecommendationFacade(research),
            versions=versions(),
        )
        frozen = flow.prepare_inputs(
            actor=AuthenticatedActor(owner, Role.OWNER, 1),
            thesis_id=thesis_id,
            expected_thesis_version=record.version,
            valuation_id=valuation.valuation_id,
            expected_valuation_version=1,
            expected_portfolio_version=2,
            benchmark_source="company_history",
            source_selection_reason="Confirmed company-history benchmark",
            portfolio_snapshot_id=str(uuid.uuid4()),
            now=NOW,
        )
    input_id = str(uuid.uuid4())
    recommendations.admit(
        inputs=frozen,
        input_id=input_id,
        job_id=str(uuid.uuid4()),
        versions=versions(),
        idempotency_key=str(uuid.uuid4()),
        command_digest="1" * 64,
    )
    job = recommendations.claim_job()
    candidate, critic = evidence()
    candidate = candidate.replace("snapshot-1", snapshot_id)
    critic_value = json.loads(critic)
    critic_value["candidate_digest"] = hashlib.sha256(candidate.encode()).hexdigest()
    critic_value["checks"][0]["supporting_snapshot_ids"] = [snapshot_id]
    critic = json.dumps(critic_value)
    command = RecommendationPublicationCommand(
        job.job_id,
        job.input_id,
        job.input_digest,
        job.actor_id,
        job.thesis_id,
        job.cycle,
        job.lease_token,
        job.lease_expires_at,
        job.attempt,
        job.versions,
        candidate,
        critic,
        NOW,
    )
    transaction = PostgresRecommendationTransaction(
        access=PostgresAccessAdapter(lambda: url),
        theses=theses,
        portfolio=portfolio,
        research=research,
        recommendations=recommendations,
        workflow=workflow,
        flow=flow,
        clock=lambda: NOW,
    )
    return transaction, command, recommendations, portfolio, workflow, frozen


def test_real_publication_commits_all_owner_participants_without_creating_a_trade(
    context,
):
    transaction, command, store, portfolio, workflow, frozen = prepare(context)
    before = portfolio.get(command.actor_id)
    view = transaction.publish(command)
    assert view.record_id == command.input_id and view.allowed_actions == (
        "accept",
        "reject",
        "defer",
    )
    record = store.get_record(command.actor_id, view.record_id, 1)
    assert record.direction == "buy" and record.minimum_return == Decimal("0.05")
    assert (
        portfolio.get_recommendation_snapshot(
            command.actor_id, frozen.portfolio_snapshot_id
        )
        is not None
    )
    assert portfolio.get(command.actor_id) == before
    assert store.job_status(command.actor_id, command.input_id) == ("succeeded", None)
    assert (
        workflow.get_by_source(command.actor_id, "recommendation", view.record_id, 1)
        is not None
    )


def test_stale_lease_and_revoked_owner_never_publish(context):
    transaction, command, store, portfolio, _, frozen = prepare(context)
    with pytest.raises(ValueError, match="lease_unavailable"):
        transaction.publish(replace(command, lease_token="stolen"))
    assert store.get_record(command.actor_id, command.input_id, 1) is None
    url, _ = context
    with psycopg.connect(url) as connection:
        connection.execute(
            "UPDATE access.users SET status='disabled' WHERE user_id=%s",
            (command.actor_id,),
        )
    with pytest.raises(PermissionError, match="resource_unavailable"):
        transaction.publish(command)
    assert (
        portfolio.get_recommendation_snapshot(
            command.actor_id, frozen.portfolio_snapshot_id
        )
        is None
    )
    store.fail_job(
        RecommendationFlow._publication_job(command),
        error_code="resource_unavailable",
        transient=False,
    )


def test_changed_cash_rejects_before_writing_a_recommendation(context):
    transaction, command, store, portfolio, _, frozen = prepare(context)
    PortfolioService(portfolio).save_investable_cash(
        SaveInvestableCashCommand(
            PortfolioActorContext(command.actor_id, True),
            2,
            Decimal(10000),
            NOW,
            "Changed after analysis",
            str(uuid.uuid4()),
        ),
        now=NOW,
    )
    with pytest.raises(
        ValueError, match="portfolio_version_conflict|superseded_inputs"
    ):
        transaction.publish(command)
    assert store.get_record(command.actor_id, command.input_id, 1) is None
    assert (
        portfolio.get_recommendation_snapshot(
            command.actor_id, frozen.portfolio_snapshot_id
        )
        is None
    )
    store.fail_job(
        RecommendationFlow._publication_job(command),
        error_code="superseded_inputs",
        transient=False,
    )


def test_database_failure_at_last_participant_rolls_back_risk_record_workflow_and_audits(
    context,
):
    transaction, command, store, portfolio, workflow, frozen = prepare(context)
    url, _ = context

    class FailingAccess(PostgresAccessAdapter):
        @contextmanager
        def recommendation_transaction(self, actor_id):
            with super().recommendation_transaction(actor_id) as values:
                connection = values[0]
                connection.exec_driver_sql(
                    """CREATE FUNCTION pg_temp.reject_recommendation_finish() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.state='succeeded' THEN RAISE EXCEPTION 'injected-final-participant'; END IF; RETURN NEW; END $$"""
                )
                connection.exec_driver_sql(
                    "CREATE TRIGGER wave7_atomic_test_failure BEFORE UPDATE ON recommendation.jobs FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_recommendation_finish()"
                )
                yield values

    transaction._access = FailingAccess(lambda: url)
    with pytest.raises(PostgresUnavailable, match="postgres_unavailable"):
        transaction.publish(command)
    assert store.get_record(command.actor_id, command.input_id, 1) is None
    assert (
        portfolio.get_recommendation_snapshot(
            command.actor_id, frozen.portfolio_snapshot_id
        )
        is None
    )
    assert (
        workflow.get_by_source(command.actor_id, "recommendation", command.input_id, 1)
        is None
    )
    assert store.job_status(command.actor_id, command.input_id) == ("processing", None)
    with psycopg.connect(url) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM recommendation.audit_events WHERE owner_user_id=%s",
                (command.actor_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM workflow.creation_receipts WHERE actor_user_id=%s",
                (command.actor_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='wave7_atomic_test_failure'"
            ).fetchone()[0]
            == 0
        )
    transaction._access = PostgresAccessAdapter(lambda: url)
    assert transaction.publish(command).record_id == command.input_id


def test_access_owner_fence_needs_no_account_select_or_update_grant(context):
    url, security = context
    role_name = "wave7_owner_lock_" + uuid.uuid4().hex
    with psycopg.connect(url) as connection:
        # Role, grants and observations are rolled back together, including on assertion failure.
        with pytest.raises(ValueError, match="rollback-owner-role"):
            with connection.transaction():
                connection.execute(
                    psycopg.sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS"
                    ).format(psycopg.sql.Identifier(role_name))
                )
                connection.execute(
                    psycopg.sql.SQL("GRANT USAGE ON SCHEMA access TO {}").format(
                        psycopg.sql.Identifier(role_name)
                    )
                )
                connection.execute(
                    psycopg.sql.SQL(
                        "GRANT EXECUTE ON FUNCTION access.lock_recommendation_owner(text) TO {}"
                    ).format(psycopg.sql.Identifier(role_name))
                )
                connection.execute(
                    psycopg.sql.SQL("SET LOCAL ROLE {}").format(
                        psycopg.sql.Identifier(role_name)
                    )
                )
                connection.execute(
                    "SELECT set_config('app.user_id',%s,true)", (security.user_id,)
                )
                connection.execute("SELECT set_config('app.role','owner',true)")
                assert connection.execute(
                    "SELECT has_table_privilege(current_user,'access.users','SELECT'),has_table_privilege(current_user,'access.users','UPDATE')"
                ).fetchone() == (False, False)
                assert connection.execute(
                    "SELECT user_id,role FROM access.lock_recommendation_owner(%s)",
                    (security.user_id,),
                ).fetchone() == (security.user_id, "owner")
                assert (
                    connection.execute(
                        "SELECT user_id FROM access.lock_recommendation_owner(%s)",
                        (str(uuid.uuid4()),),
                    ).fetchone()
                    is None
                )
                raise ValueError("rollback-owner-role")


def test_validity_is_rechecked_after_writes_before_finishing_the_lease(context):
    transaction, command, store, portfolio, workflow, frozen = prepare(context)
    expiry = next(
        bound.valid_until for bound in frozen.bindings if bound.valid_until is not None
    )
    times = iter((NOW, expiry))
    transaction._clock = lambda: next(times)
    with pytest.raises(ValueError, match="superseded_inputs"):
        transaction.publish(command)
    assert store.get_record(command.actor_id, command.input_id, 1) is None
    assert (
        portfolio.get_recommendation_snapshot(
            command.actor_id, frozen.portfolio_snapshot_id
        )
        is None
    )
    assert (
        workflow.get_by_source(command.actor_id, "recommendation", command.input_id, 1)
        is None
    )


def test_actual_runtime_grants_keep_worker_out_of_accounts_trades_cash_and_sources(
    context,
):
    url, security = context
    grant = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "infra/postgres/run-production-migrations.py"
        )
    )["apply_runtime_grants"]
    with psycopg.connect(url) as connection:
        with pytest.raises(ValueError, match="rollback-runtime-grants"):
            with connection.transaction():
                for role in (
                    "thesis_trace_api",
                    "thesis_trace_collector",
                    "thesis_trace_ai_worker",
                ):
                    if not connection.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)",
                        (role,),
                    ).fetchone()[0]:
                        connection.execute(
                            psycopg.sql.SQL(
                                "CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS"
                            ).format(psycopg.sql.Identifier(role))
                        )
                grant(connection)
                connection.execute("SET LOCAL ROLE thesis_trace_ai_worker")
                assert connection.execute(
                    "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).fetchone() == (False, False)
                for table, permission in (
                    ("access.users", "UPDATE"),
                    ("access.users", "SELECT"),
                    ("portfolio.current_state", "UPDATE"),
                    ("portfolio.holdings", "UPDATE"),
                    ("portfolio.trades", "INSERT"),
                    ("research.valuation_source_facts", "INSERT"),
                    ("recommendation.queue_capacity", "SELECT"),
                    ("recommendation.queue_capacity", "UPDATE"),
                    ("recommendation.expiry_candidates", "SELECT"),
                    ("recommendation.expiry_cursor", "UPDATE"),
                ):
                    assert (
                        connection.execute(
                            "SELECT has_table_privilege(current_user,%s,%s)",
                            (table, permission),
                        ).fetchone()[0]
                        is False
                    )
                for table, permission in (
                    ("recommendation.jobs", "UPDATE"),
                    ("recommendation.records", "INSERT"),
                    ("portfolio.recommendation_snapshots", "INSERT"),
                    ("workflow.action_items", "UPDATE"),
                    ("research.valuation_source_facts", "SELECT"),
                    ("thesis.theses", "SELECT"),
                ):
                    assert (
                        connection.execute(
                            "SELECT has_table_privilege(current_user,%s,%s)",
                            (table, permission),
                        ).fetchone()[0]
                        is True
                    )
                connection.execute(
                    "SELECT set_config('app.user_id',%s,true)", (security.user_id,)
                )
                connection.execute("SELECT set_config('app.role','owner',true)")
                assert (
                    connection.execute(
                        "SELECT user_id FROM access.lock_recommendation_owner(%s)",
                        (security.user_id,),
                    ).fetchone()[0]
                    == security.user_id
                )
                connection.execute("SET LOCAL ROLE thesis_trace_api")
                assert (
                    connection.execute(
                        "SELECT has_function_privilege(current_user,'recommendation.next_expiry_candidate()','EXECUTE')"
                    ).fetchone()[0]
                    is False
                )
                assert connection.execute(
                    "SELECT has_table_privilege(current_user,'recommendation.jobs','INSERT'),has_table_privilege(current_user,'recommendation.jobs','UPDATE')"
                ).fetchone() == (True, False)
                assert connection.execute(
                    "SELECT has_table_privilege(current_user,'recommendation.queue_capacity','SELECT'),has_table_privilege(current_user,'recommendation.queue_capacity','UPDATE')"
                ).fetchone() == (False, False)
                raise ValueError("rollback-runtime-grants")


def test_all_publication_sql_runs_under_actual_worker_role_and_production_grants(
    context,
):
    transaction, command, store, portfolio, workflow, frozen = prepare(context)
    url, _ = context
    grant = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "infra/postgres/run-production-migrations.py"
        )
    )["apply_runtime_grants"]
    engine = create_database_engine(lambda: url)
    try:
        with pytest.raises(ValueError, match="rollback-worker-publication"):
            with database_connection(engine) as connection:
                for role in (
                    "thesis_trace_api",
                    "thesis_trace_collector",
                    "thesis_trace_ai_worker",
                ):
                    if not connection.exec_driver_sql(
                        "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)",
                        (role,),
                    ).scalar_one():
                        connection.exec_driver_sql(
                            f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS"
                        )
                grant(connection.connection.driver_connection)
                connection.exec_driver_sql("SET LOCAL ROLE thesis_trace_ai_worker")

                class BoundAccess(PostgresAccessAdapter):
                    @contextmanager
                    def recommendation_transaction(self, actor_id):
                        actor, provider = self._locked_recommendation_owner(
                            connection, actor_id
                        )
                        yield connection, actor, provider

                transaction._access = BoundAccess(lambda: url)
                assert connection.exec_driver_sql(
                    "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).one() == (False, False)
                assert (
                    connection.exec_driver_sql(
                        "SELECT has_function_privilege(current_user,'recommendation.next_expiry_candidate()','EXECUTE')"
                    ).scalar_one()
                    is True
                )
                view = transaction.publish(command)
                assert view.record_id == command.input_id
                assert (
                    connection.exec_driver_sql(
                        "SELECT state FROM recommendation.jobs WHERE job_id=%s",
                        (command.job_id,),
                    ).scalar_one()
                    == "succeeded"
                )
                assert (
                    connection.exec_driver_sql(
                        "SELECT count(*) FROM workflow.action_items WHERE assignee_user_id=%s AND source_domain='recommendation' AND source_record_id=%s",
                        (command.actor_id, command.input_id),
                    ).scalar_one()
                    == 1
                )
                assert connection.exec_driver_sql(
                    "SELECT has_database_privilege(current_user,current_database(),'TEMP'),has_database_privilege(current_user,current_database(),'CREATE')"
                ).one() == (False, False)
                connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
                raise ValueError("rollback-worker-publication")
        assert store.get_record(command.actor_id, command.input_id, 1) is None
        assert (
            portfolio.get_recommendation_snapshot(
                command.actor_id, frozen.portfolio_snapshot_id
            )
            is None
        )
        assert (
            workflow.get_by_source(
                command.actor_id, "recommendation", command.input_id, 1
            )
            is None
        )
    finally:
        engine.dispose()
