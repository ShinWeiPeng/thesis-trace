from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from thesis_trace.modules.portfolio.contracts import HoldingSnapshot, PortfolioSnapshot
from thesis_trace.modules.portfolio.policy import aggregate_exposure, select_dca_multiplier


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


def snapshot(*, cash: str = "900", quantity: str = "1", close: str = "100") -> PortfolioSnapshot:
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
    assert result.theme_exposure == {"ai": Decimal("0.1"), "taiwan-tech": Decimal("0.1")}
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
        official_industry="semiconductor",
        themes=("ai",),
        **FACT,
    )

    assert selection.multiplier == Decimal("0")
    assert selection.reasons == ("risk_cap",)
    assert selection.evaluated == (Decimal("1.5"), Decimal("1"), Decimal("0.5"), Decimal("0"))
