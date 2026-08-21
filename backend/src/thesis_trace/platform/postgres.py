from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import uuid
from typing import Any, Callable, Iterator, Protocol

from thesis_trace.modules.access.contracts import SecurityContext

from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot
from thesis_trace.modules.research.evidence_intake.contracts import (
    CollectionRequest,
    CompanyRecord,
    EvidenceAccepted,
    EvidenceAuditFact,
    EvidenceRecord,
    EvidenceStatus,
    LeasedCollectionJob,
)
from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    DimensionFacts,
    EvidenceStage,
    EvidenceStageRecord,
    GateResult,
    SourceConfirmation,
    StageEvaluation,
    confirmation_matches,
)
from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyAnalysisJob,
    AnomalyAnalysisVersions,
    AnomalyAssessmentRecord,
    AnomalyClass,
    AnomalyDecisionTrace,
    AssessmentStatus,
    ClueRoute,
    DecisionGate,
    EvaluateAssessmentCommand,
    RequestAssessmentCommand,
    SourceCharacteristicSnapshot,
    SourceTier,
)


class DatabaseUrlProvider(Protocol):
    """Resolve a database URL for one connection attempt without retaining it."""

    def __call__(self) -> str: ...


MIGRATION_0001 = """
CREATE SCHEMA IF NOT EXISTS research;
CREATE TABLE research.companies (
  company_id text PRIMARY KEY, ticker text NOT NULL UNIQUE, name text NOT NULL,
  version integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research.evidence_intakes (
  evidence_id text PRIMARY KEY, version integer NOT NULL, company_id text NOT NULL REFERENCES research.companies(company_id),
  company_version integer NOT NULL, submitted_url text NOT NULL, status text NOT NULL,
  failure_code text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research.audit_events (
  event_id uuid PRIMARY KEY, actor_id text NOT NULL, action text NOT NULL,
  subject_id text NOT NULL, subject_version integer NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research.collection_jobs (
  job_id uuid PRIMARY KEY, evidence_id text NOT NULL REFERENCES research.evidence_intakes(evidence_id),
  evidence_version integer NOT NULL, submitted_url text NOT NULL, idempotency_key text NOT NULL UNIQUE,
  state text NOT NULL DEFAULT 'pending', attempt integer NOT NULL DEFAULT 0,
  available_at timestamptz NOT NULL DEFAULT now(), lease_token uuid, lease_expires_at timestamptz,
  failure_code text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research.idempotency_receipts (
  idempotency_key text PRIMARY KEY, evidence_id text NOT NULL, evidence_version integer NOT NULL
);
CREATE TABLE IF NOT EXISTS research.source_snapshots (
  snapshot_id uuid PRIMARY KEY, canonical_url text NOT NULL,
  publisher text NOT NULL, content_hash text NOT NULL UNIQUE, retrieved_at timestamptz NOT NULL,
  published_at timestamptz, observed_at timestamptz, excerpt text, source_category text NOT NULL,
  lineage text, UNIQUE(canonical_url)
);
CREATE TABLE IF NOT EXISTS research.source_observations (
  evidence_id text PRIMARY KEY REFERENCES research.evidence_intakes(evidence_id),
  snapshot_id uuid NOT NULL REFERENCES research.source_snapshots(snapshot_id),
  submitted_url text NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now()
);
"""

MIGRATION_0002 = """
CREATE SCHEMA access;
CREATE TABLE access.account_capacity(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton));
INSERT INTO access.account_capacity(singleton) VALUES(true);
CREATE TABLE access.users(user_id uuid PRIMARY KEY, role text NOT NULL CHECK(role IN ('owner','learner','admin')), status text NOT NULL CHECK(status IN ('active','disabled')), identity_version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), disabled_at timestamptz);
CREATE TABLE access.identities(identity_id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES access.users(user_id), provider_id text NOT NULL, provider_type text NOT NULL, provider_subject text NOT NULL, email_fact text NOT NULL, enabled boolean NOT NULL DEFAULT true, version integer NOT NULL DEFAULT 1, UNIQUE(provider_id,provider_type,provider_subject));
CREATE TABLE access.sessions(session_id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES access.users(user_id), identity_id uuid NOT NULL REFERENCES access.identities(identity_id), token_digest text NOT NULL UNIQUE, recovery boolean NOT NULL, jwt_expires_at timestamptz NOT NULL, expires_at timestamptz NOT NULL, revoked_at timestamptz, identity_version integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), CHECK(expires_at<=jwt_expires_at));
CREATE TABLE access.confirmation_challenges(challenge_id uuid PRIMARY KEY, actor_user_id uuid NOT NULL REFERENCES access.users(user_id), action_type text NOT NULL, target_id text NOT NULL, target_version integer NOT NULL, payload_digest text NOT NULL, impact_summary text NOT NULL, token_digest text NOT NULL UNIQUE, policy_version integer NOT NULL DEFAULT 1, issued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL, consumed_at timestamptz, revoked_at timestamptz, result_id text, CHECK(expires_at<=issued_at+interval '5 minutes'));
CREATE TABLE access.security_audit_events(event_id uuid PRIMARY KEY, actor_user_id uuid, subject_id text NOT NULL, action text NOT NULL, reason text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}', occurred_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE access.workflow_outbox(event_id uuid PRIMARY KEY, event_type text NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), delivered_at timestamptz);
CREATE OR REPLACE FUNCTION access.enforce_active_capacity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM 1 FROM access.account_capacity WHERE singleton=true FOR UPDATE; IF NEW.status='active' AND (TG_OP='INSERT' OR OLD.status IS DISTINCT FROM 'active') AND (SELECT count(*) FROM access.users WHERE status='active') >= 10 THEN RAISE EXCEPTION 'active_account_limit'; END IF; RETURN NEW; END $$;
CREATE TRIGGER access_active_capacity BEFORE INSERT OR UPDATE OF status ON access.users FOR EACH ROW EXECUTE FUNCTION access.enforce_active_capacity();
REVOKE UPDATE,DELETE ON access.security_audit_events FROM PUBLIC;
CREATE OR REPLACE FUNCTION access.reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'append_only_audit'; END $$;
CREATE TRIGGER access_audit_append_only BEFORE UPDATE OR DELETE ON access.security_audit_events FOR EACH ROW EXECUTE FUNCTION access.reject_audit_mutation();
CREATE INDEX access_active_identity_idx ON access.identities(provider_id,provider_type,provider_subject) WHERE enabled;
CREATE INDEX access_live_session_idx ON access.sessions(token_digest) WHERE revoked_at IS NULL;
CREATE INDEX access_open_challenge_idx ON access.confirmation_challenges(actor_user_id,expires_at) WHERE consumed_at IS NULL AND revoked_at IS NULL;
"""

MIGRATION_0003 = """
ALTER TABLE research.companies ENABLE ROW LEVEL SECURITY; ALTER TABLE research.companies FORCE ROW LEVEL SECURITY;
ALTER TABLE research.evidence_intakes ENABLE ROW LEVEL SECURITY; ALTER TABLE research.evidence_intakes FORCE ROW LEVEL SECURITY;
CREATE POLICY company_read ON research.companies FOR SELECT USING (current_setting('app.role',true) IN ('owner','learner'));
CREATE POLICY company_write ON research.companies FOR ALL USING (current_setting('app.role',true)='owner') WITH CHECK (current_setting('app.role',true)='owner');
CREATE POLICY evidence_read ON research.evidence_intakes FOR SELECT USING (current_setting('app.role',true) IN ('owner','learner'));
CREATE POLICY evidence_write ON research.evidence_intakes FOR ALL USING (current_setting('app.role',true)='owner') WITH CHECK (current_setting('app.role',true)='owner');
CREATE POLICY collector_company_read ON research.companies FOR SELECT USING (current_setting('app.role',true)='collector');
CREATE POLICY collector_evidence_read ON research.evidence_intakes FOR SELECT USING (current_setting('app.role',true)='collector');
CREATE POLICY collector_evidence_update ON research.evidence_intakes FOR UPDATE USING (current_setting('app.role',true)='collector') WITH CHECK (current_setting('app.role',true)='collector');
"""

MIGRATION_0004 = """
ALTER TABLE access.sessions ADD COLUMN recovery_policy_version text;
"""

MIGRATION_0005 = """
ALTER TABLE research.source_snapshots ADD COLUMN normalization_policy_version text;
UPDATE research.source_snapshots SET normalization_policy_version='url-normalization-legacy';
ALTER TABLE research.source_snapshots ALTER COLUMN normalization_policy_version SET NOT NULL;
CREATE TABLE research.canonical_sources (
  source_id uuid PRIMARY KEY,
  normalization_policy_version text NOT NULL,
  canonical_url text NOT NULL,
  UNIQUE(normalization_policy_version,canonical_url)
);
INSERT INTO research.canonical_sources(source_id,normalization_policy_version,canonical_url)
SELECT snapshot_id,normalization_policy_version,canonical_url FROM research.source_snapshots;
ALTER TABLE research.source_observations ADD COLUMN source_id uuid REFERENCES research.canonical_sources(source_id);
UPDATE research.source_observations o SET source_id=s.snapshot_id
FROM research.source_snapshots s WHERE s.snapshot_id=o.snapshot_id;
ALTER TABLE research.source_observations ALTER COLUMN source_id SET NOT NULL;
ALTER TABLE research.source_snapshots DROP CONSTRAINT source_snapshots_canonical_url_key;
"""

MIGRATION_0006 = """
CREATE TABLE research.evidence_stage_versions (
  evidence_id text NOT NULL REFERENCES research.evidence_intakes(evidence_id),
  version integer NOT NULL CHECK(version >= 1),
  source_snapshot_id uuid NOT NULL REFERENCES research.source_snapshots(snapshot_id),
  actor_id text NOT NULL,
  confirmed_at timestamptz NOT NULL,
  reason text NOT NULL CHECK(length(btrim(reason)) > 0),
  source_confirmation text NOT NULL CHECK(source_confirmation IN ('unverified','official','two_independent_credible')),
  product_established boolean NOT NULL,
  commercialization_established boolean NOT NULL,
  identifiable_revenue boolean NOT NULL,
  identifiable_profit_or_cash_flow boolean NOT NULL,
  consecutive_financial_quarters integer NOT NULL CHECK(consecutive_financial_quarters >= 0),
  stage text NOT NULL CHECK(stage IN ('E0','E1','E2','E3','E4','E5','E6')),
  policy_version text NOT NULL,
  gate_trace jsonb NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  PRIMARY KEY(evidence_id,version)
);
ALTER TABLE research.evidence_stage_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE research.evidence_stage_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY evidence_stage_read ON research.evidence_stage_versions FOR SELECT
  USING (current_setting('app.role',true) IN ('owner','learner'));
CREATE POLICY evidence_stage_owner_insert ON research.evidence_stage_versions FOR INSERT
  WITH CHECK (current_setting('app.role',true)='owner');
"""

MIGRATION_0007 = """
CREATE TABLE research.anomaly_assessments (
  assessment_id uuid PRIMARY KEY,
  version integer NOT NULL CHECK(version >= 1),
  evidence_id text NOT NULL REFERENCES research.evidence_intakes(evidence_id),
  evidence_version integer NOT NULL CHECK(evidence_version >= 1),
  actor_id text NOT NULL,
  source_snapshot_ids uuid[] NOT NULL CHECK(cardinality(source_snapshot_ids) > 0),
  source_characteristics jsonb NOT NULL,
  status text NOT NULL CHECK(status IN ('pending','succeeded','failed','superseded')),
  reason text NOT NULL CHECK(length(btrim(reason)) > 0),
  requested_at timestamptz NOT NULL,
  trace jsonb,
  failure_code text,
  idempotency_key text NOT NULL UNIQUE
);
CREATE TABLE research.anomaly_analysis_jobs (
  job_id uuid PRIMARY KEY,
  assessment_id uuid NOT NULL UNIQUE REFERENCES research.anomaly_assessments(assessment_id),
  assessment_version integer NOT NULL,
  evidence_id text NOT NULL REFERENCES research.evidence_intakes(evidence_id),
  evidence_version integer NOT NULL,
  state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','processing','retrying','succeeded','failed','dead_letter','superseded')),
  attempt integer NOT NULL DEFAULT 0,
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_token uuid,
  lease_expires_at timestamptz,
  build_version text NOT NULL,
  policy_version text NOT NULL,
  candidate_schema_version text NOT NULL,
  candidate_prompt_version text NOT NULL,
  provider_model_version text NOT NULL,
  critic_schema_version text NOT NULL,
  critic_prompt_version text NOT NULL,
  critic_model_version text NOT NULL,
  failure_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE research.anomaly_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE research.anomaly_assessments FORCE ROW LEVEL SECURITY;
CREATE POLICY anomaly_assessment_read ON research.anomaly_assessments FOR SELECT
  USING (current_setting('app.role',true) IN ('owner','learner'));
CREATE POLICY anomaly_assessment_owner_insert ON research.anomaly_assessments FOR INSERT
  WITH CHECK (current_setting('app.role',true)='owner');
CREATE POLICY anomaly_assessment_owner_update ON research.anomaly_assessments FOR UPDATE
  USING (current_setting('app.role',true) IN ('owner','ai_worker'))
  WITH CHECK (current_setting('app.role',true) IN ('owner','ai_worker'));
CREATE POLICY anomaly_assessment_ai_worker_read ON research.anomaly_assessments FOR SELECT
  USING (current_setting('app.role',true)='ai_worker');
CREATE POLICY anomaly_evidence_ai_worker_read ON research.evidence_intakes FOR SELECT
  USING (current_setting('app.role',true)='ai_worker');
CREATE INDEX anomaly_job_due_idx ON research.anomaly_analysis_jobs(state,available_at);
"""

MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "wave0_company_evidence", MIGRATION_0001),
    (2, "access_identity_session_confirmation", MIGRATION_0002),
    (3, "access_rls", MIGRATION_0003),
    (4, "recovery_session_policy_binding", MIGRATION_0004),
    (5, "source_normalization_policy_version", MIGRATION_0005),
    (6, "owner_confirmed_evidence_stage", MIGRATION_0006),
    (7, "shadow_first_anomaly_assessment", MIGRATION_0007),
)


def _psycopg() -> Any:
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("psycopg is required for PostgreSQL runtime") from error
    return psycopg


class PostgresUnavailable(RuntimeError):
    """Stable non-secret error for unavailable PostgreSQL capability."""


_REQUEST_SECURITY_CONTEXT: ContextVar[SecurityContext | None] = ContextVar("database_security_context", default=None)


@contextmanager
def database_security_context(context: SecurityContext) -> Iterator[None]:
    token = _REQUEST_SECURITY_CONTEXT.set(context)
    try:
        yield
    finally:
        _REQUEST_SECURITY_CONTEXT.reset(token)


@contextmanager
def _redacted_connection(database_url_provider: DatabaseUrlProvider) -> Iterator[Any]:
    try:
        with _psycopg().connect(database_url_provider()) as connection:
            yield connection
    except (ValueError, PermissionError, LookupError):
        raise
    except Exception:
        raise PostgresUnavailable("postgres_unavailable") from None


def bootstrap_schema(database_url_provider: DatabaseUrlProvider) -> None:
    with _redacted_connection(database_url_provider) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS research")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS research.schema_migrations (
            version integer PRIMARY KEY, name text NOT NULL, checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now())"""
        )
        connection.execute("SELECT pg_advisory_xact_lock(908177431)")
        applied = {int(row[0]): (str(row[1]), str(row[2])) for row in connection.execute(
            "SELECT version,name,checksum FROM research.schema_migrations ORDER BY version"
        ).fetchall()}
        known_versions = {item[0] for item in MIGRATIONS}
        if any(version not in known_versions for version in applied):
            raise RuntimeError("database schema is newer than this application")
        for version, name, sql in MIGRATIONS:
            checksum = sha256(sql.encode("utf-8")).hexdigest()
            if version in applied:
                if applied[version] != (name, checksum):
                    raise RuntimeError(f"migration {version} was changed after application")
                continue
            with connection.transaction():
                connection.execute(sql)
                connection.execute(
                    "INSERT INTO research.schema_migrations(version,name,checksum) VALUES (%s,%s,%s)",
                    (version, name, checksum),
                )


def verify_schema_compatibility(database_url_provider: DatabaseUrlProvider) -> None:
    """Require the exact migrated schema without granting runtime DDL authority."""
    with _redacted_connection(database_url_provider) as connection:
        rows = connection.execute(
            "SELECT version,name,checksum FROM research.schema_migrations ORDER BY version"
        ).fetchall()
    applied = [(int(row[0]), str(row[1]), str(row[2])) for row in rows]
    expected = [
        (version, name, sha256(sql.encode("utf-8")).hexdigest())
        for version, name, sql in MIGRATIONS
    ]
    if applied != expected:
        raise RuntimeError("database schema is not compatible with this application")


class PostgresEvidenceStore:
    def __init__(self, database_url_provider: DatabaseUrlProvider, *, max_attempts: int = 3, lease_seconds: int = 60,
                 admission_fault_hook: Callable[[], None] | None = None, runtime_role: str | None = None) -> None:
        if not callable(database_url_provider):
            raise TypeError("database URL provider is required")
        self._database_url_provider = database_url_provider
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds
        self._admission_fault_hook = admission_fault_hook
        self._runtime_role = runtime_role

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with _redacted_connection(self._database_url_provider) as connection:
            context = _REQUEST_SECURITY_CONTEXT.get()
            if context is not None:
                connection.execute("SELECT set_config('app.user_id',%s,true)", (context.user_id,))
                connection.execute("SELECT set_config('app.role',%s,true)", (context.role.value,))
                connection.execute("SELECT set_config('app.request_id',%s,true)", (context.ownership_scope,))
            elif self._runtime_role in {"collector", "ai_worker"}:
                connection.execute("SELECT set_config('app.role',%s,true)", (self._runtime_role,))
            yield connection

    def create_company(self, ticker: str, name: str) -> CompanyRecord:
        ticker = ticker.strip()
        name = name.strip()
        if not ticker or not name:
            raise ValueError("invalid_company")
        with self._connection() as connection:
            try:
                row = connection.execute(
                    "INSERT INTO research.companies(company_id,ticker,name,version) VALUES (%s,%s,%s,1) RETURNING company_id,ticker,name,version",
                    (ticker, ticker, name),
                ).fetchone()
            except Exception as error:
                raise ValueError("company_exists") from error
        return CompanyRecord(str(row[0]), str(row[1]), str(row[2]), int(row[3]))

    def list_companies(self) -> list[CompanyRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT company_id,ticker,name,version FROM research.companies ORDER BY ticker"
            ).fetchall()
        return [CompanyRecord(str(row[0]), str(row[1]), str(row[2]), int(row[3])) for row in rows]

    def get_company(self, company_id: str) -> CompanyRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT company_id,ticker,name,version FROM research.companies WHERE company_id=%s",
                (company_id,),
            ).fetchone()
        return None if row is None else CompanyRecord(str(row[0]), str(row[1]), str(row[2]), int(row[3]))

    def find_accepted(self, idempotency_key: str) -> EvidenceAccepted | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT evidence_id, evidence_version FROM research.idempotency_receipts WHERE idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else EvidenceAccepted(str(row[0]), int(row[1]))

    def commit_admission(self, *, idempotency_key: str, record: EvidenceRecord,
                         audit: EvidenceAuditFact, job: CollectionRequest,
                         accepted: EvidenceAccepted) -> None:
        with self._connection() as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (idempotency_key,),
                )
                existing = connection.execute(
                    "SELECT evidence_id FROM research.idempotency_receipts WHERE idempotency_key=%s FOR UPDATE",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return
                connection.execute(
                    "INSERT INTO research.evidence_intakes(evidence_id,version,company_id,company_version,submitted_url,status) VALUES (%s,%s,%s,%s,%s,%s)",
                    (record.evidence_id, record.version, record.company_id, record.company_version, record.url, record.status.value),
                )
                if self._admission_fault_hook is not None:
                    self._admission_fault_hook()
                connection.execute(
                    "INSERT INTO research.audit_events(event_id,actor_id,action,subject_id,subject_version) VALUES (%s,%s,%s,%s,%s)",
                    (uuid.uuid4(), audit.actor_id, audit.action, audit.subject_id, audit.subject_version),
                )
                connection.execute(
                    "INSERT INTO research.collection_jobs(job_id,evidence_id,evidence_version,submitted_url,idempotency_key) VALUES (%s,%s,%s,%s,%s)",
                    (uuid.uuid4(), job.evidence_id, job.evidence_version, job.url, job.idempotency_key),
                )
                connection.execute(
                    "INSERT INTO research.idempotency_receipts(idempotency_key,evidence_id,evidence_version) VALUES (%s,%s,%s)",
                    (idempotency_key, accepted.evidence_id, accepted.version),
                )

    def get_record(self, evidence_id: str) -> EvidenceRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT evidence_id,version,company_id,company_version,submitted_url,status FROM research.evidence_intakes WHERE evidence_id=%s",
                (evidence_id,),
            ).fetchone()
        return None if row is None else EvidenceRecord(str(row[0]), int(row[1]), str(row[2]), int(row[3]), str(row[4]), EvidenceStatus(row[5]))

    def get_source_snapshot_id(self, evidence_id: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT o.snapshot_id FROM research.evidence_intakes e
                JOIN research.source_observations o USING(evidence_id)
                WHERE e.evidence_id=%s AND e.status='succeeded'""",
                (evidence_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _stage_record(row: Any) -> EvidenceStageRecord:
        trace = tuple(
            GateResult(EvidenceStage(item["gate"]), bool(item["passed"]), str(item["code"]))
            for item in row[13]
        )
        facts = DimensionFacts(
            source_confirmation=SourceConfirmation(row[6]),
            product_established=bool(row[7]),
            commercialization_established=bool(row[8]),
            identifiable_revenue=bool(row[9]),
            identifiable_profit_or_cash_flow=bool(row[10]),
            consecutive_financial_quarters=int(row[11]),
        )
        confirmed_at = row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4])
        return EvidenceStageRecord(
            evidence_id=str(row[0]),
            version=int(row[1]),
            source_snapshot_id=str(row[2]),
            actor_id=str(row[3]),
            confirmed_at=confirmed_at,
            reason=str(row[5]),
            facts=facts,
            evaluation=StageEvaluation(EvidenceStage(row[12]), trace),
            policy_version=str(row[14]),
        )

    @staticmethod
    def _stage_select() -> str:
        return """SELECT evidence_id,version,source_snapshot_id,actor_id,confirmed_at,reason,
        source_confirmation,product_established,commercialization_established,identifiable_revenue,
        identifiable_profit_or_cash_flow,consecutive_financial_quarters,stage,gate_trace,policy_version
        FROM research.evidence_stage_versions"""

    @staticmethod
    def _source_values(source: SourceCharacteristicSnapshot) -> dict[str, Any]:
        return {
            "source_snapshot_id": source.source_snapshot_id,
            "publisher_identity": source.publisher_identity,
            "authoritative_first_party": source.authoritative_first_party,
            "formal_record": source.formal_record,
            "editorial_responsibility": source.editorial_responsibility,
            "attributed_author": source.attributed_author,
            "verifiable_primary_evidence": source.verifiable_primary_evidence,
            "underlying_evidence_id": source.underlying_evidence_id,
            "canonical_url": source.canonical_url,
            "excerpt": source.excerpt,
            "retrieved_at": source.retrieved_at,
            "published_at": source.published_at,
            "observed_at": source.observed_at,
        }

    @staticmethod
    def _source_characteristics_match(
        stored: object, requested: tuple[SourceCharacteristicSnapshot, ...]
    ) -> bool:
        if not isinstance(stored, list) or len(stored) != len(requested):
            return False
        for value, source in zip(stored, requested, strict=True):
            if not isinstance(value, dict):
                return False
            if value.get("source_snapshot_id") != source.source_snapshot_id:
                return False
        return True

    @staticmethod
    def _trace_values(trace: AnomalyDecisionTrace) -> dict[str, Any]:
        return {
            "anomaly_class": trace.anomaly_class.value,
            "source_tiers": [tier.value for tier in trace.source_tiers],
            "clue_score": trace.clue_score,
            "clue_route": None if trace.clue_route is None else trace.clue_route.value,
            "gates": [
                {"gate": gate.gate, "passed": gate.passed, "code": gate.code}
                for gate in trace.gates
            ],
            "policy_version": trace.policy_version,
        }

    @staticmethod
    def _anomaly_record(row: Any) -> AnomalyAssessmentRecord:
        trace_data = row[9]
        trace = None
        if trace_data is not None:
            trace = AnomalyDecisionTrace(
                anomaly_class=AnomalyClass(trace_data["anomaly_class"]),
                source_tiers=tuple(SourceTier(value) for value in trace_data["source_tiers"]),
                clue_score=trace_data["clue_score"],
                clue_route=None if trace_data["clue_route"] is None else ClueRoute(trace_data["clue_route"]),
                gates=tuple(
                    DecisionGate(str(item["gate"]), bool(item["passed"]), str(item["code"]))
                    for item in trace_data["gates"]
                ),
                policy_version=str(trace_data["policy_version"]),
            )
        requested_at = row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8])
        return AnomalyAssessmentRecord(
            assessment_id=str(row[0]),
            version=int(row[1]),
            evidence_id=str(row[2]),
            evidence_version=int(row[3]),
            actor_id=str(row[4]),
            source_snapshot_ids=tuple(str(value) for value in row[5]),
            status=AssessmentStatus(row[6]),
            reason=str(row[7]),
            requested_at=requested_at,
            trace=trace,
            failure_code=None if row[10] is None else str(row[10]),
        )

    @staticmethod
    def _anomaly_select() -> str:
        return """SELECT assessment_id,version,evidence_id,evidence_version,actor_id,
        source_snapshot_ids,status,reason,requested_at,trace,failure_code
        FROM research.anomaly_assessments"""

    def commit_confirmation(
        self,
        *,
        command: ConfirmDimensionFactsCommand,
        evaluation: StageEvaluation,
        confirmed_at: str,
        policy_version: str,
    ) -> EvidenceStageRecord:
        with self._connection() as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"evidence-stage:{command.evidence_id}",),
                )
                replay_row = connection.execute(
                    f"{self._stage_select()} WHERE idempotency_key=%s",
                    (command.idempotency_key,),
                ).fetchone()
                if replay_row is not None:
                    replay = self._stage_record(replay_row)
                    if not confirmation_matches(replay, command, evaluation, policy_version):
                        raise ValueError("idempotency_conflict")
                    return replay
                target = connection.execute(
                    """SELECT e.evidence_id FROM research.evidence_intakes e
                    JOIN research.source_observations o USING(evidence_id)
                    WHERE e.evidence_id=%s AND e.status='succeeded' AND o.snapshot_id=%s::uuid
                    FOR UPDATE OF e""",
                    (command.evidence_id, command.source_snapshot_id),
                ).fetchone()
                if target is None:
                    raise LookupError("resource_unavailable")
                current = connection.execute(
                    "SELECT coalesce(max(version),0) FROM research.evidence_stage_versions WHERE evidence_id=%s",
                    (command.evidence_id,),
                ).fetchone()[0]
                if int(current) != command.expected_version:
                    raise ValueError("version_conflict")
                version = int(current) + 1
                trace_json = json.dumps([
                    {"gate": item.gate.value, "passed": item.passed, "code": item.code}
                    for item in evaluation.gate_trace
                ], separators=(",", ":"))
                row = connection.execute(
                    f"""INSERT INTO research.evidence_stage_versions(
                    evidence_id,version,source_snapshot_id,actor_id,confirmed_at,reason,
                    source_confirmation,product_established,commercialization_established,
                    identifiable_revenue,identifiable_profit_or_cash_flow,consecutive_financial_quarters,
                    stage,policy_version,gate_trace,idempotency_key)
                    VALUES (%s,%s,%s::uuid,%s,%s::timestamptz,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                    RETURNING {self._stage_select().split('FROM ')[0].removeprefix('SELECT ')}""",
                    (
                        command.evidence_id, version, command.source_snapshot_id, command.actor.actor_id,
                        confirmed_at, command.reason, command.facts.source_confirmation.value,
                        command.facts.product_established, command.facts.commercialization_established,
                        command.facts.identifiable_revenue, command.facts.identifiable_profit_or_cash_flow,
                        command.facts.consecutive_financial_quarters, evaluation.stage.value, policy_version,
                        trace_json, command.idempotency_key,
                    ),
                ).fetchone()
                connection.execute(
                    """INSERT INTO research.audit_events(event_id,actor_id,action,subject_id,subject_version,occurred_at)
                    VALUES (%s,%s,'evidence.stage.confirmed',%s,%s,%s::timestamptz)""",
                    (uuid.uuid4(), command.actor.actor_id, command.evidence_id, version, confirmed_at),
                )
        return self._stage_record(row)

    def get_stage(self, evidence_id: str) -> EvidenceStageRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                f"{self._stage_select()} WHERE evidence_id=%s ORDER BY version DESC LIMIT 1",
                (evidence_id,),
            ).fetchone()
        return None if row is None else self._stage_record(row)

    def request_assessment(
        self,
        *,
        command: RequestAssessmentCommand,
        requested_at: str,
        policy_version: str,
        versions: AnomalyAnalysisVersions,
    ) -> AnomalyAssessmentRecord:
        with self._connection() as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"anomaly-request:{command.idempotency_key}",),
                )
                replay_row = connection.execute(
                    f"{self._anomaly_select()} WHERE idempotency_key=%s",
                    (command.idempotency_key,),
                ).fetchone()
                if replay_row is not None:
                    replay = self._anomaly_record(replay_row)
                    replay_sources = connection.execute(
                        "SELECT source_characteristics FROM research.anomaly_assessments "
                        "WHERE idempotency_key=%s",
                        (command.idempotency_key,),
                    ).fetchone()[0]
                    if (
                        replay.evidence_id != command.evidence_id
                        or replay.evidence_version != command.expected_evidence_version
                        or replay.actor_id != command.actor_id
                        or replay.source_snapshot_ids != tuple(source.source_snapshot_id for source in command.sources)
                        or not self._source_characteristics_match(replay_sources, command.sources)
                        or replay.reason != command.reason
                    ):
                        raise ValueError("idempotency_conflict")
                    return replay
                source_ids = tuple(source.source_snapshot_id for source in command.sources)
                target = connection.execute(
                    "SELECT version,status,company_id FROM research.evidence_intakes "
                    "WHERE evidence_id=%s FOR UPDATE",
                    (command.evidence_id,),
                ).fetchone()
                if (
                    target is None
                    or str(target[1]) != "succeeded"
                    or int(target[0]) != command.expected_evidence_version
                ):
                    raise ValueError("version_conflict") if target is not None else LookupError("resource_unavailable")
                linked_rows = connection.execute(
                    """SELECT DISTINCT ON (s.snapshot_id) s.snapshot_id::text,s.canonical_url,s.publisher,
                    s.retrieved_at::text,s.published_at::text,s.observed_at::text,s.excerpt,
                    s.source_category,s.lineage
                    FROM research.source_observations o
                    JOIN research.source_snapshots s USING(snapshot_id)
                    JOIN research.evidence_intakes e ON e.evidence_id=o.evidence_id
                    WHERE e.company_id=%s AND e.status='succeeded'
                    AND s.snapshot_id=ANY(%s::uuid[])
                    ORDER BY s.snapshot_id,o.observed_at DESC""",
                    (str(target[2]), list(source_ids)),
                ).fetchall()
                if len(linked_rows) != len(source_ids):
                    raise LookupError("resource_unavailable")
                linked_by_id = {str(item[0]): item for item in linked_rows}
                stored_sources = []
                for source in command.sources:
                    linked = linked_by_id[source.source_snapshot_id]
                    category = str(linked[7]).strip().upper()
                    stored_sources.append(
                        SourceCharacteristicSnapshot(
                            source_snapshot_id=source.source_snapshot_id,
                            publisher_identity=str(linked[2]),
                            authoritative_first_party=category == "A",
                            formal_record=category == "A",
                            editorial_responsibility=category == "B",
                            attributed_author=category == "B",
                            verifiable_primary_evidence=category == "B",
                            underlying_evidence_id=(
                                None if linked[8] is None or not str(linked[8]).strip()
                                else str(linked[8])
                            ),
                            canonical_url=str(linked[1]),
                            excerpt=None if linked[6] is None else str(linked[6]),
                            retrieved_at=str(linked[3]),
                            published_at=None if linked[4] is None else str(linked[4]),
                            observed_at=None if linked[5] is None else str(linked[5]),
                        )
                    )
                assessment_id = uuid.uuid4()
                row = connection.execute(
                    f"""INSERT INTO research.anomaly_assessments(
                    assessment_id,version,evidence_id,evidence_version,actor_id,source_snapshot_ids,
                    source_characteristics,status,reason,requested_at,idempotency_key)
                    VALUES (%s,1,%s,%s,%s,%s::uuid[],%s::jsonb,'pending',%s,%s::timestamptz,%s)
                    RETURNING {self._anomaly_select().split('FROM ')[0].removeprefix('SELECT ')}""",
                    (
                        assessment_id,
                        command.evidence_id,
                        command.expected_evidence_version,
                        command.actor_id,
                        list(source_ids),
                        json.dumps([self._source_values(source) for source in stored_sources], separators=(",", ":")),
                        command.reason,
                        requested_at,
                        command.idempotency_key,
                    ),
                ).fetchone()
                connection.execute(
                    """INSERT INTO research.anomaly_analysis_jobs(
                    job_id,assessment_id,assessment_version,evidence_id,evidence_version,
                    build_version,policy_version,candidate_schema_version,candidate_prompt_version,
                    provider_model_version,critic_schema_version,critic_prompt_version,
                    critic_model_version)
                    VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        uuid.uuid4(), assessment_id, command.evidence_id,
                        command.expected_evidence_version, versions.build_version, policy_version,
                        versions.candidate_schema_version, versions.candidate_prompt_version,
                        versions.provider_model_version, versions.critic_schema_version,
                        versions.critic_prompt_version, versions.critic_model_version,
                    ),
                )
                connection.execute(
                    """INSERT INTO research.audit_events(event_id,actor_id,action,subject_id,subject_version,occurred_at)
                    VALUES (%s,%s,'anomaly.assessment.requested',%s,1,%s::timestamptz)""",
                    (uuid.uuid4(), command.actor_id, str(assessment_id), requested_at),
                )
        return self._anomaly_record(row)

    def claim_anomaly_job(self) -> AnomalyAnalysisJob | None:
        lease_token = uuid.uuid4()
        with self._connection() as connection:
            row = connection.execute(
                """WITH candidate AS (
                  SELECT job_id FROM research.anomaly_analysis_jobs
                  WHERE available_at <= now() AND (
                    state IN ('pending','retrying') OR
                    (state='processing' AND lease_expires_at <= now())
                  ) ORDER BY created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE research.anomaly_analysis_jobs j
                  SET state='processing',attempt=j.attempt+1,lease_token=%s,
                      lease_expires_at=now()+(%s * interval '1 second'),updated_at=now()
                  FROM candidate WHERE j.job_id=candidate.job_id
                  RETURNING j.job_id,j.assessment_id,j.assessment_version,j.evidence_id,
                    j.evidence_version,j.attempt,j.build_version,j.policy_version,
                    j.candidate_schema_version,j.candidate_prompt_version,j.provider_model_version,
                    j.critic_schema_version,j.critic_prompt_version,j.critic_model_version""",
                (lease_token, self._lease_seconds),
            ).fetchone()
        if row is None:
            return None
        return AnomalyAnalysisJob(
            job_id=str(row[0]), assessment_id=str(row[1]), assessment_version=int(row[2]),
            evidence_id=str(row[3]), evidence_version=int(row[4]), lease_token=str(lease_token),
            attempt=int(row[5]), build_version=str(row[6]), policy_version=str(row[7]),
            candidate_schema_version=str(row[8]), candidate_prompt_version=str(row[9]),
            provider_model_version=str(row[10]), critic_schema_version=str(row[11]),
            critic_prompt_version=str(row[12]), critic_model_version=str(row[13]),
        )

    def load_anomaly_sources(
        self, assessment_id: str
    ) -> tuple[SourceCharacteristicSnapshot, ...]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT source_characteristics FROM research.anomaly_assessments "
                "WHERE assessment_id=%s::uuid",
                (assessment_id,),
            ).fetchone()
        if row is None:
            return ()
        return tuple(
            SourceCharacteristicSnapshot(
                source_snapshot_id=str(item["source_snapshot_id"]),
                publisher_identity=str(item["publisher_identity"]),
                authoritative_first_party=bool(item["authoritative_first_party"]),
                formal_record=bool(item["formal_record"]),
                editorial_responsibility=bool(item["editorial_responsibility"]),
                attributed_author=bool(item["attributed_author"]),
                verifiable_primary_evidence=bool(item["verifiable_primary_evidence"]),
                underlying_evidence_id=(
                    None
                    if item.get("underlying_evidence_id") is None
                    else str(item["underlying_evidence_id"])
                ),
                canonical_url=None if item.get("canonical_url") is None else str(item["canonical_url"]),
                excerpt=None if item.get("excerpt") is None else str(item["excerpt"]),
                retrieved_at=None if item.get("retrieved_at") is None else str(item["retrieved_at"]),
                published_at=None if item.get("published_at") is None else str(item["published_at"]),
                observed_at=None if item.get("observed_at") is None else str(item["observed_at"]),
            )
            for item in row[0]
        )

    def commit_anomaly_result(
        self,
        *,
        command: EvaluateAssessmentCommand,
        trace: AnomalyDecisionTrace,
    ) -> AnomalyAssessmentRecord:
        with self._connection() as connection:
            with connection.transaction():
                row = connection.execute(
                    f"{self._anomaly_select()} WHERE assessment_id=%s::uuid FOR UPDATE",
                    (command.assessment_id,),
                ).fetchone()
                if row is None:
                    raise LookupError("resource_unavailable")
                current = self._anomaly_record(row)
                if current.version != command.expected_assessment_version:
                    raise ValueError("version_conflict")
                job = connection.execute(
                    """SELECT evidence_version FROM research.anomaly_analysis_jobs
                    WHERE assessment_id=%s::uuid AND state='processing' AND lease_token::text=%s FOR UPDATE""",
                    (command.assessment_id, command.lease_token),
                ).fetchone()
                if job is None:
                    raise ValueError("lease_unavailable")
                source_ids = tuple(source.source_snapshot_id for source in command.sources)
                if source_ids != current.source_snapshot_ids:
                    raise ValueError("source_version_conflict")
                evidence_version = connection.execute(
                    "SELECT version FROM research.evidence_intakes WHERE evidence_id=%s",
                    (current.evidence_id,),
                ).fetchone()[0]
                stale = int(evidence_version) != current.evidence_version or int(job[0]) != current.evidence_version
                status = AssessmentStatus.SUPERSEDED if stale else AssessmentStatus.SUCCEEDED
                failure_code = "stale_input" if stale else None
                updated = connection.execute(
                    f"""UPDATE research.anomaly_assessments
                    SET version=version+1,status=%s,trace=%s::jsonb,failure_code=%s
                    WHERE assessment_id=%s::uuid
                    RETURNING {self._anomaly_select().split('FROM ')[0].removeprefix('SELECT ')}""",
                    (status.value, json.dumps(self._trace_values(trace), separators=(",", ":")), failure_code, command.assessment_id),
                ).fetchone()
                connection.execute(
                    """UPDATE research.anomaly_analysis_jobs
                    SET state=%s,lease_token=NULL,lease_expires_at=NULL,updated_at=now()
                    WHERE assessment_id=%s::uuid""",
                    ("superseded" if stale else "succeeded", command.assessment_id),
                )
                connection.execute(
                    """INSERT INTO research.audit_events(event_id,actor_id,action,subject_id,subject_version)
                    VALUES (%s,'ai-worker','anomaly.assessment.completed',%s,%s)""",
                    (uuid.uuid4(), command.assessment_id, current.version + 1),
                )
        return self._anomaly_record(updated)

    def get_anomaly_assessment(self, assessment_id: str) -> AnomalyAssessmentRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                f"{self._anomaly_select()} WHERE assessment_id=%s::uuid",
                (assessment_id,),
            ).fetchone()
        return None if row is None else self._anomaly_record(row)

    def claim_collection_job(self) -> LeasedCollectionJob | None:
        lease_token = uuid.uuid4()
        with self._connection() as connection:
            row = connection.execute(
                """WITH candidate AS (
                  SELECT job_id FROM research.collection_jobs
                  WHERE available_at <= now() AND (
                    state IN ('pending','retrying') OR
                    (state='processing' AND lease_expires_at <= now())
                  )
                  ORDER BY created_at, job_id FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE research.collection_jobs j SET state='processing', attempt=j.attempt+1,
                    lease_token=%s, lease_expires_at=now()+(%s * interval '1 second'), updated_at=now()
                  FROM candidate WHERE j.job_id=candidate.job_id
                  RETURNING j.job_id,j.evidence_id,j.evidence_version,j.submitted_url,j.idempotency_key,j.attempt""",
                (lease_token, self._lease_seconds),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE research.evidence_intakes SET status='processing',version=version+1,updated_at=now() WHERE evidence_id=%s",
                (row[1],),
            )
        return LeasedCollectionJob(str(row[0]), str(row[1]), int(row[2]), str(row[3]), str(row[4]), str(lease_token), int(row[5]))

    def transition(self, evidence_id: str, status: EvidenceStatus) -> None:
        with self._connection() as connection:
            connection.execute("UPDATE research.evidence_intakes SET status=%s,version=version+1,updated_at=now() WHERE evidence_id=%s", (status.value, evidence_id))

    def complete_collection(self, evidence_id: str, snapshot: CollectedSourceSnapshot,
                            lease_token: str | None = None) -> bool:
        if lease_token is None:
            return False
        with self._connection() as connection:
            with connection.transaction():
                canonical_key = f"{snapshot.normalization_policy_version}\x1f{snapshot.canonical_url}"
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (canonical_key,))
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (snapshot.content_hash,))
                result = connection.execute(
                    "UPDATE research.collection_jobs SET state='succeeded',lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE evidence_id=%s AND state='processing' AND lease_token::text=%s",
                    (evidence_id, lease_token),
                )
                if result.rowcount != 1:
                    return False
                existing_source = connection.execute(
                    """SELECT source_id FROM research.canonical_sources
                    WHERE normalization_policy_version=%s AND canonical_url=%s""",
                    (snapshot.normalization_policy_version, snapshot.canonical_url),
                ).fetchone()
                existing_snapshot = connection.execute(
                    "SELECT snapshot_id FROM research.source_snapshots WHERE content_hash=%s",
                    (snapshot.content_hash,),
                ).fetchone()
                snapshot_id = existing_snapshot[0] if existing_snapshot else uuid.uuid4()
                if existing_snapshot is None:
                    connection.execute(
                        """INSERT INTO research.source_snapshots(snapshot_id,canonical_url,normalization_policy_version,publisher,content_hash,retrieved_at,published_at,observed_at,excerpt,source_category,lineage)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (snapshot_id, snapshot.canonical_url, snapshot.normalization_policy_version,
                         snapshot.publisher, snapshot.content_hash, snapshot.retrieved_at,
                         snapshot.published_at, snapshot.observed_at, snapshot.excerpt,
                         snapshot.source_category, snapshot.lineage),
                    )
                if existing_source is None:
                    source_id = uuid.uuid4()
                    connection.execute(
                        """INSERT INTO research.canonical_sources(source_id,normalization_policy_version,canonical_url)
                        VALUES (%s,%s,%s)""",
                        (source_id, snapshot.normalization_policy_version, snapshot.canonical_url),
                    )
                else:
                    source_id = existing_source[0]
                connection.execute(
                    """INSERT INTO research.source_observations(evidence_id,source_id,snapshot_id,submitted_url)
                    SELECT evidence_id,%s,%s,submitted_url FROM research.evidence_intakes WHERE evidence_id=%s
                    ON CONFLICT (evidence_id) DO NOTHING""",
                    (source_id, snapshot_id, evidence_id),
                )
                connection.execute("UPDATE research.evidence_intakes SET status='succeeded',version=version+1,updated_at=now() WHERE evidence_id=%s", (evidence_id,))
        return True

    def fail_collection(self, job: LeasedCollectionJob, lease_token: str, failure_code: str,
                        *, retryable: bool) -> bool:
        terminal = not retryable or job.attempt >= self._max_attempts
        job_state = "dead_letter" if terminal and retryable else ("failed" if terminal else "retrying")
        evidence_state = EvidenceStatus.DEAD_LETTER.value if job_state == "dead_letter" else job_state
        with self._connection() as connection:
            with connection.transaction():
                result = connection.execute(
                    """UPDATE research.collection_jobs SET state=%s,failure_code=%s,lease_token=NULL,lease_expires_at=NULL,
                    available_at=CASE WHEN %s THEN now()+((attempt*attempt)*interval '1 minute') ELSE available_at END,updated_at=now()
                    WHERE job_id=%s AND state='processing' AND lease_token::text=%s""",
                    (job_state, failure_code, not terminal, job.job_id, lease_token),
                )
                if result.rowcount != 1:
                    return False
                connection.execute("UPDATE research.evidence_intakes SET status=%s,failure_code=%s,version=version+1,updated_at=now() WHERE evidence_id=%s", (evidence_state, failure_code, job.evidence_id))
        return True

    def ping(self) -> bool:
        try:
            with self._connection() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except Exception:
            return False

    def applied_migrations(self) -> list[tuple[int, str]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT version,name FROM research.schema_migrations ORDER BY version"
            ).fetchall()
        return [(int(row[0]), str(row[1])) for row in rows]

    def delete_all_for_test(self) -> None:
        with self._connection() as connection:
            connection.execute(
                "TRUNCATE research.anomaly_analysis_jobs,research.anomaly_assessments,"
                "research.evidence_stage_versions,research.source_observations,"
                "research.canonical_sources,research.source_snapshots,research.collection_jobs,"
                "research.audit_events,research.idempotency_receipts,research.evidence_intakes,"
                "research.companies CASCADE"
            )

    def count_audit_events(self, evidence_id: str) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT count(*) FROM research.audit_events WHERE subject_id=%s", (evidence_id,)).fetchone()[0])

    def count_collection_jobs(self, evidence_id: str) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT count(*) FROM research.collection_jobs WHERE evidence_id=%s", (evidence_id,)).fetchone()[0])

    def count_anomaly_jobs(self, assessment_id: str) -> int:
        with self._connection() as connection:
            return int(
                connection.execute(
                    "SELECT count(*) FROM research.anomaly_analysis_jobs WHERE assessment_id=%s::uuid",
                    (assessment_id,),
                ).fetchone()[0]
            )

    def count_source_snapshots(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT count(*) FROM research.source_snapshots").fetchone()[0])

    def count_canonical_sources(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT count(*) FROM research.canonical_sources").fetchone()[0])

    def count_source_observations(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT count(*) FROM research.source_observations").fetchone()[0])

    def get_source_provenance(self, evidence_id: str) -> tuple[str, str, str, str, str, str | None, str | None, str | None, str, str | None] | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT c.canonical_url,c.normalization_policy_version,s.publisher,s.content_hash,s.retrieved_at::text,
                s.published_at::text,s.observed_at::text,s.excerpt,s.source_category,o.submitted_url
                FROM research.source_observations o
                JOIN research.canonical_sources c USING(source_id)
                JOIN research.source_snapshots s ON s.snapshot_id=o.snapshot_id
                WHERE o.evidence_id=%s""", (evidence_id,)
            ).fetchone()
        return None if row is None else tuple(None if value is None else str(value) for value in row)
