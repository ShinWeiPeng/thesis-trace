from typing import Protocol
from datetime import datetime

from thesis_trace.modules.recommendation.contracts import (
    OwnerDecision,
    RecommendationRecord,
    RecommendationInputSnapshot,
    RecommendationJob,
)


class RecommendationStorePort(Protocol):
    """Owner storage participant; the parent supplies atomic confirmation/fencing."""

    def next_expiry_candidate(self) -> tuple[str, str, int, int] | None: ...

    def get_request(
        self, actor_id: str, input_id: str
    ) -> tuple[str, str, str, str | None, datetime, int | None] | None: ...

    def list_requests(
        self,
        actor_id: str,
        company_id: str,
        *,
        before: str | None = None,
        limit: int = 26,
    ) -> tuple[tuple[str, str, str, str | None, datetime, int | None], ...]: ...

    def find_admission(
        self, actor_id: str, idempotency_key: str, command_digest: str
    ) -> str | None: ...

    def admit(
        self,
        *,
        inputs: RecommendationInputSnapshot,
        input_id: str,
        job_id: str,
        versions: tuple[tuple[str, str], ...],
        idempotency_key: str,
        command_digest: str,
    ) -> str: ...

    def get_input(
        self, actor_id: str, input_id: str
    ) -> tuple[RecommendationInputSnapshot, tuple[tuple[str, str], ...]] | None: ...

    def claim_job(self) -> RecommendationJob | None: ...

    def load_job_input(self, job: RecommendationJob) -> RecommendationInputSnapshot: ...

    def renew_job(self, job: RecommendationJob) -> RecommendationJob: ...

    def finish_job(self, job: RecommendationJob) -> None: ...

    def fail_job(
        self, job: RecommendationJob, *, error_code: str, transient: bool
    ) -> None: ...

    def job_status(
        self, actor_id: str, input_id: str
    ) -> tuple[str, str | None] | None: ...

    def append_record(self, record: RecommendationRecord) -> RecommendationRecord: ...

    def find_decision_receipt(
        self, actor_id: str, idempotency_key: str, command_digest: str
    ) -> OwnerDecision | None: ...

    def lock_decision_stream(
        self, actor_id: str, recommendation_id: str, version: int
    ) -> None: ...

    def latest_decision(
        self, actor_id: str, recommendation_id: str, version: int
    ) -> OwnerDecision | None: ...

    def get_record(
        self, actor_id: str, recommendation_id: str, version: int
    ) -> RecommendationRecord | None: ...

    def append_decision(
        self,
        decision: OwnerDecision,
        *,
        expected_sequence: int,
        idempotency_key: str,
        command_digest: str,
    ) -> OwnerDecision: ...

    def decision_history(
        self,
        actor_id: str,
        recommendation_id: str,
        version: int,
        *,
        limit: int | None = None,
        before_sequence: int | None = None,
    ) -> tuple[OwnerDecision, ...]: ...
