from dataclasses import replace
from decimal import Decimal
from datetime import timedelta

import pytest

from thesis_trace.modules.thesis.contracts import PublishValuationCommand
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.modules.thesis.valuation import final_size_valuation_return
from test_thesis_domain import ACTOR, MemoryThesisStore, NOW, create
from test_valuation_domain import command


def published_valuation():
    service = ThesisService(MemoryThesisStore(), id_factory=lambda: "thesis-1")
    record = create(service)
    draft_command = command(record.version)
    draft_command = replace(
        draft_command,
        forecast=Decimal("108"),
        company_history_samples=tuple(
            replace(sample, multiple=Decimal(1))
            for sample in draft_command.company_history_samples
        ),
    )
    saved = service.save_valuation_draft(draft_command, now=NOW)
    return service.publish_valuation(
        PublishValuationCommand(
            ACTOR,
            saved.thesis_id,
            saved.version,
            1,
            "confirmed",
            "Publish",
            "publish-1",
        ),
        now=NOW,
    ).valuation_snapshots[0]


def calculate(snapshot, **changes):
    values = dict(
        multiplier=Decimal("0.5"),
        cost_profile_version=1,
        buy_rate=Decimal(0),
        minimum_buy_fee=Decimal(20),
        sell_rate=Decimal(0),
        minimum_sell_fee=Decimal(20),
        tax_rate=Decimal("0.003"),
        now=NOW,
    )
    values.update(changes)
    return final_size_valuation_return(snapshot, **values)


def test_clipped_size_recalculates_minimum_fees_and_dividend_at_original_basis():
    snapshot = published_valuation()
    result = calculate(snapshot)
    # Independent worked vector: buy 500+20; sell 540-20-1.62+25.
    assert result.purchase_outflow == Decimal("520")
    assert result.terminal_inflow == Decimal("543.38")
    assert result.annualized_return == Decimal("0.044961538461538461538461538")
    assert snapshot.draft.result.annualized_return > Decimal("0.05")
    assert result.annualized_return < Decimal("0.05")


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"multiplier": Decimal(0)}, "invalid_multiplier"),
        ({"multiplier": Decimal("NaN")}, "invalid_multiplier"),
        ({"multiplier": True}, "invalid_multiplier"),
        ({"cost_profile_version": 2}, "cost_profile_version_conflict"),
        ({"cost_profile_version": True}, "cost_profile_version_conflict"),
    ],
)
def test_final_size_rejects_invalid_size_or_changed_cost(changes, code):
    with pytest.raises(ValueError, match=code):
        calculate(published_valuation(), **changes)


def test_final_size_never_guesses_legacy_basis_or_extends_validity():
    snapshot = published_valuation()
    legacy = replace(
        snapshot, draft=replace(snapshot.draft, basis_date=None, horizon_months=None)
    )
    with pytest.raises(ValueError, match="valuation_basis_unavailable"):
        calculate(legacy)
    with pytest.raises(ValueError, match="forecast_expired"):
        calculate(snapshot, now=snapshot.draft.validity.expires_at)
    assert calculate(snapshot, now=NOW + timedelta(days=1)) == calculate(snapshot)
