from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, localcontext
from fractions import Fraction

from thesis_trace.modules.portfolio.contracts import (
    CostProfileSnapshot,
    DcaSelection,
    ExposureSnapshot,
    HoldingSnapshot,
    PortfolioSnapshot,
)


SECURITY_CAP = Decimal("0.10")
CLASSIFICATION_CAP = Decimal("0.30")
_DCA_CANDIDATES = (Decimal("1.5"), Decimal("1"), Decimal("0.5"), Decimal("0"))


def _valid_decimal(value: Decimal, *, positive: bool = False) -> bool:
    return (
        isinstance(value, Decimal) and value.is_finite() and (not positive or value > 0)
    )


def _exposure_totals(portfolio: PortfolioSnapshot):
    if (
        portfolio.version < 1
        or not _valid_decimal(portfolio.cash)
        or portfolio.cash < 0
    ):
        raise ValueError("incomplete_portfolio_snapshot")
    security_values: dict[str, Fraction] = defaultdict(Fraction)
    industry_values: dict[str, Fraction] = defaultdict(Fraction)
    theme_values: dict[str, Fraction] = defaultdict(Fraction)
    for holding in portfolio.holdings:
        if (
            not holding.bucket_id
            or not holding.security_id
            or not holding.official_industry
            or not _valid_decimal(holding.quantity)
            or holding.quantity < 0
            or not _valid_decimal(holding.official_close, positive=True)
            or not holding.price_source
            or not holding.industry_source
            or holding.classification_effective_at.tzinfo is None
            or holding.theme_snapshot_version < 1
            or not holding.theme_source
            or holding.theme_effective_at.tzinfo is None
        ):
            raise ValueError("incomplete_portfolio_snapshot")
        value = Fraction(holding.quantity) * Fraction(holding.official_close)
        security_values[holding.security_id] += value
        industry_values[holding.official_industry] += value
        for theme in tuple(dict.fromkeys(holding.themes)):
            if not theme:
                raise ValueError("incomplete_portfolio_snapshot")
            theme_values[theme] += value
    nav = Fraction(portfolio.cash) + sum(security_values.values(), Fraction(0))
    if nav <= 0:
        raise ValueError("nonpositive_nav")
    return nav, security_values, industry_values, theme_values


def _cap_reasons(nav, security_values, industry_values, theme_values):
    return tuple(
        [
            f"security_cap_exceeded:{key}"
            for key, value in sorted(security_values.items())
            if value > Fraction(SECURITY_CAP) * nav
        ]
        + [
            f"industry_cap_exceeded:{key}"
            for key, value in sorted(industry_values.items())
            if value > Fraction(CLASSIFICATION_CAP) * nav
        ]
        + [
            f"theme_cap_exceeded:{key}"
            for key, value in sorted(theme_values.items())
            if value > Fraction(CLASSIFICATION_CAP) * nav
        ]
    )


def _decimal_value(value: Fraction) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        return Decimal(value.numerator) / Decimal(value.denominator)


def _exposure_result(
    nav, security_values, industry_values, theme_values
) -> ExposureSnapshot:
    reasons = _cap_reasons(nav, security_values, industry_values, theme_values)
    return ExposureSnapshot(
        _decimal_value(nav),
        {
            key: _decimal_value(value / nav)
            for key, value in sorted(security_values.items())
        },
        {
            key: _decimal_value(value / nav)
            for key, value in sorted(industry_values.items())
        },
        {
            key: _decimal_value(value / nav)
            for key, value in sorted(theme_values.items())
        },
        not reasons,
        reasons,
    )


def aggregate_exposure(portfolio: PortfolioSnapshot) -> ExposureSnapshot:
    return _exposure_result(*_exposure_totals(portfolio))


def select_dca_multiplier(
    *,
    base_amount: Decimal,
    raw_ceiling: Decimal,
    portfolio: PortfolioSnapshot,
    security_id: str,
    official_close: Decimal,
    buy_price: Decimal,
    cost_profile: CostProfileSnapshot | None,
    official_industry: str,
    themes: tuple[str, ...],
    price_date: date,
    price_source: str,
    industry_source: str,
    classification_effective_at: datetime,
    theme_snapshot_version: int,
    theme_source: str,
    theme_effective_at: datetime,
) -> DcaSelection:
    if (
        not _valid_decimal(base_amount, positive=True)
        or not _valid_decimal(raw_ceiling)
        or not _valid_decimal(official_close, positive=True)
        or not _valid_decimal(buy_price, positive=True)
        or raw_ceiling not in _DCA_CANDIDATES
    ):
        return DcaSelection(Decimal(0), ("invalid_input",), _DCA_CANDIDATES)
    try:
        nav, securities, industries, theme_values = _exposure_totals(portfolio)
    except ValueError:
        return DcaSelection(Decimal(0), ("incomplete_snapshot",), _DCA_CANDIDATES)
    if _cap_reasons(nav, securities, industries, theme_values):
        return DcaSelection(Decimal(0), ("current_portfolio_breach",), _DCA_CANDIDATES)
    if (
        not isinstance(cost_profile, CostProfileSnapshot)
        or type(cost_profile.version) is not int
        or cost_profile.version < 1
        or cost_profile.effective_at.utcoffset() is None
        or any(
            not _valid_decimal(value) or value < 0
            for value in (
                cost_profile.buy_rate,
                cost_profile.minimum_buy_fee,
                cost_profile.sell_rate,
                cost_profile.minimum_sell_fee,
                cost_profile.tax_rate,
            )
        )
    ):
        return DcaSelection(Decimal(0), ("invalid_cost_profile",), _DCA_CANDIDATES)
    try:
        # Validate target provenance through the same snapshot seam before sizing.
        target = HoldingSnapshot(
            bucket_id="dca-preview",
            security_id=security_id,
            quantity=Decimal(1),
            official_close=official_close,
            official_industry=official_industry,
            themes=themes,
            price_date=price_date,
            price_source=price_source,
            industry_source=industry_source,
            classification_effective_at=classification_effective_at,
            theme_snapshot_version=theme_snapshot_version,
            theme_source=theme_source,
            theme_effective_at=theme_effective_at,
        )
        _exposure_totals(PortfolioSnapshot(1, Decimal(0), (target,)))
    except ValueError:
        return DcaSelection(Decimal(0), ("incomplete_snapshot",), _DCA_CANDIDATES)
    for multiplier in _DCA_CANDIDATES:
        if multiplier > raw_ceiling:
            continue
        if multiplier == 0:
            return DcaSelection(multiplier, ("risk_cap",), _DCA_CANDIDATES)
        notional = Fraction(base_amount) * Fraction(multiplier)
        fee = max(
            Fraction(cost_profile.minimum_buy_fee),
            notional * Fraction(cost_profile.buy_rate),
        )
        outflow = notional + fee
        if outflow > Fraction(portfolio.cash):
            continue
        added_value = notional / Fraction(buy_price) * Fraction(official_close)
        projected_nav = nav - outflow + added_value
        if projected_nav <= 0:
            continue
        projected_securities = securities.copy()
        projected_industries = industries.copy()
        projected_themes = theme_values.copy()
        projected_securities[security_id] += added_value
        projected_industries[official_industry] += added_value
        for theme in set(themes):
            projected_themes[theme] += added_value
        if not _cap_reasons(
            projected_nav, projected_securities, projected_industries, projected_themes
        ):
            return DcaSelection(
                multiplier,
                (),
                _DCA_CANDIDATES,
                post_exposure=_exposure_result(
                    projected_nav,
                    projected_securities,
                    projected_industries,
                    projected_themes,
                ),
                purchase_outflow=_decimal_value(outflow),
                acquired_quantity=_decimal_value(notional / Fraction(buy_price)),
            )
    return DcaSelection(Decimal(0), ("risk_cap",), _DCA_CANDIDATES)
