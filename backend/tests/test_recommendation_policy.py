import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import replace

import pytest

from thesis_trace.modules.recommendation.contracts import RecommendationSource
from thesis_trace.modules.recommendation.service import RecommendationService


NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def source():
    return RecommendationSource(
        "snapshot-1",
        "TWSE",
        "公司公布新的年度財報",
        "https://www.twse.com.tw/report",
        NOW,
        None,
        NOW,
    )


def candidate(**changes):
    value = {
        "schema_version": "investment-candidate-v1",
        "direction": "buy",
        "raw_dca_ceiling": "0.5",
        "claims": [
            {"text": "公司公布新的年度財報", "supporting_snapshot_ids": ["snapshot-1"]}
        ],
    }
    value.update(changes)
    return json.dumps(value, ensure_ascii=False)


def test_candidate_preserves_exact_source_bound_claims_and_original_payload_digest():
    raw = candidate()
    result = RecommendationService.validate_candidate(raw, sources=(source(),), now=NOW)
    assert result.direction == "buy"
    assert result.raw_dca_ceiling == Decimal("0.5")
    assert result.claims == (("公司公布新的年度財報", ("snapshot-1",)),)
    assert result.digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    "raw",
    [
        candidate(schema_version="anomaly-candidate-v1"),
        candidate(direction="exit"),
        candidate(target_price="1000"),
        candidate(raw_dca_ceiling=True),
        candidate(raw_dca_ceiling=0.5),
        candidate(raw_dca_ceiling="NaN"),
        candidate(raw_dca_ceiling="0.50"),
        candidate(direction="hold"),
        candidate(raw_dca_ceiling="0"),
        candidate(claims=[]),
        candidate(claims=[{"text": "no citation", "supporting_snapshot_ids": []}]),
        candidate(claims=[{"text": " ", "supporting_snapshot_ids": ["snapshot-1"]}]),
        candidate(
            claims=[{"text": "unsupported", "supporting_snapshot_ids": ["foreign"]}]
        ),
        candidate(
            claims=[
                {
                    "text": "duplicated",
                    "supporting_snapshot_ids": ["snapshot-1", "snapshot-1"],
                }
            ]
        ),
        candidate(
            claims=[{"text": "x" * 2049, "supporting_snapshot_ids": ["snapshot-1"]}]
        ),
        candidate(
            claims=[{"text": "x", "supporting_snapshot_ids": ["snapshot-1"]}] * 33
        ),
        '{"direction":"hold","direction":"buy"}',
        "[]",
        "null",
        "{",
        '{"a":NaN}',
        " " * 65537,
    ],
)
def test_invalid_candidate_never_becomes_a_validated_recommendation(raw):
    with pytest.raises(ValueError, match="invalid_candidate"):
        RecommendationService.validate_candidate(raw, sources=(source(),), now=NOW)


@pytest.mark.parametrize(
    "sources",
    [
        (),
        (source(), source()),
        (replace(source(), publisher=""),),
        (replace(source(), published_at=None),),
        (replace(source(), retrieved_at=NOW.replace(tzinfo=None)),),
        (replace(source(), excerpt="x" * 2049),),
    ],
)
def test_incomplete_or_ambiguous_pinned_sources_fail_closed(sources):
    with pytest.raises(ValueError, match="invalid_candidate_sources"):
        RecommendationService.validate_candidate(candidate(), sources=sources, now=NOW)


def critic(validated, **changes):
    value = {
        "schema_version": "investment-critic-v1",
        "verdict": "PASS",
        "candidate_digest": validated.digest,
        "checks": [
            {
                "claim_index": index,
                "supporting_snapshot_ids": list(ids),
                "source_available": True,
                "direct_support": True,
                "subject_matches": True,
                "time_reasonable": True,
            }
            for index, (_, ids) in enumerate(validated.claims)
        ],
    }
    value.update(changes)
    return json.dumps(value)


def test_critic_pass_is_bound_to_the_exact_candidate_and_every_claim():
    validated = RecommendationService.validate_candidate(
        candidate(), sources=(source(),), now=NOW
    )
    assert (
        RecommendationService.validate_critic(critic(validated), candidate=validated)
        is True
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "anomaly-critic-v1"},
        {"verdict": "pass"},
        {"verdict": True},
        {"candidate_digest": "different-candidate"},
        {"candidate_digest": None},
        {"untrusted_override": True},
        {"checks": []},
        {"checks": {}},
    ],
)
def test_critic_rejects_wrong_schema_digest_and_incomplete_coverage(changes):
    validated = RecommendationService.validate_candidate(
        candidate(), sources=(source(),), now=NOW
    )
    with pytest.raises(ValueError, match="invalid_critic"):
        RecommendationService.validate_critic(
            critic(validated, **changes), candidate=validated
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"claim_index": True},
        {"claim_index": -1},
        {"claim_index": 1},
        {"supporting_snapshot_ids": ["foreign"]},
        {"supporting_snapshot_ids": []},
        {"supporting_snapshot_ids": ["snapshot-1", "snapshot-1"]},
        {"source_available": 1},
        {"direct_support": "true"},
        {"subject_matches": None},
        {"time_reasonable": []},
        {"extra": "do not ignore"},
    ],
)
def test_critic_checks_require_exact_indexes_citations_keys_and_boolean_types(changes):
    validated = RecommendationService.validate_candidate(
        candidate(), sources=(source(),), now=NOW
    )
    payload = json.loads(critic(validated))
    payload["checks"][0].update(changes)
    with pytest.raises(ValueError, match="invalid_critic"):
        RecommendationService.validate_critic(json.dumps(payload), candidate=validated)


@pytest.mark.parametrize(
    "failed_field",
    [
        "source_available",
        "direct_support",
        "subject_matches",
        "time_reasonable",
    ],
)
def test_critic_cannot_pass_by_verdict_when_any_subcheck_failed(failed_field):
    validated = RecommendationService.validate_candidate(
        candidate(), sources=(source(),), now=NOW
    )
    payload = json.loads(critic(validated))
    payload["checks"][0][failed_field] = False
    assert (
        RecommendationService.validate_critic(json.dumps(payload), candidate=validated)
        is False
    )


def test_critic_fail_verdict_does_not_publish_even_with_all_checks_true():
    validated = RecommendationService.validate_candidate(
        candidate(), sources=(source(),), now=NOW
    )
    assert (
        RecommendationService.validate_critic(
            critic(validated, verdict="FAIL"), candidate=validated
        )
        is False
    )


def test_critic_cannot_repeat_one_claim_in_place_of_another():
    validated = RecommendationService.validate_candidate(
        candidate(
            claims=[
                {"text": text, "supporting_snapshot_ids": ["snapshot-1"]}
                for text in ("one", "two")
            ]
        ),
        sources=(source(),),
        now=NOW,
    )
    payload = json.loads(critic(validated))
    payload["checks"][1] = payload["checks"][0]
    with pytest.raises(ValueError, match="invalid_critic"):
        RecommendationService.validate_critic(json.dumps(payload), candidate=validated)


@pytest.mark.parametrize(
    "direction,ceiling",
    [
        ("buy", "0.5"),
        ("buy", "1"),
        ("buy", "1.5"),
        ("hold", "0"),
        ("abstain", "0"),
    ],
)
def test_all_permitted_direction_ceiling_pairs_remain_exact(direction, ceiling):
    validated = RecommendationService.validate_candidate(
        candidate(direction=direction, raw_dca_ceiling=ceiling),
        sources=(source(),),
        now=NOW,
    )
    assert validated.direction == direction
    assert str(validated.raw_dca_ceiling) == ceiling


@pytest.mark.parametrize("response_kind", ["candidate", "critic"])
def test_response_limit_is_utf8_bytes_and_accepts_exactly_64_kib(response_kind):
    validated = RecommendationService.validate_candidate(
        candidate(), sources=(source(),), now=NOW
    )
    if response_kind == "candidate":
        raw = candidate()
        validate = lambda body: RecommendationService.validate_candidate(
            body, sources=(source(),), now=NOW
        )
    else:
        raw = critic(validated)
        validate = lambda body: RecommendationService.validate_critic(
            body, candidate=validated
        )
    boundary = raw + " " * (65536 - len(raw.encode("utf-8")))
    assert validate(boundary)
    with pytest.raises(ValueError, match=f"invalid_{response_kind}"):
        validate(boundary + " ")


def test_maximum_sources_claims_and_text_are_admitted_without_truncation():
    sources = tuple(
        replace(source(), snapshot_id=f"source-{index}") for index in range(32)
    )
    validated = RecommendationService.validate_candidate(
        candidate(
            claims=[
                {
                    "text": "x" * 2048 if index == 0 else "claim",
                    "supporting_snapshot_ids": [f"source-{index}"],
                }
                for index in range(32)
            ]
        ),
        sources=sources,
        now=NOW,
    )
    assert len(validated.claims) == 32
    assert len(validated.claims[0][0]) == 2048
    assert (
        RecommendationService.validate_critic(critic(validated), candidate=validated)
        is True
    )
    with pytest.raises(ValueError, match="invalid_candidate_sources"):
        RecommendationService.validate_candidate(
            candidate(), sources=sources + (source(),), now=NOW
        )


def test_critic_rejects_duplicate_nested_json_keys_even_if_last_value_passes():
    validated = RecommendationService.validate_candidate(
        candidate(), sources=(source(),), now=NOW
    )
    raw = critic(validated).replace(
        '"direct_support": true', '"direct_support": false, "direct_support": true'
    )
    with pytest.raises(ValueError, match="invalid_critic"):
        RecommendationService.validate_critic(raw, candidate=validated)
