from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from collections import Counter
import pytest

from thesis_trace.application.contracts import (
    RecommendationDecisionCommand,
    RecommendationFlow,
)
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.portfolio.service import PortfolioService
from thesis_trace.modules.research import (
    ResearchRecommendationFacade,
    ResearchRecommendationSource,
    ResearchRecordReference,
)
from thesis_trace.modules.thesis.contracts import ThesisStatus
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.modules.recommendation.service import RecommendationService
from test_portfolio_domain import NOW, MemoryPortfolioStore, configured
from test_thesis_domain import MemoryThesisStore, create
from test_recommendation_final_size import published_valuation
from test_recommendation_admission import versions
from test_valuation_flow import Research
from test_access_wave1 import MemoryAccessRepository
from test_recommendation_store_contract import MemoryRecords
from test_recommendation_publication import plan as publication
from thesis_trace.modules.access.orchestration import AccessConfirmationService
from thesis_trace.modules.access.confirmation_challenge.service import (
    ConfirmationService,
)
from thesis_trace.modules.recommendation.contracts import OwnerDecision


class Queries:
    def __init__(self):
        self.source_version = 1
        self.fact_digest = "confirmed-fact-digest"
        self.missing = False
        self.source_reads = []

    def get_recommendation_source(self, evidence_id):
        self.source_reads.append(evidence_id)
        if self.missing:
            return None
        return ResearchRecommendationSource(
            ResearchRecordReference(
                "evidence", evidence_id, self.source_version, "company-1"
            ),
            "snapshot-history",
            "https://example.test/facts",
            "Publisher",
            "Saved source excerpt",
            "A",
            "underlying-report",
            NOW,
            None,
            NOW,
            None,
            None,
            None,
            None,
        )

    def get_recommendation_fact(self, evidence_id, fact_id):
        return ResearchRecordReference(
            "valuation_fact", fact_id, 1, "company-1"
        ), self.fact_digest + fact_id


def setup():
    thesis_store = MemoryThesisStore()
    thesis = ThesisService(thesis_store, id_factory=lambda: "thesis-1")
    current = create(thesis)
    valuation = published_valuation()
    draft = valuation.draft
    history = replace(
        draft.company_history,
        valid_samples=tuple(
            replace(sample, source=replace(sample.source, fact_id=sample.sample_id))
            for sample in draft.company_history.valid_samples
        ),
    )
    valuation = replace(
        valuation,
        draft=replace(
            draft,
            company_history=history,
            forecast_source=replace(draft.forecast_source, fact_id="forecast"),
        ),
    )
    thesis_store.records[current.thesis_id] = replace(
        current, status=ThesisStatus.ACTIVE, valuation_snapshots=(valuation,)
    )
    portfolio_store = MemoryPortfolioStore()
    portfolio = PortfolioService(portfolio_store)
    configured(portfolio)
    queries = Queries()
    flow = RecommendationFlow(
        thesis,
        portfolio,
        Research(),
        minimum_return=Decimal("0.05"),
        minimum_return_policy_version="local-acceptance-minimum-return-v1",
        source_queries=ResearchRecommendationFacade(queries),
        versions=versions(),
    )
    return flow, thesis_store, portfolio_store, queries


def prepare(flow, **changes):
    values = dict(
        actor=AuthenticatedActor("owner-1", Role.OWNER, 1),
        thesis_id="thesis-1",
        expected_thesis_version=1,
        valuation_id="thesis-1:valuation:1",
        expected_valuation_version=1,
        expected_portfolio_version=2,
        benchmark_source="company_history",
        source_selection_reason="Use the confirmed historical distribution",
        portfolio_snapshot_id="risk-admission",
        now=NOW,
    )
    values.update(changes)
    return flow.prepare_inputs(**values)


def test_parent_freezes_context_and_all_consumed_owner_bindings():
    flow, _, _, _ = setup()
    frozen = prepare(flow)
    assert {item.owner_domain for item in frozen.bindings} == {
        "thesis",
        "research",
        "portfolio",
        "runtime",
    }
    assert len(frozen.sources) == 1 and frozen.sources[0].source_category == "A"
    assert frozen.sources[0].lineage == "underlying-report"
    assert dict(frozen.analysis_context)["thesis"]
    assert len(RecommendationService.admission_digest(frozen, versions())) == 64
    assert (
        flow.current_bindings(
            AuthenticatedActor("owner-1", Role.OWNER, 1),
            frozen,
            now=NOW + timedelta(minutes=1),
        )
        == frozen.bindings
    )


def test_unrelated_title_and_decimal_presentation_do_not_expire_a_recommendation():
    flow, thesis_store, portfolio_store, _ = setup()
    frozen = prepare(flow)
    old = thesis_store.records["thesis-1"]
    thesis_store.records["thesis-1"] = replace(
        old,
        title="New display title",
        version=old.version + 1,
        updated_at=NOW + timedelta(seconds=1),
    )
    portfolio_store.official["2330"] = replace(
        portfolio_store.official["2330"], official_close=Decimal("100.000")
    )
    current = flow.current_bindings(
        AuthenticatedActor("owner-1", Role.OWNER, 1), frozen, now=NOW
    )
    assert RecommendationService.expiry_reasons(frozen.bindings, current, now=NOW) == ()
    thesis_store.records["thesis-1"] = replace(
        old, narrative="Changed decision-critical research assumption"
    )
    current = flow.current_bindings(
        AuthenticatedActor("owner-1", Role.OWNER, 1), frozen, now=NOW
    )
    assert RecommendationService.expiry_reasons(frozen.bindings, current, now=NOW)


def test_source_fact_and_official_price_changes_are_bound_independently():
    for changed in ("source", "fact", "price"):
        flow, _, portfolio_store, queries = setup()
        frozen = prepare(flow)
        if changed == "source":
            queries.source_version = 2
        elif changed == "fact":
            queries.fact_digest = "different-confirmed-fact"
        else:
            portfolio_store.official["2330"] = replace(
                portfolio_store.official["2330"], official_close=Decimal(101)
            )
        current = flow.current_bindings(
            AuthenticatedActor("owner-1", Role.OWNER, 1), frozen, now=NOW
        )
        assert RecommendationService.expiry_reasons(frozen.bindings, current, now=NOW)


def test_known_removed_source_expires_without_assuming_unknown_inputs_valid():
    flow, _, _, queries = setup()
    frozen = prepare(flow)
    queries.missing = True
    current = flow.current_bindings(
        AuthenticatedActor("owner-1", Role.OWNER, 1), frozen, now=NOW
    )
    assert RecommendationService.expiry_reasons(frozen.bindings, current, now=NOW)


def test_admission_reads_each_evidence_source_once_even_for_many_bound_facts():
    flow, _, _, queries = setup()
    prepare(flow)
    assert queries.source_reads
    assert all(count == 1 for count in Counter(queries.source_reads).values())


def test_duplicate_snapshot_identity_with_conflicting_metadata_is_rejected():
    flow, theses, _, queries = setup()
    record = theses.records["thesis-1"]
    reference = replace(
        record.valuation_snapshots[0].draft.forecast_source,
        record_id="another-evidence",
        fact_id=None,
    )
    theses.records["thesis-1"] = replace(record, evidence_refs=(reference,))
    original = queries.get_recommendation_source

    def inconsistent(evidence_id):
        return replace(original(evidence_id), excerpt=evidence_id)

    queries.get_recommendation_source = inconsistent
    with pytest.raises(ValueError, match="invalid_candidate_sources"):
        prepare(flow)


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_thesis_version": True},
        {"expected_valuation_version": True},
        {"expected_portfolio_version": "2"},
    ],
)
def test_public_input_preparation_rejects_coerced_or_boolean_versions(changes):
    flow, _, _, _ = setup()
    with pytest.raises(ValueError, match="invalid_admission_intent"):
        prepare(flow, **changes)


class DecisionRecords(MemoryRecords):
    def __init__(self, record, previous=None):
        super().__init__(record.inputs.actor.actor_id)
        self.append_record(record)
        self.previous = previous

    def latest_decision(self, actor, record_id, version):
        return self.previous if self.get_record(actor, record_id, version) else None


@pytest.mark.parametrize(
    "target,action,after",
    [("accepted", "接受建議", "已接受"), ("rejected", "拒絕建議", "已拒絕")],
)
@pytest.mark.parametrize("was_deferred", [False, True])
def test_decision_preview_identifies_server_target_and_state_change(
    target, action, after, was_deferred
):
    flow, _, _, _ = setup()
    frozen = prepare(flow)
    record = replace(publication(), inputs=frozen, published_at=NOW)
    previous = (
        OwnerDecision(
            "rec-1",
            1,
            1,
            "deferred",
            "Review later",
            "owner-1",
            NOW,
            NOW + timedelta(days=1),
            "recommendation-decision-v1",
        )
        if was_deferred
        else None
    )
    store = DecisionRecords(record, previous)
    actor = AuthenticatedActor("owner-1", Role.OWNER, 1)
    confirmations = AccessConfirmationService(
        ConfirmationService(MemoryAccessRepository(), clock=lambda: NOW)
    )
    command = RecommendationDecisionCommand(
        "owner-1",
        1,
        "rec-1",
        1,
        1 if was_deferred else 0,
        target,
        "Reviewed evidence and risk",
        None,
        "preview-only",
    )

    preview = flow.preview_decision(
        command, actor=actor, store=store, confirmations=confirmations, now=NOW
    )

    assert preview.challenge_token and preview.expires_at == NOW + timedelta(minutes=5)
    assert "公司／證券：2330 · Demo（company-1）" in preview.impact_summary
    assert "目標建議：rec-1 / v1" in preview.impact_summary
    assert "關聯 Thesis：thesis-1 / 週期 1" in preview.impact_summary
    assert f"動作：{action}" in preview.impact_summary
    before = "已延後" if was_deferred else "尚未決策"
    assert f"決策狀態：{before} → {after}" in preview.impact_summary
    assert "審查待辦：結束" in preview.impact_summary
    assert "不會建立交易、下單、保留或扣除現金" in preview.impact_summary
    assert store.latest_decision("owner-1", "rec-1", 1) == previous
