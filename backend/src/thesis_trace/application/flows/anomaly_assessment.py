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
