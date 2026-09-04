from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import uuid
from typing import Any, Callable, Iterator, Protocol

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from thesis_trace.modules.thesis.contracts import (
    InvalidationCondition,
    ReflectionDraftRevision,
    ThesisOutcome,
    ThesisRecord,
    ThesisReflection,
    ThesisResearchReference,
    ThesisStatus,
    ValuationCoverage,
    ValuationBenchmarkSnapshot,
    ValuationDistribution,
    ValuationDraft,
    ValuationMethod,
    ValuationSample,
    PeerValuationMember,
    ValuationReturn,
    ValuationSnapshot,
    ValuationValidity,
)
from thesis_trace.platform.database import (
    DatabaseUrlProvider,
    create_database_engine,
    database_connection,
)


_METADATA = sa.MetaData()
_THESES = sa.Table(
    "theses", _METADATA,
    sa.Column("thesis_id", sa.Text, primary_key=True), sa.Column("version", sa.Integer),
    sa.Column("owner_user_id", sa.Text), sa.Column("company_id", sa.Text),
    sa.Column("company_version", sa.Integer), sa.Column("status", sa.Text),
    sa.Column("cycle", sa.Integer), sa.Column("title", sa.Text), sa.Column("narrative", sa.Text),
    sa.Column("reflection_pending", sa.Boolean), sa.Column("policy_version", sa.Text),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("valuation_draft_version", sa.Integer), schema="thesis",
)
_VALUATION_DRAFTS = sa.Table(
    "valuation_drafts", _METADATA,
    sa.Column("thesis_id", sa.Text, primary_key=True),
    sa.Column("draft_version", sa.Integer, primary_key=True), sa.Column("owner_user_id", sa.Text),
    sa.Column("payload", sa.JSON), sa.Column("saved_at", sa.DateTime(timezone=True)),
    sa.Column("method", sa.Text), sa.Column("benchmark_source", sa.Text),
    sa.Column("benchmark_variant", sa.Text), sa.Column("target_date", sa.Date),
    sa.Column("expires_at", sa.DateTime(timezone=True)), sa.Column("cost_profile_version", sa.Integer),
    sa.Column("policy_version", sa.Text), schema="thesis",
)
_VALUATION_SNAPSHOTS = sa.Table(
    "valuation_snapshots", _METADATA,
    sa.Column("valuation_id", sa.Text, primary_key=True), sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("thesis_id", sa.Text), sa.Column("owner_user_id", sa.Text),
    sa.Column("draft_version", sa.Integer), sa.Column("payload", sa.JSON),
    sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("method", sa.Text),
    sa.Column("benchmark_source", sa.Text), sa.Column("benchmark_variant", sa.Text),
    sa.Column("target_date", sa.Date), sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("cost_profile_version", sa.Integer), sa.Column("policy_version", sa.Text),
    sa.Column("reason", sa.Text), schema="thesis",
)
_RECORD_VERSIONS = sa.Table(
    "record_versions", _METADATA,
    sa.Column("thesis_id", sa.Text), sa.Column("version", sa.Integer),
    sa.Column("owner_user_id", sa.Text), sa.Column("cycle", sa.Integer),
    sa.Column("status", sa.Text), sa.Column("payload", sa.JSON),
    sa.Column("recorded_at", sa.DateTime(timezone=True)), schema="thesis",
)
_LIFECYCLE_CYCLES = sa.Table(
    "lifecycle_cycles", _METADATA,
    sa.Column("thesis_id", sa.Text), sa.Column("thesis_version", sa.Integer),
    sa.Column("owner_user_id", sa.Text), sa.Column("cycle", sa.Integer),
    sa.Column("status", sa.Text), sa.Column("reflection_pending", sa.Boolean),
    sa.Column("recorded_at", sa.DateTime(timezone=True)), schema="thesis",
)
_CONDITIONS = sa.Table(
    "invalidation_conditions", _METADATA,
    sa.Column("thesis_id", sa.Text), sa.Column("thesis_version", sa.Integer),
    sa.Column("owner_user_id", sa.Text), sa.Column("cycle", sa.Integer),
    sa.Column("condition_id", sa.Text), sa.Column("condition_version", sa.Integer),
    sa.Column("summary", sa.Text), sa.Column("active", sa.Boolean),
    sa.Column("published_at", sa.DateTime(timezone=True)), schema="thesis",
)
_EVIDENCE_LINKS = sa.Table(
    "evidence_links", _METADATA,
    sa.Column("thesis_id", sa.Text), sa.Column("thesis_version", sa.Integer),
    sa.Column("owner_user_id", sa.Text), sa.Column("evidence_id", sa.Text),
    sa.Column("evidence_version", sa.Integer), sa.Column("company_id", sa.Text),
    sa.Column("linked_at", sa.DateTime(timezone=True)), schema="thesis",
)
_OUTCOMES = sa.Table(
    "outcomes", _METADATA,
    sa.Column("thesis_id", sa.Text), sa.Column("outcome_id", sa.Text),
    sa.Column("version", sa.Integer), sa.Column("owner_user_id", sa.Text),
    sa.Column("cycle", sa.Integer), sa.Column("observed_at", sa.DateTime(timezone=True)),
    sa.Column("result", sa.Text), sa.Column("recorded_at", sa.DateTime(timezone=True)),
    schema="thesis",
)
_OUTCOME_EVIDENCE_LINKS = sa.Table(
    "outcome_evidence_links", _METADATA,
    sa.Column("outcome_id", sa.Text), sa.Column("outcome_version", sa.Integer),
    sa.Column("owner_user_id", sa.Text), sa.Column("evidence_id", sa.Text),
    sa.Column("evidence_version", sa.Integer), sa.Column("company_id", sa.Text), schema="thesis",
)
_REFLECTION_DRAFTS = sa.Table(
    "reflection_draft_revisions", _METADATA,
    sa.Column("thesis_id", sa.Text), sa.Column("owner_user_id", sa.Text),
    sa.Column("cycle", sa.Integer), sa.Column("revision", sa.Integer),
    sa.Column("original_assumption", sa.Text), sa.Column("judgment_errors", sa.Text),
    sa.Column("missing_evidence", sa.Text), sa.Column("improvement", sa.Text),
    sa.Column("saved_at", sa.DateTime(timezone=True)), schema="thesis",
)
_REFLECTIONS = sa.Table(
    "reflections", _METADATA,
    sa.Column("thesis_id", sa.Text), sa.Column("reflection_id", sa.Text),
    sa.Column("version", sa.Integer), sa.Column("owner_user_id", sa.Text),
    sa.Column("cycle", sa.Integer), sa.Column("original_assumption", sa.Text),
    sa.Column("judgment_errors", sa.Text), sa.Column("missing_evidence", sa.Text),
    sa.Column("improvement", sa.Text), sa.Column("recorded_at", sa.DateTime(timezone=True)),
    schema="thesis",
)
_AUDIT_EVENTS = sa.Table(
    "audit_events", _METADATA,
    sa.Column("event_id", sa.Uuid), sa.Column("thesis_id", sa.Text),
    sa.Column("thesis_version", sa.Integer), sa.Column("owner_user_id", sa.Text),
    sa.Column("action", sa.Text), sa.Column("reason", sa.Text),
    sa.Column("occurred_at", sa.DateTime(timezone=True)),
    sa.Column("before_version", sa.Integer), sa.Column("after_version", sa.Integer),
    sa.Column("correlation_id", sa.Text), sa.Column("causation_id", sa.Text),
    sa.Column("policy_version", sa.Text), sa.Column("build_version", sa.Text), schema="thesis",
)
_COMMAND_RECEIPTS = sa.Table(
    "command_receipts", _METADATA,
    sa.Column("actor_user_id", sa.Text), sa.Column("idempotency_key", sa.Text),
    sa.Column("command_digest", sa.Text), sa.Column("thesis_id", sa.Text),
    sa.Column("thesis_version", sa.Integer), schema="thesis",
)


class _SecurityContext(Protocol):
    user_id: str
    role: Any
    ownership_scope: str


class _Connection:
    """Small SQLAlchemy/driver bridge for transaction-scoped repository SQL."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, statement: Any, parameters: tuple[Any, ...] | None = None) -> Any:
        if isinstance(statement, str):
            execute = getattr(self._connection, "exec_driver_sql", None)
            if execute is not None:
                return execute(statement, parameters or ())
            return self._connection.execute(statement, parameters or ())
        return self._connection.execute(statement)


class PostgresThesisStore:
    """RLS-scoped current snapshots plus immutable Thesis history."""

    def __init__(
        self,
        database_url_provider: DatabaseUrlProvider,
        *,
        security_context_provider: Callable[[], _SecurityContext | None],
        transaction_connection: Any | None = None,
        build_version: str = "test-build",
    ) -> None:
        self._database_url_provider = database_url_provider
        self._security_context_provider = security_context_provider
        self._transaction_connection = transaction_connection
        self._build_version = build_version
        self._engine = create_database_engine(database_url_provider) if transaction_connection is None else None

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        context = self._security_context_provider()
        if context is None:
            raise PermissionError("missing_security_context")
        if self._transaction_connection is not None:
            yield _Connection(self._transaction_connection)
            return
        assert self._engine is not None
        with database_connection(self._engine) as raw_connection:
            connection = _Connection(raw_connection)
            connection.execute("SELECT set_config('app.user_id',%s,true)", (context.user_id,))
            connection.execute("SELECT set_config('app.role',%s,true)", (context.role.value,))
            connection.execute("SELECT set_config('app.request_id',%s,true)", (context.ownership_scope,))
            yield connection

    def for_transaction(self, connection: Any) -> PostgresThesisStore:
        """Return an immutable request-scoped binding to the caller-owned transaction."""
        return PostgresThesisStore(
            self._database_url_provider,
            security_context_provider=self._security_context_provider,
            transaction_connection=connection,
            build_version=self._build_version,
        )

    @staticmethod
    def _lock_key(value: str) -> int:
        return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)

    @staticmethod
    def _reference(value: dict[str, Any]) -> ThesisResearchReference:
        return ThesisResearchReference(
            value["record_type"], value["record_id"], int(value["version"]), value["company_id"],
            value.get("fact_id"),
        )

    @staticmethod
    def _valuation_draft(value: dict[str, Any]) -> ValuationDraft:
        def distribution(item: dict[str, Any] | None) -> ValuationDistribution | None:
            if item is None:
                return None
            return ValuationDistribution(
                median=Decimal(item["median"]), p75=Decimal(item["p75"]),
                coverage=ValuationCoverage(item["coverage"]), sample_count=int(item["sample_count"]),
                sorted_samples=tuple(Decimal(child) for child in item.get("sorted_samples", [])),
                p75_position=Decimal(item.get("p75_position", "0")),
                p75_lower_index=int(item.get("p75_lower_index", 0)),
                p75_upper_index=int(item.get("p75_upper_index", 0)),
                p75_interpolation_fraction=Decimal(item.get("p75_interpolation_fraction", "0")),
                policy_version=item["policy_version"],
            )
        def sample(item: dict[str, Any]) -> ValuationSample:
            return ValuationSample(
                item["sample_id"], item["company_id"], date.fromisoformat(item["observed_on"]),
                Decimal(item["multiple"]), Decimal(item["denominator"]),
                PostgresThesisStore._reference(item["source"]),
            )
        def benchmark(item: dict[str, Any] | None) -> ValuationBenchmarkSnapshot | None:
            if item is None:
                return None
            resolved = distribution(item["distribution"])
            assert resolved is not None
            return ValuationBenchmarkSnapshot(
                item["source"], resolved, tuple(sample(child) for child in item["valid_samples"]),
                tuple(item["exclusions"]), date.fromisoformat(item["data_start"]),
                date.fromisoformat(item["data_end"]), item["policy_version"],
            )
        selected_distribution = distribution(value.get("distribution"))
        validity = value["validity"]
        result = value.get("result")
        forecast_source = value.get("forecast_source")
        return ValuationDraft(
            int(value["version"]), ValuationMethod(value["method"]), value["benchmark_source"],
            value["benchmark_variant"], tuple(value["peer_company_ids"]),
            selected_distribution,
            ValuationValidity(
                date.fromisoformat(validity["target_date"]), datetime.fromisoformat(validity["expires_at"]),
                tuple(validity["expiry_causes"]), validity["policy_version"],
            ),
            None if result is None else ValuationReturn(
                Decimal(result["target_price"]), Decimal(result["purchase_outflow"]),
                Decimal(result["terminal_inflow"]), Decimal(result["annualized_return"]),
                result["tax_disclaimer"], result["policy_version"],
            ),
            None if value.get("forecast") is None else Decimal(value["forecast"]), Decimal(value["quantity"]), Decimal(value["buy_price"]),
            Decimal(value["cash_dividend"]), int(value["cost_profile_version"]),
            datetime.fromisoformat(value["saved_at"]),
            benchmark(value.get("company_history")), benchmark(value.get("peer_group")),
            None if value.get("benchmark_difference_median") is None else Decimal(value["benchmark_difference_median"]),
            None if value.get("benchmark_difference_p75") is None else Decimal(value["benchmark_difference_p75"]),
            tuple(value.get("benchmark_abstentions", [])), value.get("source_selection_reason", ""),
            None if forecast_source is None else PostgresThesisStore._reference(forecast_source),
            None if value.get("forecast_confirmed_at") is None else datetime.fromisoformat(value["forecast_confirmed_at"]),
            None if value.get("next_report_time") is None else datetime.fromisoformat(value["next_report_time"]),
            None if value.get("material_event_time") is None else datetime.fromisoformat(value["material_event_time"]),
            tuple(
                PeerValuationMember(
                    item["company_id"], item["inclusion_reason"], ValuationMethod(item["method"]),
                    bool(item["taiwan_listed"]), bool(item["owner_confirmed"]), sample(item["sample"]),
                ) for item in value.get("peer_members", [])
            ),
            value["policy_version"],
        )

    @staticmethod
    def _valuation_draft_payload(value: ValuationDraft) -> dict[str, Any]:
        def normalize(item: Any) -> Any:
            if isinstance(item, Decimal):
                return str(item)
            if isinstance(item, (date, datetime)):
                return item.isoformat()
            if isinstance(item, Enum):
                return item.value
            if isinstance(item, dict):
                return {key: normalize(child) for key, child in item.items()}
            if isinstance(item, (list, tuple)):
                return [normalize(child) for child in item]
            return item
        return normalize(asdict(value))

    @classmethod
    def decode_record(cls, value: dict[str, Any]) -> ThesisRecord:
        outcome_value = value.get("outcome")
        reflection_value = value.get("reflection")
        draft_value = value.get("reflection_draft")
        valuation_draft_value = value.get("valuation_draft")
        outcome = None if outcome_value is None else ThesisOutcome(
            outcome_value["outcome_id"],
            int(outcome_value["version"]),
            int(outcome_value["cycle"]),
            datetime.fromisoformat(outcome_value["observed_at"]),
            outcome_value["result"],
            tuple(cls._reference(item) for item in outcome_value["evidence_refs"]),
        )
        reflection = None if reflection_value is None else ThesisReflection(
            reflection_value["reflection_id"],
            int(reflection_value["version"]),
            int(reflection_value["cycle"]),
            reflection_value["original_assumption"],
            reflection_value["judgment_errors"],
            reflection_value["missing_evidence"],
            reflection_value["improvement"],
        )
        draft = None if draft_value is None else ReflectionDraftRevision(
            int(draft_value["revision"]),
            int(draft_value["cycle"]),
            draft_value.get("original_assumption", ""),
            draft_value.get("judgment_errors", ""),
            draft_value.get("missing_evidence", ""),
            draft_value.get("improvement", ""),
            datetime.fromisoformat(draft_value["saved_at"]),
        )
        valuation_draft = None if valuation_draft_value is None else cls._valuation_draft(valuation_draft_value)
        valuation_snapshots = tuple(
            ValuationSnapshot(
                item["valuation_id"], int(item["version"]), int(item["draft_version"]),
                cls._valuation_draft(item["draft"]), datetime.fromisoformat(item["published_at"]),
                item["reason"], item["policy_version"],
            ) for item in value.get("valuation_snapshots", [])
        )
        return ThesisRecord(
            thesis_id=value["thesis_id"],
            version=int(value["version"]),
            owner_user_id=value["owner_user_id"],
            company_id=value["company_id"],
            company_version=int(value["company_version"]),
            title=value["title"],
            narrative=value["narrative"],
            status=ThesisStatus(value["status"]),
            cycle=int(value["cycle"]),
            reflection_pending=bool(value["reflection_pending"]),
            created_at=datetime.fromisoformat(value["created_at"]),
            updated_at=datetime.fromisoformat(value["updated_at"]),
            conditions=tuple(
                InvalidationCondition(
                    item["condition_id"], int(item["version"]), item["summary"], bool(item["active"])
                )
                for item in value["conditions"]
            ),
            evidence_refs=tuple(cls._reference(item) for item in value["evidence_refs"]),
            outcome=outcome,
            reflection=reflection,
            reflection_draft=draft,
            valuation_draft=valuation_draft,
            valuation_snapshots=valuation_snapshots,
            policy_version=value["policy_version"],
        )

    @staticmethod
    def encode_record(record: ThesisRecord) -> dict[str, Any]:
        def reference(value: ThesisResearchReference) -> dict[str, Any]:
            return {
                "record_type": value.record_type,
                "record_id": value.record_id,
                "version": value.version,
                "company_id": value.company_id,
            }

        outcome = None if record.outcome is None else {
            "outcome_id": record.outcome.outcome_id,
            "version": record.outcome.version,
            "cycle": record.outcome.cycle,
            "observed_at": record.outcome.observed_at.isoformat(),
            "result": record.outcome.result,
            "evidence_refs": [reference(item) for item in record.outcome.evidence_refs],
        }
        reflection = None if record.reflection is None else {
            "reflection_id": record.reflection.reflection_id,
            "version": record.reflection.version,
            "cycle": record.reflection.cycle,
            "original_assumption": record.reflection.original_assumption,
            "judgment_errors": record.reflection.judgment_errors,
            "missing_evidence": record.reflection.missing_evidence,
            "improvement": record.reflection.improvement,
        }
        draft = None if record.reflection_draft is None else {
            "revision": record.reflection_draft.revision,
            "cycle": record.reflection_draft.cycle,
            "original_assumption": record.reflection_draft.original_assumption,
            "judgment_errors": record.reflection_draft.judgment_errors,
            "missing_evidence": record.reflection_draft.missing_evidence,
            "improvement": record.reflection_draft.improvement,
            "saved_at": record.reflection_draft.saved_at.isoformat(),
        }
        valuation_draft = None if record.valuation_draft is None else PostgresThesisStore._valuation_draft_payload(record.valuation_draft)
        valuation_snapshots = [{
            "valuation_id": item.valuation_id, "version": item.version,
            "draft_version": item.draft_version,
            "draft": PostgresThesisStore._valuation_draft_payload(item.draft),
            "published_at": item.published_at.isoformat(), "reason": item.reason,
            "policy_version": item.policy_version,
        } for item in record.valuation_snapshots]
        return {
            "thesis_id": record.thesis_id,
            "version": record.version,
            "owner_user_id": record.owner_user_id,
            "company_id": record.company_id,
            "company_version": record.company_version,
            "title": record.title,
            "narrative": record.narrative,
            "status": record.status.value,
            "cycle": record.cycle,
            "reflection_pending": record.reflection_pending,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "conditions": [
                {
                    "condition_id": item.condition_id,
                    "version": item.version,
                    "summary": item.summary,
                    "active": item.active,
                }
                for item in record.conditions
            ],
            "evidence_refs": [reference(item) for item in record.evidence_refs],
            "outcome": outcome,
            "reflection": reflection,
            "reflection_draft": draft,
            "valuation_draft": valuation_draft,
            "valuation_snapshots": valuation_snapshots,
            "policy_version": record.policy_version,
        }

    def _get(self, connection: Any, actor_id: str, thesis_id: str) -> ThesisRecord | None:
        row = connection.execute(sa.select(
            _THESES.c.thesis_id, _THESES.c.version, _THESES.c.owner_user_id,
            _THESES.c.company_id, _THESES.c.company_version, _THESES.c.title,
            _THESES.c.narrative, _THESES.c.status, _THESES.c.cycle,
            _THESES.c.reflection_pending, _THESES.c.created_at, _THESES.c.updated_at,
            _THESES.c.policy_version, _THESES.c.valuation_draft_version,
        ).where(
            _THESES.c.thesis_id == thesis_id,
            _THESES.c.owner_user_id == actor_id,
        )).fetchone()
        if row is None:
            return None
        payload: dict[str, Any] = {
            "thesis_id": row[0], "version": int(row[1]), "owner_user_id": row[2],
            "company_id": row[3], "company_version": int(row[4]), "title": row[5],
            "narrative": row[6], "status": row[7], "cycle": int(row[8]),
            "reflection_pending": bool(row[9]), "created_at": row[10].isoformat(),
            "updated_at": row[11].isoformat(), "policy_version": row[12],
            "valuation_draft": None, "valuation_snapshots": [],
        }
        if row[13] is not None:
            draft_row = connection.execute(sa.select(_VALUATION_DRAFTS.c.payload).where(
                _VALUATION_DRAFTS.c.thesis_id == thesis_id,
                _VALUATION_DRAFTS.c.draft_version == int(row[13]),
                _VALUATION_DRAFTS.c.owner_user_id == actor_id,
            )).fetchone()
            if draft_row is not None:
                payload["valuation_draft"] = draft_row[0]
        snapshot_rows = connection.execute(sa.select(
            _VALUATION_SNAPSHOTS.c.valuation_id, _VALUATION_SNAPSHOTS.c.version,
            _VALUATION_SNAPSHOTS.c.draft_version, _VALUATION_SNAPSHOTS.c.payload,
            _VALUATION_SNAPSHOTS.c.published_at, _VALUATION_SNAPSHOTS.c.reason,
            _VALUATION_SNAPSHOTS.c.policy_version,
        ).where(
            _VALUATION_SNAPSHOTS.c.thesis_id == thesis_id,
            _VALUATION_SNAPSHOTS.c.owner_user_id == actor_id,
        ).order_by(
            _VALUATION_SNAPSHOTS.c.version, _VALUATION_SNAPSHOTS.c.valuation_id,
        )).fetchall()
        payload["valuation_snapshots"] = [
            {
                "valuation_id": value[0], "version": int(value[1]),
                "draft_version": int(value[2]), "draft": value[3]["draft"],
                "published_at": value[4].isoformat(), "reason": value[5],
                "policy_version": value[6],
            }
            for value in snapshot_rows
        ]
        payload["conditions"] = [
            {"condition_id": value[0], "version": int(value[1]), "summary": value[2], "active": bool(value[3])}
            for value in connection.execute(sa.select(
                _CONDITIONS.c.condition_id, _CONDITIONS.c.condition_version,
                _CONDITIONS.c.summary, _CONDITIONS.c.active,
            ).where(
                _CONDITIONS.c.thesis_id == thesis_id,
                _CONDITIONS.c.thesis_version == row[1],
            ).order_by(_CONDITIONS.c.condition_id)).fetchall()
        ]
        payload["evidence_refs"] = [
            {"record_type": "evidence", "record_id": value[0], "version": int(value[1]), "company_id": value[2]}
            for value in connection.execute(sa.select(
                _EVIDENCE_LINKS.c.evidence_id, _EVIDENCE_LINKS.c.evidence_version,
                _EVIDENCE_LINKS.c.company_id,
            ).where(
                _EVIDENCE_LINKS.c.thesis_id == thesis_id,
                _EVIDENCE_LINKS.c.thesis_version == row[1],
            ).order_by(
                _EVIDENCE_LINKS.c.evidence_id, _EVIDENCE_LINKS.c.evidence_version,
            )).fetchall()
        ]
        outcome = connection.execute(sa.select(
            _OUTCOMES.c.outcome_id, _OUTCOMES.c.version, _OUTCOMES.c.cycle,
            _OUTCOMES.c.observed_at, _OUTCOMES.c.result,
        ).where(
            _OUTCOMES.c.thesis_id == thesis_id,
            _OUTCOMES.c.owner_user_id == actor_id,
            _OUTCOMES.c.cycle == row[8],
        ).order_by(_OUTCOMES.c.version.desc()).limit(1)).fetchone()
        if outcome is None:
            payload["outcome"] = None
        else:
            outcome_refs = connection.execute(sa.select(
                _OUTCOME_EVIDENCE_LINKS.c.evidence_id,
                _OUTCOME_EVIDENCE_LINKS.c.evidence_version,
                _OUTCOME_EVIDENCE_LINKS.c.company_id,
            ).where(
                _OUTCOME_EVIDENCE_LINKS.c.outcome_id == outcome[0],
                _OUTCOME_EVIDENCE_LINKS.c.outcome_version == outcome[1],
            ).order_by(
                _OUTCOME_EVIDENCE_LINKS.c.evidence_id,
                _OUTCOME_EVIDENCE_LINKS.c.evidence_version,
            )).fetchall()
            payload["outcome"] = {
                "outcome_id": outcome[0], "version": int(outcome[1]), "cycle": int(outcome[2]),
                "observed_at": outcome[3].isoformat(), "result": outcome[4],
                "evidence_refs": [
                    {"record_type": "evidence", "record_id": value[0], "version": int(value[1]), "company_id": value[2]}
                    for value in outcome_refs
                ],
            }
        reflection = connection.execute(sa.select(
            _REFLECTIONS.c.reflection_id, _REFLECTIONS.c.version, _REFLECTIONS.c.cycle,
            _REFLECTIONS.c.original_assumption, _REFLECTIONS.c.judgment_errors,
            _REFLECTIONS.c.missing_evidence, _REFLECTIONS.c.improvement,
        ).where(
            _REFLECTIONS.c.thesis_id == thesis_id,
            _REFLECTIONS.c.owner_user_id == actor_id,
            _REFLECTIONS.c.cycle == row[8],
        ).order_by(_REFLECTIONS.c.version.desc()).limit(1)).fetchone()
        payload["reflection"] = None if reflection is None else {
            "reflection_id": reflection[0], "version": int(reflection[1]), "cycle": int(reflection[2]),
            "original_assumption": reflection[3], "judgment_errors": reflection[4],
            "missing_evidence": reflection[5], "improvement": reflection[6],
        }
        draft = connection.execute(sa.select(
            _REFLECTION_DRAFTS.c.revision, _REFLECTION_DRAFTS.c.cycle,
            _REFLECTION_DRAFTS.c.original_assumption, _REFLECTION_DRAFTS.c.judgment_errors,
            _REFLECTION_DRAFTS.c.missing_evidence, _REFLECTION_DRAFTS.c.improvement,
            _REFLECTION_DRAFTS.c.saved_at,
        ).where(
            _REFLECTION_DRAFTS.c.thesis_id == thesis_id,
            _REFLECTION_DRAFTS.c.owner_user_id == actor_id,
            _REFLECTION_DRAFTS.c.cycle == row[8],
        ).order_by(_REFLECTION_DRAFTS.c.revision.desc()).limit(1)).fetchone()
        payload["reflection_draft"] = None if draft is None else {
            "revision": int(draft[0]), "cycle": int(draft[1]),
            "original_assumption": draft[2], "judgment_errors": draft[3],
            "missing_evidence": draft[4], "improvement": draft[5],
            "saved_at": draft[6].isoformat(),
        }
        return self.decode_record(payload)

    def get(self, actor_id: str, thesis_id: str) -> ThesisRecord | None:
        with self._connection() as connection:
            return self._get(connection, actor_id, thesis_id)

    def list_for_company(self, actor_id: str, company_id: str) -> list[ThesisRecord]:
        with self._connection() as connection:
            rows = connection.execute(sa.select(_THESES.c.thesis_id).where(
                _THESES.c.owner_user_id == actor_id,
                _THESES.c.company_id == company_id,
            ).order_by(_THESES.c.updated_at.desc(), _THESES.c.thesis_id)).fetchall()
            return [value for row in rows if (value := self._get(connection, actor_id, row[0])) is not None]

    def commit(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        command_digest: str,
        expected_version: int,
        record: ThesisRecord,
        action: str,
        reason: str,
    ) -> ThesisRecord:
        context = self._security_context_provider()
        if context is None or context.user_id != actor_id or record.owner_user_id != actor_id:
            raise PermissionError("resource_unavailable")
        payload = self.encode_record(record)
        with self._connection() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (self._lock_key(f"{actor_id}:{idempotency_key}"),),
            )
            receipt = connection.execute(sa.select(
                _COMMAND_RECEIPTS.c.command_digest, _COMMAND_RECEIPTS.c.thesis_id,
            ).where(
                _COMMAND_RECEIPTS.c.actor_user_id == actor_id,
                _COMMAND_RECEIPTS.c.idempotency_key == idempotency_key,
            )).fetchone()
            if receipt is not None:
                if receipt[0] != command_digest:
                    raise ValueError("idempotency_conflict")
                replay = self._get(connection, actor_id, receipt[1])
                if replay is None:
                    raise LookupError("resource_unavailable")
                return replay
            current = connection.execute(sa.select(_THESES.c.version).where(
                _THESES.c.thesis_id == record.thesis_id,
                _THESES.c.owner_user_id == actor_id,
            ).with_for_update()).fetchone()
            current_version = 0 if current is None else int(current[0])
            if current_version != expected_version:
                raise ValueError("version_conflict")
            if current is None:
                connection.execute(sa.insert(_THESES).values(
                    thesis_id=record.thesis_id, version=record.version, owner_user_id=actor_id,
                    company_id=record.company_id, company_version=record.company_version,
                    status=record.status.value, cycle=record.cycle, title=record.title,
                    narrative=record.narrative, reflection_pending=record.reflection_pending,
                    policy_version=record.policy_version, created_at=record.created_at,
                    updated_at=record.updated_at,
                    valuation_draft_version=(
                        None if record.valuation_draft is None else record.valuation_draft.version
                    ),
                ))
            else:
                connection.execute(sa.update(_THESES).where(
                    _THESES.c.thesis_id == record.thesis_id,
                    _THESES.c.owner_user_id == actor_id,
                ).values(
                    version=record.version, company_id=record.company_id,
                    company_version=record.company_version, status=record.status.value,
                    cycle=record.cycle, title=record.title, narrative=record.narrative,
                    reflection_pending=record.reflection_pending, policy_version=record.policy_version,
                    updated_at=record.updated_at,
                    valuation_draft_version=(
                        None if record.valuation_draft is None else record.valuation_draft.version
                    ),
                ))
            connection.execute(sa.insert(_RECORD_VERSIONS).values(
                thesis_id=record.thesis_id, version=record.version,
                owner_user_id=actor_id, cycle=record.cycle, status=record.status.value,
                payload=payload, recorded_at=record.updated_at,
            ))
            connection.execute(sa.insert(_LIFECYCLE_CYCLES).values(
                thesis_id=record.thesis_id, thesis_version=record.version,
                owner_user_id=actor_id, cycle=record.cycle, status=record.status.value,
                reflection_pending=record.reflection_pending, recorded_at=record.updated_at,
            ))
            for condition in record.conditions:
                connection.execute(sa.insert(_CONDITIONS).values(
                    thesis_id=record.thesis_id, thesis_version=record.version,
                    owner_user_id=actor_id, cycle=record.cycle,
                    condition_id=condition.condition_id, condition_version=condition.version,
                    summary=condition.summary, active=condition.active,
                    published_at=record.updated_at,
                ))
            for evidence in record.evidence_refs:
                connection.execute(sa.insert(_EVIDENCE_LINKS).values(
                    thesis_id=record.thesis_id, thesis_version=record.version,
                    owner_user_id=actor_id, evidence_id=evidence.record_id,
                    evidence_version=evidence.version, company_id=evidence.company_id,
                    linked_at=record.updated_at,
                ))
            if record.outcome is not None:
                connection.execute(pg_insert(_OUTCOMES).values(
                    thesis_id=record.thesis_id, outcome_id=record.outcome.outcome_id,
                    version=record.outcome.version, owner_user_id=actor_id,
                    cycle=record.outcome.cycle, observed_at=record.outcome.observed_at,
                    result=record.outcome.result, recorded_at=record.updated_at,
                ).on_conflict_do_nothing())
                for evidence in record.outcome.evidence_refs:
                    connection.execute(pg_insert(_OUTCOME_EVIDENCE_LINKS).values(
                        outcome_id=record.outcome.outcome_id,
                        outcome_version=record.outcome.version, owner_user_id=actor_id,
                        evidence_id=evidence.record_id, evidence_version=evidence.version,
                        company_id=evidence.company_id,
                    ).on_conflict_do_nothing())
            if record.reflection_draft is not None:
                connection.execute(pg_insert(_REFLECTION_DRAFTS).values(
                    thesis_id=record.thesis_id, owner_user_id=actor_id,
                    cycle=record.reflection_draft.cycle,
                    revision=record.reflection_draft.revision,
                    original_assumption=record.reflection_draft.original_assumption,
                    judgment_errors=record.reflection_draft.judgment_errors,
                    missing_evidence=record.reflection_draft.missing_evidence,
                    improvement=record.reflection_draft.improvement,
                    saved_at=record.reflection_draft.saved_at,
                ).on_conflict_do_nothing())
            if record.reflection is not None:
                connection.execute(pg_insert(_REFLECTIONS).values(
                    thesis_id=record.thesis_id,
                    reflection_id=record.reflection.reflection_id,
                    version=record.reflection.version, owner_user_id=actor_id,
                    cycle=record.reflection.cycle,
                    original_assumption=record.reflection.original_assumption,
                    judgment_errors=record.reflection.judgment_errors,
                    missing_evidence=record.reflection.missing_evidence,
                    improvement=record.reflection.improvement,
                    recorded_at=record.updated_at,
                ).on_conflict_do_nothing())
            if record.valuation_draft is not None:
                draft = record.valuation_draft
                connection.execute(pg_insert(_VALUATION_DRAFTS).values(
                    thesis_id=record.thesis_id, draft_version=draft.version, owner_user_id=actor_id,
                    payload=self._valuation_draft_payload(draft), saved_at=draft.saved_at,
                    method=draft.method.value, benchmark_source=draft.benchmark_source,
                    benchmark_variant=draft.benchmark_variant,
                    target_date=draft.validity.target_date, expires_at=draft.validity.expires_at,
                    cost_profile_version=draft.cost_profile_version, policy_version=draft.policy_version,
                ).on_conflict_do_nothing(
                    index_elements=[_VALUATION_DRAFTS.c.thesis_id, _VALUATION_DRAFTS.c.draft_version],
                ))
            for snapshot in record.valuation_snapshots:
                connection.execute(pg_insert(_VALUATION_SNAPSHOTS).values(
                    valuation_id=snapshot.valuation_id, version=snapshot.version,
                    thesis_id=record.thesis_id, owner_user_id=actor_id,
                    draft_version=snapshot.draft_version,
                    payload={"draft": self._valuation_draft_payload(snapshot.draft)},
                    published_at=snapshot.published_at, method=snapshot.draft.method.value,
                    benchmark_source=snapshot.draft.benchmark_source,
                    benchmark_variant=snapshot.draft.benchmark_variant,
                    target_date=snapshot.draft.validity.target_date,
                    expires_at=snapshot.draft.validity.expires_at,
                    cost_profile_version=snapshot.draft.cost_profile_version,
                    policy_version=snapshot.policy_version, reason=snapshot.reason,
                ).on_conflict_do_nothing(
                    index_elements=[_VALUATION_SNAPSHOTS.c.valuation_id, _VALUATION_SNAPSHOTS.c.version],
                ))
            connection.execute(sa.insert(_AUDIT_EVENTS).values(
                event_id=uuid.uuid4(), thesis_id=record.thesis_id,
                thesis_version=record.version, owner_user_id=actor_id,
                action=action, reason=reason, occurred_at=record.updated_at,
                before_version=expected_version, after_version=record.version,
                correlation_id=idempotency_key, causation_id=command_digest,
                policy_version=record.policy_version, build_version=self._build_version,
            ))
            connection.execute(sa.insert(_COMMAND_RECEIPTS).values(
                actor_user_id=actor_id, idempotency_key=idempotency_key,
                command_digest=command_digest, thesis_id=record.thesis_id,
                thesis_version=record.version,
            ))
            result = self._get(connection, actor_id, record.thesis_id)
            if result is None:
                raise LookupError("resource_unavailable")
            return result

    def delete_all_for_test(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """TRUNCATE thesis.command_receipts,thesis.audit_events,thesis.valuation_snapshots,
                thesis.valuation_drafts,thesis.reflections,
                thesis.reflection_draft_revisions,thesis.outcome_evidence_links,thesis.outcomes,
                thesis.evidence_links,thesis.invalidation_conditions,thesis.lifecycle_cycles,
                thesis.record_versions,thesis.theses"""
            )

    def count_versions(self, thesis_id: str) -> int:
        with self._connection() as connection:
            return int(connection.execute(
                sa.select(sa.func.count()).select_from(_RECORD_VERSIONS).where(
                    _RECORD_VERSIONS.c.thesis_id == thesis_id,
                )
            ).fetchone()[0])

    def count_audit_events(self, thesis_id: str) -> int:
        with self._connection() as connection:
            return int(connection.execute(
                sa.select(sa.func.count()).select_from(_AUDIT_EVENTS).where(
                    _AUDIT_EVENTS.c.thesis_id == thesis_id,
                )
            ).fetchone()[0])
