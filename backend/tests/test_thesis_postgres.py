from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
import uuid

import pytest

from thesis_trace.adapters.postgres_thesis.adapter import PostgresThesisStore
from thesis_trace.adapters.postgres_portfolio.adapter import PostgresPortfolioStore
from thesis_trace.adapters.postgres_access.adapter import PostgresAccessAdapter
from thesis_trace.bootstrap.application import PostgresConfirmedThesisTransition, PostgresConfirmedValuationPublication
from thesis_trace.modules.access.contracts import Role, SecurityContext
from thesis_trace.modules.access.contracts import AuthenticatedActor
from thesis_trace.modules.access.confirmation_challenge.service import ConfirmationService
from thesis_trace.modules.thesis.contracts import (
    CreateThesisCommand,
    ThesisActorContext,
    ThesisResearchReference,
    ThesisStatus,
    TransitionThesisCommand,
    PublishValuationCommand,
    SaveValuationDraftCommand,
    ValuationMethod,
    ValuationSample,
)
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.modules.portfolio.contracts import PortfolioActorContext, SaveCostProfileCommand
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot, ValuationSourceFact
from thesis_trace.modules.research.evidence_intake.contracts import (
    CollectionRequest, EvidenceAccepted, EvidenceAuditFact, EvidenceRecord, EvidenceStatus,
)
from thesis_trace.platform.postgres import (
    PostgresEvidenceStore,
    PostgresUnavailable,
    bootstrap_schema,
    database_security_context,
)


psycopg = pytest.importorskip("psycopg")


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="set THESIS_TRACE_TEST_DATABASE_URL for PostgreSQL integration evidence",
)

NOW = datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc)
OWNER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_ID = "00000000-0000-0000-0000-000000000099"


def _context(user_id: str = OWNER_ID) -> SecurityContext:
    return SecurityContext(user_id, Role.OWNER, "thesis-postgres-test")


@pytest.fixture(autouse=True)
def research_security_context():
    """Exercise Research RLS with the same verified owner context as the API request."""
    with database_security_context(_context()):
        yield


@pytest.fixture()
def thesis() -> tuple[ThesisService, PostgresThesisStore]:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    store = PostgresThesisStore(lambda: url, security_context_provider=_context)
    store.delete_all_for_test()
    return ThesisService(store, id_factory=lambda: "thesis-1"), store


def _create(service: ThesisService):
    actor = ThesisActorContext(OWNER_ID, True)
    return service.create(
        CreateThesisCommand(
            actor,
            ThesisResearchReference("company", "company-1", 1, "company-1"),
            "AI server demand",
            "Demand and product mix support durable cash flow.",
            ("Server revenue declines for two quarters",),
            (),
            "Create thesis",
            "create-1",
        ),
        now=NOW,
    )


def test_postgres_commit_replay_version_history_and_audit_are_consistent(
    thesis: tuple[ThesisService, PostgresThesisStore],
) -> None:
    service, store = thesis
    draft = _create(service)
    active = service.transition(
        TransitionThesisCommand(
            ThesisActorContext(OWNER_ID, True),
            draft.thesis_id,
            draft.version,
            ThesisStatus.ACTIVE,
            "Activate thesis",
            "activate-1",
        ),
        now=NOW,
    )

    replay = _create(service)
    assert replay == active
    assert service.get(ThesisActorContext(OWNER_ID, True), draft.thesis_id) == active
    assert service.list_for_company(ThesisActorContext(OWNER_ID, True), "company-1") == [active]
    assert store.count_versions(draft.thesis_id) == 2
    assert store.count_audit_events(draft.thesis_id) == 2

    with pytest.raises(ValueError, match="version_conflict"):
        service.transition(
            TransitionThesisCommand(
                ThesisActorContext(OWNER_ID, True),
                draft.thesis_id,
                draft.version,
                ThesisStatus.ACTIVE,
                "Stale transition",
                "activate-stale",
            ),
            now=NOW,
        )


def test_thesis_rls_hides_other_owners(
    thesis: tuple[ThesisService, PostgresThesisStore],
) -> None:
    service, _store = thesis
    item = _create(service)
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    role_name = "thesis_trace_thesis_rls_integration"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role_name}') "
            f"THEN CREATE ROLE {role_name} NOLOGIN NOBYPASSRLS; END IF; END $$"
        )
        connection.execute(f"GRANT USAGE ON SCHEMA thesis TO {role_name}")
        connection.execute(f"GRANT SELECT ON thesis.theses TO {role_name}")
        connection.execute(f"SET ROLE {role_name}")
        with connection.transaction():
            connection.execute("SELECT set_config('app.user_id',%s,true)", (OWNER_ID,))
            assert connection.execute("SELECT thesis_id FROM thesis.theses").fetchone()[0] == item.thesis_id
        with connection.transaction():
            connection.execute("SELECT set_config('app.user_id',%s,true)", (OTHER_ID,))
            assert connection.execute("SELECT count(*) FROM thesis.theses").fetchone()[0] == 0
        connection.execute("RESET ROLE")


def test_confirmed_transition_consumes_challenge_and_mutates_thesis_atomically(
    thesis: tuple[ThesisService, PostgresThesisStore],
) -> None:
    service, store = thesis
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    with psycopg.connect(url) as connection:
        connection.execute(
            """INSERT INTO access.users(user_id,role,status)
            VALUES(%s,'owner','active') ON CONFLICT(user_id) DO UPDATE SET role='owner',status='active'""",
            (OWNER_ID,),
        )
    draft = _create(service)
    active = service.transition(
        TransitionThesisCommand(
            ThesisActorContext(OWNER_ID, True), draft.thesis_id, 1,
            ThesisStatus.ACTIVE, "Activate", "activate-atomic",
        ), now=NOW,
    )
    access = PostgresAccessAdapter(lambda: url)
    confirmations = ConfirmationService(access, clock=lambda: NOW, token_factory=lambda: f"atomic-token-{uuid.uuid4()}")
    payload = {"thesis_id": active.thesis_id, "target_status": "invalidated"}
    token, _challenge = confirmations.preview(
        OWNER_ID, "transition_personal_thesis", active.thesis_id, active.version,
        payload, {"consequences": ["Invalidates the Thesis"]},
    )
    coordinator = PostgresConfirmedThesisTransition(access, store, service)
    changed = coordinator.execute(
        actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), thesis_id=active.thesis_id,
        expected_version=active.version, target=ThesisStatus.INVALIDATED,
        reason="Condition met", idempotency_key="invalidate-atomic",
        challenge_token=token, now=NOW,
    )
    replay = coordinator.execute(
        actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), thesis_id=active.thesis_id,
        expected_version=active.version, target=ThesisStatus.INVALIDATED,
        reason="Condition met", idempotency_key="invalidate-atomic",
        challenge_token=token, now=NOW,
    )

    assert changed.status is ThesisStatus.INVALIDATED
    assert replay == changed
    assert store.count_versions(active.thesis_id) == 3
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT consumed_at IS NOT NULL FROM access.confirmation_challenges WHERE token_digest=%s",
            (__import__("hashlib").sha256(token.encode()).hexdigest(),),
        ).fetchone()[0] is True


def test_confirmed_transition_rolls_back_both_schemas_on_fault(
    thesis: tuple[ThesisService, PostgresThesisStore],
) -> None:
    service, store = thesis
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    with psycopg.connect(url) as connection:
        connection.execute(
            """INSERT INTO access.users(user_id,role,status)
            VALUES(%s,'owner','active') ON CONFLICT(user_id) DO UPDATE SET role='owner',status='active'""",
            (OWNER_ID,),
        )
    active = service.transition(
        TransitionThesisCommand(
            ThesisActorContext(OWNER_ID, True), _create(service).thesis_id, 1,
            ThesisStatus.ACTIVE, "Activate", "activate-rollback",
        ), now=NOW,
    )
    access = PostgresAccessAdapter(
        lambda: url,
        confirmed_mutation_fault_hook=lambda: (_ for _ in ()).throw(RuntimeError("fault")),
    )
    confirmations = ConfirmationService(access, clock=lambda: NOW, token_factory=lambda: f"rollback-token-{uuid.uuid4()}")
    payload = {"thesis_id": active.thesis_id, "target_status": "invalidated"}
    token, _challenge = confirmations.preview(
        OWNER_ID, "transition_personal_thesis", active.thesis_id, active.version,
        payload, {"consequences": ["Invalidates the Thesis"]},
    )
    with pytest.raises(PostgresUnavailable, match="postgres_unavailable"):
        PostgresConfirmedThesisTransition(access, store, service).execute(
            actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), thesis_id=active.thesis_id,
            expected_version=active.version, target=ThesisStatus.INVALIDATED,
            reason="Condition met", idempotency_key="invalidate-rollback",
            challenge_token=token, now=NOW,
        )

    assert service.get(ThesisActorContext(OWNER_ID, True), active.thesis_id) == active
    assert store.count_versions(active.thesis_id) == 2
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT consumed_at IS NULL FROM access.confirmation_challenges WHERE token_digest=%s",
            (__import__("hashlib").sha256(token.encode()).hexdigest(),),
        ).fetchone()[0] is True


def test_confirmed_valuation_publication_is_atomic_and_persisted(
    thesis: tuple[ThesisService, PostgresThesisStore],
) -> None:
    service, store = thesis
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    research = PostgresEvidenceStore(lambda: url)
    research.delete_all_for_test()
    research.create_company("company-1", "Company One")
    research.commit_admission(
        idempotency_key="valuation-source-admission",
        record=EvidenceRecord("history-source", 1, "company-1", 1, "https://example.com/value", EvidenceStatus.RECEIVED),
        audit=EvidenceAuditFact(OWNER_ID, "evidence.received", "history-source", 1),
        job=CollectionRequest("history-source", 1, "https://example.com/value", "collect-history-source"),
        accepted=EvidenceAccepted("history-source", 1),
    )
    collector = PostgresEvidenceStore(lambda: url, runtime_role="collector")
    with database_security_context(None):
        lease = collector.claim_collection_job()
        assert lease is not None
        assert collector.complete_collection("history-source", CollectedSourceSnapshot(
            "https://example.com/value", "MOPS", "valuation-source-hash", NOW.isoformat(),
            published_at=NOW.isoformat(), excerpt="valuation facts", source_category="A",
        ), lease.lease_token)
    evidence = research.get_record("history-source")
    snapshot_id = research.get_source_snapshot_id("history-source")
    assert evidence is not None and snapshot_id is not None
    facts = tuple(
        ValuationSourceFact(
            f"pe-history-{index + 1}", "history-source", evidence.version, snapshot_id,
            "company-1", "pe", "history_multiple",
            date(2023 + index // 12, index % 12 + 1, 1), Decimal(index + 1), Decimal("1"),
        ) for index in range(36)
    ) + (ValuationSourceFact(
        "pe-forecast", "history-source", evidence.version, snapshot_id, "company-1", "pe",
        "forecast", NOW.date(), Decimal("12"), None, NOW, NOW + timedelta(days=30), None,
        target_date=date(2027, 8, 29),
    ),)
    with database_security_context(None):
        collector.save_valuation_facts("history-source", facts)
    portfolio_store = PostgresPortfolioStore(lambda: url, security_context_provider=_context)
    portfolio_store.delete_all_for_test()
    portfolio = PortfolioService(portfolio_store)
    portfolio.save_cost_profile(SaveCostProfileCommand(
        PortfolioActorContext(OWNER_ID, True), 0, Decimal("0"), Decimal("20"), Decimal("0"),
        Decimal("20"), Decimal("0.003"), NOW, "Costs", "valuation-cost-profile",
    ), now=NOW)
    with psycopg.connect(url) as connection:
        connection.execute(
            """INSERT INTO access.users(user_id,role,status)
            VALUES(%s,'owner','active') ON CONFLICT(user_id) DO UPDATE SET role='owner',status='active'""",
            (OWNER_ID,),
        )
    created = _create(service)
    source = ThesisResearchReference("evidence", "history-source", evidence.version, "company-1")
    samples = tuple(
        ValuationSample(
            f"pe-history-{value}", "company-1", date(2023 + (value - 1) // 12, (value - 1) % 12 + 1, 1),
            Decimal(value), Decimal("1"), ThesisResearchReference(
                "evidence", "history-source", evidence.version, "company-1", f"pe-history-{value}",
            ),
        ) for value in range(1, 37)
    )
    drafted = service.save_valuation_draft(SaveValuationDraftCommand(
        actor=ThesisActorContext(OWNER_ID, True), thesis_id=created.thesis_id,
        expected_thesis_version=created.version, expected_draft_version=0,
        method=ValuationMethod.PE, benchmark_source="company_history", benchmark_variant="p75",
        peer_company_ids=(), samples=(), basis_date=date(2026, 8, 29), horizon_months=12,
        forecast=Decimal("12"), quantity=Decimal("10"), buy_price=Decimal("100"),
        cash_dividend=Decimal("50"), buy_rate=Decimal("0"), minimum_buy_fee=Decimal("20"),
        sell_rate=Decimal("0"), minimum_sell_fee=Decimal("20"), tax_rate=Decimal("0.003"),
        cost_profile_version=1, reason="Save valuation", idempotency_key="valuation-postgres",
        company_history_samples=samples, source_selection_reason="Use company history",
        forecast_source=ThesisResearchReference(
            "evidence", "history-source", evidence.version, "company-1", "pe-forecast",
        ), forecast_confirmed_at=NOW, next_report_time=NOW + timedelta(days=30), method_confirmed=True,
    ), now=NOW)
    assert service.get(ThesisActorContext(OWNER_ID, True), created.thesis_id).valuation_draft is not None

    access = PostgresAccessAdapter(lambda: url)
    confirmations = ConfirmationService(access, clock=lambda: NOW, token_factory=lambda: f"valuation-token-{uuid.uuid4()}")
    payload = {
        "thesis_id": created.thesis_id, "draft_version": 1, "cost_profile_version": 1,
        "research_sources": [{
            "record_id": "history-source", "version": evidence.version,
            "company_id": "company-1", "source_snapshot_id": snapshot_id,
            "fact_id": fact.fact_id, "fact_policy_version": fact.policy_version,
        } for fact in facts],
    }
    token, _challenge = confirmations.preview(
        OWNER_ID, "publish_thesis_valuation", created.thesis_id, drafted.version,
        payload, {"consequences": ["publish"]},
    )
    published = PostgresConfirmedValuationPublication(
        access, store, service, research, portfolio_store,
    ).execute(
        actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), thesis_id=created.thesis_id,
        expected_thesis_version=drafted.version, expected_draft_version=1,
        reason="Publish valuation", idempotency_key="valuation-publish-postgres",
        challenge_token=token, binding_payload=payload, now=NOW,
    )
    assert published.version == 3
    assert published.valuation_snapshots[0].draft.result.target_price == Decimal("327.00")
    assert store.count_versions(created.thesis_id) == 3
    with psycopg.connect(url) as connection:
        connection.execute("SELECT set_config('app.user_id',%s,true)", (OWNER_ID,))
        connection.execute("SELECT set_config('app.role','owner',true)")
        current = connection.execute(
            """SELECT valuation_draft_version,valuation_draft,valuation_snapshots
            FROM thesis.theses WHERE thesis_id=%s""", (created.thesis_id,),
        ).fetchone()
        assert current == (1, None, None)
        snapshot_metadata = connection.execute(
            """SELECT method,benchmark_source,benchmark_variant,target_date,
            cost_profile_version,policy_version,reason
            FROM thesis.valuation_snapshots WHERE thesis_id=%s""", (created.thesis_id,),
        ).fetchone()
        assert snapshot_metadata == (
            "pe", "company_history", "p75", date(2027, 8, 29), 1,
            "valuation-publication-v1", "Publish valuation",
        )
        audit = connection.execute(
                """SELECT before_version,after_version,correlation_id,causation_id,
                policy_version,build_version FROM thesis.audit_events
                WHERE thesis_id=%s AND action='valuation_published'""", (created.thesis_id,),
        ).fetchone()
        assert audit[:3] == (2, 3, "valuation-publish-postgres")
        assert len(audit[3]) == 64
        assert audit[4:] == ("thesis-lifecycle-v1", "test-build")

    def save_next_draft(expected_thesis_version: int, expected_draft_version: int, cost_version: int, key: str):
        return service.save_valuation_draft(SaveValuationDraftCommand(
            actor=ThesisActorContext(OWNER_ID, True), thesis_id=created.thesis_id,
            expected_thesis_version=expected_thesis_version,
            expected_draft_version=expected_draft_version,
            method=ValuationMethod.PE, benchmark_source="company_history", benchmark_variant="p75",
            peer_company_ids=(), samples=(), basis_date=date(2026, 8, 29), horizon_months=12,
            forecast=Decimal("12"), quantity=Decimal("10"), buy_price=Decimal("100"),
            cash_dividend=Decimal("50"), buy_rate=Decimal("0"), minimum_buy_fee=Decimal("20"),
            sell_rate=Decimal("0"), minimum_sell_fee=Decimal("20"), tax_rate=Decimal("0.003"),
            cost_profile_version=cost_version, reason="Save valuation", idempotency_key=key,
            company_history_samples=samples, source_selection_reason="Use company history",
            forecast_source=ThesisResearchReference(
                "evidence", "history-source", evidence.version, "company-1", "pe-forecast",
            ), forecast_confirmed_at=NOW, next_report_time=NOW + timedelta(days=30), method_confirmed=True,
        ), now=NOW)

    def publication_payload(draft_version: int, cost_version: int) -> dict[str, object]:
        return {
            "thesis_id": created.thesis_id, "draft_version": draft_version,
            "cost_profile_version": cost_version,
            "research_sources": [{
                "record_id": "history-source", "version": evidence.version,
                "company_id": "company-1", "source_snapshot_id": snapshot_id,
                "fact_id": fact.fact_id, "fact_policy_version": fact.policy_version,
            } for fact in facts],
        }

    stale_cost_draft = save_next_draft(published.version, 1, 1, "valuation-stale-cost-draft")
    stale_cost_payload = publication_payload(2, 1)
    stale_cost_token, _ = confirmations.preview(
        OWNER_ID, "publish_thesis_valuation", created.thesis_id, stale_cost_draft.version,
        stale_cost_payload, {"consequences": ["publish"]},
    )
    portfolio.save_cost_profile(SaveCostProfileCommand(
        PortfolioActorContext(OWNER_ID, True), 1, Decimal("0.001"), Decimal("20"),
        Decimal("0.001"), Decimal("20"), Decimal("0.003"), NOW,
        "Updated costs", "valuation-cost-profile-2",
    ), now=NOW)
    coordinator = PostgresConfirmedValuationPublication(access, store, service, research, portfolio_store)
    with pytest.raises(ValueError, match="cost_profile_version_conflict"):
        coordinator.execute(
            actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), thesis_id=created.thesis_id,
            expected_thesis_version=stale_cost_draft.version, expected_draft_version=2,
            reason="Publish stale costs", idempotency_key="publish-stale-cost",
            challenge_token=stale_cost_token, binding_payload=stale_cost_payload, now=NOW,
        )
    assert service.get(ThesisActorContext(OWNER_ID, True), created.thesis_id).version == stale_cost_draft.version

    stale_source_draft = save_next_draft(stale_cost_draft.version, 2, 2, "valuation-stale-source-draft")
    stale_source_payload = publication_payload(3, 2)
    stale_source_token, _ = confirmations.preview(
        OWNER_ID, "publish_thesis_valuation", created.thesis_id, stale_source_draft.version,
        stale_source_payload, {"consequences": ["publish"]},
    )
    research.transition("history-source", EvidenceStatus.FAILED)
    with pytest.raises(ValueError, match="valuation_source_invalid"):
        coordinator.execute(
            actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), thesis_id=created.thesis_id,
            expected_thesis_version=stale_source_draft.version, expected_draft_version=3,
            reason="Publish stale source", idempotency_key="publish-stale-source",
            challenge_token=stale_source_token, binding_payload=stale_source_payload, now=NOW,
        )
    assert service.get(ThesisActorContext(OWNER_ID, True), created.thesis_id).version == stale_source_draft.version
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            """SELECT consumed_at FROM access.confirmation_challenges
            WHERE token_digest IN (%s,%s) ORDER BY issued_at""",
            (
                __import__("hashlib").sha256(stale_cost_token.encode()).hexdigest(),
                __import__("hashlib").sha256(stale_source_token.encode()).hexdigest(),
            ),
        ).fetchall()
    assert rows == [(None,), (None,)]
