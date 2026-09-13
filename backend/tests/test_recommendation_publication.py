import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from thesis_trace.modules.recommendation.contracts import (
    BoundRecommendationInput,
    RecommendationActor,
    RecommendationInputSnapshot,
    RecommendationSource,
)
from thesis_trace.modules.recommendation.service import RecommendationService


NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def inputs():
    return RecommendationInputSnapshot(
        actor=RecommendationActor("owner-1", True),
        thesis_id="thesis-1",
        cycle=1,
        bindings=(
            BoundRecommendationInput(
                "thesis", "valuation-1", 1, "digest", NOW + timedelta(days=1)
            ),
        ),
        sources=(
            RecommendationSource(
                "snapshot-1",
                "Publisher",
                "Reported earnings",
                "https://example.test/report",
                NOW,
                None,
                NOW,
            ),
        ),
        valuation_id="valuation-1",
        portfolio_snapshot_id="risk-1",
        source_selection_reason="Confirmed company history",
        gate_reasons=(),
        company_id="2330",
        benchmark_source="company_history",
        admitted_at=NOW,
        analysis_context=(
            ("thesis", "Frozen investment thesis"),
            ("conditions", "Predeclared condition"),
            ("valuation", "PE forecast context"),
            ("thesis_record_version", "1"),
        ),
    )


def evidence(direction="buy", ceiling="1"):
    candidate = json.dumps(
        {
            "schema_version": "investment-candidate-v1",
            "direction": direction,
            "raw_dca_ceiling": ceiling,
            "claims": [
                {
                    "text": "Earnings support the assessment",
                    "supporting_snapshot_ids": ["snapshot-1"],
                }
            ],
        }
    )
    critic = json.dumps(
        {
            "schema_version": "investment-critic-v1",
            "verdict": "PASS",
            "candidate_digest": hashlib.sha256(candidate.encode()).hexdigest(),
            "checks": [
                {
                    "claim_index": 0,
                    "supporting_snapshot_ids": ["snapshot-1"],
                    "source_available": True,
                    "direct_support": True,
                    "subject_matches": True,
                    "time_reasonable": True,
                }
            ],
        }
    )
    return candidate, critic


def plan(**changes):
    frozen = inputs()
    candidate, critic = evidence()
    values = dict(
        actor=frozen.actor,
        recommendation_id="rec-1",
        version=1,
        inputs=frozen,
        current=frozen.bindings,
        raw_candidate=candidate,
        raw_critic=critic,
        selected_multiplier=Decimal("0.5"),
        annualized_return=Decimal("0.12"),
        minimum_return=Decimal("0.08"),
        calculation_trace=(("quantity", "0.5"), ("buy_fee", "20")),
        provenance=tuple(
            (name, "test-v1")
            for name in (
                "provider",
                "model",
                "prompt",
                "build",
                "minimum_return_policy",
                "risk_policy",
                "cost_profile_policy",
            )
        ),
        now=NOW,
    )
    values.update(changes)
    return RecommendationService.plan_publication(**values)


def test_publication_keeps_candidate_separate_from_server_clipped_size():
    record = plan()
    assert record.direction == "buy"
    assert record.final_multiplier == Decimal("0.5")
    assert record.candidate.raw_dca_ceiling == Decimal("1")
    assert record.minimum_return == Decimal("0.08")
    assert record.annualized_return == Decimal("0.12")
    assert record.inputs == inputs()
    assert record.critic_evidence == evidence()[1]
    assert record.reasons == ()


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"minimum_return": None}, "minimum_return_unconfigured"),
        ({"minimum_return": Decimal("NaN")}, "minimum_return_invalid"),
        ({"annualized_return": None}, "final_size_return_unavailable"),
        (
            {"annualized_return": Decimal("0.07999999999999999999999999999")},
            "minimum_return_not_met",
        ),
        ({"selected_multiplier": Decimal("0")}, "no_feasible_size"),
        (
            {"inputs": replace(inputs(), gate_reasons=("missing_official_price",))},
            "missing_official_price",
        ),
        (
            {"inputs": replace(inputs(), portfolio_snapshot_id=None)},
            "portfolio_snapshot_unavailable",
        ),
        (
            {"inputs": replace(inputs(), benchmark_source="abstain")},
            "benchmark_abstained",
        ),
    ],
)
def test_schema_valid_buy_fails_closed_with_a_reason(changes, reason):
    record = plan(**changes)
    assert record.direction == "abstain"
    assert record.final_multiplier == 0
    assert record.candidate.direction == "buy"
    assert reason in record.reasons


def test_return_threshold_equality_passes_without_rounding():
    assert plan(annualized_return=Decimal("0.08")).direction == "buy"


@pytest.mark.parametrize("direction", ["hold", "abstain"])
def test_zero_size_model_direction_stays_distinct(direction):
    candidate, critic = evidence(direction, "0")
    result = plan(
        raw_candidate=candidate,
        raw_critic=critic,
        selected_multiplier=Decimal(0),
        annualized_return=None,
    )
    assert result.direction == direction
    assert result.final_multiplier == 0


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"actor": RecommendationActor("other-owner", True)}, "resource_unavailable"),
        ({"actor": RecommendationActor("owner-1", False)}, "resource_unavailable"),
        ({"now": NOW + timedelta(days=1)}, "superseded_inputs"),
        ({"current": (replace(inputs().bindings[0], version=2),)}, "superseded_inputs"),
        ({"selected_multiplier": Decimal("1.5")}, "invalid_sizing_result"),
        ({"selected_multiplier": Decimal("NaN")}, "invalid_sizing_result"),
        ({"selected_multiplier": True}, "invalid_sizing_result"),
        ({"raw_candidate": "{}"}, "invalid_candidate"),
        ({"raw_critic": "{}"}, "invalid_critic"),
        ({"provenance": ()}, "invalid_publication_provenance"),
        (
            {"inputs": replace(inputs(), admitted_at=NOW + timedelta(seconds=1))},
            "invalid_publication_inputs",
        ),
    ],
)
def test_bad_authority_staleness_or_evidence_never_produces_record(changes, code):
    with pytest.raises(ValueError, match=code):
        plan(**changes)


def test_critic_failure_is_analysis_failure_not_a_successful_hold():
    candidate, critic = evidence()
    value = json.loads(critic)
    value["checks"][0]["direct_support"] = False
    with pytest.raises(ValueError, match="critic_rejected"):
        plan(raw_candidate=candidate, raw_critic=json.dumps(value))
