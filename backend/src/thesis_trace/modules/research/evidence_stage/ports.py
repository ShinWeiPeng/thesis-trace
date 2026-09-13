from __future__ import annotations

from typing import Protocol

from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    EvidenceStageRecord,
    StageEvaluation,
)


class EvidenceStageStorePort(Protocol):
    def commit_confirmation(
        self,
        *,
        command: ConfirmDimensionFactsCommand,
        evaluation: StageEvaluation,
        confirmed_at: str,
        policy_version: str,
    ) -> EvidenceStageRecord: ...

    def get_stage(self, evidence_id: str) -> EvidenceStageRecord | None: ...
