from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from thesis_trace.adapters.postgres_thesis.adapter import PostgresThesisStore
from thesis_trace.modules.thesis.contracts import (
    InvalidationCondition,
    ReflectionDraftRevision,
    ThesisOutcome,
    ThesisRecord,
    ThesisReflection,
    ThesisResearchReference,
    ThesisStatus,
)


ROOT = Path(__file__).resolve().parents[1]


def test_thesis_general_persistence_uses_declared_sqlalchemy_core_tables() -> None:
    source = (ROOT / "src/thesis_trace/adapters/postgres_thesis/adapter.py").read_text()

    assert '"""SELECT' not in source
    assert '"""INSERT' not in source


def test_thesis_record_json_round_trip_preserves_learning_state() -> None:
    now = datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc)
    evidence = ThesisResearchReference("evidence", "evidence-1", 3, "company-1")
    record = ThesisRecord(
        "thesis-1",
        8,
        "owner-1",
        "company-1",
        2,
        "Durable demand",
        "Demand supports durable cash flow.",
        ThesisStatus.INVALIDATED,
        2,
        True,
        now,
        now,
        (InvalidationCondition("condition-1", 2, "Demand declines", True),),
        (evidence,),
        ThesisOutcome("outcome-1", 1, 2, now, "Invalidated", (evidence,)),
        ThesisReflection("reflection-1", 1, 2, "A", "B", "C", "D"),
        ReflectionDraftRevision(3, 2, "Original", "Errors", "Missing", "Draft", now),
    )

    assert PostgresThesisStore.decode_record(PostgresThesisStore.encode_record(record)) == record
