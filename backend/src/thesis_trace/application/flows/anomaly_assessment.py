from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from thesis_trace.application.ai_ports import (
    AnalysisSource,
    RecommendationCriticPort,
    RecommendationCriticRequest,
    RecommendationProviderPort,
    RecommendationProviderRequest,
    ValidatedAnomalyCandidate,
    validate_anomaly_candidate,
    validate_critic_pass,
)

from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research import (
    ResearchActorContext,
    ResearchAnomalyFacade,
    ResearchAnomalyRequest,
    ResearchAnomalyResult,
    ResearchAnomalySource,
    ResearchValidatedAnomalyCandidate,
)
from thesis_trace.modules.workflow.contracts import (
    ActionInboxQuery,
    ActionItem,
    ActionItemStatus,
    ActionSourceRef,
    CreateActionItemCommand,
    TransitionActionItemCommand,
    WorkflowActorContext,
)
from thesis_trace.modules.workflow.service import WorkflowService


@dataclass(frozen=True, slots=True)
class AnomalySourceInput:
    source_snapshot_id: str


@dataclass(frozen=True, slots=True)
class RequestAnomalyAssessment:
    evidence_id: str
    expected_evidence_version: int
    sources: tuple[AnomalySourceInput, ...]
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class AnomalyGateResult:
    gate: str
    passed: bool
    code: str


@dataclass(frozen=True, slots=True)
class AnomalyTraceResult:
    anomaly_class: str
    source_tiers: tuple[str, ...]
    clue_score: int | None
    clue_route: str | None
    gates: tuple[AnomalyGateResult, ...]
    policy_version: str


@dataclass(frozen=True, slots=True)
class AnomalyAssessmentResult:
    assessment_id: str
    version: int
    evidence_id: str
    evidence_version: int
    source_snapshot_ids: tuple[str, ...]
    status: str
    requested_at: str
    trace: AnomalyTraceResult | None
    failure_code: str | None


class AnomalyAssessmentFlow:
    """L0 actor and result mapping for anomaly admission and query."""

    def __init__(self, *, research: ResearchAnomalyFacade) -> None:
        self._research = research

    @staticmethod
    def _actor(actor: AuthenticatedActor) -> ResearchActorContext:
        return ResearchActorContext(
            actor_id=actor.actor_id,
            may_confirm_evidence_stage=False,
            may_read_evidence_stage=False,
            may_request_anomaly_assessment=actor.role is Role.OWNER,
            may_read_anomaly_assessment=actor.role in {Role.OWNER, Role.LEARNER},
        )

    @staticmethod
    def _result(record: ResearchAnomalyResult) -> AnomalyAssessmentResult:
        trace = None
        if record.trace is not None:
            trace = AnomalyTraceResult(
                anomaly_class=record.trace.anomaly_class,
                source_tiers=record.trace.source_tiers,
                clue_score=record.trace.clue_score,
                clue_route=record.trace.clue_route,
                gates=tuple(
                    AnomalyGateResult(item.gate, item.passed, item.code)
                    for item in record.trace.gates
                ),
                policy_version=record.trace.policy_version,
            )
        return AnomalyAssessmentResult(
            assessment_id=record.assessment_id,
            version=record.version,
            evidence_id=record.evidence_id,
            evidence_version=record.evidence_version,
            source_snapshot_ids=record.source_snapshot_ids,
            status=record.status,
            requested_at=record.requested_at,
            trace=trace,
            failure_code=record.failure_code,
        )

    def request(
        self, actor: AuthenticatedActor, request: RequestAnomalyAssessment
    ) -> AnomalyAssessmentResult:
        return self._result(
            self._research.request(
                self._actor(actor),
                ResearchAnomalyRequest(
                    evidence_id=request.evidence_id,
                    expected_evidence_version=request.expected_evidence_version,
                    sources=tuple(
                        ResearchAnomalySource(
                            item.source_snapshot_id,
                            "",
                            False,
                            False,
                            False,
                            False,
                            False,
                            None,
                        )
                        for item in request.sources
                    ),
                    reason=request.reason,
                    idempotency_key=request.idempotency_key,
                ),
            )
        )

    def get(self, actor: AuthenticatedActor, assessment_id: str) -> AnomalyAssessmentResult:
        return self._result(self._research.get(self._actor(actor), assessment_id))


@dataclass(frozen=True, slots=True)
class CreateAnomalyReviewActionRequest:
    assessment_id: str
    expected_assessment_version: int
    reason: str
    due_at: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class QueryActionInboxRequest:
    search: str | None = None
    company_id: str | None = None
    item_type: str | None = None
    status: str | None = None
    priority: str | None = None
    created_from: str | None = None
    created_to: str | None = None
    due_from: str | None = None
    due_to: str | None = None
    open_only: bool = True
    sort: str = "effective_priority"
    direction: str = "desc"
    page_size: int = 25
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class QueryActionItemRequest:
    item_id: str


@dataclass(frozen=True, slots=True)
class TransitionActionItemRequest:
    item_id: str
    expected_version: int
    target_status: str
    reason: str
    defer_until: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ActionItemResult:
    item_id: str
    version: int
    item_type: str
    source_domain: str
    source_record_id: str
    source_version: int
    company_id: str
    company_ticker: str
    company_name: str
    reason: str
    status: str
    system_priority: str
    effective_priority: str
    safety_floor: str | None
    safety_locked: bool
    priority_rule_ids: tuple[str, ...]
    priority_policy_version: str
    priority_reason: str
    created_at: str
    updated_at: str
    due_at: str | None
    defer_until: str | None
    recurrence_of: str | None
    allowed_transitions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActionInboxResult:
    urgent: int
    due_today: int
    deferred: int
    all_open: int
    total_count: int
    items: tuple[ActionItemResult, ...]
    next_cursor: str | None
    as_of: str


class ActionInboxFlow:
    """L0 mapping between immutable Research context and Workflow policy."""

    def __init__(self, *, research: ResearchAnomalyFacade, workflow: WorkflowService, clock: Callable[[], str]) -> None:
        self._research = research
        self._workflow = workflow
        self._clock = clock

    @staticmethod
    def _research_actor(actor: AuthenticatedActor) -> ResearchActorContext:
        return ResearchActorContext(
            actor_id=actor.actor_id,
            may_confirm_evidence_stage=False,
            may_read_evidence_stage=False,
            may_request_anomaly_assessment=False,
            may_read_anomaly_assessment=actor.role in {Role.OWNER, Role.LEARNER},
        )

    @staticmethod
    def _workflow_actor(actor: AuthenticatedActor) -> WorkflowActorContext:
        return WorkflowActorContext(
            actor_id=actor.actor_id,
            may_create=actor.role is Role.OWNER,
            may_read=actor.role in {Role.OWNER, Role.LEARNER},
            may_transition=actor.role in {Role.OWNER, Role.LEARNER},
        )

    @staticmethod
    def _result(item: ActionItem) -> ActionItemResult:
        return ActionItemResult(
            item_id=item.item_id, version=item.version, item_type=item.item_type.value,
            source_domain=item.source_domain, source_record_id=item.source_record_id,
            source_version=item.source_version, company_id=item.company_id,
            company_ticker=item.company_ticker, company_name=item.company_name,
            reason=item.reason, status=item.status.value,
            system_priority=item.priority.system_priority.value,
            effective_priority=item.priority.effective_priority.value,
            safety_floor=None if item.priority.safety_floor is None else item.priority.safety_floor.value,
            safety_locked=item.priority.safety_locked, priority_rule_ids=item.priority.rule_ids,
            priority_policy_version=item.priority.policy_version,
            priority_reason=item.priority.reason, created_at=item.created_at,
            updated_at=item.updated_at, due_at=item.due_at, defer_until=item.defer_until,
            recurrence_of=item.recurrence_of,
            allowed_transitions=tuple(value.value for value in item.allowed_transitions),
        )

    def create(self, actor: AuthenticatedActor, request: CreateAnomalyReviewActionRequest) -> ActionItemResult:
        if actor.role is not Role.OWNER:
            raise PermissionError("forbidden")
        anomaly = self._research.get(self._research_actor(actor), request.assessment_id)
        if anomaly.actor_id != actor.actor_id:
            raise PermissionError("forbidden")
        if anomaly.version != request.expected_assessment_version:
            raise ValueError("version_conflict")
        if (
            anomaly.status != "succeeded" or anomaly.trace is None
            or not anomaly.company_id or not anomaly.company_ticker or not anomaly.company_name
            or not (anomaly.trace.anomaly_class == "would_be_hard" or anomaly.trace.clue_route == "human_review")
        ):
            raise LookupError("resource_unavailable")
        required_handling = (
            "would_be_hard" if anomaly.trace.anomaly_class == "would_be_hard" else "human_review"
        )
        return self._result(self._workflow.create(CreateActionItemCommand(
            actor=self._workflow_actor(actor),
            source=ActionSourceRef(
                source_domain="anomaly_assessment", source_record_id=anomaly.assessment_id,
                source_version=anomaly.version, source_owner_id=anomaly.actor_id,
                company_id=anomaly.company_id, company_ticker=anomaly.company_ticker,
                company_name=anomaly.company_name, trigger_kind=WorkflowService.CREATION_RULE_VERSION,
                required_handling=required_handling,
            ),
            reason=request.reason, due_at=request.due_at, idempotency_key=request.idempotency_key,
        )))

    def query(self, actor: AuthenticatedActor, request: QueryActionInboxRequest) -> ActionInboxResult:
        page = self._workflow.query(ActionInboxQuery(
            actor=self._workflow_actor(actor), search=request.search, company_id=request.company_id,
            item_type=request.item_type, status=request.status, priority=request.priority,
            created_from=request.created_from, created_to=request.created_to,
            due_from=request.due_from, due_to=request.due_to, open_only=request.open_only,
            sort=request.sort, direction=request.direction, page_size=request.page_size,
            cursor=request.cursor,
        ))
        return ActionInboxResult(
            page.summary.urgent, page.summary.due_today, page.summary.deferred,
            page.summary.all_open, page.total_count,
            tuple(self._result(item) for item in page.items), page.next_cursor, page.as_of,
        )

    def get(self, actor: AuthenticatedActor, request: QueryActionItemRequest) -> ActionItemResult:
        return self._result(self._workflow.get(self._workflow_actor(actor), request.item_id))

    def transition(self, actor: AuthenticatedActor, request: TransitionActionItemRequest) -> ActionItemResult:
        return self._result(self._workflow.transition(TransitionActionItemCommand(
            actor=self._workflow_actor(actor), item_id=request.item_id,
            expected_version=request.expected_version, target_status=ActionItemStatus(request.target_status),
            reason=request.reason, defer_until=request.defer_until,
            idempotency_key=request.idempotency_key, server_time=self._clock(),
            underlying_resolved=False,
        )))


class AnomalyJobProcessor:
    """Lease one job and map untrusted AI bytes into fail-closed Research facts."""

    def __init__(
        self,
        *,
        research: ResearchAnomalyFacade,
        provider: RecommendationProviderPort,
        critic: RecommendationCriticPort,
        invalidation_match: Callable[[str], bool] | None = None,
    ) -> None:
        self._research = research
        self._provider = provider
        self._critic = critic
        self._invalidation_match = invalidation_match or (lambda _assessment_id: False)

    @staticmethod
    def _source(item: ResearchAnomalySource) -> AnalysisSource:
        return AnalysisSource(
            source_snapshot_id=item.source_snapshot_id,
            publisher_identity=item.publisher_identity,
            source_tier_facts=(
                item.authoritative_first_party,
                item.formal_record,
                item.editorial_responsibility,
                item.attributed_author,
                item.verifiable_primary_evidence,
            ),
            underlying_evidence_id=item.underlying_evidence_id,
            canonical_url=item.canonical_url,
            excerpt=item.excerpt,
            retrieved_at=item.retrieved_at,
            published_at=item.published_at,
            observed_at=item.observed_at,
        )

    @staticmethod
    def _failed_candidate() -> ValidatedAnomalyCandidate:
        return ValidatedAnomalyCandidate(
            schema_version="anomaly-candidate-v1",
            direct_supporting_snapshot_ids=(),
            clue_features=None,
            has_source_conflict=False,
            newer_authoritative_refutation=False,
            price_or_volume_only=False,
            novel_unsupported_event=False,
        )

    def run_once(self) -> bool:
        job = self._research.claim()
        if job is None:
            return False
        sources = tuple(self._source(item) for item in self._research.load_sources(job.assessment_id))
        candidate = self._failed_candidate()
        critic_passed = False
        try:
            candidate_json = self._provider.analyze(
                RecommendationProviderRequest(
                    assessment_id=job.assessment_id,
                    evidence_id=job.evidence_id,
                    evidence_version=job.evidence_version,
                    sources=sources,
                    schema_version=job.candidate_schema_version,
                    prompt_version=job.candidate_prompt_version,
                    model_version=job.provider_model_version,
                )
            )
            candidate = validate_anomaly_candidate(
                candidate_json,
                sources=sources,
            )
            critic_passed = validate_critic_pass(
                self._critic.criticize(
                    RecommendationCriticRequest(
                        assessment_id=job.assessment_id,
                        sources=sources,
                        candidate_json=candidate_json,
                        schema_version=job.critic_schema_version,
                        prompt_version=job.critic_prompt_version,
                        model_version=job.critic_model_version,
                    )
                )
            )
        except Exception:
            critic_passed = False
        self._research.evaluate(
            job,
            ResearchValidatedAnomalyCandidate(
                candidate_schema_version=candidate.schema_version,
                critic_schema_version=job.critic_schema_version,
                critic_passed=critic_passed,
                direct_supporting_snapshot_ids=candidate.direct_supporting_snapshot_ids,
                clue_features=candidate.clue_features,
                has_source_conflict=candidate.has_source_conflict,
                newer_authoritative_refutation=candidate.newer_authoritative_refutation,
                price_or_volume_only=candidate.price_or_volume_only,
                novel_unsupported_event=candidate.novel_unsupported_event,
            ),
            predeclared_invalidation_matches=self._invalidation_match(job.assessment_id),
        )
        return True
