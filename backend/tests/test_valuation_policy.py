from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from thesis_trace.modules.thesis.valuation import (
    ValuationAbstained,
    add_calendar_months_clamped,
    annualized_net_return,
    company_history_benchmark,
    company_history_distribution,
    evaluate_validity,
    peer_group_distribution,
    peer_group_benchmark,
)
from thesis_trace.modules.thesis.contracts import (
    PeerValuationMember,
    ThesisResearchReference,
    ValuationMethod,
    ValuationSample,
)


UTC = timezone.utc


def test_company_history_uses_inclusive_linear_p75_and_dec_104_coverage() -> None:
    limited = company_history_distribution(tuple(Decimal(value) for value in range(1, 37)))
    standard = company_history_distribution(tuple(Decimal(value) for value in range(1, 61)))

    assert (limited.median, limited.p75, limited.coverage.value, limited.sample_count) == (
        Decimal("18.5"),
        Decimal("27.25"),
        "limited_history",
        36,
    )
    assert (standard.median, standard.p75, standard.coverage.value) == (
        Decimal("30.5"),
        Decimal("45.25"),
        "standard_history",
    )

    with pytest.raises(ValuationAbstained, match="insufficient_company_history"):
        company_history_distribution(tuple(Decimal(value) for value in range(1, 36)))


def test_peer_group_requires_5_to_12_unique_non_target_companies() -> None:
    result = peer_group_distribution(
        target_company_id="target",
        peer_company_ids=("a", "b", "c", "d", "e"),
        samples=tuple(Decimal(value) for value in ("10", "20", "30", "40", "50")),
    )
    assert result.median == Decimal("30")
    assert result.p75 == Decimal("40")
    with pytest.raises(ValuationAbstained, match="invalid_peer_group"):
        peer_group_distribution(
            target_company_id="target", peer_company_ids=("a", "b", "c", "d"),
            samples=(Decimal("1"),) * 4,
        )
    with pytest.raises(ValuationAbstained, match="invalid_peer_group"):
        peer_group_distribution(
            target_company_id="target", peer_company_ids=("a", "b", "c", "d", "a"),
            samples=(Decimal("1"),) * 5,
        )


def test_calendar_month_horizon_clamps_to_month_end() -> None:
    assert add_calendar_months_clamped(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_calendar_months_clamped(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_calendar_months_clamped(date(2026, 8, 31), 6) == date(2027, 2, 28)


def test_validity_fails_closed_at_the_earliest_expiry() -> None:
    saved_at = datetime(2026, 1, 1, tzinfo=UTC)
    next_report = saved_at + timedelta(days=70)
    material_event = saved_at + timedelta(days=80)

    valid = evaluate_validity(
        basis_date=date(2026, 1, 31),
        horizon_months=12,
        saved_at=saved_at,
        evaluation_time=next_report - timedelta(microseconds=1),
        next_report_time=next_report,
        material_event_time=material_event,
    )
    assert valid.target_date == date(2027, 1, 31)
    assert valid.expires_at == next_report
    assert valid.expiry_causes == ("next_report",)

    with pytest.raises(ValuationAbstained, match="forecast_expired"):
        evaluate_validity(
            basis_date=date(2026, 1, 31),
            horizon_months=12,
            saved_at=saved_at,
            evaluation_time=next_report,
            next_report_time=next_report,
            material_event_time=material_event,
        )


def test_annualized_return_uses_exact_costs_tax_and_dividend() -> None:
    result = annualized_net_return(
        forecast=Decimal("12"),
        multiple=Decimal("10"),
        quantity=Decimal("10"),
        buy_price=Decimal("100"),
        cash_dividend=Decimal("50"),
        buy_rate=Decimal("0"),
        minimum_buy_fee=Decimal("20"),
        sell_rate=Decimal("0"),
        minimum_sell_fee=Decimal("20"),
        tax_rate=Decimal("0.003"),
        holding_days=365,
    )

    assert result.target_price == Decimal("120")
    assert result.purchase_outflow == Decimal("1020")
    assert result.terminal_inflow == Decimal("1226.400")
    assert result.annualized_return == Decimal("0.202352941176470588235294118")
    assert result.tax_disclaimer == "Taiwan securities transaction tax is included from the bound Cost Profile."


def test_source_bound_benchmarks_preserve_exclusions_and_percentile_trace() -> None:
    source = ThesisResearchReference("evidence", "source-1", 1, "2330")
    samples = tuple(
        ValuationSample(
            f"m-{index + 1}", "2330", date(2023 + index // 12, index % 12 + 1, 1),
            Decimal(index + 1), Decimal("0") if index == 0 else Decimal("1"), source,
        ) for index in range(37)
    )
    history = company_history_benchmark(
        method=ValuationMethod.PE, target_company_id="2330", samples=samples,
    )
    assert history.distribution.sample_count == 36
    assert history.exclusions == ("m-1:nonpositive_denominator",)
    assert history.distribution.sorted_samples[0] == Decimal("2")
    assert history.distribution.p75_position == Decimal("27.25")

    members = tuple(
        PeerValuationMember(
            str(2300 + index), f"same revenue driver {index}", ValuationMethod.PE, True, True,
            ValuationSample(
                f"peer-{index}", str(2300 + index), date(2026, 8, 1),
                Decimal(10 + index), Decimal("1"),
                ThesisResearchReference("evidence", f"peer-source-{index}", 1, str(2300 + index)),
            ),
        ) for index in range(1, 6)
    )
    peer = peer_group_benchmark(method=ValuationMethod.PE, target_company_id="2330", members=members)
    assert peer.distribution.sample_count == 5
    assert peer.valid_samples[0].source.record_id == "peer-source-1"
