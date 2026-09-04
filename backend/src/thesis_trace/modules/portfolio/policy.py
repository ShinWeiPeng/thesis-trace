from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from thesis_trace.modules.portfolio.contracts import (
    DcaSelection,
    ExposureSnapshot,
    HoldingSnapshot,
    PortfolioSnapshot,
)


SECURITY_CAP = Decimal("0.10")
CLASSIFICATION_CAP = Decimal("0.30")
_DCA_CANDIDATES = (Decimal("1.5"), Decimal("1"), Decimal("0.5"), Decimal("0"))


def _valid_decimal(value: Decimal, *, positive: bool = False) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and (not positive or value > 0)


def aggregate_exposure(portfolio: PortfolioSnapshot) -> ExposureSnapshot:
    if portfolio.version < 1 or not _valid_decimal(portfolio.cash) or portfolio.cash < 0:
        raise ValueError("incomplete_portfolio_snapshot")
    security_values: dict[str, Decimal] = defaultdict(Decimal)
    industry_values: dict[str, Decimal] = defaultdict(Decimal)
    theme_values: dict[str, Decimal] = defaultdict(Decimal)
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
        value = holding.quantity * holding.official_close
        security_values[holding.security_id] += value
        industry_values[holding.official_industry] += value
        for theme in tuple(dict.fromkeys(holding.themes)):
            if not theme:
                raise ValueError("incomplete_portfolio_snapshot")
            theme_values[theme] += value
    nav = portfolio.cash + sum(security_values.values(), Decimal(0))
    if nav <= 0:
        raise ValueError("nonpositive_nav")
    security = {key: value / nav for key, value in sorted(security_values.items())}
    industries = {key: value / nav for key, value in sorted(industry_values.items())}
    themes = {key: value / nav for key, value in sorted(theme_values.items())}
    reasons = tuple(
        [f"security_cap_exceeded:{key}" for key, value in security.items() if value > SECURITY_CAP]
        + [f"industry_cap_exceeded:{key}" for key, value in industries.items() if value > CLASSIFICATION_CAP]
        + [f"theme_cap_exceeded:{key}" for key, value in themes.items() if value > CLASSIFICATION_CAP]
    )
    return ExposureSnapshot(nav, security, industries, themes, not reasons, reasons)


def select_dca_multiplier(
    *,
    base_amount: Decimal,
    raw_ceiling: Decimal,
    portfolio: PortfolioSnapshot,
    security_id: str,
    official_close: Decimal,
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
    if not _valid_decimal(base_amount, positive=True) or not _valid_decimal(raw_ceiling) or not _valid_decimal(official_close, positive=True):
        return DcaSelection(Decimal(0), ("invalid_input",), _DCA_CANDIDATES)
    try:
        current = aggregate_exposure(portfolio)
    except ValueError:
        return DcaSelection(Decimal(0), ("incomplete_snapshot",), _DCA_CANDIDATES)
    if not current.feasible:
        return DcaSelection(Decimal(0), ("current_portfolio_breach",), _DCA_CANDIDATES)
    for multiplier in _DCA_CANDIDATES:
        if multiplier > raw_ceiling:
            continue
        if multiplier == 0:
            return DcaSelection(multiplier, ("risk_cap",), _DCA_CANDIDATES)
        outflow = base_amount * multiplier
        if outflow > portfolio.cash:
            continue
        added = HoldingSnapshot(
            bucket_id="dca-preview",
            security_id=security_id,
            quantity=outflow / official_close,
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
        projected = PortfolioSnapshot(portfolio.version, portfolio.cash - outflow, portfolio.holdings + (added,))
        try:
            if aggregate_exposure(projected).feasible:
                return DcaSelection(multiplier, (), _DCA_CANDIDATES)
        except ValueError:
            pass
    return DcaSelection(Decimal(0), ("risk_cap",), _DCA_CANDIDATES)
