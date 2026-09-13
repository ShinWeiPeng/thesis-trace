from dataclasses import replace
from decimal import Decimal, localcontext
import pytest

from thesis_trace.application.contracts import RecommendationFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.modules.thesis.contracts import ThesisStatus
from thesis_trace.platform.runtime import minimum_return_configuration
from test_portfolio_domain import (
    ACTOR as PORTFOLIO_ACTOR,
    NOW,
    MemoryPortfolioStore,
    configured,
)
from test_thesis_domain import MemoryThesisStore, create
from test_recommendation_final_size import published_valuation
from test_recommendation_publication import inputs, evidence
from test_valuation_flow import Research


def setup_flow(minimum_return=Decimal("0.05"), *, cash=Decimal(10000), quantity=None):
    thesis_store = MemoryThesisStore()
    thesis = ThesisService(thesis_store, id_factory=lambda: "thesis-1")
    current = create(thesis)
    snapshot = published_valuation()
    if quantity is not None:
        snapshot = replace(snapshot, draft=replace(snapshot.draft, quantity=quantity))
    thesis_store.records[current.thesis_id] = replace(
        current, status=ThesisStatus.ACTIVE, valuation_snapshots=(snapshot,)
    )
    portfolio_store = MemoryPortfolioStore()
    portfolio = PortfolioService(portfolio_store)
    current_portfolio = configured(portfolio)
    portfolio_store.record = replace(
        current_portfolio,
        cash=cash,
        cost_profile=replace(
            current_portfolio.cost_profile,
            minimum_buy_fee=Decimal(20),
            minimum_sell_fee=Decimal(20),
            tax_rate=Decimal("0.003"),
        ),
    )
    frozen = inputs()
    frozen = replace(
        frozen,
        company_id="company-1",
        valuation_id=snapshot.valuation_id,
        admitted_at=NOW,
        sources=tuple(
            replace(source, published_at=NOW, retrieved_at=NOW)
            for source in frozen.sources
        ),
    )
    flow = RecommendationFlow(
        thesis,
        portfolio,
        Research(),
        minimum_return=minimum_return,
        minimum_return_policy_version="local-acceptance-minimum-return-v1",
    )
    return flow, frozen, portfolio


def plan(flow, frozen, **changes):
    candidate, critic = evidence()
    values = dict(
        actor=AuthenticatedActor("owner-1", Role.OWNER, 1),
        recommendation_id="rec-1",
        version=1,
        inputs=frozen,
        current=frozen.bindings,
        expected_portfolio_version=2,
        raw_candidate=candidate,
        raw_critic=critic,
        provenance=(
            ("provider", "fixture"),
            ("model", "fixture-v1"),
            ("prompt", "test-v1"),
            ("build", "test-build"),
        ),
        now=NOW,
    )
    values.update(changes)
    return flow.plan_publication(**values)


def test_configured_five_percent_is_applied_to_recomputed_final_size(monkeypatch):
    monkeypatch.delenv("THESIS_TRACE_MINIMUM_ANNUALIZED_RETURN_FILE", raising=False)
    monkeypatch.delenv("THESIS_TRACE_MINIMUM_RETURN_POLICY_VERSION_FILE", raising=False)
    monkeypatch.setenv("THESIS_TRACE_MINIMUM_ANNUALIZED_RETURN", "0.05")
    monkeypatch.setenv(
        "THESIS_TRACE_MINIMUM_RETURN_POLICY_VERSION",
        "local-acceptance-minimum-return-v1",
    )
    minimum, _ = minimum_return_configuration()
    flow, frozen, portfolio = setup_flow(minimum)
    before = portfolio.get(PORTFOLIO_ACTOR)
    result, risk = plan(flow, frozen)
    assert risk.sizing.multiplier == Decimal("0.5")
    assert result.minimum_return == Decimal("0.05")
    assert result.annualized_return == Decimal("0.044961538461538461538461538")
    assert result.direction == "abstain"
    assert result.final_multiplier == 0
    assert "minimum_return_not_met" in result.reasons
    assert result.inputs == frozen
    assert portfolio.get(PORTFOLIO_ACTOR) == before


@pytest.mark.parametrize("role", [Role.LEARNER, Role.ADMIN])
def test_non_owner_cannot_request_a_financial_recommendation_plan(role):
    flow, frozen, _ = setup_flow()
    with pytest.raises(ValueError, match="resource_unavailable"):
        plan(flow, frozen, actor=AuthenticatedActor("owner-1", role, 1))


def test_unconfigured_policy_cannot_enable_a_buy_even_with_sufficient_return():
    flow, frozen, _ = setup_flow(None, cash=Decimal(20000))
    result, risk = plan(flow, frozen)
    assert risk.sizing.multiplier == 1
    assert result.annualized_return > Decimal("0.05")
    assert result.direction == "abstain"
    assert "minimum_return_unconfigured" in result.reasons


def test_changed_source_choice_requires_a_new_valuation_publication():
    flow, frozen, _ = setup_flow()
    with pytest.raises(ValueError, match="valuation_source_selection_conflict"):
        plan(flow, replace(frozen, benchmark_source="peer_group"))


def test_final_risk_failure_does_not_rewrite_admitted_inputs():
    flow, frozen, _ = setup_flow(cash=Decimal(1000))
    result, risk = plan(flow, frozen)
    assert risk.sizing.multiplier == 0
    assert result.direction == "abstain"
    assert result.inputs == frozen


def test_caller_decimal_precision_cannot_round_notional_before_risk_checks():
    flow, frozen, _ = setup_flow(quantity=Decimal("10.123"))
    expected = plan(flow, frozen)
    with localcontext() as context:
        context.prec = 2
        actual = plan(flow, frozen)
    assert actual == expected
    assert actual[1].base_amount == Decimal("1012.300")
