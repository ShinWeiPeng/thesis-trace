from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

httpx = pytest.importorskip("httpx")

from thesis_trace.api import EvidenceApi, create_fastapi_app
from thesis_trace.application.contracts import PortfolioFlow
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.portfolio.contracts import ConfirmTradeCommand, PortfolioActorContext
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.platform.in_memory import InMemoryEvidenceStore
from test_portfolio_domain import MemoryPortfolioStore


NOW = datetime(2026, 8, 29, 5, 0, tzinfo=timezone.utc)


class Confirmations:
    def preview(self, *_args):
        return "trade-token", SimpleNamespace(expires_at=NOW)


class ConfirmedTrades:
    def __init__(self, service): self.service = service
    def execute(self, *, actor, preview, reason, idempotency_key, challenge_token, now):
        return self.service.confirm_trade(ConfirmTradeCommand(
            PortfolioActorContext(actor.actor_id, True), preview, "challenge-1", reason, idempotency_key,
        ), now=now)


def test_portfolio_http_contract_rejects_client_authority_and_confirms_preview() -> None:
    async def actor_provider() -> AuthenticatedActor:
        return AuthenticatedActor("owner-1", Role.OWNER, 1)

    service = PortfolioService(MemoryPortfolioStore(), trade_id_factory=lambda: "trade-1")
    flow = PortfolioFlow(service, confirmations=Confirmations(), confirmed_trades=ConfirmedTrades(service), clock=lambda: NOW)
    app = create_fastapi_app(EvidenceApi(
        flow=EvidenceIntakeFlow(store=InMemoryEvidenceStore(), id_generator=lambda: "unused"),
        portfolio_flow=flow,
    ), actor_provider)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            profile = await client.put("/api/portfolio/cost-profile", json={
                "expected_version": 0, "buy_rate": "0", "minimum_buy_fee": "0", "sell_rate": "0",
                "minimum_sell_fee": "0", "tax_rate": "0", "effective_at": NOW.isoformat(),
                "reason": "Set costs", "idempotency_key": "cost-1",
            })
            cash = await client.put("/api/portfolio/investable-cash", json={
                "expected_version": 1, "cash": "1000", "as_of": NOW.isoformat(),
                "reason": "Set cash", "idempotency_key": "cash-1",
            })
            trade = {
                "expected_version": 2, "source_kind": "manual", "source_row_id": "row-1",
                "broker_reference": None, "security_id": "2330", "side": "buy", "quantity": 1,
                "price": "100", "fees": "0", "tax": "0", "executed_at": NOW.isoformat(),
                "allocations": [{"bucket_id": "independent", "quantity": 1}],
            }
            injected = await client.post("/api/portfolio/trade-previews", json={
                **trade, "post_cash": "999999", "feasible": True,
            })
            preview = await client.post("/api/portfolio/trade-previews", json=trade)
            confirmed = await client.post("/api/portfolio/trades", json={
                **trade, "reason": "Confirm", "idempotency_key": "trade-1",
                "challenge_token": preview.json()["challenge_token"],
            })
            return profile, cash, injected, preview, confirmed

    profile, cash, injected, preview, confirmed = asyncio.run(exercise())
    assert profile.status_code == 200 and profile.json()["version"] == 1
    assert cash.status_code == 200 and cash.json()["cash"] == "1000"
    assert injected.status_code == 422
    assert preview.status_code == 200 and preview.json()["post_cash"] == "900"
    assert confirmed.status_code == 200 and confirmed.json()["version"] == 3
    schema = app.openapi()["components"]["schemas"]["TradePreviewBody"]
    assert schema["additionalProperties"] is False
    assert "post_cash" not in schema["properties"]
    assert "feasible" not in schema["properties"]
    assert "official_close" not in schema["properties"]
    assert "official_industry" not in schema["properties"]
    assert "themes" not in schema["properties"]
