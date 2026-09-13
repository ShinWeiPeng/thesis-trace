from dataclasses import replace
from decimal import Decimal
from datetime import timedelta

import pytest

from thesis_trace.modules.portfolio.service import PortfolioService
from test_portfolio_domain import ACTOR, NOW, MemoryPortfolioStore, configured, holding


def prepare(subject, version, **changes):
    values = dict(
        snapshot_id="risk-1",
        expected_version=version,
        cost_profile_version=1,
        security_id="2330",
        base_amount=Decimal(100),
        buy_price=Decimal(100),
        raw_ceiling=Decimal(1),
        now=NOW,
    )
    values.update(changes)
    return subject.prepare_recommendation_snapshot(ACTOR, **values)


def test_prepared_risk_snapshot_uses_current_official_sources_without_trading():
    store = MemoryPortfolioStore()
    subject = PortfolioService(store)
    current = configured(subject)
    store.record = replace(
        current, cost_profile=replace(current.cost_profile, minimum_buy_fee=Decimal(20))
    )
    before = subject.get(ACTOR)
    result = prepare(subject, before.version)
    assert result.sizing.multiplier == Decimal("0.5")
    assert result.portfolio.cash == Decimal(1000)
    assert result.cost.minimum_buy_fee == Decimal(20)
    assert result.target == store.official["2330"]
    assert result.cash_as_of == NOW
    assert result.base_amount == Decimal(100)
    assert result.buy_price == Decimal(100)
    assert result.sizing.purchase_outflow == Decimal(70)
    assert result.sizing.acquired_quantity == Decimal("0.5")
    assert result.sizing.post_exposure.nav == Decimal(980)
    assert result.sizing.post_exposure.security_exposure["2330"] == Decimal(
        50
    ) / Decimal(980)
    assert result.sizing.post_exposure.feasible is True
    assert subject.get(ACTOR) == before


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"expected_version": 999}, "version_conflict"),
        ({"cost_profile_version": 2}, "cost_profile_version_conflict"),
        ({"now": NOW + timedelta(days=8)}, "official_security_invalid"),
        ({"security_id": "missing"}, "official_security_missing"),
    ],
)
def test_unavailable_or_stale_financial_inputs_reject(changes, code):
    subject = PortfolioService(MemoryPortfolioStore())
    record = configured(subject)
    with pytest.raises(ValueError, match=code):
        prepare(subject, record.version, **changes)


def test_risk_query_aggregates_same_security_across_all_buckets():
    store = MemoryPortfolioStore()
    subject = PortfolioService(store)
    current = configured(subject)
    store.record = replace(
        current,
        holdings=(
            holding(quantity="0.6"),
            replace(holding(quantity="0.6"), bucket_id="thesis-2"),
        ),
    )
    result = prepare(subject, current.version)
    assert result.sizing.multiplier == 0
    assert result.sizing.reasons == ("current_portfolio_breach",)
    assert len(result.portfolio.holdings) == 2
    assert result.sizing.purchase_outflow == 0
    assert result.sizing.acquired_quantity == 0
    assert result.sizing.post_exposure == result.exposure
