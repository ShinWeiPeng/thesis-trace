from __future__ import annotations

from collections.abc import Callable

from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyAnalysisJob,
    AnomalyAnalysisVersions,
    AnomalyAssessmentRecord,
    EvaluateAssessmentCommand,
    RequestAssessmentCommand,
    SourceCharacteristicSnapshot,
)
from thesis_trace.modules.research.anomaly_assessment.policy import (
    ANOMALY_POLICY_VERSION,
    evaluate_anomaly,
)
from thesis_trace.modules.research.anomaly_assessment.ports import AnomalyAssessmentStorePort


class AnomalyAssessmentService:
    def __init__(
        self,
        *,
        store: AnomalyAssessmentStorePort,
        clock: Callable[[], str],
        versions: AnomalyAnalysisVersions | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._versions = versions or AnomalyAnalysisVersions(
            build_version="test-build",
            candidate_schema_version="anomaly-candidate-v1",
            candidate_prompt_version="anomaly-prompt-v1",
            provider_model_version="test-provider-model",
            critic_schema_version="recommendation-critic-v1",
            critic_prompt_version="recommendation-critic-prompt-v1",
            critic_model_version="test-critic-model",
        )
        if any(not value.strip() for value in (
            self._versions.build_version,
            self._versions.candidate_schema_version,
            self._versions.candidate_prompt_version,
            self._versions.provider_model_version,
            self._versions.critic_schema_version,
            self._versions.critic_prompt_version,
            self._versions.critic_model_version,
        )):
            raise ValueError("invalid_analysis_versions")

    def request(self, command: RequestAssessmentCommand) -> AnomalyAssessmentRecord:
        if not command.may_request:
            raise PermissionError("forbidden")
        if not command.reason.strip():
            raise ValueError("invalid_reason")
        if not command.sources:
            raise ValueError("missing_sources")
        snapshot_ids = tuple(source.source_snapshot_id for source in command.sources)
        if any(not value.strip() for value in snapshot_ids) or len(set(snapshot_ids)) != len(snapshot_ids):
            raise ValueError("invalid_sources")
        normalized = RequestAssessmentCommand(
            actor_id=command.actor_id,
            may_request=True,
            evidence_id=command.evidence_id,
            expected_evidence_version=command.expected_evidence_version,
            sources=command.sources,
            reason=command.reason.strip(),
            idempotency_key=command.idempotency_key,
        )
        return self._store.request_assessment(
            command=normalized,
            requested_at=self._clock(),
            policy_version=ANOMALY_POLICY_VERSION,
            versions=self._versions,
        )

    def evaluate(self, command: EvaluateAssessmentCommand) -> AnomalyAssessmentRecord:
        trace = evaluate_anomaly(
            sources=command.sources,
            direct_supporting_snapshot_ids=command.direct_supporting_snapshot_ids,
            predeclared_invalidation_matches=command.predeclared_invalidation_matches,
            critic_passed=command.critic_passed,
            clue_features=command.clue_features,
            has_source_conflict=command.has_source_conflict,
            newer_authoritative_refutation=command.newer_authoritative_refutation,
            price_or_volume_only=command.price_or_volume_only,
            novel_unsupported_event=command.novel_unsupported_event,
        )
        return self._store.commit_anomaly_result(command=command, trace=trace)

    def claim(self) -> AnomalyAnalysisJob | None:
        return self._store.claim_anomaly_job()

    def load_sources(
        self, assessment_id: str
    ) -> tuple[SourceCharacteristicSnapshot, ...]:
        sources = self._store.load_anomaly_sources(assessment_id)
        if not sources:
            raise LookupError("resource_unavailable")
        return sources

    def get(self, *, assessment_id: str, may_read: bool) -> AnomalyAssessmentRecord:
        if not may_read:
            raise PermissionError("resource_unavailable")
        record = self._store.get_anomaly_assessment(assessment_id)
        if record is None:
            raise LookupError("resource_unavailable")
        return record
