from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator, Protocol
import hashlib
import uuid

import sqlalchemy as sa

from thesis_trace.modules.recommendation.contracts import (
    OwnerDecision,
    RecommendationRecord,
    RecommendationInputSnapshot,
    RecommendationJob,
)
from thesis_trace.modules.recommendation.service import RecommendationService
from thesis_trace.platform.database import (
    DatabaseUrlProvider,
    create_database_engine,
    database_connection,
)
from thesis_trace.adapters.postgres_recommendation.mapping import (
    _decision,
    _identity,
    _insert,
    _load,
    _tables,
    _insert_input,
    _load_input,
)


class _SecurityContext(Protocol):
    user_id: str
    role: Any
    ownership_scope: str


class PostgresRecommendationStore:
    """Owner-schema participant, never a substitute for the parent atomic operation."""

    def __init__(
        self,
        database_url_provider: DatabaseUrlProvider,
        *,
        security_context_provider: Callable[[], _SecurityContext | None],
        transaction_connection: sa.Connection | None = None,
        build_version: str = "test-build",
    ) -> None:
        self._database_url_provider = database_url_provider
        self._security_context_provider = security_context_provider
        self._transaction_connection = transaction_connection
        self._build_version = build_version
        self._engine = (
            create_database_engine(database_url_provider)
            if transaction_connection is None
            else None
        )

    def for_transaction(
        self,
        connection: sa.Connection,
        *,
        security_context_provider: Callable[[], _SecurityContext | None] | None = None,
    ) -> PostgresRecommendationStore:
        return PostgresRecommendationStore(
            self._database_url_provider,
            security_context_provider=security_context_provider
            or self._security_context_provider,
            transaction_connection=connection,
            build_version=self._build_version,
        )

    def get_request(
        self, actor_id: str, input_id: str
    ) -> tuple[str, str, str, str | None, datetime, int | None] | None:
        if not self._authorized(actor_id):
            return None
        with self._connection() as connection:
            row = connection.exec_driver_sql(
                """SELECT a.input_id,a.thesis_id,j.state,j.error_code,a.admitted_at,
                (SELECT max(r.version) FROM recommendation.records r WHERE r.owner_user_id=a.owner_user_id AND r.recommendation_id=a.input_id)
                FROM recommendation.admissions a JOIN recommendation.jobs j USING(owner_user_id,input_id)
                WHERE a.owner_user_id=%s AND a.input_id=%s""",
                (actor_id, input_id),
            ).fetchone()
            return tuple(row) if row is not None else None

    def list_requests(
        self,
        actor_id: str,
        company_id: str,
        *,
        before: str | None = None,
        limit: int = 26,
    ) -> tuple[tuple[str, str, str, str | None, datetime, int | None], ...]:
        if not self._authorized(actor_id):
            return ()
        if type(limit) is not int or not 1 <= limit <= 26:
            raise ValueError("invalid_query")
        with self._connection() as connection:
            cursor_time = None
            if before is not None:
                row = connection.exec_driver_sql(
                    "SELECT admitted_at FROM recommendation.admissions WHERE owner_user_id=%s AND company_id=%s AND input_id=%s",
                    (actor_id, company_id, before),
                ).fetchone()
                if row is None:
                    raise LookupError("resource_unavailable")
                cursor_time = row[0]
            sql = """SELECT a.input_id,a.thesis_id,j.state,j.error_code,a.admitted_at,
                (SELECT max(r.version) FROM recommendation.records r WHERE r.owner_user_id=a.owner_user_id AND r.recommendation_id=a.input_id)
                FROM recommendation.admissions a JOIN recommendation.jobs j USING(owner_user_id,input_id)
                WHERE a.owner_user_id=%s AND a.company_id=%s"""
            values = (actor_id, company_id)
            if before is not None:
                sql += " AND (a.admitted_at,a.input_id)<(%s,%s)"
                values += (cursor_time, before)
            sql += " ORDER BY a.admitted_at DESC,a.input_id DESC LIMIT %s"
            return tuple(
                tuple(row)
                for row in connection.exec_driver_sql(sql, values + (limit,)).fetchall()
            )

    def _authorized(self, actor_id: str) -> bool:
        context = self._security_context_provider()
        return (
            context is not None
            and context.user_id == actor_id
            and context.role.value == "owner"
        )

    def next_expiry_candidate(self) -> tuple[str, str, int, int] | None:
        # This worker-only owner function exposes no research or financial content.
        # Its own short transaction advances a durable cursor before source work.
        with self._job_connection() as connection:
            row = connection.exec_driver_sql(
                "SELECT owner_id,record_id,record_version,decision_sequence FROM recommendation.next_expiry_candidate()"
            ).fetchone()
            return (
                (str(row[0]), str(row[1]), int(row[2]), int(row[3]))
                if row is not None
                else None
            )

    @contextmanager
    def _job_connection(self) -> Iterator[sa.Connection]:
        # Global claims rely on the database worker credential/RLS, not an API GUC.
        # Owner-bound calls still validate the caller's active transaction context.
        if self._security_context_provider() is not None:
            with self._connection() as connection:
                yield connection
        elif self._transaction_connection is not None:
            if not self._transaction_connection.in_transaction():
                raise ValueError("active_transaction_required")
            yield self._transaction_connection
        else:
            assert self._engine is not None
            with database_connection(self._engine) as connection:
                yield connection

    def admit(
        self,
        *,
        inputs: RecommendationInputSnapshot,
        input_id: str,
        job_id: str,
        versions: tuple[tuple[str, str], ...],
        idempotency_key: str,
        command_digest: str,
    ) -> str:
        actor = inputs.actor.actor_id
        if not self._authorized(actor):
            raise PermissionError("resource_unavailable")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (input_id, job_id, idempotency_key, command_digest)
        ):
            raise ValueError("invalid_admission_identity")
        if len(command_digest) != 64 or any(
            c not in "0123456789abcdef" for c in command_digest
        ):
            raise ValueError("invalid_idempotency")
        digest = RecommendationService.admission_digest(inputs, versions)
        tables = _tables()
        header, jobs = tables["admissions"], tables["jobs"]
        try:
            with self._connection() as connection:
                self._lock(
                    connection, "recommendation-admission", actor, idempotency_key
                )
                existing = (
                    connection.execute(
                        sa.select(header).where(
                            header.c.owner_user_id == actor,
                            header.c.idempotency_key == idempotency_key,
                        )
                    )
                    .mappings()
                    .first()
                )
                if existing is not None:
                    if (
                        existing["command_digest"] != command_digest
                        or existing["input_digest"] != digest
                    ):
                        raise ValueError("idempotency_conflict")
                    return existing["input_id"]
                _insert_input(
                    connection,
                    tables,
                    inputs,
                    input_id=input_id,
                    digest=digest,
                    versions=versions,
                    idempotency_key=idempotency_key,
                    command_digest=command_digest,
                )
                connection.execute(
                    jobs.insert().values(
                        job_id=job_id,
                        owner_user_id=actor,
                        input_id=input_id,
                        thesis_id=inputs.thesis_id,
                        cycle=inputs.cycle,
                        state="pending",
                        attempt=0,
                        available_at=sa.func.clock_timestamp(),
                        updated_at=sa.func.clock_timestamp(),
                    )
                )
        except Exception as error:
            # Inspect the nested driver diagnostic without leaking SQL or credentials.
            cause = error
            while cause is not None:
                original = getattr(cause, "orig", cause)
                if (
                    getattr(getattr(original, "diag", None), "message_primary", None)
                    == "recommendation_queue_full"
                ):
                    raise ValueError("recommendation_queue_full") from None
                cause = cause.__cause__
            raise
        return input_id

    def get_input(
        self, actor_id: str, input_id: str
    ) -> tuple[RecommendationInputSnapshot, tuple[tuple[str, str], ...]] | None:
        if not self._authorized(actor_id):
            return None
        with self._connection() as connection:
            result = _load_input(connection, _tables(), actor_id, input_id)
            if result is None:
                return None
            inputs, versions, digest = result
            if RecommendationService.admission_digest(inputs, versions) != digest:
                raise ValueError("input_digest_conflict")
            return inputs, versions

    def find_admission(
        self, actor_id: str, idempotency_key: str, command_digest: str
    ) -> str | None:
        if not self._authorized(actor_id):
            raise PermissionError("resource_unavailable")
        table = _tables()["admissions"]
        with self._connection() as connection:
            self._lock(
                connection, "recommendation-admission", actor_id, idempotency_key
            )
            row = connection.execute(
                sa.select(table.c.input_id, table.c.command_digest).where(
                    table.c.owner_user_id == actor_id,
                    table.c.idempotency_key == idempotency_key,
                )
            ).first()
            if row is None:
                return None
            if row.command_digest != command_digest:
                raise ValueError("idempotency_conflict")
            return row.input_id

    @staticmethod
    def _claimed(
        connection: sa.Connection, tables: dict[str, sa.Table], row: Any
    ) -> RecommendationJob:
        header = tables["admissions"]
        admitted = (
            connection.execute(
                sa.select(header.c.input_digest, header.c.versions).where(
                    header.c.owner_user_id == row["owner_user_id"],
                    header.c.input_id == row["input_id"],
                )
            )
            .mappings()
            .one()
        )
        return RecommendationJob(
            row["job_id"],
            row["input_id"],
            admitted["input_digest"],
            row["owner_user_id"],
            row["thesis_id"],
            row["cycle"],
            row["lease_token"],
            row["lease_expires_at"],
            row["attempt"],
            tuple(tuple(pair) for pair in admitted["versions"]),
        )

    def claim_job(self) -> RecommendationJob | None:
        tables = _tables()
        jobs = tables["jobs"]
        context = self._security_context_provider()
        scope = (
            sa.true() if context is None else jobs.c.owner_user_id == context.user_id
        )
        with self._job_connection() as connection:
            # Short DB-only serialization closes the same-stream NOT EXISTS race.
            self._lock(connection, "recommendation-claim")
            exhausted = connection.execute(
                sa.select(jobs.c.job_id)
                .where(
                    scope,
                    jobs.c.state == "processing",
                    jobs.c.attempt >= 3,
                    jobs.c.lease_expires_at <= sa.func.clock_timestamp(),
                )
                .order_by(jobs.c.available_at, jobs.c.job_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).first()
            if exhausted is not None:
                connection.execute(
                    jobs.update()
                    .where(jobs.c.job_id == exhausted[0])
                    .values(
                        state="dead_letter",
                        error_code="lease_exhausted",
                        lease_token=None,
                        lease_expires_at=None,
                        updated_at=sa.func.clock_timestamp(),
                    )
                )
            other = jobs.alias("other_processing")
            busy = sa.exists(
                sa.select(other.c.job_id).where(
                    other.c.owner_user_id == jobs.c.owner_user_id,
                    other.c.thesis_id == jobs.c.thesis_id,
                    other.c.cycle == jobs.c.cycle,
                    other.c.state == "processing",
                    other.c.job_id != jobs.c.job_id,
                )
            )
            candidate = (
                connection.execute(
                    sa.select(jobs)
                    .where(
                        scope,
                        jobs.c.available_at <= sa.func.clock_timestamp(),
                        jobs.c.attempt < 3,
                        ~busy,
                        sa.or_(
                            jobs.c.state.in_(("pending", "retrying")),
                            sa.and_(
                                jobs.c.state == "processing",
                                jobs.c.lease_expires_at <= sa.func.clock_timestamp(),
                            ),
                        ),
                    )
                    .order_by(jobs.c.available_at, jobs.c.job_id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .first()
            )
            if candidate is None:
                return None
            row = (
                connection.execute(
                    jobs.update()
                    .where(jobs.c.job_id == candidate["job_id"])
                    .values(
                        state="processing",
                        attempt=jobs.c.attempt + 1,
                        lease_token=str(uuid.uuid4()),
                        lease_expires_at=sa.func.clock_timestamp()
                        + timedelta(seconds=300),
                        updated_at=sa.func.clock_timestamp(),
                        error_code=None,
                    )
                    .returning(jobs)
                )
                .mappings()
                .one()
            )
            return self._claimed(connection, tables, row)

    def _assert_lease(
        self,
        connection: sa.Connection,
        tables: dict[str, sa.Table],
        job: RecommendationJob,
    ) -> None:
        if self._security_context_provider() is not None and not self._authorized(
            job.actor_id
        ):
            raise ValueError("lease_unavailable")
        jobs = tables["jobs"]
        row = (
            connection.execute(
                sa.select(jobs).where(jobs.c.job_id == job.job_id).with_for_update()
            )
            .mappings()
            .first()
        )
        now = connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if (
            row is None
            or row["state"] != "processing"
            or row["lease_expires_at"] <= now
        ):
            raise ValueError("lease_unavailable")
        actual = self._claimed(connection, tables, row)
        # Renewal changes only the timestamp; all authority-bearing claim fields must still match.
        if replace(actual, lease_expires_at=job.lease_expires_at) != job:
            raise ValueError("lease_unavailable")

    def load_job_input(self, job: RecommendationJob) -> RecommendationInputSnapshot:
        tables = _tables()
        with self._job_connection() as connection:
            self._assert_lease(connection, tables, job)
            result = _load_input(connection, tables, job.actor_id, job.input_id)
            if result is None:
                raise ValueError("input_digest_conflict")
            inputs, versions, digest = result
            if (
                digest != job.input_digest
                or RecommendationService.admission_digest(inputs, versions) != digest
            ):
                raise ValueError("input_digest_conflict")
            return inputs

    def renew_job(self, job: RecommendationJob) -> RecommendationJob:
        tables = _tables()
        jobs = tables["jobs"]
        with self._job_connection() as connection:
            self._assert_lease(connection, tables, job)
            row = (
                connection.execute(
                    jobs.update()
                    .where(
                        jobs.c.job_id == job.job_id,
                        jobs.c.lease_expires_at > sa.func.clock_timestamp(),
                    )
                    .values(
                        lease_expires_at=sa.func.clock_timestamp()
                        + timedelta(seconds=300),
                        updated_at=sa.func.clock_timestamp(),
                    )
                    .returning(jobs)
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ValueError("lease_unavailable")
            return self._claimed(connection, tables, row)

    def _finish(
        self,
        job: RecommendationJob,
        *,
        state: str,
        error_code: str | None,
        delay: int = 0,
    ) -> None:
        tables = _tables()
        jobs = tables["jobs"]
        with self._job_connection() as connection:
            self._assert_lease(connection, tables, job)
            result = connection.execute(
                jobs.update()
                .where(
                    jobs.c.job_id == job.job_id,
                    jobs.c.lease_expires_at > sa.func.clock_timestamp(),
                )
                .values(
                    state=state,
                    error_code=error_code,
                    lease_token=None,
                    lease_expires_at=None,
                    available_at=sa.func.clock_timestamp() + timedelta(seconds=delay),
                    updated_at=sa.func.clock_timestamp(),
                )
            )
            if result.rowcount != 1:
                raise ValueError("lease_unavailable")

    def finish_job(self, job: RecommendationJob) -> None:
        self._finish(job, state="succeeded", error_code=None)

    def fail_job(
        self, job: RecommendationJob, *, error_code: str, transient: bool
    ) -> None:
        transport = error_code in (
            "provider_transport_failure",
            "critic_transport_failure",
        )
        if not transport and error_code not in (
            "provider_unavailable",
            "invalid_candidate",
            "invalid_candidate_sources",
            "invalid_critic",
            "critic_rejected",
            "superseded_inputs",
            "resource_unavailable",
            "input_digest_conflict",
            "input_too_large",
            "publication_rejected",
        ):
            raise ValueError("invalid_failure_code")
        retry = transient is True and transport and job.attempt < 3
        self._finish(
            job,
            state="retrying"
            if retry
            else "dead_letter"
            if transport and job.attempt >= 3
            else "failed",
            error_code=error_code,
            delay=(60 if job.attempt == 1 else 240) if retry else 0,
        )

    def job_status(self, actor_id: str, input_id: str) -> tuple[str, str | None] | None:
        if not self._authorized(actor_id):
            return None
        table = _tables()["jobs"]
        with self._connection() as connection:
            row = connection.execute(
                sa.select(table.c.state, table.c.error_code).where(
                    table.c.owner_user_id == actor_id, table.c.input_id == input_id
                )
            ).first()
            return None if row is None else tuple(row)

    @contextmanager
    def _connection(self) -> Iterator[sa.Connection]:
        context = self._security_context_provider()
        if context is None or context.role.value != "owner":
            raise PermissionError("resource_unavailable")
        if self._transaction_connection is not None:
            if not self._transaction_connection.in_transaction():
                raise ValueError("active_transaction_required")
            identity = self._transaction_connection.exec_driver_sql(
                "SELECT current_setting('app.user_id',true),current_setting('app.role',true)"
            ).fetchone()
            if tuple(identity) != (context.user_id, context.role.value):
                raise PermissionError("transaction_context_mismatch")
            yield self._transaction_connection
            return
        assert self._engine is not None
        with database_connection(self._engine) as connection:
            connection.exec_driver_sql(
                "SELECT set_config('app.user_id',%s,true)", (context.user_id,)
            )
            connection.exec_driver_sql(
                "SELECT set_config('app.role',%s,true)", (context.role.value,)
            )
            connection.exec_driver_sql(
                "SELECT set_config('app.request_id',%s,true)",
                (context.ownership_scope,),
            )
            yield connection

    @staticmethod
    def _lock(connection: sa.Connection, namespace: str, *identity: str) -> None:
        # Length-prefixed identity avoids delimiter collisions; namespace separates receipt/record locks.
        value = namespace + "".join(f"{len(part)}:{part}" for part in identity)
        key = int.from_bytes(
            hashlib.sha256(value.encode()).digest()[:8], "big", signed=True
        )
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (key,))

    def get_record(
        self, actor_id: str, recommendation_id: str, version: int
    ) -> RecommendationRecord | None:
        if not self._authorized(actor_id):
            return None
        with self._connection() as connection:
            return _load(connection, _tables(), actor_id, recommendation_id, version)

    def append_record(self, record: RecommendationRecord) -> RecommendationRecord:
        actor = record.inputs.actor.actor_id
        if not self._authorized(actor) or record.inputs.actor.may_manage is not True:
            raise PermissionError("resource_unavailable")
        tables = _tables()
        with self._connection() as connection:
            self._lock(
                connection,
                "recommendation-record",
                actor,
                record.recommendation_id,
                str(record.version),
            )
            existing = _load(
                connection, tables, actor, record.recommendation_id, record.version
            )
            if existing is not None:
                if existing != record:
                    raise ValueError("version_conflict")
                return existing
            _insert(connection, tables, record)
            connection.execute(
                tables["audit_events"]
                .insert()
                .values(
                    event_id=str(uuid.uuid4()),
                    owner_user_id=actor,
                    recommendation_id=record.recommendation_id,
                    version=record.version,
                    action="recommendation_published",
                    reason=record.inputs.source_selection_reason,
                    occurred_at=record.published_at,
                    before_sequence=0,
                    after_sequence=0,
                    correlation_id=self._security_context_provider().ownership_scope,
                    causation_id=record.candidate.digest,
                    policy_version=record.policy_version,
                    build_version=self._build_version,
                )
            )
        return record

    def find_decision_receipt(
        self, actor_id: str, idempotency_key: str, command_digest: str
    ) -> OwnerDecision | None:
        if not self._authorized(actor_id):
            raise PermissionError("resource_unavailable")
        tables = _tables()
        receipts, decisions = tables["receipts"], tables["decisions"]
        with self._connection() as connection:
            self._lock(connection, "recommendation-receipt", actor_id, idempotency_key)
            receipt = (
                connection.execute(
                    sa.select(receipts).where(
                        receipts.c.owner_user_id == actor_id,
                        receipts.c.idempotency_key == idempotency_key,
                    )
                )
                .mappings()
                .first()
            )
            if receipt is None:
                return None
            if receipt["command_digest"] != command_digest:
                raise ValueError("idempotency_conflict")
            row = (
                connection.execute(
                    sa.select(decisions).where(
                        _identity(
                            decisions,
                            actor_id,
                            receipt["recommendation_id"],
                            receipt["version"],
                        ),
                        decisions.c.sequence == receipt["decision_sequence"],
                    )
                )
                .mappings()
                .one()
            )
            return _decision(row)

    def lock_decision_stream(
        self, actor_id: str, recommendation_id: str, version: int
    ) -> None:
        if (
            self._transaction_connection is None
            or not self._transaction_connection.in_transaction()
        ):
            raise ValueError("inactive_transaction")
        if not self._authorized(actor_id):
            raise PermissionError("resource_unavailable")
        records = _tables()["records"]
        with self._connection() as connection:
            if (
                connection.execute(
                    sa.select(records.c.version)
                    .where(_identity(records, actor_id, recommendation_id, version))
                    .with_for_update()
                ).first()
                is None
            ):
                raise LookupError("resource_unavailable")

    def latest_decision(
        self, actor_id: str, recommendation_id: str, version: int
    ) -> OwnerDecision | None:
        if not self._authorized(actor_id):
            raise PermissionError("resource_unavailable")
        table = _tables()["decisions"]
        with self._connection() as connection:
            row = (
                connection.execute(
                    sa.select(table)
                    .where(_identity(table, actor_id, recommendation_id, version))
                    .order_by(table.c.sequence.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            return _decision(row) if row is not None else None

    def decision_history(
        self,
        actor_id: str,
        recommendation_id: str,
        version: int,
        *,
        limit: int | None = None,
        before_sequence: int | None = None,
    ) -> tuple[OwnerDecision, ...]:
        if not self._authorized(actor_id):
            return ()
        if (limit is not None and (type(limit) is not int or not 1 <= limit <= 51)) or (
            before_sequence is not None
            and (type(before_sequence) is not int or before_sequence < 1)
        ):
            raise ValueError("invalid_query")
        table = _tables()["decisions"]
        with self._connection() as connection:
            statement = sa.select(table).where(
                _identity(table, actor_id, recommendation_id, version)
            )
            if before_sequence is not None:
                statement = statement.where(table.c.sequence < before_sequence)
            statement = statement.order_by(
                table.c.sequence.desc() if limit is not None else table.c.sequence
            )
            if limit is not None:
                statement = statement.limit(limit)
            result = tuple(
                _decision(row) for row in connection.execute(statement).mappings()
            )
            return tuple(reversed(result)) if limit is not None else result

    def append_decision(
        self,
        decision: OwnerDecision,
        *,
        expected_sequence: int,
        idempotency_key: str,
        command_digest: str,
    ) -> OwnerDecision:
        actor = decision.actor_id
        if not self._authorized(actor):
            raise PermissionError("resource_unavailable")
        if (
            not idempotency_key.strip()
            or len(command_digest) != 64
            or any(c not in "0123456789abcdef" for c in command_digest)
        ):
            raise ValueError("invalid_idempotency")
        tables = _tables()
        receipts, decisions, records = (
            tables["receipts"],
            tables["decisions"],
            tables["records"],
        )
        with self._connection() as connection:
            self._lock(connection, "recommendation-receipt", actor, idempotency_key)
            receipt = (
                connection.execute(
                    sa.select(receipts).where(
                        receipts.c.owner_user_id == actor,
                        receipts.c.idempotency_key == idempotency_key,
                    )
                )
                .mappings()
                .first()
            )
            if receipt is not None:
                if (
                    receipt["command_digest"],
                    receipt["recommendation_id"],
                    receipt["version"],
                ) != (
                    command_digest,
                    decision.recommendation_id,
                    decision.recommendation_version,
                ):
                    raise ValueError("idempotency_conflict")
                row = (
                    connection.execute(
                        sa.select(decisions).where(
                            _identity(
                                decisions,
                                actor,
                                decision.recommendation_id,
                                decision.recommendation_version,
                            ),
                            decisions.c.sequence == receipt["decision_sequence"],
                        )
                    )
                    .mappings()
                    .one()
                )
                return _decision(row)
            record = (
                connection.execute(
                    sa.select(records)
                    .where(
                        _identity(
                            records,
                            actor,
                            decision.recommendation_id,
                            decision.recommendation_version,
                        )
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if record is None:
                raise LookupError("resource_unavailable")
            previous = (
                connection.execute(
                    sa.select(decisions)
                    .where(
                        _identity(
                            decisions,
                            actor,
                            decision.recommendation_id,
                            decision.recommendation_version,
                        )
                    )
                    .order_by(decisions.c.sequence.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if (
                type(expected_sequence) is not int
                or expected_sequence != (previous["sequence"] if previous else 0)
                or decision.sequence != expected_sequence + 1
            ):
                raise ValueError("version_conflict")
            if (
                record["direction"] not in ("buy", "hold")
                or previous is not None
                and previous["status"] in ("accepted", "rejected", "expired")
            ):
                raise ValueError("invalid_transition")
            if decision.recorded_at.utcoffset() is None or decision.recorded_at < (
                previous["recorded_at"] if previous else record["published_at"]
            ):
                raise ValueError("invalid_decision_time")
            identity = dict(
                owner_user_id=actor,
                recommendation_id=decision.recommendation_id,
                version=decision.recommendation_version,
            )
            connection.execute(
                decisions.insert().values(
                    **identity,
                    sequence=decision.sequence,
                    status=decision.status,
                    reason=decision.reason,
                    recorded_at=decision.recorded_at,
                    defer_until=decision.defer_until,
                    policy_version=decision.policy_version,
                    input_checks=[list(pair) for pair in decision.input_checks],
                    confirmation_id=decision.confirmation_id,
                )
            )
            connection.execute(
                receipts.insert().values(
                    **identity,
                    idempotency_key=idempotency_key,
                    command_digest=command_digest,
                    decision_sequence=decision.sequence,
                )
            )
            connection.execute(
                tables["audit_events"]
                .insert()
                .values(
                    **identity,
                    event_id=str(uuid.uuid4()),
                    action="recommendation_" + decision.status,
                    reason=decision.reason,
                    occurred_at=decision.recorded_at,
                    before_sequence=expected_sequence,
                    after_sequence=decision.sequence,
                    correlation_id=idempotency_key,
                    causation_id=command_digest,
                    policy_version=decision.policy_version,
                    build_version=self._build_version,
                )
            )
        return decision
