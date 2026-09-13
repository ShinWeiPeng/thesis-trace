from __future__ import annotations

from thesis_trace.modules.research.evidence_intake.contracts import (
    CollectionRequest,
    EvidenceAccepted,
    CompanyRecord,
    EvidenceAuditFact,
    EvidenceRecord,
    EvidenceStatus,
    LeasedCollectionJob,
)
import uuid
from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot
from thesis_trace.modules.research.evidence_collection.contracts import ValuationSourceFact
from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    EvidenceStageRecord,
    StageEvaluation,
    confirmation_matches,
)
from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyAnalysisJob,
    AnomalyAnalysisVersions,
    AnomalyAssessmentRecord,
    AnomalyDecisionTrace,
    AssessmentStatus,
    EvaluateAssessmentCommand,
    RequestAssessmentCommand,
)


class InMemoryEvidenceStore:
    """Deterministic test adapter implementing the atomic admission boundary."""

    def __init__(self) -> None:
        self.records: dict[str, EvidenceRecord] = {}
        self.companies: dict[str, CompanyRecord] = {}
        self.audit_events: list[EvidenceAuditFact] = []
        self.collection_jobs: list[CollectionRequest] = []
        self.source_snapshots: dict[str, CollectedSourceSnapshot] = {}
        self.valuation_facts: dict[tuple[str, str], ValuationSourceFact] = {}
        self._accepted_by_key: dict[str, EvidenceAccepted] = {}
        self.stage_records: dict[str, EvidenceStageRecord] = {}
        self._stage_by_idempotency_key: dict[str, EvidenceStageRecord] = {}
        self.anomaly_records: dict[str, AnomalyAssessmentRecord] = {}
        self.anomaly_jobs: list[AnomalyAnalysisJob] = []
        self._anomaly_by_idempotency_key: dict[str, tuple[RequestAssessmentCommand, AnomalyAssessmentRecord]] = {}
        self._anomaly_sources: dict[str, tuple[object, ...]] = {}
        self.current_evidence_versions: dict[str, int] = {}

    def create_company(self, ticker: str, name: str) -> CompanyRecord:
        ticker = ticker.strip()
        name = name.strip()
        if not ticker or not name:
            raise ValueError("invalid_company")
        if ticker in self.companies:
            raise ValueError("company_exists")
        company = CompanyRecord(ticker, ticker, name, 1)
        self.companies[ticker] = company
        return company

    def list_companies(self) -> list[CompanyRecord]:
        return sorted(self.companies.values(), key=lambda item: item.ticker)

    def get_company(self, company_id: str) -> CompanyRecord | None:
        return self.companies.get(company_id)

    def find_accepted(self, idempotency_key: str) -> EvidenceAccepted | None:
        return self._accepted_by_key.get(idempotency_key)

    def commit_admission(
        self,
        *,
        idempotency_key: str,
        record: EvidenceRecord,
        audit: EvidenceAuditFact,
        job: CollectionRequest,
        accepted: EvidenceAccepted,
    ) -> None:
        if idempotency_key in self._accepted_by_key:
            return
        if record.evidence_id in self.records:
            raise ValueError("duplicate evidence id")
        self.records[record.evidence_id] = record
        self.audit_events.append(audit)
        self.collection_jobs.append(job)
        self._accepted_by_key[idempotency_key] = accepted

    def get_record(self, evidence_id: str) -> EvidenceRecord | None:
        return self.records.get(evidence_id)

    def get_source_snapshot_id(self, evidence_id: str) -> str | None:
        return evidence_id if evidence_id in self.source_snapshots else None

    def get_valuation_fact(self, evidence_id: str, fact_id: str) -> ValuationSourceFact | None:
        return self.valuation_facts.get((evidence_id, fact_id))

    def save_valuation_facts(self, evidence_id: str, facts: tuple[ValuationSourceFact, ...]) -> None:
        for fact in facts:
            if fact.evidence_id != evidence_id:
                raise ValueError("valuation_source_invalid")
            self.valuation_facts[(evidence_id, fact.fact_id)] = fact

    def claim_collection_job(self) -> LeasedCollectionJob | None:
        if not self.collection_jobs:
            return None
        job = self.collection_jobs.pop(0)
        self.transition(job.evidence_id, EvidenceStatus.PROCESSING)
        return LeasedCollectionJob(
            job_id=str(uuid.uuid4()), evidence_id=job.evidence_id,
            evidence_version=job.evidence_version, url=job.url,
            idempotency_key=job.idempotency_key, lease_token=str(uuid.uuid4()), attempt=1,
        )

    def transition(self, evidence_id: str, status: EvidenceStatus) -> None:
        current = self.records[evidence_id]
        self.records[evidence_id] = EvidenceRecord(
            evidence_id=current.evidence_id,
            version=current.version + 1,
            company_id=current.company_id,
            company_version=current.company_version,
            url=current.url,
            status=status,
        )

    def complete_collection(
        self,
        evidence_id: str,
        snapshot: CollectedSourceSnapshot,
        lease_token: str | None = None,
    ) -> bool:
        self.source_snapshots[evidence_id] = snapshot
        self.transition(evidence_id, EvidenceStatus.SUCCEEDED)
        return True

    def fail_collection(self, job: LeasedCollectionJob, lease_token: str,
                        failure_code: str, *, retryable: bool) -> bool:
        if lease_token != job.lease_token:
            return False
        status = EvidenceStatus.RETRYING if retryable else EvidenceStatus.FAILED
        self.transition(job.evidence_id, status)
        return True

    def commit_confirmation(
        self,
        *,
        command: ConfirmDimensionFactsCommand,
        evaluation: StageEvaluation,
        confirmed_at: str,
        policy_version: str,
    ) -> EvidenceStageRecord:
        replay = self._stage_by_idempotency_key.get(command.idempotency_key)
        if replay is not None:
            if not confirmation_matches(replay, command, evaluation, policy_version):
                raise ValueError("idempotency_conflict")
            return replay
        evidence = self.records.get(command.evidence_id)
        if evidence is None or evidence.status is not EvidenceStatus.SUCCEEDED:
            raise LookupError("resource_unavailable")
        if command.source_snapshot_id != command.evidence_id or command.evidence_id not in self.source_snapshots:
            raise LookupError("resource_unavailable")
        current = self.stage_records.get(command.evidence_id)
        current_version = 0 if current is None else current.version
        if command.expected_version != current_version:
            raise ValueError("version_conflict")
        record = EvidenceStageRecord(
            evidence_id=command.evidence_id,
            version=current_version + 1,
            source_snapshot_id=command.source_snapshot_id,
            actor_id=command.actor.actor_id,
            confirmed_at=confirmed_at,
            reason=command.reason,
            facts=command.facts,
            evaluation=evaluation,
            policy_version=policy_version,
        )
        self.stage_records[command.evidence_id] = record
        self._stage_by_idempotency_key[command.idempotency_key] = record
        return record

    def get_stage(self, evidence_id: str) -> EvidenceStageRecord | None:
        return self.stage_records.get(evidence_id)

    def request_assessment(
        self,
        *,
        command: RequestAssessmentCommand,
        requested_at: str,
        policy_version: str,
        versions: AnomalyAnalysisVersions,
    ) -> AnomalyAssessmentRecord:
        replay = self._anomaly_by_idempotency_key.get(command.idempotency_key)
        if replay is not None:
            if replay[0] != command:
                raise ValueError("idempotency_conflict")
            return replay[1]
        current_version = self.current_evidence_versions.setdefault(
            command.evidence_id, command.expected_evidence_version
        )
        if current_version != command.expected_evidence_version:
            raise ValueError("version_conflict")
        assessment_id = f"assessment-{len(self.anomaly_records) + 1}"
        record = AnomalyAssessmentRecord(
            assessment_id=assessment_id,
            version=1,
            evidence_id=command.evidence_id,
            evidence_version=command.expected_evidence_version,
            actor_id=command.actor_id,
            source_snapshot_ids=tuple(source.source_snapshot_id for source in command.sources),
            status=AssessmentStatus.PENDING,
            reason=command.reason,
            requested_at=requested_at,
        )
        self.anomaly_records[assessment_id] = record
        self._anomaly_sources[assessment_id] = command.sources
        self._anomaly_by_idempotency_key[command.idempotency_key] = (command, record)
        self.anomaly_jobs.append(
            AnomalyAnalysisJob(
                job_id=f"anomaly-job-{len(self.anomaly_jobs) + 1}",
                assessment_id=assessment_id,
                assessment_version=1,
                evidence_id=command.evidence_id,
                evidence_version=command.expected_evidence_version,
                lease_token=None,
                attempt=0,
                build_version=versions.build_version,
                policy_version=policy_version,
                candidate_schema_version=versions.candidate_schema_version,
                candidate_prompt_version=versions.candidate_prompt_version,
                provider_model_version=versions.provider_model_version,
                critic_schema_version=versions.critic_schema_version,
                critic_prompt_version=versions.critic_prompt_version,
                critic_model_version=versions.critic_model_version,
            )
        )
        return record

    def claim_anomaly_job(self) -> AnomalyAnalysisJob | None:
        if not self.anomaly_jobs:
            return None
        queued = self.anomaly_jobs.pop(0)
        return AnomalyAnalysisJob(
            job_id=queued.job_id,
            assessment_id=queued.assessment_id,
            assessment_version=queued.assessment_version,
            evidence_id=queued.evidence_id,
            evidence_version=queued.evidence_version,
            lease_token=str(uuid.uuid4()),
            attempt=queued.attempt + 1,
            build_version=queued.build_version,
            policy_version=queued.policy_version,
            candidate_schema_version=queued.candidate_schema_version,
            candidate_prompt_version=queued.candidate_prompt_version,
            provider_model_version=queued.provider_model_version,
            critic_schema_version=queued.critic_schema_version,
            critic_prompt_version=queued.critic_prompt_version,
            critic_model_version=queued.critic_model_version,
        )

    def load_anomaly_sources(self, assessment_id: str):
        return self._anomaly_sources.get(assessment_id, ())

    def commit_anomaly_result(
        self,
        *,
        command: EvaluateAssessmentCommand,
        trace: AnomalyDecisionTrace,
    ) -> AnomalyAssessmentRecord:
        current = self.anomaly_records.get(command.assessment_id)
        if current is None:
            raise LookupError("resource_unavailable")
        if current.version != command.expected_assessment_version:
            raise ValueError("version_conflict")
        if not command.lease_token:
            raise ValueError("lease_unavailable")
        stale = self.current_evidence_versions.get(current.evidence_id) != current.evidence_version
        record = AnomalyAssessmentRecord(
            assessment_id=current.assessment_id,
            version=current.version + 1,
            evidence_id=current.evidence_id,
            evidence_version=current.evidence_version,
            actor_id=current.actor_id,
            source_snapshot_ids=current.source_snapshot_ids,
            status=AssessmentStatus.SUPERSEDED if stale else AssessmentStatus.SUCCEEDED,
            reason=current.reason,
            requested_at=current.requested_at,
            trace=trace,
            failure_code="stale_input" if stale else None,
        )
        self.anomaly_records[record.assessment_id] = record
        return record

    def get_anomaly_assessment(self, assessment_id: str) -> AnomalyAssessmentRecord | None:
        return self.anomaly_records.get(assessment_id)
