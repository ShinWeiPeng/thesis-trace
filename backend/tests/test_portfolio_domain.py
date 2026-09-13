from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from thesis_trace.modules.portfolio.contracts import (
    CanonicalTrade,
    ConfirmTradeCommand,
    ConfirmTradeCorrectionCommand,
    ConfirmCompanyActionCommand,
    HoldingSnapshot,
    OfficialSecuritySnapshot,
    PortfolioActorContext,
    PreviewTradeCommand,
    SaveCostProfileCommand,
    SaveInvestableCashCommand,
    TradeAllocation,
    TradeSide,
)
from thesis_trace.modules.portfolio.service import PortfolioService


NOW = datetime(2026, 8, 29, 5, 0, tzinfo=timezone.utc)
ACTOR = PortfolioActorContext("owner-1", True)


class MemoryPortfolioStore:
    def __init__(self) -> None:
        self.record = None
        self.receipts = {}
        self.official = {
            "2330": OfficialSecuritySnapshot(
                "2330",
                Decimal("100"),
                date(2026, 8, 28),
                "https://www.twse.com.tw/close/2330",
                "semiconductor",
                "https://www.twse.com.tw/industry/2330",
                NOW,
                ("ai",),
                1,
                "owner-confirmed-theme:1",
                NOW,
            )
        }

    def get(self, actor_id: str):
        return (
            self.record
            if self.record is not None and self.record.owner_user_id == actor_id
            else None
        )

    def get_official_security(self, actor_id: str, security_id: str):
        return self.official.get(security_id)

    def commit(
        self,
        *,
        actor_id,
        idempotency_key,
        command_digest,
        expected_version,
        record,
        action,
        reason,
    ):
        key = (actor_id, idempotency_key)
        if key in self.receipts:
            digest = self.receipts[key]
            if digest != command_digest:
                raise ValueError("idempotency_conflict")
            return self.record
        current_version = 0 if self.record is None else self.record.version
        if current_version != expected_version:
            raise ValueError("version_conflict")
        self.record = record
        self.receipts[key] = command_digest
        return record


def service() -> PortfolioService:
    return PortfolioService(MemoryPortfolioStore(), trade_id_factory=lambda: "trade-1")


def holding(*, quantity: str) -> HoldingSnapshot:
    fact = MemoryPortfolioStore().official["2330"]
    return HoldingSnapshot(
        "independent",
        "2330",
        Decimal(quantity),
        fact.official_close,
        fact.official_industry,
        fact.themes,
        fact.price_date,
        fact.price_source,
        fact.industry_source,
        fact.classification_effective_at,
        fact.theme_snapshot_version,
        fact.theme_source,
        fact.theme_effective_at,
    )


def configured(subject: PortfolioService):
    with_cost = subject.save_cost_profile(
        SaveCostProfileCommand(
            ACTOR,
            0,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            NOW,
            "Set cost profile",
            "cost-1",
        ),
        now=NOW,
    )
    return subject.save_investable_cash(
        SaveInvestableCashCommand(
            ACTOR, with_cost.version, Decimal("1000"), NOW, "Set cash", "cash-1"
        ),
        now=NOW,
    )


def preview_command(version: int) -> PreviewTradeCommand:
    return PreviewTradeCommand(
        actor=ACTOR,
        expected_version=version,
        trade=CanonicalTrade(
            "manual",
            "row-1",
            None,
            "2330",
            TradeSide.BUY,
            1,
            Decimal("100"),
            Decimal("0"),
            Decimal("0"),
            NOW,
        ),
        allocations=(TradeAllocation("independent", 1),),
        available_by_bucket={},
        allowed_bucket_ids=frozenset({"independent"}),
    )


def test_cost_cash_preview_and_confirm_are_versioned_and_server_authoritative() -> None:
    subject = service()
    portfolio = configured(subject)
    preview = subject.preview_trade(preview_command(portfolio.version), now=NOW)

    assert preview.expected_portfolio_version == 2
    assert preview.post_portfolio.cash == Decimal("900")
    assert preview.exposure.security_exposure == {"2330": Decimal("0.1")}
    assert preview.exposure.feasible is True

    with pytest.raises(PermissionError, match="confirmation_required"):
        subject.confirm_trade(
            ConfirmTradeCommand(ACTOR, preview, "", "Confirm trade", "trade-1"), now=NOW
        )

    committed = subject.confirm_trade(
        ConfirmTradeCommand(ACTOR, preview, "challenge-1", "Confirm trade", "trade-1"),
        now=NOW,
    )
    assert committed.version == 3
    assert committed.cash == Decimal("900")
    assert committed.trades[0].trade_id == "trade-1"
    assert committed.trades[0].fingerprint == preview.fingerprint


def test_non_owner_and_stale_preview_fail_closed() -> None:
    subject = service()
    portfolio = configured(subject)
    preview = subject.preview_trade(preview_command(portfolio.version), now=NOW)

    with pytest.raises(PermissionError, match="resource_unavailable"):
        subject.get(PortfolioActorContext("learner-1", False))

    subject.save_investable_cash(
        SaveInvestableCashCommand(
            ACTOR, 2, Decimal("950"), NOW, "Update cash", "cash-2"
        ),
        now=NOW,
    )
    with pytest.raises(ValueError, match="version_conflict"):
        subject.confirm_trade(
            ConfirmTradeCommand(
                ACTOR, preview, "challenge-1", "Confirm stale trade", "trade-stale"
            ),
            now=NOW,
        )


def test_missing_official_fact_fails_and_sell_may_reduce_existing_breach() -> None:
    store = MemoryPortfolioStore()
    subject = PortfolioService(store)
    current = configured(subject)
    store.official.pop("2330")
    with pytest.raises(ValueError, match="official_security_missing"):
        subject.preview_trade(preview_command(current.version), now=NOW)

    store.official = MemoryPortfolioStore().official
    store.record = replace(
        current, cash=Decimal("700"), holdings=(holding(quantity="3"),)
    )
    sell = replace(
        preview_command(current.version),
        trade=replace(
            preview_command(current.version).trade, side=TradeSide.SELL, quantity=1
        ),
        allocations=(TradeAllocation("independent", 1),),
        available_by_bucket={"independent": 3},
    )
    preview = subject.preview_trade(sell, now=NOW)
    assert preview.exposure.feasible is False
    assert preview.exposure.security_exposure["2330"] < Decimal("0.3")


def test_trade_correction_is_append_only_and_reverses_original_projection() -> None:
    store = MemoryPortfolioStore()
    subject = PortfolioService(
        store,
        trade_id_factory=lambda: "trade-1",
        correction_id_factory=lambda: "correction-1",
    )
    current = configured(subject)
    trade_preview = subject.preview_trade(preview_command(current.version), now=NOW)
    traded = subject.confirm_trade(
        ConfirmTradeCommand(ACTOR, trade_preview, "challenge", "Confirm", "trade-1"),
        now=NOW,
    )
    correction = subject.preview_correction(
        ACTOR,
        expected_version=traded.version,
        original_trade_id="trade-1",
        now=NOW,
    )
    corrected = subject.confirm_correction(
        ConfirmTradeCorrectionCommand(
            ACTOR, correction, "challenge-2", "Broker correction", "correction-1"
        ),
        now=NOW,
    )
    assert corrected.cash == Decimal("1000")
    assert corrected.holdings == ()
    assert corrected.trades[0].trade_id == "trade-1"
    assert corrected.corrections[0].original_trade_id == "trade-1"
    updated_costs = subject.save_cost_profile(
        SaveCostProfileCommand(
            ACTOR,
            corrected.version,
            Decimal("0.001"),
            Decimal("1"),
            Decimal("0.001"),
            Decimal("1"),
            Decimal("0.003"),
            NOW,
            "Update costs",
            "cost-2",
        ),
        now=NOW,
    )
    assert updated_costs.trades == corrected.trades
    assert updated_costs.corrections == corrected.corrections
    with pytest.raises(ValueError, match="trade_already_corrected"):
        subject.preview_correction(
            ACTOR,
            expected_version=updated_costs.version,
            original_trade_id="trade-1",
            now=NOW,
        )


def test_same_canonical_trade_cannot_be_confirmed_with_a_new_idempotency_key() -> None:
    subject = service()
    current = configured(subject)
    current = subject.save_investable_cash(
        SaveInvestableCashCommand(
            ACTOR,
            current.version,
            Decimal("10000"),
            NOW,
            "More cash",
            "cash-2",
        ),
        now=NOW,
    )
    first_preview = subject.preview_trade(preview_command(current.version), now=NOW)
    first = subject.confirm_trade(
        ConfirmTradeCommand(
            ACTOR, first_preview, "challenge-1", "Confirm", "trade-import-1"
        ),
        now=NOW,
    )
    duplicate_preview = subject.preview_trade(preview_command(first.version), now=NOW)
    with pytest.raises(ValueError, match="duplicate_trade"):
        subject.confirm_trade(
            ConfirmTradeCommand(
                ACTOR, duplicate_preview, "challenge-2", "Retry", "trade-import-2"
            ),
            now=NOW,
        )


def test_company_action_uses_largest_remainder_across_buckets_and_appends_record() -> (
    None
):
    store = MemoryPortfolioStore()
    subject = PortfolioService(store, company_action_id_factory=lambda: "action-1")
    current = configured(subject)
    store.record = replace(
        current,
        cash=Decimal("9700"),
        holdings=(
            replace(holding(quantity="1"), bucket_id="thesis-a"),
            replace(holding(quantity="2"), bucket_id="independent"),
        ),
    )
    preview = subject.preview_company_action(
        ACTOR,
        expected_version=current.version,
        security_id="2330",
        action_kind="split",
        confirmed_post_action_shares=5,
        cash_in_lieu=Decimal("30"),
        now=NOW,
    )
    changed = subject.confirm_company_action(
        ConfirmCompanyActionCommand(
            ACTOR, preview, "challenge", "Confirmed split", "action-1"
        ),
        now=NOW,
    )
    assert sum(value.quantity for value in changed.holdings) == Decimal("5")
    assert changed.cash == Decimal("9730")
    assert changed.company_actions[0].allocation.remainder_order == (
        "thesis-a",
        "independent",
    )
    updated_costs = subject.save_cost_profile(
        SaveCostProfileCommand(
            ACTOR,
            changed.version,
            Decimal("0.001"),
            Decimal("1"),
            Decimal("0.001"),
            Decimal("1"),
            Decimal("0.003"),
            NOW,
            "Update costs",
            "cost-after-action",
        ),
        now=NOW,
    )
    assert updated_costs.company_actions == changed.company_actions
