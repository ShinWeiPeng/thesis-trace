from __future__ import annotations

from typing import Protocol

from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyAnalysisJob,
    AnomalyAnalysisVersions,
    AnomalyAssessmentRecord,
    AnomalyDecisionTrace,
    EvaluateAssessmentCommand,
    RequestAssessmentCommand,
    SourceCharacteristicSnapshot,
)


class AnomalyAssessmentStorePort(Protocol):
    def request_assessment(
        self,
        *,
        command: RequestAssessmentCommand,
        requested_at: str,
        policy_version: str,
        versions: AnomalyAnalysisVersions,
    ) -> AnomalyAssessmentRecord: ...

    def claim_anomaly_job(self) -> AnomalyAnalysisJob | None: ...

    def load_anomaly_sources(
        self, assessment_id: str
    ) -> tuple[SourceCharacteristicSnapshot, ...]: ...

    def commit_anomaly_result(
        self,
        *,
        command: EvaluateAssessmentCommand,
        trace: AnomalyDecisionTrace,
    ) -> AnomalyAssessmentRecord: ...

    def get_anomaly_assessment(self, assessment_id: str) -> AnomalyAssessmentRecord | None: ...
