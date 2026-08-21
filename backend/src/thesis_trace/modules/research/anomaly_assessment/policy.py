from __future__ import annotations

from itertools import combinations

from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyClass,
    AnomalyDecisionTrace,
    ClueFeatureVector,
    ClueRoute,
    DecisionGate,
    SourceCharacteristicSnapshot,
    SourceTier,
)


ANOMALY_POLICY_VERSION = "anomaly-policy-v1"


def classify_source(source: SourceCharacteristicSnapshot) -> SourceTier:
    if source.authoritative_first_party and source.formal_record:
        return SourceTier.A
    if (
        source.editorial_responsibility
        and source.attributed_author
        and source.verifiable_primary_evidence
    ):
        return SourceTier.B
    return SourceTier.C


def score_clue(features: ClueFeatureVector) -> tuple[int, ClueRoute]:
    values = (
        features.timeliness,
        features.traceability,
        features.specificity,
        features.corroboration,
        features.invalidation_relevance,
    )
    if any(isinstance(value, bool) or value < 0 or value > 2 for value in values):
        raise ValueError("invalid_clue_feature")
    score = sum(values)
    if score <= 4:
        return score, ClueRoute.SAVE_ONLY
    if score <= 7:
        return score, ClueRoute.WATCH_DAILY
    return score, ClueRoute.HUMAN_REVIEW


def _has_source_quorum(
    sources: tuple[SourceCharacteristicSnapshot, ...],
    tiers: tuple[SourceTier, ...],
    direct_supporting_snapshot_ids: frozenset[str],
) -> bool:
    direct_a = any(
        tier is SourceTier.A and source.source_snapshot_id in direct_supporting_snapshot_ids
        for source, tier in zip(sources, tiers, strict=True)
    )
    if direct_a:
        return True
    eligible_b: set[tuple[str, str]] = set()
    for source, tier in zip(sources, tiers, strict=True):
        if tier is not SourceTier.B or source.source_snapshot_id not in direct_supporting_snapshot_ids:
            continue
        publisher = source.publisher_identity.strip().casefold()
        evidence = (source.underlying_evidence_id or "").strip().casefold()
        if publisher and evidence:
            eligible_b.add((publisher, evidence))
    return any(
        left[0] != right[0] and left[1] != right[1]
        for left, right in combinations(eligible_b, 2)
    )


def evaluate_anomaly(
    *,
    sources: tuple[SourceCharacteristicSnapshot, ...],
    direct_supporting_snapshot_ids: tuple[str, ...],
    predeclared_invalidation_matches: bool,
    critic_passed: bool,
    clue_features: ClueFeatureVector | None = None,
    has_source_conflict: bool = False,
    newer_authoritative_refutation: bool = False,
    price_or_volume_only: bool = False,
    novel_unsupported_event: bool = False,
) -> AnomalyDecisionTrace:
    if not sources:
        raise ValueError("missing_sources")
    if len({source.source_snapshot_id for source in sources}) != len(sources):
        raise ValueError("duplicate_source_snapshot")
    tiers = tuple(classify_source(source) for source in sources)
    clue_score: int | None = None
    clue_route: ClueRoute | None = None
    if SourceTier.C in tiers and clue_features is not None and critic_passed:
        clue_score, clue_route = score_clue(clue_features)
    quorum = _has_source_quorum(sources, tiers, frozenset(direct_supporting_snapshot_ids))
    checks = (
        ("predeclared_invalidation", predeclared_invalidation_matches),
        ("source_quorum", quorum),
        ("critic", critic_passed),
        ("source_conflict", not has_source_conflict),
        ("newer_authoritative_refutation", not newer_authoritative_refutation),
        ("market_only", not price_or_volume_only),
        ("novel_unsupported", not novel_unsupported_event),
    )
    gates = tuple(
        DecisionGate(gate=name, passed=passed, code="passed" if passed else "fail_closed")
        for name, passed in checks
    )
    anomaly_class = (
        AnomalyClass.WOULD_BE_HARD if all(gate.passed for gate in gates) else AnomalyClass.SOFT
    )
    return AnomalyDecisionTrace(
        anomaly_class=anomaly_class,
        source_tiers=tiers,
        clue_score=clue_score,
        clue_route=clue_route,
        gates=gates,
        policy_version=ANOMALY_POLICY_VERSION,
    )
