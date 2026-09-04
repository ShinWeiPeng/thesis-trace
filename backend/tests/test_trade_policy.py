from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from thesis_trace.modules.portfolio.contracts import CanonicalTrade, TradeAllocation, TradeSide
from thesis_trace.modules.portfolio.trades import (
    allocate_company_action,
    canonical_trade_fingerprint,
    parse_canonical_csv,
    validate_allocations,
)


NOW = datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc)


def trade() -> CanonicalTrade:
    return CanonicalTrade(
        source_kind="manual",
        source_row_id="row-1",
        broker_reference=None,
        security_id="2330",
        side=TradeSide.BUY,
        quantity=3,
        price=Decimal("1000"),
        fees=Decimal("20"),
        tax=Decimal("0"),
        executed_at=NOW,
    )


def test_trade_fingerprint_is_stable_and_allocations_must_conserve_quantity() -> None:
    subject = trade()
    assert canonical_trade_fingerprint(subject) == canonical_trade_fingerprint(subject)

    validate_allocations(subject, (TradeAllocation("core:a", 2), TradeAllocation("satellite:b", 1)))
    with pytest.raises(ValueError, match="allocation_quantity_mismatch"):
        validate_allocations(subject, (TradeAllocation("core:a", 2),))


def test_company_action_uses_largest_remainder_and_bucket_id_tie_break() -> None:
    result = allocate_company_action(
        pre_action_quantities={"bucket-c": 1, "bucket-a": 1, "bucket-b": 1},
        confirmed_post_action_shares=2,
        cash_in_lieu=Decimal("30"),
    )

    assert result.shares == {"bucket-a": 1, "bucket-b": 1, "bucket-c": 0}
    assert result.cash == {"bucket-a": Decimal("10"), "bucket-b": Decimal("10"), "bucket-c": Decimal("10")}
    assert result.remainder_order == ("bucket-a", "bucket-b", "bucket-c")


def test_sell_cannot_draw_from_another_bucket() -> None:
    sell = replace(trade(), side=TradeSide.SELL, quantity=2)
    with pytest.raises(ValueError, match="bucket_oversell"):
        validate_allocations(sell, (TradeAllocation("core:a", 2),), available_by_bucket={"core:a": 1, "core:b": 5})


def test_canonical_csv_parses_valid_rows_and_reports_duplicates_without_mutation() -> None:
    header = "source_row_id,broker_reference,security_id,side,quantity,price,fees,tax,executed_at\n"
    row = "row-1,,2330,buy,1,100,0,0,2026-08-29T04:00:00+00:00\n"
    preview = parse_canonical_csv(header + row + row)

    assert len(preview.trades) == 1
    assert preview.trades[0].source_kind == "csv"
    assert preview.issues == (type(preview.issues[0])(3, "duplicate_trade"),)


def test_canonical_csv_rejects_unknown_header_and_invalid_row() -> None:
    wrong = parse_canonical_csv("ticker,quantity\n2330,1\n")
    invalid = parse_canonical_csv(
        "source_row_id,broker_reference,security_id,side,quantity,price,fees,tax,executed_at\n"
        "row-1,,2330,buy,nope,100,0,0,2026-08-29T04:00:00+00:00\n"
    )
    assert wrong.issues[0].code == "invalid_header"
    assert invalid.issues[0].code == "invalid_row"
