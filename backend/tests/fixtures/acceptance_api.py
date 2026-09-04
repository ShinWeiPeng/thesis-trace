from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
import uuid
import psycopg

from thesis_trace.api import EvidenceApi, OwnerSessionResponse, create_fastapi_app
from thesis_trace.adapters.postgres_access.adapter import PostgresAccessAdapter
from thesis_trace.adapters.postgres_thesis.adapter import PostgresThesisStore
from thesis_trace.adapters.postgres_portfolio.adapter import PostgresPortfolioStore
from thesis_trace.application.contracts import PortfolioFlow, ThesisLifecycleFlow, ValuationFlow
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.application.flows.anomaly_assessment import AnomalyAssessmentFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role, SecurityContext
from thesis_trace.modules.access.confirmation_challenge.service import ConfirmationService
from thesis_trace.modules.research import ResearchAnomalyFacade
from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot, ValuationSourceFact
from thesis_trace.modules.research.evidence_intake.contracts import (
    CollectionRequest,
    EvidenceAccepted,
    EvidenceAuditFact,
    EvidenceRecord,
    EvidenceStatus,
)
from thesis_trace.modules.research.anomaly_assessment.service import AnomalyAssessmentService
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.modules.portfolio.contracts import OfficialSecuritySnapshot
from thesis_trace.bootstrap.application import (
    PostgresConfirmedPortfolioTrade,
    PostgresConfirmedThesisTransition,
    PostgresConfirmedValuationPublication,
)
from thesis_trace.platform.postgres import PostgresEvidenceStore, bootstrap_schema


database_url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
provider = lambda: database_url
bootstrap_schema(provider)
store = PostgresEvidenceStore(provider)
store.delete_all_for_test()
owner_id = "00000000-0000-0000-0000-000000000001"
with psycopg.connect(database_url) as connection:
    connection.execute(
        """INSERT INTO access.users(user_id,role,status)
        VALUES(%s,'owner','active') ON CONFLICT(user_id) DO UPDATE SET role='owner',status='active'""",
        (owner_id,),
    )


def seed_valuation_source(ticker: str, name: str, evidence_id: str) -> None:
    store.create_company(ticker, name)
    url = f"https://example.com/acceptance/valuation/{ticker}"
    store.commit_admission(
        idempotency_key=f"acceptance-valuation:{ticker}",
        record=EvidenceRecord(evidence_id, 1, ticker, 1, url, EvidenceStatus.RECEIVED),
        audit=EvidenceAuditFact(owner_id, "evidence.received", evidence_id, 1),
        job=CollectionRequest(evidence_id, 1, url, f"collect:{evidence_id}"),
        accepted=EvidenceAccepted(evidence_id, 1),
    )
    lease = store.claim_collection_job()
    assert lease is not None and lease.evidence_id == evidence_id
    assert store.complete_collection(
        evidence_id,
        CollectedSourceSnapshot(
            canonical_url=url, publisher="MOPS acceptance fixture",
            content_hash=f"acceptance-valuation-{ticker}",
            retrieved_at="2026-08-28T00:00:00+00:00",
            published_at="2026-08-28T00:00:00+00:00",
            excerpt=f"Source-bound valuation facts for {ticker}", source_category="A",
        ),
        lease.lease_token,
    )
    snapshot_id = store.get_source_snapshot_id(evidence_id)
    record = store.get_record(evidence_id)
    assert snapshot_id is not None and record is not None
    facts: list[ValuationSourceFact] = []
    for method in ("pe", "pb"):
        facts.extend(
            ValuationSourceFact(
                f"{method}-history-{index + 1}", evidence_id, record.version, snapshot_id,
                ticker, method, "history_multiple",
                date(2023 + index // 12, index % 12 + 1, 1), Decimal(index + 10), Decimal("1"),
            )
            for index in range(36)
        )
        facts.append(ValuationSourceFact(
            f"{method}-peer", evidence_id, record.version, snapshot_id, ticker, method,
            "peer_multiple", date(2026, 8, 28), Decimal(int(ticker) % 10 + 20), Decimal("1"),
        ))
        facts.append(ValuationSourceFact(
            f"{method}-forecast", evidence_id, record.version, snapshot_id, ticker, method,
            "forecast", date(2026, 8, 28), Decimal("12"), None,
            datetime(2026, 8, 28, tzinfo=timezone.utc),
            datetime(2026, 10, 1, tzinfo=timezone.utc), None,
            target_date=date(2027, 8, 29),
        ))
    store.save_valuation_facts(evidence_id, tuple(facts))


for ticker, name, evidence_id in (
    ("2330", "台積電驗收資料", "10000000-0000-0000-0000-000000000001"),
    ("2301", "光寶科驗收資料", "10000000-0000-0000-0000-000000000002"),
    ("2302", "麗正驗收資料", "10000000-0000-0000-0000-000000000003"),
    ("2303", "聯電驗收資料", "10000000-0000-0000-0000-000000000004"),
    ("2304", "國聲驗收資料", "10000000-0000-0000-0000-000000000005"),
    ("2305", "全友驗收資料", "10000000-0000-0000-0000-000000000006"),
):
    seed_valuation_source(ticker, name, evidence_id)
thesis_store = PostgresThesisStore(
    provider,
    security_context_provider=lambda: SecurityContext(owner_id, Role.OWNER, "acceptance"),
)
thesis_store.delete_all_for_test()
portfolio_store = PostgresPortfolioStore(
    provider,
    security_context_provider=lambda: SecurityContext(owner_id, Role.OWNER, "acceptance"),
)
portfolio_store.delete_all_for_test()
portfolio_store.save_official_security(owner_id, OfficialSecuritySnapshot(
    "2330", Decimal("100"), date(2026, 8, 28), "https://www.twse.com.tw/close/2330",
    "半導體業", "https://www.twse.com.tw/industry/2330", datetime(2026, 8, 28, tzinfo=timezone.utc),
    ("AI",), 1, "owner-confirmed-theme:acceptance-v1", datetime(2026, 8, 28, tzinfo=timezone.utc),
))
access_store = PostgresAccessAdapter(provider)
thesis_service = ThesisService(thesis_store, id_factory=lambda: str(uuid.uuid4()))
portfolio_service = PortfolioService(portfolio_store)
confirmations = ConfirmationService(access_store)


async def fixture_owner() -> AuthenticatedActor:
    return AuthenticatedActor(owner_id, Role.OWNER, 1)


app = create_fastapi_app(
    EvidenceApi(
        flow=EvidenceIntakeFlow(store=store, id_generator=lambda: str(uuid.uuid4())),
        anomaly_flow=AnomalyAssessmentFlow(
            research=ResearchAnomalyFacade(
                AnomalyAssessmentService(
                    store=store, clock=lambda: datetime.now(timezone.utc).isoformat()
                )
            )
        ),
        thesis_flow=ThesisLifecycleFlow(
            thesis_service,
            store,
            confirmations=confirmations,
            confirmed_transitions=PostgresConfirmedThesisTransition(
                access_store, thesis_store, thesis_service,
            ),
        ),
        portfolio_flow=PortfolioFlow(
            portfolio_service,
            thesis=thesis_service,
            confirmations=confirmations,
            confirmed_trades=PostgresConfirmedPortfolioTrade(
                access_store, portfolio_store, portfolio_service,
            ),
        ),
        valuation_flow=ValuationFlow(
            thesis_service,
            portfolio_service,
            store,
            confirmations=confirmations,
            confirmed_publications=PostgresConfirmedValuationPublication(
                access_store, thesis_store, thesis_service, store, portfolio_store,
            ),
        ),
    ),
    fixture_owner,
)


@app.get("/api/session", response_model=OwnerSessionResponse)
async def fixture_session() -> OwnerSessionResponse:
    return OwnerSessionResponse(
        kind="owner",
        user_id=owner_id,
        capabilities=["research:read", "research:write", "thesis:read", "thesis:write", "portfolio:read", "portfolio:write"],
        session_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        is_recovery_session=False,
        display_name="Acceptance Owner",
    )


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/acceptance/evidence/{evidence_id}")
async def acceptance_evidence(evidence_id: str) -> dict[str, object]:
    return {
        "audit_events": store.count_audit_events(evidence_id),
        "collection_jobs": store.count_collection_jobs(evidence_id),
        "provenance": store.get_source_provenance(evidence_id),
    }


@app.get("/acceptance/anomaly/{assessment_id}")
async def acceptance_anomaly(assessment_id: str) -> dict[str, int]:
    return {
        "audit_events": store.count_audit_events(assessment_id),
        "analysis_jobs": store.count_anomaly_jobs(assessment_id),
    }
