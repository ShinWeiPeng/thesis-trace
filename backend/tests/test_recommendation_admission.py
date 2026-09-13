from dataclasses import replace
from datetime import timezone, timedelta
import pytest

from thesis_trace.modules.recommendation.service import RecommendationService
from test_recommendation_publication import inputs


def versions():
    return tuple(
        {
            "provider": "openai",
            "model": "fixture-model",
            "prompt": "investment-candidate-prompt-v1",
            "critic_model": "fixture-critic",
            "critic_prompt": "investment-critic-prompt-v1",
            "build": "test-build",
            "candidate_schema": "investment-candidate-v1",
            "critic_schema": "investment-critic-v1",
            "minimum_return_policy": "local-acceptance-minimum-return-v1",
            "risk_policy": "exposure-policy-v1",
            "cost_profile_policy": "cost-profile-v1",
            "sizing_policy": "dca-selection-v1",
            "return_policy": "valuation-return-v1",
        }.items()
    )


def test_input_digest_is_deterministic_and_binds_all_versions():
    frozen = inputs()
    digest = RecommendationService.admission_digest(frozen, versions())
    assert len(digest) == 64
    assert (
        RecommendationService.admission_digest(frozen, tuple(reversed(versions())))
        == digest
    )
    assert (
        RecommendationService.admission_digest(
            replace(frozen, source_selection_reason="Another reason"), versions()
        )
        != digest
    )
    assert (
        RecommendationService.admission_digest(
            frozen,
            tuple(
                (key, "other-build" if key == "build" else value)
                for key, value in versions()
            ),
        )
        != digest
    )
    shifted = replace(
        frozen, admitted_at=frozen.admitted_at.astimezone(timezone(timedelta(hours=8)))
    )
    assert RecommendationService.admission_digest(shifted, versions()) == digest


@pytest.mark.parametrize(
    "change",
    [
        {"actor": replace(inputs().actor, may_manage=False)},
        {"sources": ()},
        {"bindings": ()},
        {"source_selection_reason": " "},
        {"cycle": True},
        {"sources": (replace(inputs().sources[0], excerpt="x" * 2049),)},
    ],
)
def test_invalid_admission_fails_before_persistence(change):
    with pytest.raises(ValueError):
        RecommendationService.admission_digest(replace(inputs(), **change), versions())


def test_unpinned_or_oversized_admission_rejects():
    with pytest.raises(ValueError, match="invalid_admission_versions"):
        RecommendationService.admission_digest(inputs(), ())
    with pytest.raises(ValueError, match="input_too_large"):
        RecommendationService.admission_digest(
            replace(inputs(), source_selection_reason="x" * 262144), versions()
        )


def test_missing_analysis_context_is_not_reconstructed_from_live_state():
    with pytest.raises(ValueError, match="invalid_analysis_context"):
        RecommendationService.admission_digest(
            replace(inputs(), analysis_context=()), versions()
        )
