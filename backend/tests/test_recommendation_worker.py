from dataclasses import replace
from datetime import timedelta

import pytest

from thesis_trace.application.contracts import RecommendationFlow
from thesis_trace.modules.recommendation.contracts import RecommendationJob
from thesis_trace.modules.recommendation.service import RecommendationService
from test_recommendation_admission import versions
from test_recommendation_publication import NOW, evidence, inputs


class Store:
    def __init__(self):
        self.inputs = inputs()
        self.versions = versions()
        self.job = RecommendationJob(
            "job-1",
            "input-1",
            RecommendationService.admission_digest(self.inputs, self.versions),
            "owner-1",
            "thesis-1",
            1,
            "lease-1",
            NOW + timedelta(minutes=5),
            1,
            self.versions,
        )
        self.calls = []
        self.failures = []
        self.lose_lease = False

    def claim_job(self):
        self.calls.append("claim")
        return self.job

    def load_job_input(self, job):
        self.calls.append("load")
        return self.inputs

    def renew_job(self, job):
        self.calls.append("renew")
        if self.lose_lease:
            raise ValueError("lease_unavailable")
        return job

    def fail_job(self, job, **failure):
        if self.lose_lease:
            raise ValueError("lease_unavailable")
        self.failures.append(failure)

    def finish_job(self, _job):
        raise AssertionError("Only the atomic publication participant may finish")


class Transactions:
    def __init__(self, calls):
        self.calls = calls

    def publish(self, command):
        self.calls.append("publish")
        assert command.raw_candidate == evidence()[0]
        assert command.raw_critic == evidence()[1]


def run(store, provider=None, critic=None, transactions=None):
    candidate, checked = evidence()

    def analyze(request):
        store.calls.append("provider")
        assert dict(request.source_context)["thesis"] == "Frozen investment thesis"
        assert "portfolio" not in dict(request.source_context)
        assert request.candidate_text is None
        return candidate

    def criticize(request):
        store.calls.append("critic")
        assert request.candidate_text == candidate
        return checked

    return RecommendationFlow.process_one(
        store=store,
        provider=provider or analyze,
        critic=critic or criticize,
        transactions=transactions or Transactions(store.calls),
        versions=store.versions,
        clock=lambda: NOW,
    )


def test_worker_validates_and_renews_between_bounded_stages_without_split_finish():
    store = Store()
    assert run(store) is True
    assert store.calls == [
        "claim",
        "load",
        "provider",
        "renew",
        "critic",
        "renew",
        "publish",
    ]
    assert store.failures == []


def test_empty_queue_does_not_call_network():
    store = Store()
    store.job = None
    assert run(store) is False
    assert store.calls == ["claim"]


@pytest.mark.parametrize("change", ["digest", "versions", "owner"])
def test_job_binding_mismatch_fails_without_network(change):
    store = Store()
    if change == "digest":
        store.inputs = replace(
            store.inputs, source_selection_reason="Changed after admission"
        )
    elif change == "versions":
        store.job = replace(
            store.job, versions=(*store.versions, ("future", "changed"))
        )
    else:
        store.job = replace(store.job, actor_id="other-owner")
    assert run(store) is True
    assert "provider" not in store.calls
    assert "publish" not in store.calls
    assert len(store.failures) == 1


@pytest.mark.parametrize(
    "code,transient",
    [
        ("provider_transport_failure", True),
        ("provider_unavailable", False),
        ("invalid_output", False),
        ("private upstream body", False),
    ],
)
def test_only_classified_transport_failures_retry_and_errors_are_redacted(
    code, transient
):
    store = Store()

    def fail(_request):
        raise RuntimeError(code)

    assert run(store, provider=fail) is True
    assert len(store.failures) == 1
    assert store.failures[0]["transient"] is transient
    assert "private" not in str(store.failures)
    assert "publish" not in store.calls


def test_candidate_schema_failure_never_calls_critic_or_publishes():
    store = Store()
    run(store, provider=lambda _request: '{"schema_version":"anomaly-candidate-v1"}')
    assert "critic" not in store.calls
    assert store.failures == [{"error_code": "invalid_candidate", "transient": False}]


def test_critic_rejection_never_publishes():
    store = Store()
    run(store, critic=lambda _request: evidence()[1].replace('"PASS"', '"FAIL"'))
    assert "publish" not in store.calls
    assert store.failures == [{"error_code": "critic_rejected", "transient": False}]


def test_lost_lease_stops_without_overwriting_new_worker_result():
    store = Store()
    store.lose_lease = True
    run(store)
    assert "critic" not in store.calls
    assert "publish" not in store.calls
    assert store.failures == []


def test_database_outage_is_not_labeled_as_content_failure():
    store = Store()

    class Unavailable:
        def publish(self, _command):
            raise OSError("database unavailable")

    with pytest.raises(OSError):
        run(store, transactions=Unavailable())
    assert store.failures == []
