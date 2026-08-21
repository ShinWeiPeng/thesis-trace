from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyClass,
    AssessmentStatus,
    ClueFeatureVector,
    ClueRoute,
    SourceCharacteristicSnapshot,
    SourceTier,
    EvaluateAssessmentCommand,
    RequestAssessmentCommand,
)
from thesis_trace.modules.research.anomaly_assessment.policy import (
    classify_source,
    evaluate_anomaly,
    score_clue,
)
from thesis_trace.modules.research.anomaly_assessment.service import AnomalyAssessmentService
from thesis_trace.platform.in_memory import InMemoryEvidenceStore


def source(
    source_snapshot_id: str,
    publisher: str,
    *,
    authoritative: bool = False,
    formal: bool = False,
    editorial: bool = False,
    attributed: bool = False,
    primary_evidence: bool = False,
    underlying: str | None = None,
) -> SourceCharacteristicSnapshot:
    return SourceCharacteristicSnapshot(
        source_snapshot_id=source_snapshot_id,
        publisher_identity=publisher,
        authoritative_first_party=authoritative,
        formal_record=formal,
        editorial_responsibility=editorial,
        attributed_author=attributed,
        verifiable_primary_evidence=primary_evidence,
        underlying_evidence_id=underlying,
    )


def test_source_classification_resolves_ambiguity_downward_without_promotion() -> None:
    assert classify_source(source("a", "TWSE", authoritative=True, formal=True)) is SourceTier.A
    assert classify_source(
        source("b", "Publisher", editorial=True, attributed=True, primary_evidence=True)
    ) is SourceTier.B
    assert classify_source(
        source("c", "Publisher", editorial=True, attributed=True, primary_evidence=False)
    ) is SourceTier.C


def test_clue_score_routes_exact_boundaries_and_rejects_invalid_features() -> None:
    assert score_clue(ClueFeatureVector(0, 1, 1, 1, 1)) == (4, ClueRoute.SAVE_ONLY)
    assert score_clue(ClueFeatureVector(1, 1, 1, 1, 1)) == (5, ClueRoute.WATCH_DAILY)
    assert score_clue(ClueFeatureVector(2, 2, 1, 1, 1)) == (7, ClueRoute.WATCH_DAILY)
    assert score_clue(ClueFeatureVector(2, 2, 2, 1, 1)) == (8, ClueRoute.HUMAN_REVIEW)

    try:
        score_clue(ClueFeatureVector(3, 0, 0, 0, 0))
    except ValueError as error:
        assert str(error) == "invalid_clue_feature"
    else:
        raise AssertionError("out-of-range clue feature was scored")


def test_hard_requires_predeclared_invalidation_and_one_direct_a() -> None:
    result = evaluate_anomaly(
        sources=(source("a", "TWSE", authoritative=True, formal=True),),
        direct_supporting_snapshot_ids=("a",),
        predeclared_invalidation_matches=True,
        critic_passed=True,
    )

    assert result.anomaly_class is AnomalyClass.WOULD_BE_HARD
    assert result.source_tiers == (SourceTier.A,)
    assert result.clue_score is None
    assert all(gate.passed for gate in result.gates)


def test_two_b_sources_must_have_distinct_publishers_and_underlying_evidence() -> None:
    independent = (
        source("b1", "Publisher 1", editorial=True, attributed=True, primary_evidence=True, underlying="u1"),
        source("b2", "Publisher 2", editorial=True, attributed=True, primary_evidence=True, underlying="u2"),
    )
    echoed = (
        independent[0],
        source("b3", "Publisher 2", editorial=True, attributed=True, primary_evidence=True, underlying="u1"),
    )

    assert evaluate_anomaly(
        sources=independent,
        direct_supporting_snapshot_ids=("b1", "b2"),
        predeclared_invalidation_matches=True,
        critic_passed=True,
    ).anomaly_class is AnomalyClass.WOULD_BE_HARD
    echoed_result = evaluate_anomaly(
        sources=echoed,
        direct_supporting_snapshot_ids=("b1", "b3"),
        predeclared_invalidation_matches=True,
        critic_passed=True,
    )
    assert echoed_result.anomaly_class is AnomalyClass.SOFT
    assert "source_quorum" in echoed_result.failure_codes


def test_b_quorum_finds_a_valid_independent_pair_regardless_of_source_order() -> None:
    sources = (
        source("b1", "Publisher 1", editorial=True, attributed=True, primary_evidence=True, underlying="u1"),
        source("b2", "Publisher 1", editorial=True, attributed=True, primary_evidence=True, underlying="u2"),
        source("b3", "Publisher 2", editorial=True, attributed=True, primary_evidence=True, underlying="u1"),
    )
    for ordered in (sources, tuple(reversed(sources))):
        result = evaluate_anomaly(
            sources=ordered,
            direct_supporting_snapshot_ids=("b1", "b2", "b3"),
            predeclared_invalidation_matches=True,
            critic_passed=True,
        )
        assert result.anomaly_class is AnomalyClass.WOULD_BE_HARD


def test_every_uncertain_or_critic_failure_path_fails_closed_to_soft() -> None:
    official = source("a", "TWSE", authoritative=True, formal=True)
    cases = (
        {"predeclared_invalidation_matches": False},
        {"critic_passed": False},
        {"has_source_conflict": True},
        {"newer_authoritative_refutation": True},
        {"price_or_volume_only": True},
        {"novel_unsupported_event": True},
    )
    for override in cases:
        values = {
            "sources": (official,),
            "direct_supporting_snapshot_ids": ("a",),
            "predeclared_invalidation_matches": True,
            "critic_passed": True,
        }
        values.update(override)
        result = evaluate_anomaly(**values)
        assert result.anomaly_class is AnomalyClass.SOFT
        assert result.failure_codes


def test_high_scoring_c_clue_routes_review_but_never_satisfies_hard_quorum() -> None:
    result = evaluate_anomaly(
        sources=(source("c", "Forum"),),
        direct_supporting_snapshot_ids=("c",),
        predeclared_invalidation_matches=True,
        critic_passed=True,
        clue_features=ClueFeatureVector(2, 2, 2, 2, 2),
    )

    assert result.source_tiers == (SourceTier.C,)
    assert result.clue_score == 10
    assert result.clue_route is ClueRoute.HUMAN_REVIEW
    assert result.anomaly_class is AnomalyClass.SOFT
    assert "source_quorum" in result.failure_codes


def test_owner_request_and_worker_result_commit_through_public_store_port() -> None:
    store = InMemoryEvidenceStore()
    service = AnomalyAssessmentService(store=store, clock=lambda: "2026-08-21T10:00:00+00:00")
    official = source("snapshot-a", "TWSE", authoritative=True, formal=True)
    requested = service.request(
        RequestAssessmentCommand(
            actor_id="owner-1",
            may_request=True,
            evidence_id="evidence-1",
            expected_evidence_version=3,
            sources=(official,),
            reason="check the predeclared invalidation",
            idempotency_key="assessment-request-1",
        )
    )

    assert requested.status is AssessmentStatus.PENDING
    assert requested.version == 1
    job = store.claim_anomaly_job()
    assert job is not None
    completed = service.evaluate(
        EvaluateAssessmentCommand(
            assessment_id=requested.assessment_id,
            lease_token=job.lease_token or "",
            expected_assessment_version=1,
            sources=(official,),
            direct_supporting_snapshot_ids=("snapshot-a",),
            predeclared_invalidation_matches=True,
            critic_passed=True,
        )
    )

    assert completed.status is AssessmentStatus.SUCCEEDED
    assert completed.version == 2
    assert completed.trace is not None
    assert completed.trace.anomaly_class is AnomalyClass.WOULD_BE_HARD
    assert service.get(assessment_id=completed.assessment_id, may_read=True) == completed
    assert service.request(
        RequestAssessmentCommand(
            actor_id="owner-1",
            may_request=True,
            evidence_id="evidence-1",
            expected_evidence_version=3,
            sources=(official,),
            reason="check the predeclared invalidation",
            idempotency_key="assessment-request-1",
        )
    ) == requested


def test_stale_worker_result_is_saved_as_superseded_not_current_success() -> None:
    store = InMemoryEvidenceStore()
    service = AnomalyAssessmentService(store=store, clock=lambda: "2026-08-21T10:00:00+00:00")
    official = source("snapshot-a", "TWSE", authoritative=True, formal=True)
    requested = service.request(
        RequestAssessmentCommand(
            "owner-1", True, "evidence-1", 3, (official,), "review", "assessment-request-1"
        )
    )
    job = store.claim_anomaly_job()
    assert job is not None
    store.current_evidence_versions["evidence-1"] = 4

    result = service.evaluate(
        EvaluateAssessmentCommand(
            requested.assessment_id,
            job.lease_token or "",
            1,
            (official,),
            ("snapshot-a",),
            True,
            True,
        )
    )

    assert result.status is AssessmentStatus.SUPERSEDED
    assert result.trace is not None
    assert result.trace.anomaly_class is AnomalyClass.WOULD_BE_HARD
