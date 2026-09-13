from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from thesis_trace.modules.thesis.contracts import (
    PublishValuationCommand,
    SaveValuationDraftCommand,
    ThesisResearchReference,
    ValuationMethod,
    ValuationSample,
)
from thesis_trace.modules.thesis.service import ThesisService
from test_thesis_domain import ACTOR, MemoryThesisStore, NOW, create


def command(version: int, draft_version: int = 0) -> SaveValuationDraftCommand:
    source = ThesisResearchReference("evidence", "history-source", 1, "company-1")
    samples = tuple(
        ValuationSample(
            f"month-{index + 1}", "company-1", date(2023 + index // 12, index % 12 + 1, 1),
            Decimal(index + 1), Decimal("1"), source,
        ) for index in range(36)
    )
    return SaveValuationDraftCommand(
        actor=ACTOR, thesis_id="thesis-1", expected_thesis_version=version,
        expected_draft_version=draft_version, method=ValuationMethod.PE,
        benchmark_source="company_history", benchmark_variant="p75",
        peer_company_ids=(), samples=(), basis_date=date(2026, 8, 29), horizon_months=12,
        forecast=Decimal("12"), quantity=Decimal("10"), buy_price=Decimal("100"),
        cash_dividend=Decimal("50"), buy_rate=Decimal("0"), minimum_buy_fee=Decimal("20"),
        sell_rate=Decimal("0"), minimum_sell_fee=Decimal("20"), tax_rate=Decimal("0.003"),
        cost_profile_version=1, reason="Save valuation", idempotency_key="valuation-draft-1",
        company_history_samples=samples, source_selection_reason="Use reproducible company history",
        forecast_source=source, forecast_confirmed_at=NOW, method_confirmed=True,
    )


def test_valuation_draft_and_confirmed_snapshot_are_versioned_and_immutable() -> None:
    service = ThesisService(MemoryThesisStore(), id_factory=lambda: "thesis-1")
    thesis = create(service)
    drafted = service.save_valuation_draft(command(thesis.version), now=NOW)

    assert drafted.valuation_draft is not None
    assert drafted.valuation_draft.distribution.p75 == Decimal("27.25")
    assert drafted.valuation_draft.result.target_price == Decimal("327.00")
    with pytest.raises(PermissionError, match="confirmation_required"):
        service.publish_valuation(PublishValuationCommand(
            ACTOR, drafted.thesis_id, drafted.version, 1, "", "Publish", "publish-1",
        ), now=NOW)

    published = service.publish_valuation(PublishValuationCommand(
        ACTOR, drafted.thesis_id, drafted.version, 1, "challenge-1", "Publish", "publish-1",
    ), now=NOW)
    assert published.version == 3
    assert published.valuation_snapshots[0].draft == drafted.valuation_draft


def test_valuation_draft_rejects_stale_versions() -> None:
    service = ThesisService(MemoryThesisStore(), id_factory=lambda: "thesis-1")
    create(service)
    service.save_valuation_draft(command(1), now=NOW)
    with pytest.raises(ValueError, match="version_conflict"):
        service.save_valuation_draft(command(1), now=NOW)


def test_owner_can_explicitly_abstain_without_target_price() -> None:
    from dataclasses import replace

    service = ThesisService(MemoryThesisStore(), id_factory=lambda: "thesis-1")
    thesis = create(service)
    abstain = replace(
        command(thesis.version), method=ValuationMethod.ABSTAIN, benchmark_source="abstain",
        company_history_samples=(), forecast_source=None, forecast_confirmed_at=None,
        cost_profile_version=0, source_selection_reason="No applicable valuation method",
    )
    drafted = service.save_valuation_draft(abstain, now=NOW)
    assert drafted.valuation_draft is not None
    assert drafted.valuation_draft.method is ValuationMethod.ABSTAIN
    assert drafted.valuation_draft.distribution is None
    assert drafted.valuation_draft.result is None
