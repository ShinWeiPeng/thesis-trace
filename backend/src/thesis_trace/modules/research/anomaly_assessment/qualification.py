from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path

from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyClass,
    ClueFeatureVector,
    ClueRoute,
    SourceCharacteristicSnapshot,
    SourceTier,
)
from thesis_trace.modules.research.anomaly_assessment.policy import evaluate_anomaly


class QualificationCaseCategory(str, Enum):
    SINGLE_A_POSITIVE = "single_a_positive"
    INDEPENDENT_B_POSITIVE = "independent_b_positive"
    INSUFFICIENT_NEGATIVE = "insufficient_negative"
    LINEAGE_CONFLICT_NEGATIVE = "lineage_conflict_negative"
    CRITIC_FAILURE_NEGATIVE = "critic_failure_negative"
    MARKET_NOVEL_NEGATIVE = "market_novel_negative"


@dataclass(frozen=True, slots=True)
class QualificationVersionTuple:
    build_version: str
    policy_version: str
    candidate_schema_version: str
    candidate_prompt_version: str
    provider_model_version: str
    critic_schema_version: str
    critic_prompt_version: str
    critic_model_version: str


@dataclass(frozen=True, slots=True)
class QualificationCase:
    dataset_version: str
    versions: QualificationVersionTuple
    case_id: str
    category: QualificationCaseCategory
    auxiliary_label: str
    candidate_json: str
    critic_json: str | None
    company_id: str
    industry: str
    expected_class: AnomalyClass
    expected_tiers: tuple[SourceTier, ...]
    expected_score: int | None
    expected_route: ClueRoute | None
    sources: tuple[SourceCharacteristicSnapshot, ...]
    direct_supporting_snapshot_ids: tuple[str, ...]
    predeclared_invalidation_matches: bool
    critic_passed: bool
    clue_features: ClueFeatureVector | None
    has_source_conflict: bool
    newer_authoritative_refutation: bool
    price_or_volume_only: bool
    novel_unsupported_event: bool


@dataclass(frozen=True, slots=True)
class OfflineQualificationResult:
    dataset_version: str
    versions: QualificationVersionTuple | None
    passed: bool
    total_cases: int
    hard_positive_passes: int
    false_hard_count: int
    auxiliary_label_passes: int
    company_count: int
    industry_count: int
    category_counts: tuple[tuple[str, int], ...]
    failure_case_ids: tuple[str, ...]


_EXPECTED_COUNTS = (
    (QualificationCaseCategory.SINGLE_A_POSITIVE, 20),
    (QualificationCaseCategory.INDEPENDENT_B_POSITIVE, 20),
    (QualificationCaseCategory.INSUFFICIENT_NEGATIVE, 20),
    (QualificationCaseCategory.LINEAGE_CONFLICT_NEGATIVE, 15),
    (QualificationCaseCategory.CRITIC_FAILURE_NEGATIVE, 15),
    (QualificationCaseCategory.MARKET_NOVEL_NEGATIVE, 10),
)
_POSITIVE = {
    QualificationCaseCategory.SINGLE_A_POSITIVE,
    QualificationCaseCategory.INDEPENDENT_B_POSITIVE,
}
_SOURCE_KEYS = {
    "source_snapshot_id", "publisher_identity", "authoritative_first_party",
    "formal_record", "editorial_responsibility", "attributed_author",
    "verifiable_primary_evidence", "underlying_evidence_id",
}
_CLUE_KEYS = {
    "timeliness", "traceability", "specificity", "corroboration",
    "invalidation_relevance",
}
_CASE_KEYS = {
    "case_id", "category", "auxiliary_label", "company_id", "industry",
    "expected_class", "expected_tiers", "expected_score", "expected_route", "sources",
    "direct_supporting_snapshot_ids", "predeclared_invalidation_matches", "critic_passed",
    "clue_features", "has_source_conflict", "newer_authoritative_refutation",
    "price_or_volume_only", "novel_unsupported_event",
}
_VERSION_KEYS = {
    "build_version", "policy_version", "candidate_schema_version",
    "candidate_prompt_version", "provider_model_version", "critic_schema_version",
    "critic_prompt_version", "critic_model_version",
}
_VALIDATION_FIXTURE_KEYS = {
    "invented_snapshot_id", "critic_pass", "critic_schema", "subject_failure",
    "time_failure",
}
_AUXILIARY_LABELS = {
    "direct_a", "two_independent_b", "single_b", "high_c", "insufficient_evidence",
    "same_publisher", "same_underlying_evidence", "source_conflict", "critic_timeout",
    "critic_schema", "citation_failure", "subject_failure", "time_failure",
    "price_volume_only", "novel_unsupported_event",
}


def _string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_qualification_dataset")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("invalid_qualification_dataset")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("invalid_qualification_dataset")
    return value


def _source(value: dict[str, object]) -> SourceCharacteristicSnapshot:
    if not isinstance(value, dict) or set(value) != _SOURCE_KEYS:
        raise ValueError("invalid_qualification_dataset")
    lineage = value["underlying_evidence_id"]
    if lineage is not None:
        lineage = _string(lineage)
    return SourceCharacteristicSnapshot(
        source_snapshot_id=_string(value["source_snapshot_id"]),
        publisher_identity=_string(value["publisher_identity"]),
        authoritative_first_party=_boolean(value["authoritative_first_party"]),
        formal_record=_boolean(value["formal_record"]),
        editorial_responsibility=_boolean(value["editorial_responsibility"]),
        attributed_author=_boolean(value["attributed_author"]),
        verifiable_primary_evidence=_boolean(value["verifiable_primary_evidence"]),
        underlying_evidence_id=lineage,
    )


def _clue(value: object) -> ClueFeatureVector | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _CLUE_KEYS:
        raise ValueError("invalid_qualification_dataset")
    return ClueFeatureVector(
        _integer(value["timeliness"]),
        _integer(value["traceability"]),
        _integer(value["specificity"]),
        _integer(value["corroboration"]),
        _integer(value["invalidation_relevance"]),
    )


def _versions(value: object) -> QualificationVersionTuple:
    if not isinstance(value, dict) or set(value) != _VERSION_KEYS:
        raise ValueError("invalid_qualification_dataset")
    return QualificationVersionTuple(**{key: _string(value[key]) for key in _VERSION_KEYS})


def load_qualification_cases(path: Path) -> tuple[QualificationCase, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "dataset_version", "version_tuple", "validation_fixtures", "cases",
        }:
            raise ValueError("invalid_qualification_dataset")
        dataset_version = _string(payload["dataset_version"])
        versions = _versions(payload["version_tuple"])
        fixtures = payload["validation_fixtures"]
        if not isinstance(fixtures, dict) or set(fixtures) != _VALIDATION_FIXTURE_KEYS:
            raise ValueError("invalid_qualification_dataset")
        invented_snapshot_id = _string(fixtures["invented_snapshot_id"])
        for key in _VALIDATION_FIXTURE_KEYS - {"invented_snapshot_id"}:
            if not isinstance(fixtures[key], dict):
                raise ValueError("invalid_qualification_dataset")
        raw_cases = payload["cases"]
        if not isinstance(raw_cases, list):
            raise ValueError("invalid_qualification_dataset")
        for item in raw_cases:
            if not isinstance(item, dict) or set(item) != _CASE_KEYS:
                raise ValueError("invalid_qualification_dataset")
        cases = tuple(
            QualificationCase(
                dataset_version=dataset_version,
                versions=versions,
                case_id=_string(item["case_id"]),
                category=QualificationCaseCategory(item["category"]),
                auxiliary_label=_string(item["auxiliary_label"]),
                candidate_json=json.dumps(
                    {
                        "schema_version": "anomaly-candidate-v1",
                        "direct_supporting_snapshot_ids": [
                            *item["direct_supporting_snapshot_ids"],
                            *(
                                [invented_snapshot_id]
                                if item["auxiliary_label"] == "citation_failure" else []
                            ),
                        ],
                        "clue_features": item["clue_features"],
                        "has_source_conflict": item["has_source_conflict"],
                        "newer_authoritative_refutation": item["newer_authoritative_refutation"],
                        "price_or_volume_only": item["price_or_volume_only"],
                        "novel_unsupported_event": item["novel_unsupported_event"],
                    },
                    separators=(",", ":"),
                ),
                critic_json=(
                    None if item["auxiliary_label"] == "critic_timeout"
                    else json.dumps(
                        fixtures[
                            item["auxiliary_label"]
                            if item["auxiliary_label"] in {
                                "critic_schema", "subject_failure", "time_failure"
                            }
                            else "critic_pass"
                        ],
                        separators=(",", ":"),
                    )
                ),
                company_id=_string(item["company_id"]),
                industry=_string(item["industry"]),
                expected_class=AnomalyClass(item["expected_class"]),
                expected_tiers=tuple(SourceTier(_string(value)) for value in item["expected_tiers"]),
                expected_score=(
                    None if item["expected_score"] is None else _integer(item["expected_score"])
                ),
                expected_route=(
                    None if item["expected_route"] is None else ClueRoute(item["expected_route"])
                ),
                sources=tuple(_source(value) for value in item["sources"]),
                direct_supporting_snapshot_ids=tuple(
                    _string(value) for value in item["direct_supporting_snapshot_ids"]
                ),
                predeclared_invalidation_matches=_boolean(item["predeclared_invalidation_matches"]),
                critic_passed=_boolean(item["critic_passed"]),
                clue_features=_clue(item["clue_features"]),
                has_source_conflict=_boolean(item["has_source_conflict"]),
                newer_authoritative_refutation=_boolean(item["newer_authoritative_refutation"]),
                price_or_volume_only=_boolean(item["price_or_volume_only"]),
                novel_unsupported_event=_boolean(item["novel_unsupported_event"]),
            )
            for item in raw_cases
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("invalid_qualification_dataset") from None
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("invalid_qualification_dataset")
    if any(case.auxiliary_label not in _AUXILIARY_LABELS for case in cases):
        raise ValueError("invalid_qualification_dataset")
    return cases


def _gate_passed(trace, gate_name: str) -> bool:
    return next(gate.passed for gate in trace.gates if gate.gate == gate_name)


def _auxiliary_label_passes(case: QualificationCase, trace) -> bool:
    label = case.auxiliary_label
    if label == "direct_a":
        return trace.source_tiers == (SourceTier.A,) and _gate_passed(trace, "source_quorum")
    if label == "two_independent_b":
        return trace.source_tiers == (SourceTier.B, SourceTier.B) and _gate_passed(trace, "source_quorum")
    if label == "high_c":
        return (
            trace.source_tiers == (SourceTier.C,)
            and trace.clue_route is ClueRoute.HUMAN_REVIEW
            and not _gate_passed(trace, "source_quorum")
        )
    if label in {"single_b", "insufficient_evidence", "same_publisher", "same_underlying_evidence"}:
        return not _gate_passed(trace, "source_quorum")
    if label == "source_conflict":
        return not _gate_passed(trace, "source_conflict")
    if label in {"critic_timeout", "critic_schema", "citation_failure", "subject_failure", "time_failure"}:
        return not _gate_passed(trace, "critic")
    if label == "price_volume_only":
        return not _gate_passed(trace, "market_only")
    if label == "novel_unsupported_event":
        return not _gate_passed(trace, "novel_unsupported")
    return False


def evaluate_offline_qualification(
    cases: tuple[QualificationCase, ...],
) -> OfflineQualificationResult:
    category_counter = Counter(case.category for case in cases)
    failures: list[str] = []
    positive_passes = 0
    false_hard = 0
    auxiliary_passes = 0
    versions = {case.dataset_version for case in cases}
    version_tuples = {case.versions for case in cases}
    for case in cases:
        trace = evaluate_anomaly(
            sources=case.sources,
            direct_supporting_snapshot_ids=case.direct_supporting_snapshot_ids,
            predeclared_invalidation_matches=case.predeclared_invalidation_matches,
            critic_passed=case.critic_passed,
            clue_features=case.clue_features,
            has_source_conflict=case.has_source_conflict,
            newer_authoritative_refutation=case.newer_authoritative_refutation,
            price_or_volume_only=case.price_or_volume_only,
            novel_unsupported_event=case.novel_unsupported_event,
        )
        auxiliary_ok = (
            trace.source_tiers == case.expected_tiers
            and trace.clue_score == case.expected_score
            and trace.clue_route is case.expected_route
            and _auxiliary_label_passes(case, trace)
        )
        if auxiliary_ok:
            auxiliary_passes += 1
        outcome_ok = trace.anomaly_class is case.expected_class
        if case.category in _POSITIVE and trace.anomaly_class is AnomalyClass.WOULD_BE_HARD:
            positive_passes += 1
        if case.category not in _POSITIVE and trace.anomaly_class is AnomalyClass.WOULD_BE_HARD:
            false_hard += 1
        if not outcome_ok or not auxiliary_ok:
            failures.append(case.case_id)
    counts = tuple((category.value, category_counter[category]) for category, _ in _EXPECTED_COUNTS)
    shape_ok = (
        len(cases) == 100
        and versions == {"anomaly-qualification-v1"}
        and len(version_tuples) == 1
        and all(category_counter[category] == expected for category, expected in _EXPECTED_COUNTS)
        and len({case.company_id for case in cases}) >= 10
        and len({case.industry for case in cases}) >= 5
    )
    passed = (
        shape_ok
        and positive_passes == 40
        and false_hard == 0
        and auxiliary_passes == 100
        and not failures
    )
    return OfflineQualificationResult(
        dataset_version=next(iter(versions)) if len(versions) == 1 else "invalid",
        versions=next(iter(version_tuples)) if len(version_tuples) == 1 else None,
        passed=passed,
        total_cases=len(cases),
        hard_positive_passes=positive_passes,
        false_hard_count=false_hard,
        auxiliary_label_passes=auxiliary_passes,
        company_count=len({case.company_id for case in cases}),
        industry_count=len({case.industry for case in cases}),
        category_counts=counts,
        failure_case_ids=tuple(failures),
    )
