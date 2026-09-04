from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext

from thesis_trace.modules.thesis.contracts import (
    ValuationCoverage,
    ValuationBenchmarkSnapshot,
    ValuationDistribution,
    ValuationMethod,
    ValuationSample,
    PeerValuationMember,
    ValuationReturn,
    ValuationValidity,
)


class ValuationAbstained(ValueError):
    """Stable fail-closed outcome for an ineligible valuation calculation."""


def _finite(value: Decimal, code: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or (positive and value <= 0):
        raise ValuationAbstained(code)
    return value


def _inclusive_percentile(values: tuple[Decimal, ...], percentile: Decimal) -> tuple[Decimal, Decimal, int, int, Decimal]:
    if not values:
        raise ValuationAbstained("insufficient_samples")
    if len(values) == 1:
        return values[0], Decimal(1), 1, 1, Decimal(0)
    position = Decimal(1) + Decimal(len(values) - 1) * percentile
    lower = int(position)
    fraction = position - Decimal(lower)
    lower_value = values[lower - 1]
    if fraction == 0:
        return lower_value, position, lower, lower, Decimal(0)
    upper_value = values[lower]
    return lower_value + fraction * (upper_value - lower_value), position, lower, lower + 1, fraction


def company_history_distribution(samples: tuple[Decimal, ...]) -> ValuationDistribution:
    """Apply DEC-101 and DEC-104 to valid monthly company-history samples."""

    if len(samples) < 36:
        raise ValuationAbstained("insufficient_company_history")
    try:
        ordered = tuple(sorted(_finite(value, "invalid_sample", positive=True) for value in samples))
    except (InvalidOperation, TypeError) as exc:
        raise ValuationAbstained("invalid_sample") from exc
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
    coverage = ValuationCoverage.LIMITED_HISTORY if len(ordered) < 60 else ValuationCoverage.STANDARD_HISTORY
    p75, position, lower, upper, fraction = _inclusive_percentile(ordered, Decimal("0.75"))
    return ValuationDistribution(
        median=median,
        p75=p75,
        coverage=coverage,
        sample_count=len(ordered),
        sorted_samples=ordered,
        p75_position=position,
        p75_lower_index=lower,
        p75_upper_index=upper,
        p75_interpolation_fraction=fraction,
    )


def peer_group_distribution(
    *, target_company_id: str, peer_company_ids: tuple[str, ...], samples: tuple[Decimal, ...],
) -> ValuationDistribution:
    """Apply the confirmed 5–12 unique, target-excluding peer contract."""

    normalized = tuple(value.strip() for value in peer_company_ids)
    if (
        len(normalized) != len(samples)
        or len(normalized) < 5
        or len(normalized) > 12
        or len(set(normalized)) != len(normalized)
        or not target_company_id.strip()
        or target_company_id in normalized
        or any(not value for value in normalized)
    ):
        raise ValuationAbstained("invalid_peer_group")
    ordered = tuple(sorted(_finite(value, "invalid_sample", positive=True) for value in samples))
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
    p75, position, lower, upper, fraction = _inclusive_percentile(ordered, Decimal("0.75"))
    return ValuationDistribution(
        median=median,
        p75=p75,
        coverage=ValuationCoverage.STANDARD_HISTORY,
        sample_count=len(ordered),
        sorted_samples=ordered,
        p75_position=position,
        p75_lower_index=lower,
        p75_upper_index=upper,
        p75_interpolation_fraction=fraction,
    )


def company_history_benchmark(
    *, method: ValuationMethod, target_company_id: str, samples: tuple[ValuationSample, ...],
) -> ValuationBenchmarkSnapshot:
    if method not in {ValuationMethod.PE, ValuationMethod.PB}:
        raise ValuationAbstained("method_abstained")
    valid: list[ValuationSample] = []
    exclusions: list[str] = []
    seen: set[str] = set()
    seen_months: set[tuple[int, int]] = set()
    for sample in sorted(samples, key=lambda value: (value.observed_on, value.sample_id)):
        code = None
        if not sample.sample_id or sample.sample_id in seen:
            code = "duplicate_sample"
        elif (sample.observed_on.year, sample.observed_on.month) in seen_months:
            code = "duplicate_month"
        elif sample.company_id != target_company_id:
            code = "wrong_company"
        elif sample.source.record_type != "evidence" or sample.source.company_id != target_company_id:
            code = "invalid_source"
        elif not sample.multiple.is_finite() or sample.multiple <= 0:
            code = "invalid_multiple"
        elif not sample.denominator.is_finite() or sample.denominator <= 0:
            code = "nonpositive_denominator"
        if code is None:
            seen.add(sample.sample_id)
            seen_months.add((sample.observed_on.year, sample.observed_on.month))
            valid.append(sample)
        else:
            exclusions.append(f"{sample.sample_id}:{code}")
    if valid:
        first = min(value.observed_on for value in valid)
        last = max(value.observed_on for value in valid)
        covered_months = (last.year - first.year) * 12 + last.month - first.month + 1
        if covered_months < 36:
            raise ValuationAbstained("insufficient_company_history_period")
    distribution = company_history_distribution(tuple(value.multiple for value in valid))
    return ValuationBenchmarkSnapshot(
        "company_history", distribution, tuple(valid), tuple(exclusions),
        min(value.observed_on for value in valid), max(value.observed_on for value in valid),
    )


def peer_group_benchmark(
    *, method: ValuationMethod, target_company_id: str, members: tuple[PeerValuationMember, ...],
) -> ValuationBenchmarkSnapshot:
    if method not in {ValuationMethod.PE, ValuationMethod.PB}:
        raise ValuationAbstained("method_abstained")
    if len(members) < 5 or len(members) > 12:
        raise ValuationAbstained("invalid_peer_group")
    valid: list[ValuationSample] = []
    exclusions: list[str] = []
    seen: set[str] = set()
    for member in members:
        code = None
        if not member.company_id or member.company_id in seen:
            code = "duplicate_peer"
        elif member.company_id == target_company_id:
            code = "target_company"
        elif not member.inclusion_reason.strip():
            code = "missing_inclusion_reason"
        elif member.method is not method:
            code = "method_mismatch"
        elif not member.taiwan_listed:
            code = "not_taiwan_listed"
        elif not member.owner_confirmed:
            code = "unconfirmed_peer"
        elif member.sample.company_id != member.company_id or member.sample.source.company_id != member.company_id:
            code = "invalid_source"
        elif not member.sample.multiple.is_finite() or member.sample.multiple <= 0:
            code = "invalid_multiple"
        elif not member.sample.denominator.is_finite() or member.sample.denominator <= 0:
            code = "nonpositive_denominator"
        if code is None:
            seen.add(member.company_id)
            valid.append(member.sample)
        else:
            exclusions.append(f"{member.company_id}:{code}")
    if len(valid) < 5:
        raise ValuationAbstained("insufficient_valid_peers")
    distribution = peer_group_distribution(
        target_company_id=target_company_id,
        peer_company_ids=tuple(value.company_id for value in valid),
        samples=tuple(value.multiple for value in valid),
    )
    return ValuationBenchmarkSnapshot(
        "peer_group", distribution, tuple(valid), tuple(exclusions),
        min(value.observed_on for value in valid), max(value.observed_on for value in valid),
    )


def add_calendar_months_clamped(value: date, months: int) -> date:
    if months <= 0:
        raise ValuationAbstained("invalid_horizon")
    absolute_month = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute_month, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def evaluate_validity(
    *,
    basis_date: date,
    horizon_months: int,
    saved_at: datetime,
    evaluation_time: datetime,
    next_report_time: datetime | None = None,
    material_event_time: datetime | None = None,
) -> ValuationValidity:
    if horizon_months not in {6, 12, 24}:
        raise ValuationAbstained("invalid_horizon")
    if saved_at.tzinfo is None or evaluation_time.tzinfo is None:
        raise ValuationAbstained("ambiguous_timezone")
    candidates = (
        ("saved_plus_90_days", saved_at + timedelta(days=90)),
        ("next_report", next_report_time),
        ("material_event", material_event_time),
    )
    available = tuple((name, instant) for name, instant in candidates if instant is not None)
    if any(instant.tzinfo is None for _, instant in available):
        raise ValuationAbstained("ambiguous_timezone")
    expires_at = min(instant for _, instant in available)
    causes = tuple(name for name, instant in available if instant == expires_at)
    if evaluation_time >= expires_at:
        raise ValuationAbstained("forecast_expired")
    return ValuationValidity(
        target_date=add_calendar_months_clamped(basis_date, horizon_months),
        expires_at=expires_at,
        expiry_causes=causes,
    )


def annualized_net_return(
    *,
    forecast: Decimal,
    multiple: Decimal,
    quantity: Decimal,
    buy_price: Decimal,
    cash_dividend: Decimal,
    buy_rate: Decimal,
    minimum_buy_fee: Decimal,
    sell_rate: Decimal,
    minimum_sell_fee: Decimal,
    tax_rate: Decimal,
    holding_days: int,
) -> ValuationReturn:
    if holding_days <= 0:
        raise ValuationAbstained("nonpositive_holding_days")
    forecast = _finite(forecast, "invalid_forecast", positive=True)
    multiple = _finite(multiple, "invalid_multiple", positive=True)
    quantity = _finite(quantity, "invalid_quantity", positive=True)
    buy_price = _finite(buy_price, "invalid_buy_price", positive=True)
    for value, code in (
        (cash_dividend, "invalid_dividend"),
        (buy_rate, "invalid_buy_rate"),
        (minimum_buy_fee, "invalid_buy_fee"),
        (sell_rate, "invalid_sell_rate"),
        (minimum_sell_fee, "invalid_sell_fee"),
        (tax_rate, "invalid_tax_rate"),
    ):
        _finite(value, code)
        if value < 0:
            raise ValuationAbstained(code)
    with localcontext() as context:
        context.prec = 28
        target_price = forecast * multiple
        buy_notional = buy_price * quantity
        buy_fee = max(minimum_buy_fee, buy_notional * buy_rate)
        purchase_outflow = buy_notional + buy_fee
        sell_notional = target_price * quantity
        sell_fee = max(minimum_sell_fee, sell_notional * sell_rate)
        terminal_inflow = sell_notional - sell_fee - sell_notional * tax_rate + cash_dividend
        if purchase_outflow <= 0 or terminal_inflow <= 0:
            raise ValuationAbstained("nonpositive_cash_flow")
        exponent = Decimal(365) / Decimal(holding_days)
        annualized = (terminal_inflow / purchase_outflow) ** exponent - Decimal(1)
    return ValuationReturn(
        target_price=target_price,
        purchase_outflow=purchase_outflow,
        terminal_inflow=terminal_inflow,
        annualized_return=annualized,
        tax_disclaimer="Taiwan securities transaction tax is included from the bound Cost Profile.",
    )
