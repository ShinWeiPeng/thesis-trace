from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    DimensionFacts,
    EvidenceStage,
    EvidenceStageRecord,
    SourceConfirmation,
    StageActorContext,
)
from thesis_trace.modules.research.evidence_stage.service import EvidenceStageService, derive_stage
from thesis_trace.application.flows.evidence_stage import (
    ConfirmEvidenceStageRequest,
    EvidenceStageFlow,
    EvidenceStageResult,
    QueryEvidenceStageRequest,
)
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research import ResearchStageFacade
from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot
from thesis_trace.modules.research.evidence_intake.contracts import EvidenceRecord, EvidenceStatus
from thesis_trace.platform.in_memory import InMemoryEvidenceStore


def test_unverified_source_stays_e0_and_records_every_gate() -> None:
    result = derive_stage(
        DimensionFacts(
            source_confirmation=SourceConfirmation.UNVERIFIED,
            product_established=True,
            commercialization_established=True,
            identifiable_revenue=True,
            identifiable_profit_or_cash_flow=True,
            consecutive_financial_quarters=2,
        )
    )

    assert result.stage is EvidenceStage.E0
    assert [(gate.gate, gate.passed) for gate in result.gate_trace] == [
        (EvidenceStage.E1, False),
        (EvidenceStage.E2, False),
        (EvidenceStage.E3, False),
        (EvidenceStage.E4, False),
        (EvidenceStage.E5, False),
        (EvidenceStage.E6, False),
    ]
    assert result.abstention_code is None


def test_invalid_negative_quarter_count_abstains() -> None:
    result = derive_stage(
        DimensionFacts(
            source_confirmation=SourceConfirmation.OFFICIAL,
            product_established=True,
            commercialization_established=True,
            identifiable_revenue=True,
            identifiable_profit_or_cash_flow=True,
            consecutive_financial_quarters=-1,
        )
    )

    assert result.stage is EvidenceStage.E0
    assert result.gate_trace == ()
    assert result.abstention_code == "invalid_consecutive_financial_quarters"


def test_every_sequential_gate_boundary_derives_exactly_e0_through_e6() -> None:
    vectors = (
        (EvidenceStage.E0, DimensionFacts(SourceConfirmation.UNVERIFIED, True, True, True, True, 2)),
        (EvidenceStage.E1, DimensionFacts(SourceConfirmation.OFFICIAL, False, True, True, True, 2)),
        (EvidenceStage.E2, DimensionFacts(SourceConfirmation.OFFICIAL, True, False, True, True, 2)),
        (EvidenceStage.E3, DimensionFacts(SourceConfirmation.OFFICIAL, True, True, False, True, 2)),
        (EvidenceStage.E4, DimensionFacts(SourceConfirmation.OFFICIAL, True, True, True, False, 2)),
        (EvidenceStage.E5, DimensionFacts(SourceConfirmation.OFFICIAL, True, True, True, True, 1)),
        (EvidenceStage.E6, DimensionFacts(SourceConfirmation.OFFICIAL, True, True, True, True, 2)),
    )

    for expected, facts in vectors:
        evaluation = derive_stage(facts)
        assert evaluation.stage is expected
        assert tuple(result.gate for result in evaluation.gate_trace) == tuple(EvidenceStage)[1:]
        passed_count = int(expected.value[1:])
        assert [result.passed for result in evaluation.gate_trace] == [
            index <= passed_count for index in range(1, 7)
        ]


class RecordingStageStore:
    def __init__(self) -> None:
        self.confirmations = 0

    def commit_confirmation(self, **_values: object) -> EvidenceStageRecord:
        self.confirmations += 1
        raise AssertionError("unauthorized command reached the persistence port")


def test_non_owner_cannot_reach_stage_persistence() -> None:
    store = RecordingStageStore()
    service = EvidenceStageService(store=store, clock=lambda: "2026-08-20T12:00:00+00:00")
    command = ConfirmDimensionFactsCommand(
        actor=StageActorContext(actor_id="learner-1", may_confirm=False, may_read=True),
        evidence_id="evidence-1",
        source_snapshot_id="snapshot-1",
        expected_version=0,
        facts=DimensionFacts(
            source_confirmation=SourceConfirmation.OFFICIAL,
            product_established=False,
            commercialization_established=False,
            identifiable_revenue=False,
            identifiable_profit_or_cash_flow=False,
            consecutive_financial_quarters=0,
        ),
        reason="reviewed source",
        idempotency_key="confirm-1",
    )

    try:
        service.confirm(command)
    except PermissionError as error:
        assert str(error) == "forbidden"
    else:
        raise AssertionError("non-owner confirmation was accepted")
    assert store.confirmations == 0


def test_two_independent_sources_fail_closed_until_two_snapshot_references_exist() -> None:
    store = RecordingStageStore()
    service = EvidenceStageService(store=store, clock=lambda: "2026-08-20T12:00:00+00:00")
    command = ConfirmDimensionFactsCommand(
        actor=StageActorContext(actor_id="owner-1", may_confirm=True, may_read=True),
        evidence_id="evidence-1",
        source_snapshot_id="snapshot-1",
        expected_version=0,
        facts=DimensionFacts(
            SourceConfirmation.TWO_INDEPENDENT_CREDIBLE,
            product_established=False,
            commercialization_established=False,
            identifiable_revenue=False,
            identifiable_profit_or_cash_flow=False,
            consecutive_financial_quarters=0,
        ),
        reason="only one immutable snapshot is supplied",
        idempotency_key="confirm-two-source-1",
    )

    try:
        service.confirm(command)
    except ValueError as error:
        assert str(error) == "insufficient_independent_sources"
    else:
        raise AssertionError("one snapshot falsely satisfied two-source confirmation")
    assert store.confirmations == 0


def test_owner_confirmation_persists_server_derived_e6_version() -> None:
    store = InMemoryEvidenceStore()
    store.records["evidence-1"] = EvidenceRecord(
        evidence_id="evidence-1",
        version=3,
        company_id="2330",
        company_version=1,
        url="https://example.com/disclosure",
        status=EvidenceStatus.SUCCEEDED,
    )
    store.source_snapshots["evidence-1"] = CollectedSourceSnapshot(
        canonical_url="https://example.com/disclosure",
        publisher="Example Exchange",
        content_hash="abc123",
        retrieved_at="2026-08-20T10:00:00+00:00",
        normalization_policy_version="url-normalization-v1",
    )
    service = EvidenceStageService(store=store, clock=lambda: "2026-08-20T12:00:00+00:00")

    command = ConfirmDimensionFactsCommand(
            actor=StageActorContext(actor_id="owner-1", may_confirm=True, may_read=True),
            evidence_id="evidence-1",
            source_snapshot_id="evidence-1",
            expected_version=0,
            facts=DimensionFacts(
                source_confirmation=SourceConfirmation.OFFICIAL,
                product_established=True,
                commercialization_established=True,
                identifiable_revenue=True,
                identifiable_profit_or_cash_flow=True,
                consecutive_financial_quarters=2,
            ),
            reason="confirmed against the immutable disclosure",
            idempotency_key="confirm-1",
    )
    record = service.confirm(command)

    assert record.version == 1
    assert record.evaluation.stage is EvidenceStage.E6
    assert len(record.evaluation.gate_trace) == 6
    assert record.actor_id == "owner-1"
    assert record.reason == "confirmed against the immutable disclosure"
    assert record.policy_version == "e-stage-v1"
    assert service.confirm(command) == record
    try:
        service.confirm(replace(command, reason="a different command with the reused key"))
    except ValueError as error:
        assert str(error) == "idempotency_conflict"
    else:
        raise AssertionError("a conflicting idempotency replay was accepted")

    corrected = service.confirm(
        replace(
            command,
            expected_version=1,
            facts=DimensionFacts(
                SourceConfirmation.UNVERIFIED,
                product_established=False,
                commercialization_established=False,
                identifiable_revenue=False,
                identifiable_profit_or_cash_flow=False,
                consecutive_financial_quarters=0,
            ),
            reason="supporting source was withdrawn",
            idempotency_key="confirm-2",
        )
    )
    assert corrected.version == 2
    assert corrected.evaluation.stage is EvidenceStage.E0
    assert service.get_stage(command.actor, command.evidence_id) == corrected


def test_application_maps_owner_write_and_learner_read_without_cross_domain_types() -> None:
    store = InMemoryEvidenceStore()
    store.records["evidence-1"] = EvidenceRecord(
        "evidence-1", 3, "2330", 1, "https://example.com/disclosure", EvidenceStatus.SUCCEEDED
    )
    store.source_snapshots["evidence-1"] = CollectedSourceSnapshot(
        canonical_url="https://example.com/disclosure",
        publisher="Example Exchange",
        content_hash="abc123",
        retrieved_at="2026-08-20T10:00:00+00:00",
        normalization_policy_version="url-normalization-v1",
    )
    research = ResearchStageFacade(
        EvidenceStageService(store=store, clock=lambda: "2026-08-20T12:00:00+00:00")
    )
    flow = EvidenceStageFlow(research=research)
    owner = AuthenticatedActor("owner-1", Role.OWNER, 1)
    learner = AuthenticatedActor("learner-1", Role.LEARNER, 1)

    confirmed = flow.confirm(owner, ConfirmEvidenceStageRequest(
        evidence_id="evidence-1",
        source_snapshot_id="evidence-1",
        expected_version=0,
        source_confirmation="official",
        product_established=True,
        commercialization_established=False,
        identifiable_revenue=False,
        identifiable_profit_or_cash_flow=False,
        consecutive_financial_quarters=0,
        reason="official product disclosure",
        idempotency_key="confirm-flow-1",
    ))

    assert isinstance(confirmed, EvidenceStageResult)
    assert confirmed.stage == "E2"
    assert flow.get_stage(learner, QueryEvidenceStageRequest("evidence-1")) == confirmed
from dataclasses import replace
