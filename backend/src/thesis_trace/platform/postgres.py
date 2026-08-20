from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
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

MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "wave0_company_evidence", MIGRATION_0001),
    (2, "access_identity_session_confirmation", MIGRATION_0002),
    (3, "access_rls", MIGRATION_0003),
    (4, "recovery_session_policy_binding", MIGRATION_0004),
    (5, "source_normalization_policy_version", MIGRATION_0005),
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
            elif self._runtime_role == "collector":
                connection.execute("SELECT set_config('app.role','collector',true)")
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
            connection.execute("TRUNCATE research.source_observations,research.canonical_sources,research.source_snapshots,research.collection_jobs,research.audit_events,research.idempotency_receipts,research.evidence_intakes,research.companies CASCADE")

    def count_audit_events(self, evidence_id: str) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT count(*) FROM research.audit_events WHERE subject_id=%s", (evidence_id,)).fetchone()[0])

    def count_collection_jobs(self, evidence_id: str) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT count(*) FROM research.collection_jobs WHERE evidence_id=%s", (evidence_id,)).fetchone()[0])

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
