from __future__ import annotations

from thesis_trace.application.contracts import SubmitEvidenceRequest
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research.evidence_intake.contracts import EvidenceStatus
from thesis_trace.modules.research.evidence_collection.contracts import FetchedSource
from thesis_trace.modules.research.evidence_collection.service import EvidenceCollector
from thesis_trace.platform.in_memory import InMemoryEvidenceStore


def owner() -> AuthenticatedActor:
    return AuthenticatedActor(actor_id="owner-1", role=Role.OWNER, identity_version=1)


def store_with_company() -> InMemoryEvidenceStore:
    store = InMemoryEvidenceStore()
    store.create_company("2330", "台積電")
    return store


def test_owner_submits_evidence_and_can_query_received_record() -> None:
    store = store_with_company()
    flow = EvidenceIntakeFlow(store=store, id_generator=iter(["evidence-1"]).__next__)

    accepted = flow.submit(
        SubmitEvidenceRequest(
            actor=owner(),
            company_id="2330",
            company_version=1,
            url="https://example.com/disclosure/1",
            idempotency_key="request-1",
        )
    )

    assert accepted.evidence_id == "evidence-1"
    assert accepted.version == 1
    assert flow.get_status(owner(), accepted.evidence_id).status is EvidenceStatus.RECEIVED


def test_admission_atomically_records_audit_and_durable_collection_job() -> None:
    store = store_with_company()
    flow = EvidenceIntakeFlow(store=store, id_generator=iter(["evidence-1"]).__next__)

    flow.submit(
        SubmitEvidenceRequest(
            actor=owner(),
            company_id="2330",
            company_version=1,
            url="https://example.com/disclosure/1",
            idempotency_key="request-1",
        )
    )

    assert [(event.action, event.subject_id) for event in store.audit_events] == [
        ("evidence.received", "evidence-1")
    ]
    assert [(job.evidence_id, job.evidence_version) for job in store.collection_jobs] == [
        ("evidence-1", 1)
    ]


def test_replayed_idempotency_key_returns_same_record_without_duplicate_side_effects() -> None:
    store = store_with_company()
    flow = EvidenceIntakeFlow(store=store, id_generator=iter(["evidence-1"]).__next__)
    request = SubmitEvidenceRequest(
        actor=owner(),
        company_id="2330",
        company_version=1,
        url="https://example.com/disclosure/1",
        idempotency_key="request-1",
    )

    first = flow.submit(request)
    replay = flow.submit(request)

    assert replay == first
    assert len(store.audit_events) == 1
    assert len(store.collection_jobs) == 1


def test_non_owner_is_rejected_without_state_or_side_effects() -> None:
    store = store_with_company()
    flow = EvidenceIntakeFlow(store=store, id_generator=iter(["never-used"]).__next__)
    learner = AuthenticatedActor(actor_id="learner-1", role=Role.LEARNER, identity_version=1)

    result = flow.submit(
        SubmitEvidenceRequest(
            actor=learner,
            company_id="2330",
            company_version=1,
            url="https://example.com/disclosure/1",
            idempotency_key="request-1",
        )
    )

    assert result.rejection_code == "forbidden"
    assert store.records == {}
    assert store.audit_events == []
    assert store.collection_jobs == []


def test_invalid_url_is_rejected_before_acceptance() -> None:
    store = store_with_company()
    flow = EvidenceIntakeFlow(store=store, id_generator=iter(["never-used"]).__next__)

    result = flow.submit(
        SubmitEvidenceRequest(
            actor=owner(),
            company_id="2330",
            company_version=1,
            url="file:///etc/passwd",
            idempotency_key="request-1",
        )
    )

    assert result.rejection_code == "invalid_url"
    assert store.records == {}


def test_collector_processes_durable_job_and_commits_server_owned_provenance() -> None:
    store = store_with_company()
    flow = EvidenceIntakeFlow(store=store, id_generator=iter(["evidence-1"]).__next__)
    flow.submit(
        SubmitEvidenceRequest(
            actor=owner(),
            company_id="2330",
            company_version=1,
            url="https://example.com/disclosure/1",
            idempotency_key="request-1",
        )
    )

    class FakeSourceFetcher:
        def fetch(self, url: str) -> FetchedSource:
            assert url == "https://example.com/disclosure/1"
            return FetchedSource(
                canonical_url=url,
                publisher="Example Exchange",
                content=b"official disclosure",
                retrieved_at="2026-08-18T12:00:00Z",
            )

    EvidenceCollector(store=store, source_fetcher=FakeSourceFetcher()).run_once()

    snapshot = flow.get_status(owner(), "evidence-1")
    assert snapshot.status is EvidenceStatus.SUCCEEDED
    assert snapshot.version == 3
    assert store.source_snapshots["evidence-1"].content_hash == (
        "250e4986203ad771abcd8c96ba5a62646d7011c2259c400cb15e574024c10b8c"
    )
