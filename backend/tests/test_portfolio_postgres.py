from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import os
import uuid

import pytest

from thesis_trace.adapters.postgres_portfolio.adapter import PostgresPortfolioStore
from thesis_trace.adapters.postgres_access.adapter import PostgresAccessAdapter
from thesis_trace.bootstrap.application import PostgresConfirmedPortfolioTrade
from thesis_trace.modules.access.confirmation_challenge.service import ConfirmationService
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role, SecurityContext
from thesis_trace.modules.portfolio.contracts import (
    CanonicalTrade,
    OfficialSecuritySnapshot,
    PortfolioActorContext,
    PreviewTradeCommand,
    SaveCostProfileCommand,
    SaveInvestableCashCommand,
    TradeAllocation,
    TradeSide,
)
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.platform.postgres import PostgresUnavailable, bootstrap_schema


psycopg = pytest.importorskip("psycopg")


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="set THESIS_TRACE_TEST_DATABASE_URL for PostgreSQL integration evidence",
)

NOW = datetime(2026, 8, 29, 5, 0, tzinfo=timezone.utc)
OWNER_ID = "00000000-0000-0000-0000-000000000001"


def _context() -> SecurityContext:
    return SecurityContext(OWNER_ID, Role.OWNER, "portfolio-postgres-test")


def test_postgres_portfolio_versions_receipts_and_rls_projection() -> None:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    store = PostgresPortfolioStore(lambda: url, security_context_provider=_context)
    store.delete_all_for_test()
    service = PortfolioService(store)
    actor = PortfolioActorContext(OWNER_ID, True)

    profile = service.save_cost_profile(
        SaveCostProfileCommand(
            actor, 0, Decimal("0.001425"), Decimal("20"), Decimal("0.001425"),
            Decimal("20"), Decimal("0.003"), NOW, "Save costs", "cost-1",
        ),
        now=NOW,
    )
    cash = service.save_investable_cash(
        SaveInvestableCashCommand(actor, profile.version, Decimal("100000"), NOW, "Save cash", "cash-1"),
        now=NOW,
    )

    assert service.get(actor) == cash
    assert store.count_versions(OWNER_ID) == 2
    assert service.save_investable_cash(
        SaveInvestableCashCommand(actor, profile.version, Decimal("100000"), NOW, "Save cash", "cash-1"),
        now=NOW,
    ) == cash

    role_name = "thesis_trace_portfolio_rls_integration"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role_name}') "
            f"THEN CREATE ROLE {role_name} NOLOGIN NOBYPASSRLS; END IF; END $$"
        )
        connection.execute(f"GRANT USAGE ON SCHEMA portfolio TO {role_name}")
        connection.execute(f"GRANT SELECT ON portfolio.current_state TO {role_name}")
        connection.execute(f"SET ROLE {role_name}")
        with connection.transaction():
            connection.execute("SELECT set_config('app.user_id',%s,true)", (OWNER_ID,))
            assert connection.execute("SELECT count(*) FROM portfolio.current_state").fetchone()[0] == 1
        with connection.transaction():
            connection.execute(
                "SELECT set_config('app.user_id',%s,true)",
                ("00000000-0000-0000-0000-000000000099",),
            )
            assert connection.execute("SELECT count(*) FROM portfolio.current_state").fetchone()[0] == 0
        connection.execute("RESET ROLE")


def _configured(url: str) -> tuple[PortfolioService, PostgresPortfolioStore, object]:
    bootstrap_schema(lambda: url)
    store = PostgresPortfolioStore(lambda: url, security_context_provider=_context)
    store.delete_all_for_test()
    with psycopg.connect(url) as connection:
        connection.execute(
            """INSERT INTO access.users(user_id,role,status)
            VALUES(%s,'owner','active') ON CONFLICT(user_id) DO UPDATE SET role='owner',status='active'""",
            (OWNER_ID,),
        )
    service = PortfolioService(store, trade_id_factory=lambda: "trade-atomic")
    store.save_official_security(OWNER_ID, OfficialSecuritySnapshot(
        "2330", Decimal("100"), date(2026, 8, 28), "https://www.twse.com.tw/close/2330",
        "semiconductor", "https://www.twse.com.tw/industry/2330", NOW,
        ("ai",), 1, "owner-confirmed-theme:1", NOW,
    ))
    profile = service.save_cost_profile(SaveCostProfileCommand(
        PortfolioActorContext(OWNER_ID, True), 0, Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("0"), Decimal("0"), NOW, "Costs", f"cost-{uuid.uuid4()}",
    ), now=NOW)
    portfolio = service.save_investable_cash(SaveInvestableCashCommand(
        PortfolioActorContext(OWNER_ID, True), profile.version, Decimal("100000"), NOW,
        "Cash", f"cash-{uuid.uuid4()}",
    ), now=NOW)
    preview = service.preview_trade(PreviewTradeCommand(
        PortfolioActorContext(OWNER_ID, True), portfolio.version,
        CanonicalTrade("manual", "row-atomic", None, "2330", TradeSide.BUY, 1,
                       Decimal("100"), Decimal("0"), Decimal("0"), NOW),
        (TradeAllocation("independent", 1),), {}, frozenset({"independent"}),
    ))
    return service, store, preview


def test_confirmed_trade_consumes_challenge_and_portfolio_atomically() -> None:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    service, store, preview = _configured(url)
    access = PostgresAccessAdapter(lambda: url)
    confirmations = ConfirmationService(access, clock=lambda: NOW, token_factory=lambda: f"trade-token-{uuid.uuid4()}")
    payload = {"fingerprint": preview.fingerprint, "preview_digest": preview.preview_digest}
    token, _challenge = confirmations.preview(
        OWNER_ID, "confirm_portfolio_trade", OWNER_ID, preview.expected_portfolio_version,
        payload, {"consequences": ["confirm"]},
    )
    coordinator = PostgresConfirmedPortfolioTrade(access, store, service)
    changed = coordinator.execute(
        actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), preview=preview, reason="Confirm",
        idempotency_key="trade-atomic", challenge_token=token, now=NOW,
    )
    replay = coordinator.execute(
        actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), preview=preview, reason="Confirm",
        idempotency_key="trade-atomic", challenge_token=token, now=NOW,
    )
    assert changed.version == 3 and replay == changed
    assert store.count_versions(OWNER_ID) == 3
    with psycopg.connect(url) as connection:
        connection.execute("SELECT set_config('app.user_id',%s,true)", (OWNER_ID,))
        connection.execute("SELECT set_config('app.role','owner',true)")
        audit = connection.execute(
            """SELECT before_version,after_version,correlation_id,causation_id,
            policy_version,build_version FROM portfolio.audit_events
            WHERE owner_user_id=%s AND action='trade_confirmed'""", (OWNER_ID,),
        ).fetchone()
    assert audit[:3] == (2, 3, "trade-atomic")
    assert len(audit[3]) == 64
    assert audit[4:] == ("portfolio-record-v1", "test-build")


def test_confirmed_trade_fault_rolls_back_challenge_and_portfolio() -> None:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    service, store, preview = _configured(url)
    access = PostgresAccessAdapter(
        lambda: url,
        confirmed_mutation_fault_hook=lambda: (_ for _ in ()).throw(RuntimeError("fault")),
    )
    confirmations = ConfirmationService(access, clock=lambda: NOW, token_factory=lambda: f"trade-rollback-{uuid.uuid4()}")
    payload = {"fingerprint": preview.fingerprint, "preview_digest": preview.preview_digest}
    token, _challenge = confirmations.preview(
        OWNER_ID, "confirm_portfolio_trade", OWNER_ID, preview.expected_portfolio_version,
        payload, {"consequences": ["confirm"]},
    )
    with pytest.raises(PostgresUnavailable, match="postgres_unavailable"):
        PostgresConfirmedPortfolioTrade(access, store, service).execute(
            actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), preview=preview, reason="Confirm",
            idempotency_key="trade-rollback", challenge_token=token, now=NOW,
        )
    assert service.get(PortfolioActorContext(OWNER_ID, True)).version == 2
    assert store.count_versions(OWNER_ID) == 2


def test_confirmed_correction_and_company_action_are_atomic_append_only_records() -> None:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    service, store, trade_preview = _configured(url)
    access = PostgresAccessAdapter(lambda: url)
    confirmations = ConfirmationService(access, clock=lambda: NOW, token_factory=lambda: f"portfolio-mutation-{uuid.uuid4()}")
    coordinator = PostgresConfirmedPortfolioTrade(access, store, service)

    trade_payload = {"fingerprint": trade_preview.fingerprint, "preview_digest": trade_preview.preview_digest}
    trade_token, _ = confirmations.preview(
        OWNER_ID, "confirm_portfolio_trade", OWNER_ID, trade_preview.expected_portfolio_version,
        trade_payload, {"consequences": ["trade"]},
    )
    traded = coordinator.execute(
        actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), preview=trade_preview,
        reason="Confirm", idempotency_key="trade-before-action", challenge_token=trade_token, now=NOW,
    )
    action_preview = service.preview_company_action(
        PortfolioActorContext(OWNER_ID, True), expected_version=traded.version,
        security_id="2330", action_kind="split", confirmed_post_action_shares=2,
        cash_in_lieu=Decimal("0"), now=NOW,
    )
    action_payload = {"preview_digest": action_preview.preview_digest, "security_id": "2330"}
    action_token, _ = confirmations.preview(
        OWNER_ID, "confirm_portfolio_company_action", OWNER_ID, action_preview.expected_portfolio_version,
        action_payload, {"consequences": ["action"]},
    )
    acted = coordinator.execute_company_action(
        actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), preview=action_preview,
        reason="Confirmed split", idempotency_key="action-atomic", challenge_token=action_token, now=NOW,
    )
    assert acted.version == 4
    assert acted.company_actions[0].confirmed_post_action_shares == 2
    assert service.get(PortfolioActorContext(OWNER_ID, True)) == acted

    service, store, trade_preview = _configured(url)
    access = PostgresAccessAdapter(lambda: url)
    confirmations = ConfirmationService(access, clock=lambda: NOW, token_factory=lambda: f"portfolio-correction-{uuid.uuid4()}")
    coordinator = PostgresConfirmedPortfolioTrade(access, store, service)
    trade_payload = {"fingerprint": trade_preview.fingerprint, "preview_digest": trade_preview.preview_digest}
    trade_token, _ = confirmations.preview(
        OWNER_ID, "confirm_portfolio_trade", OWNER_ID, trade_preview.expected_portfolio_version,
        trade_payload, {"consequences": ["trade"]},
    )
    traded = coordinator.execute(
        actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), preview=trade_preview,
        reason="Confirm", idempotency_key="trade-before-correction", challenge_token=trade_token, now=NOW,
    )
    correction_preview = service.preview_correction(
        PortfolioActorContext(OWNER_ID, True), expected_version=traded.version,
        original_trade_id=traded.trades[0].trade_id, now=NOW,
    )
    correction_payload = {"original_trade_id": correction_preview.original_trade_id, "preview_digest": correction_preview.preview_digest}
    correction_token, _ = confirmations.preview(
        OWNER_ID, "correct_portfolio_trade", OWNER_ID, correction_preview.expected_portfolio_version,
        correction_payload, {"consequences": ["correction"]},
    )
    corrected = coordinator.execute_correction(
        actor=AuthenticatedActor(OWNER_ID, Role.OWNER, 1), preview=correction_preview,
        reason="Broker corrected", idempotency_key="correction-atomic",
        challenge_token=correction_token, now=NOW,
    )
    assert corrected.version == 4
    assert corrected.corrections[0].original_trade_id == traded.trades[0].trade_id
    assert corrected.trades == traded.trades
