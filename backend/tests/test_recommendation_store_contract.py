"""Demand-side immutable-record contract shared by memory and PostgreSQL.

Transaction, queue and grant tests remain separately required evidence.
"""

import os
from dataclasses import replace

import pytest

from test_recommendation_publication import plan


class MemoryRecords:
    def __init__(self, owner):
        self.owner = owner
        self.records = {}

    def append_record(self, record):
        if record.inputs.actor.actor_id != self.owner:
            raise PermissionError("resource_unavailable")
        key = (record.recommendation_id, record.version)
        if key in self.records and self.records[key] != record:
            raise ValueError("version_conflict")
        self.records[key] = record
        return record

    def get_record(self, actor, record_id, version):
        return self.records.get((record_id, version)) if actor == self.owner else None


@pytest.fixture(params=["memory", "postgres"])
def record_seam(request):
    if request.param == "postgres":
        if not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"):
            pytest.skip("isolated PostgreSQL required")
        from test_recommendation_store_postgres import fixture

        _, _, store, record = fixture()
        return store, record
    record = plan()
    return MemoryRecords(record.inputs.actor.actor_id), record


def test_exact_roundtrip_and_retry_preserve_immutable_evidence(record_seam):
    store, record = record_seam
    assert store.append_record(record) == record
    assert store.append_record(record) == record
    assert (
        store.get_record(
            record.inputs.actor.actor_id, record.recommendation_id, record.version
        )
        == record
    )


def test_changed_content_cannot_overwrite_a_published_version(record_seam):
    store, record = record_seam
    store.append_record(record)
    with pytest.raises(ValueError, match="version_conflict"):
        store.append_record(replace(record, policy_version="changed-policy"))
    assert (
        store.get_record(
            record.inputs.actor.actor_id, record.recommendation_id, record.version
        )
        == record
    )


def test_foreign_owner_cannot_read_or_append(record_seam):
    store, record = record_seam
    store.append_record(record)
    assert (
        store.get_record("foreign-owner", record.recommendation_id, record.version)
        is None
    )
    with pytest.raises(PermissionError, match="resource_unavailable"):
        store.append_record(
            replace(
                record,
                inputs=replace(
                    record.inputs,
                    actor=replace(record.inputs.actor, actor_id="foreign-owner"),
                ),
            )
        )
