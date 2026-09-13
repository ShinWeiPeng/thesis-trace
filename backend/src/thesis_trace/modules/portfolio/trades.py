from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from datetime import datetime
import csv
from hashlib import sha256
import io
import json

from thesis_trace.modules.portfolio.contracts import (
    CanonicalTrade,
    CanonicalCsvIssue,
    CanonicalCsvPreview,
    CompanyActionAllocation,
    TradeAllocation,
    TradeSide,
)


TRADE_POLICY_VERSION = "trade-normalization-v1"
CANONICAL_CSV_HEADERS = (
    "source_row_id", "broker_reference", "security_id", "side", "quantity",
    "price", "fees", "tax", "executed_at",
)


def parse_canonical_csv(content: str) -> CanonicalCsvPreview:
    """Parse only the documented canonical schema; broker-specific formats remain behind the Port."""

    if not isinstance(content, str) or not content.strip():
        return CanonicalCsvPreview((), (CanonicalCsvIssue(1, "empty_csv"),))
    try:
        reader = csv.DictReader(io.StringIO(content, newline=""))
        if tuple(reader.fieldnames or ()) != CANONICAL_CSV_HEADERS:
            return CanonicalCsvPreview((), (CanonicalCsvIssue(1, "invalid_header"),))
        trades: list[CanonicalTrade] = []
        issues: list[CanonicalCsvIssue] = []
        fingerprints: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            try:
                trade = CanonicalTrade(
                    source_kind="csv",
                    source_row_id=str(row["source_row_id"]),
                    broker_reference=str(row["broker_reference"]).strip() or None,
                    security_id=str(row["security_id"]),
                    side=TradeSide(str(row["side"])),
                    quantity=int(str(row["quantity"])),
                    price=Decimal(str(row["price"])),
                    fees=Decimal(str(row["fees"])),
                    tax=Decimal(str(row["tax"])),
                    executed_at=datetime.fromisoformat(str(row["executed_at"])),
                )
                fingerprint = canonical_trade_fingerprint(trade)
                if fingerprint in fingerprints:
                    raise ValueError("duplicate_trade")
                fingerprints.add(fingerprint)
                trades.append(trade)
            except (KeyError, TypeError, ValueError, ArithmeticError) as error:
                code = str(error) if str(error) in {"duplicate_trade", "invalid_trade"} else "invalid_row"
                issues.append(CanonicalCsvIssue(row_number, code))
        return CanonicalCsvPreview(tuple(trades), tuple(issues))
    except csv.Error:
        return CanonicalCsvPreview((), (CanonicalCsvIssue(1, "invalid_csv"),))


def canonical_trade_fingerprint(trade: CanonicalTrade) -> str:
    if (
        not trade.source_kind
        or not trade.source_row_id
        or not trade.security_id
        or trade.quantity <= 0
        or not trade.price.is_finite()
        or trade.price <= 0
        or not trade.fees.is_finite()
        or trade.fees < 0
        or not trade.tax.is_finite()
        or trade.tax < 0
        or trade.executed_at.tzinfo is None
    ):
        raise ValueError("invalid_trade")
    identity = trade.broker_reference or trade.source_row_id
    payload = (
        TRADE_POLICY_VERSION,
        trade.source_kind,
        identity,
        trade.side.value,
        trade.security_id,
        trade.executed_at.isoformat(),
        str(trade.quantity),
        str(trade.price),
    )
    return sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def validate_allocations(
    trade: CanonicalTrade,
    allocations: tuple[TradeAllocation, ...],
    *,
    available_by_bucket: dict[str, int] | None = None,
    allowed_bucket_ids: frozenset[str] | None = None,
) -> None:
    canonical_trade_fingerprint(trade)
    if not allocations or any(not item.bucket_id or item.quantity <= 0 for item in allocations):
        raise ValueError("invalid_allocation")
    if len({item.bucket_id for item in allocations}) != len(allocations):
        raise ValueError("duplicate_allocation_bucket")
    if allowed_bucket_ids is not None and any(item.bucket_id not in allowed_bucket_ids for item in allocations):
        raise ValueError("inactive_allocation_bucket")
    if sum(item.quantity for item in allocations) != trade.quantity:
        raise ValueError("allocation_quantity_mismatch")
    if trade.side is TradeSide.SELL:
        available = available_by_bucket or {}
        if any(item.quantity > available.get(item.bucket_id, 0) for item in allocations):
            raise ValueError("bucket_oversell")


def allocate_company_action(
    *,
    pre_action_quantities: dict[str, int],
    confirmed_post_action_shares: int,
    cash_in_lieu: Decimal,
) -> CompanyActionAllocation:
    if confirmed_post_action_shares < 0 or not cash_in_lieu.is_finite() or cash_in_lieu < 0:
        raise ValueError("invalid_company_action")
    if not pre_action_quantities or any(not key or value < 0 for key, value in pre_action_quantities.items()):
        raise ValueError("invalid_company_action")
    total = sum(pre_action_quantities.values())
    if total <= 0:
        raise ValueError("zero_pre_action_quantity")
    quotas = {
        key: Decimal(confirmed_post_action_shares) * Decimal(quantity) / Decimal(total)
        for key, quantity in pre_action_quantities.items()
    }
    shares = {key: int(quota.to_integral_value(rounding=ROUND_FLOOR)) for key, quota in quotas.items()}
    remainder_order = tuple(sorted(quotas, key=lambda key: (-(quotas[key] - Decimal(shares[key])), key)))
    remaining = confirmed_post_action_shares - sum(shares.values())
    for key in remainder_order[:remaining]:
        shares[key] += 1
    cash = {
        key: cash_in_lieu * Decimal(quantity) / Decimal(total)
        for key, quantity in sorted(pre_action_quantities.items())
    }
    return CompanyActionAllocation(dict(sorted(shares.items())), cash, remainder_order)
