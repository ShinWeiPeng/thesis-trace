"""Research-domain parent mappings and public orchestration facade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    DimensionFacts,
    EvidenceStageRecord,
    SourceConfirmation,
    StageActorContext,
)
from thesis_trace.modules.research.evidence_stage.service import EvidenceStageService
from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyAnalysisJob,
    AnomalyAssessmentRecord,
    ClueFeatureVector,
    EvaluateAssessmentCommand,
    RequestAssessmentCommand,
    SourceCharacteristicSnapshot,
)
from thesis_trace.modules.research.anomaly_assessment.service import (
    AnomalyAssessmentService,
)


@dataclass(frozen=True, slots=True)
class ResearchRecordReference:
    record_type: str
    record_id: str
    version: int
    company_id: str


@dataclass(frozen=True, slots=True)
class ResearchActorContext:
    actor_id: str
    may_confirm_evidence_stage: bool
    may_read_evidence_stage: bool
    may_request_anomaly_assessment: bool = False
    may_read_anomaly_assessment: bool = False


@dataclass(frozen=True, slots=True)
class ResearchRecommendationSource:
    evidence: ResearchRecordReference
    snapshot_id: str
    canonical_url: str
    publisher: str
    excerpt: str | None
    source_category: str
    lineage: str | None
    published_at: datetime | None
    observed_at: datetime | None
    retrieved_at: datetime
    stage_version: int | None
    stage: str | None
    stage_source_id: str | None
    stage_digest: str | None


class ResearchRecommendationQueryPort(Protocol):
    def get_recommendation_source(
        self, evidence_id: str
    ) -> ResearchRecommendationSource | None: ...

    def get_recommendation_fact(
        self, evidence_id: str, fact_id: str
    ) -> tuple[ResearchRecordReference, str] | None: ...


class ResearchRecommendationFacade:
    """Research-owned provenance read; L0 maps the result into its other children."""

    def __init__(self, queries: ResearchRecommendationQueryPort) -> None:
        self._queries = queries

    def get_source(
        self, actor: ResearchActorContext, evidence_id: str
    ) -> ResearchRecommendationSource:
        if not actor.actor_id or actor.may_read_evidence_stage is not True:
            raise PermissionError("resource_unavailable")
        source = self._queries.get_recommendation_source(evidence_id)
        if (
            source is None
            or source.evidence.record_type != "evidence"
            or source.evidence.record_id != evidence_id
        ):
            raise LookupError("resource_unavailable")
        return source

    def get_fact_binding(
        self, actor: ResearchActorContext, evidence_id: str, fact_id: str
    ) -> tuple[ResearchRecordReference, str]:
        if not actor.actor_id or actor.may_read_evidence_stage is not True:
            raise PermissionError("resource_unavailable")
        result = self._queries.get_recommendation_fact(evidence_id, fact_id)
        if (
            result is None
            or result[0].record_type != "valuation_fact"
            or result[0].record_id != fact_id
        ):
            raise LookupError("resource_unavailable")
        return result


@dataclass(frozen=True, slots=True)
class ResearchStageConfirmationRequest:
    evidence_id: str
    source_snapshot_id: str
    expected_version: int
    source_confirmation: str
    product_established: bool
    commercialization_established: bool
    identifiable_revenue: bool
    identifiable_profit_or_cash_flow: bool
    consecutive_financial_quarters: int
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResearchStageQuery:
    evidence_id: str


@dataclass(frozen=True, slots=True)
class ResearchStageFacts:
    source_confirmation: str
    product_established: bool
    commercialization_established: bool
    identifiable_revenue: bool
    identifiable_profit_or_cash_flow: bool
    consecutive_financial_quarters: int


@dataclass(frozen=True, slots=True)
class ResearchStageGate:
    gate: str
    passed: bool
    code: str


@dataclass(frozen=True, slots=True)
class ResearchStageResult:
    evidence_id: str
    version: int
    source_snapshot_id: str
    actor_id: str
    confirmed_at: str
    reason: str
    facts: ResearchStageFacts
    stage: str
    gate_trace: tuple[ResearchStageGate, ...]
    policy_version: str


class ResearchStageFacade:
    """Map Research-parent primitives into the Evidence Stage child boundary."""

    def __init__(self, service: EvidenceStageService) -> None:
        self._service = service

    @staticmethod
    def _stage_actor(actor: ResearchActorContext) -> StageActorContext:
        return StageActorContext(
            actor_id=actor.actor_id,
            may_confirm=actor.may_confirm_evidence_stage,
            may_read=actor.may_read_evidence_stage,
        )

    @staticmethod
    def _result(record: EvidenceStageRecord) -> ResearchStageResult:
        return ResearchStageResult(
            evidence_id=record.evidence_id,
            version=record.version,
            source_snapshot_id=record.source_snapshot_id,
            actor_id=record.actor_id,
            confirmed_at=record.confirmed_at,
            reason=record.reason,
            facts=ResearchStageFacts(
                source_confirmation=record.facts.source_confirmation.value,
                product_established=record.facts.product_established,
                commercialization_established=record.facts.commercialization_established,
                identifiable_revenue=record.facts.identifiable_revenue,
                identifiable_profit_or_cash_flow=record.facts.identifiable_profit_or_cash_flow,
                consecutive_financial_quarters=record.facts.consecutive_financial_quarters,
            ),
            stage=record.evaluation.stage.value,
            gate_trace=tuple(
                ResearchStageGate(item.gate.value, item.passed, item.code)
                for item in record.evaluation.gate_trace
            ),
            policy_version=record.policy_version,
        )

    def confirm(
        self,
        actor: ResearchActorContext,
        request: ResearchStageConfirmationRequest,
    ) -> ResearchStageResult:
        record = self._service.confirm(
            ConfirmDimensionFactsCommand(
                actor=self._stage_actor(actor),
                evidence_id=request.evidence_id,
                source_snapshot_id=request.source_snapshot_id,
                expected_version=request.expected_version,
                facts=DimensionFacts(
                    source_confirmation=SourceConfirmation(request.source_confirmation),
                    product_established=request.product_established,
                    commercialization_established=request.commercialization_established,
                    identifiable_revenue=request.identifiable_revenue,
                    identifiable_profit_or_cash_flow=request.identifiable_profit_or_cash_flow,
                    consecutive_financial_quarters=request.consecutive_financial_quarters,
                ),
                reason=request.reason,
                idempotency_key=request.idempotency_key,
            )
        )
        return self._result(record)

    def get_stage(
        self, actor: ResearchActorContext, query: ResearchStageQuery
    ) -> ResearchStageResult:
        return self._result(
            self._service.get_stage(self._stage_actor(actor), query.evidence_id)
        )


@dataclass(frozen=True, slots=True)
class ResearchAnomalySource:
    source_snapshot_id: str
    publisher_identity: str
    authoritative_first_party: bool
    formal_record: bool
    editorial_responsibility: bool
    attributed_author: bool
    verifiable_primary_evidence: bool
    underlying_evidence_id: str | None
    canonical_url: str | None = None
    excerpt: str | None = None
    retrieved_at: str | None = None
    published_at: str | None = None
    observed_at: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchAnomalyRequest:
    evidence_id: str
    expected_evidence_version: int
    sources: tuple[ResearchAnomalySource, ...]
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResearchValidatedAnomalyCandidate:
    candidate_schema_version: str
    critic_schema_version: str
    critic_passed: bool
    direct_supporting_snapshot_ids: tuple[str, ...] = ()
    clue_features: tuple[int, int, int, int, int] | None = None
    has_source_conflict: bool = False
    newer_authoritative_refutation: bool = False
    price_or_volume_only: bool = False
    novel_unsupported_event: bool = False


@dataclass(frozen=True, slots=True)
class ResearchAnomalyJob:
    assessment_id: str
    assessment_version: int
    evidence_id: str
    evidence_version: int
    lease_token: str
    build_version: str
    policy_version: str
    candidate_schema_version: str
    candidate_prompt_version: str
    provider_model_version: str
    critic_schema_version: str
    critic_prompt_version: str
    critic_model_version: str


@dataclass(frozen=True, slots=True)
class ResearchAnomalyGate:
    gate: str
    passed: bool
    code: str


@dataclass(frozen=True, slots=True)
class ResearchAnomalyTrace:
    anomaly_class: str
    source_tiers: tuple[str, ...]
    clue_score: int | None
    clue_route: str | None
    gates: tuple[ResearchAnomalyGate, ...]
    policy_version: str


@dataclass(frozen=True, slots=True)
class ResearchAnomalyResult:
    assessment_id: str
    version: int
    evidence_id: str
    evidence_version: int
    source_snapshot_ids: tuple[str, ...]
    status: str
    requested_at: str
    trace: ResearchAnomalyTrace | None
    failure_code: str | None
    actor_id: str = ""
    company_id: str = ""
    company_ticker: str = ""
    company_name: str = ""


class ResearchAnomalyFacade:
    """Map Research-parent primitives into the anomaly child boundary."""

    def __init__(self, service: AnomalyAssessmentService) -> None:
        self._service = service

    @staticmethod
    def _sources(
        sources: tuple[ResearchAnomalySource, ...],
    ) -> tuple[SourceCharacteristicSnapshot, ...]:
        return tuple(
            SourceCharacteristicSnapshot(
                source_snapshot_id=item.source_snapshot_id,
                publisher_identity=item.publisher_identity,
                authoritative_first_party=item.authoritative_first_party,
                formal_record=item.formal_record,
                editorial_responsibility=item.editorial_responsibility,
                attributed_author=item.attributed_author,
                verifiable_primary_evidence=item.verifiable_primary_evidence,
                underlying_evidence_id=item.underlying_evidence_id,
                canonical_url=item.canonical_url,
                excerpt=item.excerpt,
                retrieved_at=item.retrieved_at,
                published_at=item.published_at,
                observed_at=item.observed_at,
            )
            for item in sources
        )

    @staticmethod
    def _result(record: AnomalyAssessmentRecord) -> ResearchAnomalyResult:
        trace = None
        if record.trace is not None:
            trace = ResearchAnomalyTrace(
                anomaly_class=record.trace.anomaly_class.value,
                source_tiers=tuple(item.value for item in record.trace.source_tiers),
                clue_score=record.trace.clue_score,
                clue_route=None
                if record.trace.clue_route is None
                else record.trace.clue_route.value,
                gates=tuple(
                    ResearchAnomalyGate(item.gate, item.passed, item.code)
                    for item in record.trace.gates
                ),
                policy_version=record.trace.policy_version,
            )
        return ResearchAnomalyResult(
            assessment_id=record.assessment_id,
            version=record.version,
            evidence_id=record.evidence_id,
            evidence_version=record.evidence_version,
            source_snapshot_ids=record.source_snapshot_ids,
            status=record.status.value,
            requested_at=record.requested_at,
            trace=trace,
            failure_code=record.failure_code,
            actor_id=record.actor_id,
            company_id=record.company_id,
            company_ticker=record.company_ticker,
            company_name=record.company_name,
        )

    def request(
        self, actor: ResearchActorContext, request: ResearchAnomalyRequest
    ) -> ResearchAnomalyResult:
        return self._result(
            self._service.request(
                RequestAssessmentCommand(
                    actor_id=actor.actor_id,
                    may_request=actor.may_request_anomaly_assessment,
                    evidence_id=request.evidence_id,
                    expected_evidence_version=request.expected_evidence_version,
                    sources=self._sources(request.sources),
                    reason=request.reason,
                    idempotency_key=request.idempotency_key,
                )
            )
        )

    def get(
        self, actor: ResearchActorContext, assessment_id: str
    ) -> ResearchAnomalyResult:
        return self._result(
            self._service.get(
                assessment_id=assessment_id,
                may_read=actor.may_read_anomaly_assessment,
            )
        )

    def claim(self) -> ResearchAnomalyJob | None:
        job = self._service.claim()
        if job is None:
            return None
        if not job.lease_token:
            raise ValueError("lease_unavailable")
        return ResearchAnomalyJob(
            assessment_id=job.assessment_id,
            assessment_version=job.assessment_version,
            evidence_id=job.evidence_id,
            evidence_version=job.evidence_version,
            lease_token=job.lease_token,
            build_version=job.build_version,
            policy_version=job.policy_version,
            candidate_schema_version=job.candidate_schema_version,
            candidate_prompt_version=job.candidate_prompt_version,
            provider_model_version=job.provider_model_version,
            critic_schema_version=job.critic_schema_version,
            critic_prompt_version=job.critic_prompt_version,
            critic_model_version=job.critic_model_version,
        )

    def load_sources(self, assessment_id: str) -> tuple[ResearchAnomalySource, ...]:
        return tuple(
            ResearchAnomalySource(
                item.source_snapshot_id,
                item.publisher_identity,
                item.authoritative_first_party,
                item.formal_record,
                item.editorial_responsibility,
                item.attributed_author,
                item.verifiable_primary_evidence,
                item.underlying_evidence_id,
                item.canonical_url,
                item.excerpt,
                item.retrieved_at,
                item.published_at,
                item.observed_at,
            )
            for item in self._service.load_sources(assessment_id)
        )

    def evaluate(
        self,
        job: ResearchAnomalyJob,
        candidate: ResearchValidatedAnomalyCandidate,
        *,
        predeclared_invalidation_matches: bool,
    ) -> ResearchAnomalyResult:
        sources = self._sources(self.load_sources(job.assessment_id))
        clue = candidate.clue_features
        clue_value = None if clue is None else ClueFeatureVector(*clue)
        return self._result(
            self._service.evaluate(
                EvaluateAssessmentCommand(
                    assessment_id=job.assessment_id,
                    lease_token=job.lease_token,
                    expected_assessment_version=job.assessment_version,
                    sources=sources,
                    direct_supporting_snapshot_ids=candidate.direct_supporting_snapshot_ids,
                    predeclared_invalidation_matches=predeclared_invalidation_matches,
                    critic_passed=candidate.critic_passed,
                    clue_features=clue_value,
                    has_source_conflict=candidate.has_source_conflict,
                    newer_authoritative_refutation=candidate.newer_authoritative_refutation,
                    price_or_volume_only=candidate.price_or_volume_only,
                    novel_unsupported_event=candidate.novel_unsupported_event,
                )
            )
        )
