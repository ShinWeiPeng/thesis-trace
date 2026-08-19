from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from thesis_trace.modules.research.evidence_intake.contracts import (
    CollectionRequest,
    EvidenceAccepted,
    EvidenceAuditFact,
    EvidenceRecord,
    EvidenceStatus,
)
from thesis_trace.platform.postgres import PostgresEvidenceStore, PostgresUnavailable, bootstrap_schema, verify_schema_compatibility
from thesis_trace.modules.research.evidence_collection.contracts import CollectedSourceSnapshot


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="set THESIS_TRACE_TEST_DATABASE_URL for PostgreSQL integration evidence",
)


@pytest.fixture()
def store():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    result = PostgresEvidenceStore(lambda: url)
    result.delete_all_for_test()
    result.create_company("2330", "台積電")
    return result


def test_admission_atomically_persists_record_audit_and_durable_job(store: PostgresEvidenceStore) -> None:
    evidence_id = str(uuid.uuid4())
    accepted = EvidenceAccepted(evidence_id, 1)
    store.commit_admission(
        idempotency_key="request-1",
        record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/a", EvidenceStatus.RECEIVED),
        audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
        job=CollectionRequest(evidence_id, 1, "https://example.com/a", f"collect:{evidence_id}:1"),
        accepted=accepted,
    )

    assert store.find_accepted("request-1") == accepted
    assert store.get_record(evidence_id).status is EvidenceStatus.RECEIVED
    assert store.count_audit_events(evidence_id) == 1
    assert store.count_collection_jobs(evidence_id) == 1


def test_schema_migration_is_versioned_and_reapplying_is_idempotent(store: PostgresEvidenceStore) -> None:
    bootstrap_schema(lambda: os.environ["THESIS_TRACE_TEST_DATABASE_URL"])
    verify_schema_compatibility(lambda: os.environ["THESIS_TRACE_TEST_DATABASE_URL"])
    assert store.applied_migrations() == [
        (1, "wave0_company_evidence"),
        (2, "access_identity_session_confirmation"),
        (3, "access_rls"),
        (4, "recovery_session_policy_binding"),
    ]


def test_evidence_admission_requires_a_persisted_company_version(store: PostgresEvidenceStore) -> None:
    assert store.get_company("2330").version == 1
    assert store.get_company("missing") is None


def test_job_claim_is_leased_and_stale_token_cannot_ack(store: PostgresEvidenceStore) -> None:
    evidence_id = str(uuid.uuid4())
    accepted = EvidenceAccepted(evidence_id, 1)
    store.commit_admission(
        idempotency_key="request-2",
        record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/b", EvidenceStatus.RECEIVED),
        audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
        job=CollectionRequest(evidence_id, 1, "https://example.com/b", f"collect:{evidence_id}:1"),
        accepted=accepted,
    )

    lease = store.claim_collection_job()
    assert lease is not None
    assert store.claim_collection_job() is None
    assert store.fail_collection(lease, "stale-token", "timeout", retryable=True) is False
    assert store.fail_collection(lease, lease.lease_token, "timeout", retryable=True) is True
    assert store.get_record(evidence_id).status is EvidenceStatus.RETRYING


def test_injected_admission_failure_rolls_back_record_audit_and_job(store: PostgresEvidenceStore) -> None:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    failing = PostgresEvidenceStore(lambda: url, admission_fault_hook=lambda: (_ for _ in ()).throw(RuntimeError("fault")))
    evidence_id = str(uuid.uuid4())
    with pytest.raises(PostgresUnavailable, match="postgres_unavailable"):
        failing.commit_admission(
            idempotency_key="rollback", record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/r", EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, "https://example.com/r", "collect:rollback"), accepted=EvidenceAccepted(evidence_id, 1),
        )
    assert store.get_record(evidence_id) is None
    assert store.count_audit_events(evidence_id) == 0
    assert store.count_collection_jobs(evidence_id) == 0


def test_expired_lease_is_reclaimed_and_retry_exhaustion_dead_letters(store: PostgresEvidenceStore) -> None:
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    reclaiming = PostgresEvidenceStore(lambda: url, lease_seconds=0, max_attempts=2)
    evidence_id = str(uuid.uuid4())
    reclaiming.commit_admission(
        idempotency_key="reclaim", record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/x", EvidenceStatus.RECEIVED),
        audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
        job=CollectionRequest(evidence_id, 1, "https://example.com/x", "collect:reclaim"), accepted=EvidenceAccepted(evidence_id, 1),
    )
    first = reclaiming.claim_collection_job()
    second = reclaiming.claim_collection_job()
    assert second.job_id == first.job_id and second.lease_token != first.lease_token
    assert reclaiming.fail_collection(second, second.lease_token, "timeout", retryable=True)
    assert reclaiming.get_record(evidence_id).status is EvidenceStatus.DEAD_LETTER


def test_full_provenance_and_url_or_content_dedup(store: PostgresEvidenceStore) -> None:
    for index, submitted_url in enumerate(("https://example.com/shared", "https://mirror.example/shared"), start=1):
        evidence_id = f"dedup-{index}"
        store.commit_admission(
            idempotency_key=evidence_id, record=EvidenceRecord(evidence_id, 1, "2330", 1, submitted_url, EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, submitted_url, f"collect:{evidence_id}"), accepted=EvidenceAccepted(evidence_id, 1),
        )
        lease = store.claim_collection_job()
        snapshot = CollectedSourceSnapshot(
            canonical_url="https://example.com/canonical", publisher="MOPS", content_hash="same-hash",
            retrieved_at="2026-08-18T12:00:00Z", published_at="2026-08-18T10:00:00Z",
            observed_at="2026-08-18T11:00:00Z", excerpt="material fact", source_category="A", lineage=submitted_url,
        )
        assert store.complete_collection(evidence_id, snapshot, lease.lease_token)
    assert store.count_source_snapshots() == 1
    assert store.count_source_observations() == 2
    provenance = store.get_source_provenance("dedup-1")
    assert provenance[0:3] == ("https://example.com/canonical", "MOPS", "same-hash")
    assert provenance[6:] == ("material fact", "A", "https://example.com/shared")


def test_concurrent_idempotent_admission_has_one_audit_and_job(store: PostgresEvidenceStore) -> None:
    def submit(index: int) -> None:
        evidence_id = f"concurrent-{index}"
        store.commit_admission(
            idempotency_key="one-request", record=EvidenceRecord(evidence_id, 1, "2330", 1, "https://example.com/c", EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, "https://example.com/c", f"collect:{evidence_id}"), accepted=EvidenceAccepted(evidence_id, 1),
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(submit, (1, 2)))
    accepted = store.find_accepted("one-request")
    assert sum(store.count_audit_events(f"concurrent-{index}") for index in (1, 2)) == 1
    assert sum(store.count_collection_jobs(f"concurrent-{index}") for index in (1, 2)) == 1


def test_concurrent_content_completion_creates_one_source_of_record(store: PostgresEvidenceStore) -> None:
    leases = []
    for index in (1, 2):
        evidence_id = f"content-{index}"
        store.commit_admission(
            idempotency_key=evidence_id, record=EvidenceRecord(evidence_id, 1, "2330", 1, f"https://mirror{index}.example/a", EvidenceStatus.RECEIVED),
            audit=EvidenceAuditFact("owner-1", "evidence.received", evidence_id, 1),
            job=CollectionRequest(evidence_id, 1, f"https://mirror{index}.example/a", f"collect:{evidence_id}"), accepted=EvidenceAccepted(evidence_id, 1),
        )
        leases.append(store.claim_collection_job())
    snapshot = CollectedSourceSnapshot(
        canonical_url="https://canonical.example/a", publisher="MOPS", content_hash="concurrent-hash",
        retrieved_at="2026-08-18T12:00:00Z", source_category="A",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda lease: store.complete_collection(lease.evidence_id, snapshot, lease.lease_token), leases))
    assert results == [True, True]
    assert store.count_source_snapshots() == 1
    assert store.count_source_observations() == 2
