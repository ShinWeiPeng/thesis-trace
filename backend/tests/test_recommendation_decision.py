from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from thesis_trace.modules.recommendation.contracts import (
    BoundRecommendationInput,
    OwnerDecision,
    RecommendationActor,
)
from thesis_trace.modules.recommendation.service import RecommendationService


NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def test_bound_valuation_expires_at_exact_validity_boundary_not_a_fixed_ttl():
    binding = BoundRecommendationInput("thesis", "valuation-1", 1, "digest-1", NOW)

    assert (
        RecommendationService.expiry_reasons(
            (binding,), (binding,), now=NOW - timedelta(microseconds=1)
        )
        == ()
    )
    assert RecommendationService.expiry_reasons((binding,), (binding,), now=NOW) == (
        "input_expired:thesis:valuation-1",
    )


@pytest.mark.parametrize("status", ["accepted", "rejected"])
def test_final_decision_never_expires_when_inputs_later_change(status):
    decision = OwnerDecision(
        "rec-1",
        1,
        1,
        status,
        "reviewed",
        "owner-1",
        NOW,
        None,
        "recommendation-decision-v1",
    )
    assert (
        RecommendationService.plan_decision(
            actor=RecommendationActor("owner-1", True),
            owner_id="owner-1",
            recommendation_id="rec-1",
            recommendation_version=1,
            previous=decision,
            expected_sequence=1,
            bound=(),
            current=(),
            target_status="expired",
            reason="",
            now=NOW + timedelta(days=100),
        )
        is None
    )


def plan(**overrides):
    binding = BoundRecommendationInput(
        "thesis", "valuation-1", 1, "digest", NOW + timedelta(days=30)
    )
    values = dict(
        actor=RecommendationActor("owner-1", True),
        owner_id="owner-1",
        recommendation_id="rec-1",
        recommendation_version=1,
        previous=None,
        expected_sequence=0,
        bound=(binding,),
        current=(binding,),
        target_status="deferred",
        reason="Review tomorrow",
        now=NOW,
        defer_until=NOW + timedelta(days=1),
    )
    values.update(overrides)
    return RecommendationService.plan_decision(**values)


def test_deferral_appends_next_sequence_without_extending_valuation_validity():
    first = plan()
    assert first.status == "deferred"
    assert first.sequence == 1
    assert first.defer_until == NOW + timedelta(days=1)
    expired = plan(
        previous=first,
        expected_sequence=1,
        now=NOW + timedelta(days=31),
        target_status="accepted",
        reason="accept",
        defer_until=None,
    )
    assert expired.status == "expired"
    assert expired.sequence == 2
    assert expired.policy_version == "recommendation-expiry-v1"
    assert "input_expired:thesis:valuation-1" in expired.reason
    assert first.status == "deferred"


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"actor": RecommendationActor("foreign", True)}, "resource_unavailable"),
        ({"actor": RecommendationActor("owner-1", False)}, "resource_unavailable"),
        ({"expected_sequence": 1}, "version_conflict"),
        ({"expected_sequence": True}, "version_conflict"),
        ({"reason": "  "}, "missing_reason"),
        ({"defer_until": NOW}, "invalid_defer_time"),
        ({"defer_until": None}, "invalid_defer_time"),
        ({"defer_until": NOW.replace(tzinfo=None)}, "invalid_defer_time"),
        ({"target_status": "cancelled"}, "invalid_transition"),
    ],
)
def test_invalid_decision_intent_is_rejected(overrides, code):
    with pytest.raises(ValueError, match=code):
        plan(**overrides)


def test_expiry_cannot_be_forged_and_is_idempotent_for_terminal_history():
    assert plan(target_status="expired") is None
    expired = plan(now=NOW + timedelta(days=31), defer_until=None)
    assert plan(previous=expired, expected_sequence=1, target_status="expired") is None
    with pytest.raises(ValueError, match="invalid_transition"):
        plan(previous=expired, expected_sequence=1, target_status="accepted")


def test_foreign_recommendation_history_cannot_be_attached_to_another_record():
    previous = replace(plan(), recommendation_id="rec-foreign")
    with pytest.raises(ValueError, match="version_conflict"):
        plan(previous=previous, expected_sequence=1)


@pytest.mark.parametrize("changes", [{"version": 2}, {"digest": "corrected"}])
def test_changed_critical_input_invalidates_but_unrelated_inputs_do_not(changes):
    binding = BoundRecommendationInput("portfolio", "cost-1", 1, "cost-digest", None)
    unrelated = BoundRecommendationInput("thesis", "note-2", 99, "new-note", None)
    assert (
        RecommendationService.expiry_reasons(
            (binding,), (binding, unrelated), now=NOW + timedelta(days=1000)
        )
        == ()
    )
    assert RecommendationService.expiry_reasons(
        (binding,), (replace(binding, **changes), unrelated), now=NOW
    ) == ("input_version_changed:portfolio:cost-1",)


@pytest.mark.parametrize("case", ["missing", "duplicate", "empty", "naive-clock"])
def test_unknown_or_ambiguous_validity_fails_closed_instead_of_expiring_history(case):
    binding = BoundRecommendationInput("portfolio", "cost-1", 1, "digest", None)
    current = () if case == "missing" else (binding,)
    if case == "duplicate":
        current = (binding, binding)
    with pytest.raises(ValueError, match="input_validity_unavailable"):
        RecommendationService.expiry_reasons(
            () if case == "empty" else (binding,),
            current,
            now=NOW.replace(tzinfo=None) if case == "naive-clock" else NOW,
        )


def test_new_earlier_validity_boundary_does_not_extend_original_snapshot_lifetime():
    binding = BoundRecommendationInput(
        "thesis", "valuation-1", 1, "digest", NOW + timedelta(days=5)
    )
    assert RecommendationService.expiry_reasons(
        (binding,), (replace(binding, valid_until=NOW),), now=NOW
    ) == ("input_expired:thesis:valuation-1",)
