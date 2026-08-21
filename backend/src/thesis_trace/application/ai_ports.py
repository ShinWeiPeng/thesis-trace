from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AnalysisSource:
    source_snapshot_id: str
    publisher_identity: str
    source_tier_facts: tuple[bool, bool, bool, bool, bool]
    underlying_evidence_id: str | None
    canonical_url: str | None
    excerpt: str | None
    retrieved_at: str | None
    published_at: str | None
    observed_at: str | None


@dataclass(frozen=True, slots=True)
class RecommendationProviderRequest:
    assessment_id: str
    evidence_id: str
    evidence_version: int
    sources: tuple[AnalysisSource, ...]
    schema_version: str
    prompt_version: str
    model_version: str


@dataclass(frozen=True, slots=True)
class RecommendationCriticRequest:
    assessment_id: str
    sources: tuple[AnalysisSource, ...]
    candidate_json: str
    schema_version: str
    prompt_version: str
    model_version: str


@dataclass(frozen=True, slots=True)
class ValidatedAnomalyCandidate:
    schema_version: str
    direct_supporting_snapshot_ids: tuple[str, ...]
    clue_features: tuple[int, int, int, int, int] | None
    has_source_conflict: bool
    newer_authoritative_refutation: bool
    price_or_volume_only: bool
    novel_unsupported_event: bool


class RecommendationProviderPort(Protocol):
    def analyze(self, request: RecommendationProviderRequest) -> str: ...


class RecommendationCriticPort(Protocol):
    def criticize(self, request: RecommendationCriticRequest) -> str: ...


_CANDIDATE_KEYS = {
    "schema_version",
    "direct_supporting_snapshot_ids",
    "clue_features",
    "has_source_conflict",
    "newer_authoritative_refutation",
    "price_or_volume_only",
    "novel_unsupported_event",
}
_CLUE_KEYS = {
    "timeliness",
    "traceability",
    "specificity",
    "corroboration",
    "invalidation_relevance",
}
_CRITIC_KEYS = {
    "schema_version",
    "verdict",
    "source_available",
    "citation_direct_support",
    "subject_matches",
    "time_reasonable",
    "invalidation_matches",
    "b_independence",
    "no_newer_a_refutation",
}


def _object(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid_ai_output") from error
    if not isinstance(value, dict):
        raise ValueError("invalid_ai_output")
    return value


def validate_anomaly_candidate(
    raw: str, *, sources: tuple[AnalysisSource, ...]
) -> ValidatedAnomalyCandidate:
    value = _object(raw)
    if set(value) != _CANDIDATE_KEYS or value["schema_version"] != "anomaly-candidate-v1":
        raise ValueError("invalid_candidate_schema")
    supporting = value["direct_supporting_snapshot_ids"]
    sources_by_id = {source.source_snapshot_id: source for source in sources}
    if (
        not isinstance(supporting, list)
        or any(not isinstance(item, str) or item not in sources_by_id for item in supporting)
        or len(set(supporting)) != len(supporting)
    ):
        raise ValueError("invalid_candidate_citations")
    for snapshot_id in supporting:
        source = sources_by_id[snapshot_id]
        required = (
            source.publisher_identity, source.canonical_url, source.excerpt, source.retrieved_at,
        )
        if any(value is None or not value.strip() for value in required):
            raise ValueError("invalid_candidate_citations")
        if not any(
            value is not None and value.strip()
            for value in (source.published_at, source.observed_at)
        ):
            raise ValueError("invalid_candidate_citations")
    boolean_keys = _CANDIDATE_KEYS - {
        "schema_version", "direct_supporting_snapshot_ids", "clue_features"
    }
    if any(type(value[key]) is not bool for key in boolean_keys):
        raise ValueError("invalid_candidate_schema")
    clue = value["clue_features"]
    clue_values = None
    if clue is not None:
        if not isinstance(clue, dict) or set(clue) != _CLUE_KEYS:
            raise ValueError("invalid_candidate_schema")
        ordered = tuple(
            clue[key]
            for key in (
                "timeliness", "traceability", "specificity", "corroboration",
                "invalidation_relevance",
            )
        )
        if any(type(item) is not int or item < 0 or item > 2 for item in ordered):
            raise ValueError("invalid_candidate_schema")
        clue_values = ordered
    return ValidatedAnomalyCandidate(
        schema_version="anomaly-candidate-v1",
        direct_supporting_snapshot_ids=tuple(supporting),
        clue_features=clue_values,
        has_source_conflict=value["has_source_conflict"],
        newer_authoritative_refutation=value["newer_authoritative_refutation"],
        price_or_volume_only=value["price_or_volume_only"],
        novel_unsupported_event=value["novel_unsupported_event"],
    )


def validate_critic_pass(raw: str) -> bool:
    value = _object(raw)
    if set(value) != _CRITIC_KEYS or value["schema_version"] != "recommendation-critic-v1":
        raise ValueError("invalid_critic_schema")
    checks = _CRITIC_KEYS - {"schema_version", "verdict"}
    if value["verdict"] not in {"PASS", "FAIL"} or any(
        type(value[key]) is not bool for key in checks
    ):
        raise ValueError("invalid_critic_schema")
    return value["verdict"] == "PASS" and all(value[key] for key in checks)
