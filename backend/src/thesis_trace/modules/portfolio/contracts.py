from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class OfficialSecuritySnapshot:
    security_id: str
    official_close: Decimal
    price_date: date
    price_source: str
    official_industry: str
    industry_source: str
    classification_effective_at: datetime
    themes: tuple[str, ...]
    theme_snapshot_version: int
    theme_source: str
    theme_effective_at: datetime
    policy_version: str = "official-security-snapshot-v1"


@dataclass(frozen=True, slots=True)
class HoldingSnapshot:
    bucket_id: str
    security_id: str
    quantity: Decimal
    official_close: Decimal
    official_industry: str
    themes: tuple[str, ...]
    price_date: date
    price_source: str
    industry_source: str
    classification_effective_at: datetime
    theme_snapshot_version: int
    theme_source: str
    theme_effective_at: datetime


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    version: int
    cash: Decimal
    holdings: tuple[HoldingSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ExposureSnapshot:
    nav: Decimal
    security_exposure: dict[str, Decimal]
    industry_exposure: dict[str, Decimal]
    theme_exposure: dict[str, Decimal]
    feasible: bool
    reasons: tuple[str, ...]
    policy_version: str = "exposure-policy-v1"


@dataclass(frozen=True, slots=True)
class DcaSelection:
    multiplier: Decimal
    reasons: tuple[str, ...]
    evaluated: tuple[Decimal, ...]
    policy_version: str = "dca-selection-v1"
    post_exposure: ExposureSnapshot | None = None
    purchase_outflow: Decimal | None = None
    acquired_quantity: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CanonicalTrade:
    source_kind: str
    source_row_id: str
    broker_reference: str | None
    security_id: str
    side: TradeSide
    quantity: int
    price: Decimal
    fees: Decimal
    tax: Decimal
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class CanonicalCsvIssue:
    row_number: int
    code: str


@dataclass(frozen=True, slots=True)
class CanonicalCsvPreview:
    trades: tuple[CanonicalTrade, ...]
    issues: tuple[CanonicalCsvIssue, ...]
    policy_version: str = "canonical-trade-csv-v1"


@dataclass(frozen=True, slots=True)
class TradeAllocation:
    bucket_id: str
    quantity: int


@dataclass(frozen=True, slots=True)
class CompanyActionAllocation:
    shares: dict[str, int]
    cash: dict[str, Decimal]
    remainder_order: tuple[str, ...]
    policy_version: str = "largest-remainder-bucket-v1"


@dataclass(frozen=True, slots=True)
class PortfolioActorContext:
    actor_id: str
    may_manage_portfolio: bool


@dataclass(frozen=True, slots=True)
class CostProfileSnapshot:
    version: int
    buy_rate: Decimal
    minimum_buy_fee: Decimal
    sell_rate: Decimal
    minimum_sell_fee: Decimal
    tax_rate: Decimal
    effective_at: datetime
    policy_version: str = "cost-profile-v1"


@dataclass(frozen=True, slots=True)
class PortfolioRecommendationSnapshot:
    snapshot_id: str
    portfolio: PortfolioSnapshot
    cost: CostProfileSnapshot
    exposure: ExposureSnapshot
    sizing: DcaSelection
    created_at: datetime
    target: OfficialSecuritySnapshot
    base_amount: Decimal
    buy_price: Decimal
    cash_as_of: datetime


@dataclass(frozen=True, slots=True)
class TradeRecord:
    trade_id: str
    version: int
    fingerprint: str
    trade: CanonicalTrade
    allocations: tuple[TradeAllocation, ...]
    confirmed_at: datetime
    reason: str
    policy_version: str = "trade-normalization-v1"


@dataclass(frozen=True, slots=True)
class TradeCorrectionRecord:
    correction_id: str
    version: int
    original_trade_id: str
    reversed_allocations: tuple[TradeAllocation, ...]
    confirmed_at: datetime
    reason: str
    policy_version: str = "trade-correction-v1"


@dataclass(frozen=True, slots=True)
class CompanyActionRecord:
    action_id: str
    version: int
    security_id: str
    action_kind: str
    pre_action_shares: int
    confirmed_post_action_shares: int
    cash_in_lieu: Decimal
    allocation: CompanyActionAllocation
    confirmed_at: datetime
    reason: str
    policy_version: str = "company-action-v1"


@dataclass(frozen=True, slots=True)
class PortfolioRecord:
    owner_user_id: str
    version: int
    cost_profile: CostProfileSnapshot | None
    cash: Decimal
    cash_as_of: datetime | None
    holdings: tuple[HoldingSnapshot, ...]
    trades: tuple[TradeRecord, ...]
    updated_at: datetime
    corrections: tuple[TradeCorrectionRecord, ...] = ()
    company_actions: tuple[CompanyActionRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class TradePreview:
    expected_portfolio_version: int
    fingerprint: str
    preview_digest: str
    trade: CanonicalTrade
    allocations: tuple[TradeAllocation, ...]
    post_portfolio: PortfolioSnapshot
    exposure: ExposureSnapshot
    official_security: OfficialSecuritySnapshot
    policy_version: str = "trade-preview-v1"


@dataclass(frozen=True, slots=True)
class SaveCostProfileCommand:
    actor: PortfolioActorContext
    expected_version: int
    buy_rate: Decimal
    minimum_buy_fee: Decimal
    sell_rate: Decimal
    minimum_sell_fee: Decimal
    tax_rate: Decimal
    effective_at: datetime
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SaveInvestableCashCommand:
    actor: PortfolioActorContext
    expected_version: int
    cash: Decimal
    as_of: datetime
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class PreviewTradeCommand:
    actor: PortfolioActorContext
    expected_version: int
    trade: CanonicalTrade
    allocations: tuple[TradeAllocation, ...]
    available_by_bucket: dict[str, int]
    allowed_bucket_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class ConfirmTradeCommand:
    actor: PortfolioActorContext
    preview: TradePreview
    confirmation_id: str
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class TradeCorrectionPreview:
    expected_portfolio_version: int
    original_trade_id: str
    preview_digest: str
    post_portfolio: PortfolioSnapshot
    exposure: ExposureSnapshot
    policy_version: str = "trade-correction-preview-v1"


@dataclass(frozen=True, slots=True)
class ConfirmTradeCorrectionCommand:
    actor: PortfolioActorContext
    preview: TradeCorrectionPreview
    confirmation_id: str
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CompanyActionPreview:
    expected_portfolio_version: int
    security_id: str
    action_kind: str
    confirmed_post_action_shares: int
    cash_in_lieu: Decimal
    allocation: CompanyActionAllocation
    preview_digest: str
    post_portfolio: PortfolioSnapshot
    exposure: ExposureSnapshot
    policy_version: str = "company-action-preview-v1"


@dataclass(frozen=True, slots=True)
class ConfirmCompanyActionCommand:
    actor: PortfolioActorContext
    preview: CompanyActionPreview
    confirmation_id: str
    reason: str
    idempotency_key: str
