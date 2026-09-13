from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from dataclasses import replace

import pytest

from thesis_trace.modules.portfolio.contracts import (
    CostProfileSnapshot,
    HoldingSnapshot,
    PortfolioSnapshot,
)
from thesis_trace.modules.portfolio.policy import (
    aggregate_exposure,
    select_dca_multiplier,
)


NOW = datetime(2026, 8, 29, 5, 0, tzinfo=timezone.utc)
FACT = {
    "price_date": date(2026, 8, 28),
    "price_source": "https://www.twse.com.tw/close/2330",
    "industry_source": "https://www.twse.com.tw/industry/2330",
    "classification_effective_at": NOW,
    "theme_snapshot_version": 1,
    "theme_source": "owner-confirmed-theme:1",
    "theme_effective_at": NOW,
}


def snapshot(
    *, cash: str = "900", quantity: str = "1", close: str = "100"
) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        version=3,
        cash=Decimal(cash),
        holdings=(
            HoldingSnapshot(
                bucket_id="core:thesis-1",
                security_id="2330",
                quantity=Decimal(quantity),
                official_close=Decimal(close),
                official_industry="semiconductor",
                themes=("ai", "taiwan-tech"),
                **FACT,
            ),
        ),
    )


def test_exposure_aggregates_all_buckets_and_all_theme_memberships() -> None:
    result = aggregate_exposure(snapshot())

    assert result.nav == Decimal("1000")
    assert result.security_exposure == {"2330": Decimal("0.1")}
    assert result.industry_exposure == {"semiconductor": Decimal("0.1")}
    assert result.theme_exposure == {
        "ai": Decimal("0.1"),
        "taiwan-tech": Decimal("0.1"),
    }
    assert result.feasible is True


def test_exposure_equality_passes_and_current_breach_blocks_added_buys() -> None:
    equality = aggregate_exposure(snapshot(cash="900", quantity="1"))
    breached = aggregate_exposure(snapshot(cash="800", quantity="2"))

    assert equality.feasible is True
    assert breached.feasible is False
    assert breached.reasons == ("security_cap_exceeded:2330",)

    selection = select_dca_multiplier(
        base_amount=Decimal("100"),
        raw_ceiling=Decimal("1.5"),
        portfolio=snapshot(cash="800", quantity="2"),
        security_id="2330",
        official_close=Decimal("100"),
        buy_price=Decimal("100"),
        cost_profile=CostProfileSnapshot(
            1, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), NOW
        ),
        official_industry="semiconductor",
        themes=("ai", "taiwan-tech"),
        **FACT,
    )
    assert selection.multiplier == Decimal("0")
    assert selection.reasons == ("current_portfolio_breach",)


def test_dca_selects_highest_candidate_that_fits_cash_and_caps() -> None:
    selection = select_dca_multiplier(
        base_amount=Decimal("50"),
        raw_ceiling=Decimal("1.5"),
        portfolio=PortfolioSnapshot(version=1, cash=Decimal("75"), holdings=()),
        security_id="2330",
        official_close=Decimal("100"),
        buy_price=Decimal("100"),
        cost_profile=CostProfileSnapshot(
            1, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), NOW
        ),
        official_industry="semiconductor",
        themes=("ai",),
        **FACT,
    )

    assert selection.multiplier == Decimal("0")
    assert selection.reasons == ("risk_cap",)
    assert selection.evaluated == (
        Decimal("1.5"),
        Decimal("1"),
        Decimal("0.5"),
        Decimal("0"),
    )


def test_dca_fee_reduces_nav_and_clips_an_otherwise_exact_cap_equality():
    selection = select_dca_multiplier(
        base_amount=Decimal("100"),
        raw_ceiling=Decimal("1"),
        portfolio=PortfolioSnapshot(1, Decimal("1000"), ()),
        security_id="2330",
        official_close=Decimal("100"),
        buy_price=Decimal("100"),
        official_industry="semiconductor",
        themes=("ai",),
        cost_profile=CostProfileSnapshot(
            1,
            Decimal("0"),
            Decimal("20"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            NOW,
        ),
        **FACT,
    )
    # 1x = 100 / 980 > 10%; 0.5x = 50 / 980 < 10%.
    assert selection.multiplier == Decimal("0.5")


def size(**changes):
    arguments = dict(
        base_amount=Decimal("100"),
        raw_ceiling=Decimal("1"),
        portfolio=PortfolioSnapshot(1, Decimal("1000"), ()),
        security_id="2330",
        official_close=Decimal("100"),
        buy_price=Decimal("100"),
        official_industry="semiconductor",
        themes=("ai",),
        cost_profile=CostProfileSnapshot(
            1, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), NOW
        ),
        **FACT,
    )
    arguments.update(changes)
    return select_dca_multiplier(**arguments)


def test_dca_never_rounds_a_small_cap_breach_into_a_feasible_candidate():
    assert size(
        base_amount=Decimal("100.0000000000000000000000000001")
    ).multiplier == Decimal("0.5")


def test_current_cap_breach_must_not_disappear_in_display_rounding():
    portfolio = snapshot(cash="900", close="100.0000000000000000000000000001")
    assert aggregate_exposure(portfolio).feasible is False
    assert size(portfolio=portfolio).multiplier == Decimal("0")


@pytest.mark.parametrize(
    "base,expected", [("40", "1.5"), ("80", "1"), ("150", "0.5"), ("250", "0")]
)
def test_dca_selects_each_highest_feasible_discrete_multiplier(base, expected):
    assert size(
        base_amount=Decimal(base), raw_ceiling=Decimal("1.5")
    ).multiplier == Decimal(expected)


def test_dca_uses_purchase_price_for_quantity_and_official_close_for_exposure():
    # Spending 100 at 50 purchases two shares valued at 200: 200 / 1100 > 10%.
    # Spending 50 buys one share: 100 / 1050 < 10%.
    assert size(buy_price=Decimal("50")).multiplier == Decimal("0.5")


@pytest.mark.parametrize("cash,expected", [("20", "0"), ("21", "1")])
def test_dca_cash_limit_includes_minimum_fee_and_allows_exact_outflow(cash, expected):
    template = snapshot(quantity="0.98").holdings[0]
    holdings = tuple(
        replace(
            template,
            security_id=f"security-{index}",
            official_industry=f"industry-{index // 3}",
            themes=(),
        )
        for index in range(10)
    )
    costs = CostProfileSnapshot(
        1, Decimal("0"), Decimal("20"), Decimal("0"), Decimal("0"), Decimal("0"), NOW
    )
    result = size(
        base_amount=Decimal("1"),
        portfolio=PortfolioSnapshot(1, Decimal(cash), holdings),
        cost_profile=costs,
    )
    assert result.multiplier == Decimal(expected)


def test_proportional_fee_is_used_when_greater_than_minimum_fee():
    costs = CostProfileSnapshot(
        1, Decimal("0.1"), Decimal("1"), Decimal("0"), Decimal("0"), Decimal("0"), NOW
    )
    # Base 99.5 is feasible with fee 1, but 99.5 / 990.05 exceeds 10% with fee 9.95.
    assert size(base_amount=Decimal("99.5"), cost_profile=costs).multiplier == Decimal(
        "0.5"
    )


@pytest.mark.parametrize(
    "costs",
    [
        None,
        CostProfileSnapshot(
            0, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), NOW
        ),
        CostProfileSnapshot(
            1,
            Decimal("NaN"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            NOW,
        ),
        CostProfileSnapshot(
            1,
            Decimal("0"),
            Decimal("-1"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            NOW,
        ),
    ],
)
def test_dca_never_assumes_zero_cost_when_cost_profile_is_unavailable_or_invalid(costs):
    result = size(cost_profile=costs)
    assert result.multiplier == Decimal("0")
    assert result.reasons == ("invalid_cost_profile",)
