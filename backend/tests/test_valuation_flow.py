from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from thesis_trace.application.contracts import ValuationFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.portfolio.contracts import (
    PortfolioActorContext, SaveCostProfileCommand, SaveInvestableCashCommand,
)
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.modules.research.evidence_collection.contracts import ValuationSourceFact
from thesis_trace.modules.thesis.contracts import PublishValuationCommand, ThesisActorContext
from thesis_trace.modules.thesis.service import ThesisService
from test_portfolio_domain import MemoryPortfolioStore
from test_thesis_domain import MemoryThesisStore, NOW, create


OWNER = AuthenticatedActor("owner-1", Role.OWNER, 1)


class Research:
    company = SimpleNamespace(company_id="company-1", ticker="2330", name="Demo", version=1)
    evidence = SimpleNamespace(
        evidence_id="history-source", version=1, company_id="company-1",
        status=SimpleNamespace(value="succeeded"),
    )
    def get_company(self, company_id): return self.company if company_id == "company-1" else None
    def get_record(self, evidence_id): return self.evidence if evidence_id == "history-source" else None
    def get_source_snapshot_id(self, evidence_id): return "snapshot-1" if evidence_id == "history-source" else None
    def get_valuation_fact(self, evidence_id, fact_id):
        if evidence_id != "history-source": return None
        if fact_id == "pe-forecast":
            return ValuationSourceFact(
                fact_id, evidence_id, 1, "snapshot-1", "company-1", "pe", "forecast",
                date(2026, 8, 29), Decimal("12"), None, NOW, NOW + timedelta(days=30), None,
                target_date=date(2027, 8, 29),
            )
        if fact_id.startswith("pe-history-"):
            index = int(fact_id.removeprefix("pe-history-")) - 1
            return ValuationSourceFact(
                fact_id, evidence_id, 1, "snapshot-1", "company-1", "pe", "history_multiple",
                date(2023 + index // 12, index % 12 + 1, 1), Decimal(index + 1), Decimal("1"),
            )
        return None


class Confirmations:
    def preview(self, *_args): return "valuation-token", SimpleNamespace(expires_at=NOW)


class Publications:
    def __init__(self, service): self.service = service
    def execute(self, *, actor, thesis_id, expected_thesis_version, expected_draft_version,
                reason, idempotency_key, challenge_token, binding_payload, now):
        assert challenge_token == "valuation-token"
        assert binding_payload["cost_profile_version"] == 1
        assert len(binding_payload["research_sources"]) == 37
        return self.service.publish_valuation(PublishValuationCommand(
            ThesisActorContext(actor.actor_id, True), thesis_id, expected_thesis_version,
            expected_draft_version, "challenge-1", reason, idempotency_key,
        ), now=now)


def subject() -> tuple[ValuationFlow, object, PortfolioService]:
    thesis = ThesisService(MemoryThesisStore(), id_factory=lambda: "thesis-1")
    created = create(thesis)
    portfolio = PortfolioService(MemoryPortfolioStore())
    profile = portfolio.save_cost_profile(SaveCostProfileCommand(
        PortfolioActorContext("owner-1", True), 0, Decimal("0"), Decimal("20"), Decimal("0"),
        Decimal("20"), Decimal("0.003"), NOW, "Costs", "cost-1",
    ), now=NOW)
    portfolio.save_investable_cash(SaveInvestableCashCommand(
        PortfolioActorContext("owner-1", True), profile.version, Decimal("100000"), NOW, "Cash", "cash-1",
    ), now=NOW)
    return ValuationFlow(
        thesis, portfolio, Research(), confirmations=Confirmations(),
        confirmed_publications=Publications(thesis), clock=lambda: NOW,
    ), created, portfolio


def valuation_body() -> dict[str, object]:
    return {
        "expected_thesis_version": 1, "expected_draft_version": 0, "method": "pe",
        "benchmark_source": "company_history", "benchmark_variant": "p75",
        "company_history_samples": [{
            "source": {"record_id": "history-source", "version": 1, "fact_id": f"pe-history-{value}"},
        } for value in range(1, 37)],
        "peer_members": [], "source_selection_reason": "Company history is reproducible",
        "basis_date": date(2026, 8, 29).isoformat(), "horizon_months": 12,
        "quantity": "10", "buy_price": "100", "cash_dividend": "50",
        "forecast_source": {"record_id": "history-source", "version": 1, "fact_id": "pe-forecast"},
        "reason": "Save", "idempotency_key": "valuation-1",
    }


def test_flow_binds_cost_profile_and_requires_two_step_publication() -> None:
    flow, thesis, _portfolio = subject()
    drafted = flow.save(OWNER, thesis.thesis_id, valuation_body())
    preview = flow.preview_publication(OWNER, thesis.thesis_id, {
        "expected_thesis_version": 2, "expected_draft_version": 1,
    })
    published = flow.publish(OWNER, thesis.thesis_id, {
        "expected_thesis_version": 2, "expected_draft_version": 1,
        "reason": "Publish", "idempotency_key": "publish-1",
        "challenge_token": preview["challenge_token"],
    })
    assert drafted["valuation_draft"]["cost_profile_version"] == 1
    assert published["valuation_snapshots"][0]["draft"]["result"]["target_price"] == "327.00"


def test_publication_requires_a_new_preview_after_cost_profile_changes() -> None:
    flow, thesis, portfolio = subject()
    flow.save(OWNER, thesis.thesis_id, valuation_body())
    preview = flow.preview_publication(OWNER, thesis.thesis_id, {
        "expected_thesis_version": 2, "expected_draft_version": 1,
    })
    current = portfolio.get(PortfolioActorContext("owner-1", True))
    portfolio.save_cost_profile(SaveCostProfileCommand(
        PortfolioActorContext("owner-1", True), current.version, Decimal("0.001"), Decimal("20"),
        Decimal("0.001"), Decimal("20"), Decimal("0.003"), NOW, "New costs", "cost-2",
    ), now=NOW)
    with pytest.raises(ValueError, match="cost_profile_version_conflict"):
        flow.publish(OWNER, thesis.thesis_id, {
            "expected_thesis_version": 2, "expected_draft_version": 1,
            "reason": "Publish", "idempotency_key": "publish-stale-cost",
            "challenge_token": preview["challenge_token"],
        })


def test_forecast_fact_must_match_the_selected_target_date() -> None:
    flow, thesis, _portfolio = subject()
    body = valuation_body()
    body["horizon_months"] = 6
    with pytest.raises(ValueError, match="forecast_target_date_mismatch"):
        flow.save(OWNER, thesis.thesis_id, body)


def test_learner_cannot_read_or_publish_owner_valuation() -> None:
    flow, thesis, _portfolio = subject()
    with pytest.raises(PermissionError, match="resource_unavailable"):
        flow.preview_publication(AuthenticatedActor("learner-1", Role.LEARNER, 1), thesis.thesis_id, {
            "expected_thesis_version": 1, "expected_draft_version": 1,
        })
