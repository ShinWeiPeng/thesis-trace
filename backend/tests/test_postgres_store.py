from __future__ import annotations

import os
import runpy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql as psycopg_sql
import pytest

from thesis_trace.modules.research.evidence_intake.contracts import (
    CollectionRequest,
    EvidenceAccepted,
    EvidenceAuditFact,
    EvidenceRecord,
    EvidenceStatus,
)
from thesis_trace.platform.postgres import (
    MIGRATIONS,
    PostgresEvidenceStore,
    PostgresUnavailable,
    bootstrap_schema,
    verify_schema_compatibility,
)
from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot, ValuationSourceFact
from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    DimensionFacts,
    EvidenceStage,
    SourceConfirmation,
    StageActorContext,
)
from thesis_trace.modules.research.evidence_stage.service import EvidenceStageService
from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyClass,
    AssessmentStatus,
    EvaluateAssessmentCommand,
    RequestAssessmentCommand,
    SourceCharacteristicSnapshot,
)
from thesis_trace.modules.research.anomaly_assessment.service import AnomalyAssessmentService


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="set THESIS_TRACE_TEST_DATABASE_URL for PostgreSQL integration evidence",
)


@pytest.fixture()
def store():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    result = PostgresEvidenceStore(lambda: url)
    result.delete_all_for_test()
    result.create_company("2330", "台積電")
    return result


def test_admission_atomically_persists_record_audit_and_durable_job(store: PostgresEvidenceStore) -> None:
    evidence_id = str(uuid.uuid4())
    accepted = EvidenceAccepted(evidence_id, 1)
    store.commit_admission(
        idempotency_key="request-1",
        record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/a", EvidenceStatus.RECEIVED),
        audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
        job=CollectionRequest(evidence_id, 1, "https://example.com/a", f"collect:{evidence_id}:1"),
        accepted=accepted,
    )

    assert store.find_accepted("request-1") == accepted
    assert store.get_record(evidence_id).status is EvidenceStatus.RECEIVED
    assert store.count_audit_events(evidence_id) == 1
    assert store.count_collection_jobs(evidence_id) == 1


def test_owner_stage_confirmation_is_atomic_versioned_snapshot_bound_and_idempotent(
    store: PostgresEvidenceStore,
) -> None:
    evidence_id = str(uuid.uuid4())
    store.commit_admission(
        idempotency_key="stage-intake",
        record=EvidenceRecord(
            evidence_id, 1, "2330", 1, "https://example.com/stage", EvidenceStatus.RECEIVED
        ),
        audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
        job=CollectionRequest(evidence_id, 1, "https://example.com/stage", f"collect:{evidence_id}"),
        accepted=EvidenceAccepted(evidence_id, 1),
    )
    lease = store.claim_collection_job()
    assert lease is not None
    assert store.complete_collection(
        evidence_id,
        CollectedSourceSnapshot(
            canonical_url="https://example.com/stage",
            publisher="MOPS",
            content_hash="stage-content",
            retrieved_at="2026-08-20T10:00:00+00:00",
            normalization_policy_version="url-normalization-v1",
        ),
        lease.lease_token,
    )
    snapshot_id = store.get_source_snapshot_id(evidence_id)
    assert snapshot_id is not None
    service = EvidenceStageService(store=store, clock=lambda: "2026-08-20T12:00:00+00:00")
    command = ConfirmDimensionFactsCommand(
        actor=StageActorContext("owner-1", may_confirm=True, may_read=True),
        evidence_id=evidence_id,
        source_snapshot_id=snapshot_id,
        expected_version=0,
        facts=DimensionFacts(
            SourceConfirmation.OFFICIAL,
            product_established=True,
            commercialization_established=True,
            identifiable_revenue=True,
            identifiable_profit_or_cash_flow=True,
            consecutive_financial_quarters=2,
        ),
        reason="verified against MOPS snapshot",
        idempotency_key="stage-confirmation-1",
    )

    first = service.confirm(command)
    replay = service.confirm(command)

    assert first == replay == store.get_stage(evidence_id)
    assert first.version == 1
    assert first.evaluation.stage is EvidenceStage.E6
    assert first.source_snapshot_id == snapshot_id
    assert store.count_audit_events(evidence_id) == 2
    with pytest.raises(ValueError, match="version_conflict"):
        service.confirm(
            ConfirmDimensionFactsCommand(
                actor=command.actor,
                evidence_id=evidence_id,
                source_snapshot_id=snapshot_id,
                expected_version=0,
                facts=command.facts,
                reason="a distinct stale command",
                idempotency_key="stage-confirmation-2",
            )
        )

    role_name = "thesis_trace_stage_rls_integration"
    with psycopg.connect(os.environ["THESIS_TRACE_TEST_DATABASE_URL"], autocommit=True) as connection:
        connection.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role_name}') "
            f"THEN CREATE ROLE {role_name} NOLOGIN NOBYPASSRLS; END IF; END $$"
        )
        connection.execute(f"GRANT USAGE ON SCHEMA research TO {role_name}")
        connection.execute(f"GRANT SELECT,INSERT ON research.evidence_stage_versions TO {role_name}")
        assert connection.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname=%s", (role_name,)
        ).fetchone()[0] is False
        connection.execute(f"SET ROLE {role_name}")
        with connection.transaction():
            assert connection.execute(
                "SELECT count(*) FROM research.evidence_stage_versions"
            ).fetchone()[0] == 0
        with connection.transaction():
            connection.execute("SELECT set_config('app.role','learner',true)")
            assert connection.execute(
                "SELECT count(*) FROM research.evidence_stage_versions"
            ).fetchone()[0] == 1
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """INSERT INTO research.evidence_stage_versions
                    SELECT evidence_id,2,source_snapshot_id,'learner',now(),'forbidden',
                    source_confirmation,product_established,commercialization_established,
                    identifiable_revenue,identifiable_profit_or_cash_flow,
                    consecutive_financial_quarters,stage,policy_version,gate_trace,'learner-forbidden'
                    FROM research.evidence_stage_versions WHERE version=1"""
                )
        with connection.transaction():
            connection.execute("SELECT set_config('app.role','admin',true)")
            assert connection.execute(
                "SELECT count(*) FROM research.evidence_stage_versions"
            ).fetchone()[0] == 0
        with connection.transaction():
            connection.execute("SELECT set_config('app.role','owner',true)")
            connection.execute(
                """INSERT INTO research.evidence_stage_versions
                SELECT evidence_id,2,source_snapshot_id,'owner-1',now(),'owner reconfirmed',
                source_confirmation,product_established,commercialization_established,
                identifiable_revenue,identifiable_profit_or_cash_flow,
                consecutive_financial_quarters,stage,policy_version,gate_trace,'owner-confirmed-2'
                FROM research.evidence_stage_versions WHERE version=1"""
            )
            assert connection.execute(
                "SELECT count(*) FROM research.evidence_stage_versions"
            ).fetchone()[0] == 2
        connection.execute("RESET ROLE")


def test_schema_migration_is_versioned_and_reapplying_is_idempotent(store: PostgresEvidenceStore) -> None:
    bootstrap_schema(lambda: os.environ["THESIS_TRACE_TEST_DATABASE_URL"])
    verify_schema_compatibility(lambda: os.environ["THESIS_TRACE_TEST_DATABASE_URL"])
    assert store.applied_migrations() == [
        (1, "wave0_company_evidence"),
        (2, "access_identity_session_confirmation"),
        (3, "access_rls"),
        (4, "recovery_session_policy_binding"),
        (5, "source_normalization_policy_version"),
        (6, "owner_confirmed_evidence_stage"),
        (7, "shadow_first_anomaly_assessment"),
        (8, "anomaly_review_action_inbox"),
        (9, "personal_thesis_lifecycle"),
        (10, "valuation_portfolio_trade"),
        (11, "thesis_valuation_publication"),
        (12, "portfolio_official_security"),
        (13, "research_valuation_source_facts"),
        (14, "valuation_forecast_target_date"),
    ]


def test_valuation_source_facts_enforce_rls_append_only_runtime_grants(
    store: PostgresEvidenceStore,
) -> None:
    evidence_id = str(uuid.uuid4())
    store.commit_admission(
        idempotency_key="valuation-fact-intake",
        record=EvidenceRecord(
            evidence_id,
            1,
            "2330",
            1,
            "https://example.com/facts",
            EvidenceStatus.RECEIVED,
        ),
        audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
        job=CollectionRequest(
            evidence_id, 1, "https://example.com/facts", "collect:valuation-facts"
        ),
        accepted=EvidenceAccepted(evidence_id, 1),
    )
    lease = store.claim_collection_job()
    assert lease is not None
    assert store.complete_collection(
        evidence_id,
        CollectedSourceSnapshot(
            "https://example.com/facts",
            "MOPS",
            "valuation-facts-hash",
            "2026-08-29T00:00:00+00:00",
            source_category="A",
        ),
        lease.lease_token,
    )
    record = store.get_record(evidence_id)
    snapshot_id = store.get_source_snapshot_id(evidence_id)
    assert record is not None and snapshot_id is not None
    store.save_valuation_facts(
        evidence_id,
        (
            ValuationSourceFact(
                "pe-history-1",
                evidence_id,
                record.version,
                snapshot_id,
                "2330",
                "pe",
                "history_multiple",
                date(2026, 8, 1),
                Decimal("20"),
                Decimal("1"),
            ),
        ),
    )

    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    apply_runtime_grants = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "infra/postgres/run-production-migrations.py"
        )
    )["apply_runtime_grants"]
    role_snapshot_sql = """SELECT rolname, rolcanlogin, rolsuper, rolcreatedb,
        rolcreaterole, rolinherit, rolbypassrls FROM pg_roles
        WHERE rolname IN ('thesis_trace_api', 'thesis_trace_collector',
                         'thesis_trace_ai_worker') ORDER BY rolname"""
    grants_snapshot_sql = """SELECT relacl FROM pg_class
        WHERE oid = 'research.valuation_source_facts'::regclass"""
    # Test-only roles and grants must not leak into the later production bootstrap.
    with (
        psycopg.connect(url) as connection,
        connection.transaction(force_rollback=True),
    ):
        roles_before = connection.execute(role_snapshot_sql).fetchall()
        grants_before = connection.execute(grants_snapshot_sql).fetchall()
        for role_name in (
            "thesis_trace_api",
            "thesis_trace_collector",
            "thesis_trace_ai_worker",
        ):
            connection.execute(
                f"""DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role_name}')
                THEN CREATE ROLE {role_name} NOLOGIN NOBYPASSRLS; END IF; END $$"""
            )
        apply_runtime_grants(connection)
        assert (
            connection.execute(
                """SELECT relrowsecurity AND relforcerowsecurity FROM pg_class
            WHERE oid='research.valuation_source_facts'::regclass"""
            ).fetchone()[0]
            is True
        )
        api_privileges = connection.execute(
            """SELECT has_table_privilege('thesis_trace_api','research.valuation_source_facts','SELECT'),
            has_table_privilege('thesis_trace_api','research.valuation_source_facts','INSERT'),
            has_table_privilege('thesis_trace_api','research.valuation_source_facts','UPDATE'),
            has_table_privilege('thesis_trace_api','research.valuation_source_facts','DELETE')"""
        ).fetchone()
        assert api_privileges == (True, False, False, False)
        collector_privileges = connection.execute(
            """SELECT has_table_privilege('thesis_trace_collector','research.valuation_source_facts','SELECT'),
            has_table_privilege('thesis_trace_collector','research.valuation_source_facts','INSERT'),
            has_table_privilege('thesis_trace_collector','research.valuation_source_facts','UPDATE'),
            has_table_privilege('thesis_trace_collector','research.valuation_source_facts','DELETE')"""
        ).fetchone()
        assert collector_privileges == (True, True, False, False)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction():
                connection.execute("SET LOCAL ROLE thesis_trace_api")
                connection.execute("SELECT set_config('app.role','owner',true)")
                assert (
                    connection.execute(
                        "SELECT count(*) FROM research.valuation_source_facts"
                    ).fetchone()[0]
                    == 1
                )
                connection.execute("DELETE FROM research.valuation_source_facts")
        with connection.transaction():
            connection.execute("SET LOCAL ROLE thesis_trace_collector")
            connection.execute("SELECT set_config('app.role','collector',true)")
            connection.execute(
                """INSERT INTO research.valuation_source_facts(
                evidence_id,fact_id,evidence_version,source_snapshot_id,company_id,method,fact_kind,
                observed_on,value,denominator,policy_version)
                VALUES(%s,'pe-history-2',%s,%s::uuid,'2330','pe','history_multiple',%s,21,1,'valuation-source-fact-v1')""",
                (evidence_id, record.version, snapshot_id, date(2026, 7, 1)),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction():
                connection.execute("SET LOCAL ROLE thesis_trace_collector")
                connection.execute("SELECT set_config('app.role','collector',true)")
                connection.execute(
                    "UPDATE research.valuation_source_facts SET value=22 WHERE evidence_id=%s",
                    (evidence_id,),
                )

    with psycopg.connect(url) as connection:
        assert connection.execute(role_snapshot_sql).fetchall() == roles_before
        assert connection.execute(grants_snapshot_sql).fetchall() == grants_before


def test_anomaly_request_job_and_result_are_atomic_version_bound_and_shadow_only(
    store: PostgresEvidenceStore,
) -> None:
    evidence_id = str(uuid.uuid4())
    store.commit_admission(
        idempotency_key="anomaly-intake",
        record=EvidenceRecord(
            evidence_id, 1, "2330", 1, "https://example.com/anomaly", EvidenceStatus.RECEIVED
        ),
        audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
        job=CollectionRequest(evidence_id, 1, "https://example.com/anomaly", f"collect:{evidence_id}"),
        accepted=EvidenceAccepted(evidence_id, 1),
    )
    collection_job = store.claim_collection_job()
    assert collection_job is not None
    assert store.complete_collection(
        evidence_id,
        CollectedSourceSnapshot(
            canonical_url="https://example.com/anomaly",
            publisher="Publisher 1",
            content_hash=f"anomaly-{evidence_id}",
            retrieved_at="2026-08-21T09:00:00+00:00",
            normalization_policy_version="url-normalization-v1",
            source_category="B",
            lineage="underlying-1",
        ),
        collection_job.lease_token,
    )
    second_evidence_id = str(uuid.uuid4())
    store.commit_admission(
        idempotency_key="anomaly-intake-2",
        record=EvidenceRecord(
            second_evidence_id, 1, "2330", 1, "https://example.com/anomaly-2",
            EvidenceStatus.RECEIVED,
        ),
        audit=EvidenceAuditFact("owner-1", "evidence.received", second_evidence_id, 1),
        job=CollectionRequest(
            second_evidence_id, 1, "https://example.com/anomaly-2",
            f"collect:{second_evidence_id}",
        ),
        accepted=EvidenceAccepted(second_evidence_id, 1),
    )
    second_job = store.claim_collection_job()
    assert second_job is not None
    assert store.complete_collection(
        second_evidence_id,
        CollectedSourceSnapshot(
            canonical_url="https://example.com/anomaly-2",
            publisher="Publisher 2",
            content_hash=f"anomaly-{second_evidence_id}",
            retrieved_at="2026-08-21T09:05:00+00:00",
            normalization_policy_version="url-normalization-v1",
            source_category="B",
            lineage="underlying-2",
        ),
        second_job.lease_token,
    )
    evidence = store.get_record(evidence_id)
    snapshot_id = store.get_source_snapshot_id(evidence_id)
    second_snapshot_id = store.get_source_snapshot_id(second_evidence_id)
    assert evidence is not None and snapshot_id is not None and second_snapshot_id is not None
    requested_sources = (
        SourceCharacteristicSnapshot(snapshot_id, "browser-value-is-not-authority"),
        SourceCharacteristicSnapshot(second_snapshot_id, "browser-value-is-not-authority"),
    )
    service = AnomalyAssessmentService(
        store=store, clock=lambda: "2026-08-21T10:00:00+00:00"
    )
    requested = service.request(
        RequestAssessmentCommand(
            "owner-1", True, evidence_id, evidence.version, requested_sources, "review", "anomaly-1"
        )
    )
    assert service.request(
        RequestAssessmentCommand(
            "owner-1", True, evidence_id, evidence.version, requested_sources, "review", "anomaly-1"
        )
    ) == requested
    assert service.request(
        RequestAssessmentCommand(
                "owner-1", True, evidence_id, evidence.version,
                (
                    SourceCharacteristicSnapshot(snapshot_id, "different-browser-value"),
                    SourceCharacteristicSnapshot(second_snapshot_id, "different-browser-value"),
                ),
            "review", "anomaly-1",
        )
    ) == requested
    assert requested.status is AssessmentStatus.PENDING
    assert store.count_anomaly_jobs(requested.assessment_id) == 1
    job = store.claim_anomaly_job()
    assert job is not None
    assert job.build_version == "test-build"
    assert job.provider_model_version == "test-provider-model"
    assert job.critic_model_version == "test-critic-model"
    stored_sources = service.load_sources(requested.assessment_id)
    assert tuple(source.publisher_identity for source in stored_sources) == (
        "Publisher 1", "Publisher 2",
    )
    assert all(source.editorial_responsibility for source in stored_sources)
    assert tuple(source.underlying_evidence_id for source in stored_sources) == (
        "underlying-1", "underlying-2",
    )
    result = service.evaluate(
        EvaluateAssessmentCommand(
            requested.assessment_id,
            job.lease_token or "",
            1,
            stored_sources,
            (snapshot_id, second_snapshot_id),
            True,
            True,
        )
    )
    assert result.status is AssessmentStatus.SUCCEEDED
    assert result.trace is not None
    assert result.trace.anomaly_class is AnomalyClass.WOULD_BE_HARD
    assert store.count_audit_events(requested.assessment_id) == 2
    contextual = service.get(assessment_id=requested.assessment_id, may_read=True)
    assert (contextual.actor_id, contextual.company_id, contextual.company_ticker, contextual.company_name) == (
        "owner-1", "2330", "2330", "台積電",
    )

    role_name = "thesis_trace_anomaly_rls_integration"
    with psycopg.connect(os.environ["THESIS_TRACE_TEST_DATABASE_URL"], autocommit=True) as connection:
        connection.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role_name}') "
            f"THEN CREATE ROLE {role_name} NOLOGIN NOBYPASSRLS; END IF; END $$"
        )
        connection.execute(f"GRANT USAGE ON SCHEMA research TO {role_name}")
        connection.execute(
            f"GRANT SELECT,UPDATE ON research.anomaly_assessments TO {role_name}"
        )
        connection.execute(f"SET ROLE {role_name}")
        with connection.transaction():
            assert connection.execute(
                "SELECT count(*) FROM research.anomaly_assessments"
            ).fetchone()[0] == 0
        with connection.transaction():
            connection.execute("SELECT set_config('app.role','learner',true)")
            assert connection.execute(
                "SELECT count(*) FROM research.anomaly_assessments"
            ).fetchone()[0] == 1
            assert connection.execute(
                "UPDATE research.anomaly_assessments SET failure_code='forbidden'"
            ).rowcount == 0
        with connection.transaction():
            connection.execute("SELECT set_config('app.role','admin',true)")
            assert connection.execute(
                "SELECT count(*) FROM research.anomaly_assessments"
            ).fetchone()[0] == 0
        with connection.transaction():
            connection.execute("SELECT set_config('app.role','ai_worker',true)")
            assert connection.execute(
                "UPDATE research.anomaly_assessments SET failure_code=failure_code"
            ).rowcount == 1
        connection.execute("RESET ROLE")


def test_migration_0005_preserves_pre_versioned_keys_as_legacy() -> None:
    configured_url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    database_name = f"thesis_trace_migration_{uuid.uuid4().hex}"
    parsed_url = urlsplit(configured_url)
    admin_url = urlunsplit(parsed_url._replace(path="/postgres"))
    legacy_url = urlunsplit(parsed_url._replace(path=f"/{database_name}"))
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(psycopg_sql.SQL("CREATE DATABASE {}").format(psycopg_sql.Identifier(database_name)))
    try:
        snapshot_id = uuid.uuid4()
        legacy_canonical_url = "https://PUBLIC.EXAMPLE:443#historical-fragment"
        with psycopg.connect(legacy_url) as connection:
            connection.execute("CREATE SCHEMA research")
            connection.execute(
                """CREATE TABLE research.schema_migrations (
                version integer PRIMARY KEY, name text NOT NULL, checksum text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now())"""
            )
            for version, name, migration_sql in MIGRATIONS[:4]:
                connection.execute(migration_sql)
                connection.execute(
                    "INSERT INTO research.schema_migrations(version,name,checksum) VALUES (%s,%s,%s)",
                    (version, name, sha256(migration_sql.encode("utf-8")).hexdigest()),
                )
            connection.execute(
                "INSERT INTO research.companies(company_id,ticker,name,version) VALUES ('2330','2330','台積電',1)"
            )
            connection.execute(
                """INSERT INTO research.evidence_intakes(
                evidence_id,version,company_id,company_version,submitted_url,status)
                VALUES ('legacy-evidence',1,'2330',1,%s,'succeeded')""",
                (legacy_canonical_url,),
            )
            connection.execute(
                """INSERT INTO research.source_snapshots(
                snapshot_id,canonical_url,publisher,content_hash,retrieved_at,source_category)
                VALUES (%s,%s,'Legacy Publisher','legacy-content','2026-08-18T12:00:00Z','C')""",
                (snapshot_id, legacy_canonical_url),
            )
            connection.execute(
                """INSERT INTO research.source_observations(evidence_id,snapshot_id,submitted_url)
                VALUES ('legacy-evidence',%s,%s)""",
                (snapshot_id, legacy_canonical_url),
            )

        bootstrap_schema(lambda: legacy_url)
        verify_schema_compatibility(lambda: legacy_url)

        with psycopg.connect(legacy_url) as connection:
            migrated = connection.execute(
                """SELECT c.normalization_policy_version,c.canonical_url,
                s.normalization_policy_version,o.source_id
                FROM research.source_observations o
                JOIN research.canonical_sources c USING(source_id)
                JOIN research.source_snapshots s USING(snapshot_id)
                WHERE o.evidence_id='legacy-evidence'"""
            ).fetchone()
        assert migrated == (
            "url-normalization-legacy",
            legacy_canonical_url,
            "url-normalization-legacy",
            snapshot_id,
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                psycopg_sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg_sql.Identifier(database_name))
            )


def test_evidence_admission_requires_a_persisted_company_version(store: PostgresEvidenceStore) -> None:
    assert store.get_company("2330").version == 1
    assert store.get_company("missing") is None


def test_job_claim_is_leased_and_stale_token_cannot_ack(store: PostgresEvidenceStore) -> None:
    evidence_id = str(uuid.uuid4())
    accepted = EvidenceAccepted(evidence_id, 1)
    store.commit_admission(
        idempotency_key="request-2",
        record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/b", EvidenceStatus.RECEIVED),
        audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
        job=CollectionRequest(evidence_id, 1, "https://example.com/b", f"collect:{evidence_id}:1"),
        accepted=accepted,
    )

    lease = store.claim_collection_job()
    assert lease is not None
    assert store.claim_collection_job() is None
    assert store.fail_collection(lease, "stale-token", "timeout", retryable=True) is False
    assert store.fail_collection(lease, lease.lease_token, "timeout", retryable=True) is True
    assert store.get_record(evidence_id).status is EvidenceStatus.RETRYING


def test_injected_admission_failure_rolls_back_record_audit_and_job(store: PostgresEvidenceStore) -> None:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    failing = PostgresEvidenceStore(lambda: url, admission_fault_hook=lambda: (_ for _ in ()).throw(RuntimeError("fault")))
    evidence_id = str(uuid.uuid4())
    with pytest.raises(PostgresUnavailable, match="postgres_unavailable"):
        failing.commit_admission(
            idempotency_key="rollback", record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/r", EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, "https://example.com/r", "collect:rollback"), accepted=EvidenceAccepted(evidence_id, 1),
        )
    assert store.get_record(evidence_id) is None
    assert store.count_audit_events(evidence_id) == 0
    assert store.count_collection_jobs(evidence_id) == 0


def test_expired_lease_is_reclaimed_and_retry_exhaustion_dead_letters(store: PostgresEvidenceStore) -> None:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    reclaiming = PostgresEvidenceStore(lambda: url, lease_seconds=0, max_attempts=2)
    evidence_id = str(uuid.uuid4())
    reclaiming.commit_admission(
        idempotency_key="reclaim", record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/x", EvidenceStatus.RECEIVED),
        audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
        job=CollectionRequest(evidence_id, 1, "https://example.com/x", "collect:reclaim"), accepted=EvidenceAccepted(evidence_id, 1),
    )
    first = reclaiming.claim_collection_job()
    second = reclaiming.claim_collection_job()
    assert second.job_id == first.job_id and second.lease_token != first.lease_token
    assert reclaiming.fail_collection(second, second.lease_token, "timeout", retryable=True)
    assert reclaiming.get_record(evidence_id).status is EvidenceStatus.DEAD_LETTER


def test_full_provenance_and_url_or_content_dedup(store: PostgresEvidenceStore) -> None:
    for index, submitted_url in enumerate(("https://example.com/shared", "https://mirror.example/shared"), start=1):
        evidence_id = f"dedup-{index}"
        store.commit_admission(
            idempotency_key=evidence_id, record=EvidenceRecord(evidence_id, 1, "2330", 1, submitted_url, EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, submitted_url, f"collect:{evidence_id}"), accepted=EvidenceAccepted(evidence_id, 1),
        )
        lease = store.claim_collection_job()
        snapshot = CollectedSourceSnapshot(
            canonical_url="https://example.com/canonical", publisher="MOPS", content_hash="same-hash",
            retrieved_at="2026-08-18T12:00:00Z", published_at="2026-08-18T10:00:00Z",
            observed_at="2026-08-18T11:00:00Z", excerpt="material fact", source_category="A", lineage=submitted_url,
            normalization_policy_version="url-normalization-v1",
        )
        assert store.complete_collection(evidence_id, snapshot, lease.lease_token)
    assert store.count_source_snapshots() == 1
    assert store.count_source_observations() == 2
    provenance = store.get_source_provenance("dedup-1")
    assert provenance[0:4] == (
        "https://example.com/canonical", "url-normalization-v1", "MOPS", "same-hash",
    )
    assert provenance[7:] == ("material fact", "A", "https://example.com/shared")


def test_url_dedup_key_keeps_normalization_versions_separate(store: PostgresEvidenceStore) -> None:
    canonical_url = "https://example.com/disclosure"
    for index, policy_version in enumerate(("url-normalization-v1", "url-normalization-v2"), start=1):
        evidence_id = f"normalization-{index}"
        store.commit_admission(
            idempotency_key=evidence_id,
            record=EvidenceRecord(evidence_id, 1, "2330", 1, canonical_url, EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, canonical_url, f"collect:{evidence_id}"),
            accepted=EvidenceAccepted(evidence_id, 1),
        )
        lease = store.claim_collection_job()
        snapshot = CollectedSourceSnapshot(
            canonical_url=canonical_url,
            publisher="MOPS",
            content_hash="same-content-across-policies",
            retrieved_at="2026-08-18T12:00:00Z",
            normalization_policy_version=policy_version,
        )
        assert store.complete_collection(evidence_id, snapshot, lease.lease_token)

    assert store.count_source_snapshots() == 1
    assert store.count_canonical_sources() == 2
    assert store.get_source_provenance("normalization-1")[1] == "url-normalization-v1"
    assert store.get_source_provenance("normalization-2")[1] == "url-normalization-v2"


def test_same_url_with_changed_content_records_each_immutable_snapshot(store: PostgresEvidenceStore) -> None:
    canonical_url = "https://example.com/changing-disclosure"
    for index, content_hash in enumerate(("first-content", "corrected-content"), start=1):
        evidence_id = f"changed-content-{index}"
        store.commit_admission(
            idempotency_key=evidence_id,
            record=EvidenceRecord(evidence_id, 1, "2330", 1, canonical_url, EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, canonical_url, f"collect:{evidence_id}"),
            accepted=EvidenceAccepted(evidence_id, 1),
        )
        lease = store.claim_collection_job()
        assert store.complete_collection(
            evidence_id,
            CollectedSourceSnapshot(
                canonical_url=canonical_url,
                publisher="MOPS",
                content_hash=content_hash,
                retrieved_at=f"2026-08-18T12:00:0{index}Z",
                normalization_policy_version="url-normalization-v1",
            ),
            lease.lease_token,
        )

    assert store.count_canonical_sources() == 1
    assert store.count_source_snapshots() == 2
    assert store.get_source_provenance("changed-content-1")[3] == "first-content"
    assert store.get_source_provenance("changed-content-2")[3] == "corrected-content"


def test_concurrent_idempotent_admission_has_one_audit_and_job(store: PostgresEvidenceStore) -> None:
    def submit(index: int) -> None:
        evidence_id = f"concurrent-{index}"
        store.commit_admission(
            idempotency_key="one-request", record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/c", EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, "https://example.com/c", f"collect:{evidence_id}"), accepted=EvidenceAccepted(evidence_id, 1),
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(submit, (1, 2)))
    accepted = store.find_accepted("one-request")
    assert sum(store.count_audit_events(f"concurrent-{index}") for index in (1, 2)) == 1
    assert sum(store.count_collection_jobs(f"concurrent-{index}") for index in (1, 2)) == 1


def test_concurrent_distinct_urls_with_same_content_share_one_snapshot(store: PostgresEvidenceStore) -> None:
    leases = []
    for index in (1, 2):
        evidence_id = f"content-{index}"
        store.commit_admission(
            idempotency_key=evidence_id, record=EvidenceRecord(evidence_id, 1, "2330", 1, f"https://mirror{index}.example/a", EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, f"https://mirror{index}.example/a", f"collect:{evidence_id}"), accepted=EvidenceAccepted(evidence_id, 1),
        )
        leases.append(store.claim_collection_job())
    snapshots = [
        CollectedSourceSnapshot(
            canonical_url=f"https://canonical{index}.example/a",
            publisher="MOPS",
            content_hash="concurrent-hash",
            retrieved_at="2026-08-18T12:00:00Z",
            source_category="A",
        )
        for index in (1, 2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda pair: store.complete_collection(pair[0].evidence_id, pair[1], pair[0].lease_token),
            zip(leases, snapshots),
        ))
    assert results == [True, True]
    assert store.count_source_snapshots() == 1
    assert store.count_canonical_sources() == 2
    assert store.count_source_observations() == 2


def test_concurrent_same_url_with_distinct_content_keeps_both_snapshots(store: PostgresEvidenceStore) -> None:
    leases = []
    for index in (1, 2):
        evidence_id = f"changed-concurrently-{index}"
        submitted_url = "https://canonical.example/changing"
        store.commit_admission(
            idempotency_key=evidence_id,
            record=EvidenceRecord(evidence_id, 1, "2330", 1, submitted_url, EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, submitted_url, f"collect:{evidence_id}"),
            accepted=EvidenceAccepted(evidence_id, 1),
        )
        leases.append(store.claim_collection_job())
    snapshots = [
        CollectedSourceSnapshot(
            canonical_url="https://canonical.example/changing",
            publisher="MOPS",
            content_hash=f"concurrent-content-{index}",
            retrieved_at=f"2026-08-18T12:00:0{index}Z",
            source_category="A",
        )
        for index in (1, 2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda pair: store.complete_collection(pair[0].evidence_id, pair[1], pair[0].lease_token),
            zip(leases, snapshots),
        ))

    assert results == [True, True]
    assert store.count_canonical_sources() == 1
    assert store.count_source_snapshots() == 2
    assert {
        store.get_source_provenance(f"changed-concurrently-{index}")[3]
        for index in (1, 2)
    } == {"concurrent-content-1", "concurrent-content-2"}
