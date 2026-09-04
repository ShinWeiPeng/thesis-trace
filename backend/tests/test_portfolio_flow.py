from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from thesis_trace.application.contracts import PortfolioFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.portfolio.contracts import ConfirmTradeCommand, PortfolioActorContext
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.modules.thesis.contracts import (
    CreateThesisCommand,
    ThesisActorContext,
    ThesisResearchReference,
    ThesisStatus,
    TransitionThesisCommand,
)
from thesis_trace.modules.thesis.service import ThesisService
from test_portfolio_domain import MemoryPortfolioStore
from test_thesis_domain import MemoryThesisStore


NOW = datetime(2026, 8, 29, 5, 0, tzinfo=timezone.utc)
OWNER = AuthenticatedActor("owner-1", Role.OWNER, 1)


class Confirmations:
    def preview(self, *_args):
        return "trade-token", SimpleNamespace(expires_at=NOW)


class ConfirmedTrades:
    def __init__(self, service: PortfolioService) -> None:
        self.service = service

    def execute(self, *, actor, preview, reason, idempotency_key, challenge_token, now):
        assert challenge_token == "trade-token"
        return self.service.confirm_trade(ConfirmTradeCommand(
            PortfolioActorContext(actor.actor_id, True), preview, "challenge-1", reason, idempotency_key,
        ), now=now)


def subject() -> PortfolioFlow:
    service = PortfolioService(MemoryPortfolioStore(), trade_id_factory=lambda: "trade-1")
    return PortfolioFlow(
        service, confirmations=Confirmations(), confirmed_trades=ConfirmedTrades(service), clock=lambda: NOW,
    )


def configure(flow: PortfolioFlow) -> dict:
    profile = flow.save_cost_profile(OWNER, {
        "expected_version": 0, "buy_rate": "0", "minimum_buy_fee": "0", "sell_rate": "0",
        "minimum_sell_fee": "0", "tax_rate": "0", "effective_at": NOW.isoformat(),
        "reason": "Set costs", "idempotency_key": "cost-1",
    })
    return flow.save_cash(OWNER, {
        "expected_version": profile["version"], "cash": "1000", "as_of": NOW.isoformat(),
        "reason": "Set cash", "idempotency_key": "cash-1",
    })


def trade(version: int) -> dict:
    return {
        "expected_version": version, "source_kind": "manual", "source_row_id": "row-1",
        "broker_reference": None, "security_id": "2330", "side": "buy", "quantity": 1,
        "price": "100", "fees": "0", "tax": "0", "executed_at": NOW.isoformat(),
        "allocations": [{"bucket_id": "independent", "quantity": 1}],
    }


def test_owner_configures_previews_and_atomically_confirms_trade() -> None:
    flow = subject()
    portfolio = configure(flow)
    preview = flow.preview_trade(OWNER, trade(portfolio["version"]))
    committed = flow.confirm_trade(OWNER, {
        **trade(portfolio["version"]), "reason": "Confirm trade",
        "idempotency_key": "trade-1", "challenge_token": preview["challenge_token"],
    })

    assert preview["post_cash"] == "900"
    assert preview["feasible"] is True
    assert committed["version"] == 3
    assert committed["cash"] == "900"
    assert committed["holdings"][0]["bucket_id"] == "independent"


def test_learner_has_no_portfolio_projection() -> None:
    with pytest.raises(PermissionError, match="resource_unavailable"):
        subject().get(AuthenticatedActor("learner-1", Role.LEARNER, 1))


def test_l0_accepts_only_active_same_security_thesis_buckets() -> None:
    thesis = ThesisService(MemoryThesisStore(), id_factory=lambda: "thesis-active")
    created = thesis.create(CreateThesisCommand(
        ThesisActorContext("owner-1", True), ThesisResearchReference("company", "2330", 1, "2330"),
        "Active thesis", "Narrative", ("Invalidation",), (), "Create", "create-active",
    ), now=NOW)
    thesis.transition(TransitionThesisCommand(
        ThesisActorContext("owner-1", True), created.thesis_id, created.version,
        ThesisStatus.ACTIVE, "Activate", "activate",
    ), now=NOW)
    service = PortfolioService(MemoryPortfolioStore(), trade_id_factory=lambda: "trade-active")
    flow = PortfolioFlow(
        service, thesis=thesis, confirmations=Confirmations(),
        confirmed_trades=ConfirmedTrades(service), clock=lambda: NOW,
    )
    portfolio = configure(flow)
    active_trade = trade(portfolio["version"])
    active_trade["allocations"] = [{"bucket_id": "thesis-active", "quantity": 1}]
    assert flow.preview_trade(OWNER, active_trade)["feasible"] is True
    active_trade["allocations"] = [{"bucket_id": "missing-thesis", "quantity": 1}]
    with pytest.raises(LookupError, match="resource_unavailable"):
        flow.preview_trade(OWNER, active_trade)
