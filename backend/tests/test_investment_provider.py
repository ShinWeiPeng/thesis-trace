import hashlib
import json
import threading
import time
from dataclasses import replace

import pytest

from thesis_trace.adapters.openai_recommendation.adapter import (
    OpenAIRecommendationAdapter,
)
from thesis_trace.application.contracts import InvestmentAnalysisRequest
from test_openai_recommendation_adapter import RecordingTransport
from test_recommendation_publication import evidence


def request(critic=False):
    candidate, _ = evidence()
    return InvestmentAnalysisRequest(
        "input-1",
        (
            ("thesis", "Frozen hypothesis"),
            ("conditions", "Predeclared"),
            ("valuation", "Frozen PE facts"),
            ("sources", '[{"snapshot_id":"snapshot-1"}]'),
        ),
        candidate if critic else None,
        hashlib.sha256(candidate.encode()).hexdigest() if critic else None,
        "investment-critic-v1" if critic else "investment-candidate-v1",
        "investment-critic-prompt-v1" if critic else "investment-candidate-prompt-v1",
        "critic-test" if critic else "candidate-test",
    )


def adapter(transport, **kwargs):
    return OpenAIRecommendationAdapter(
        api_key_provider=lambda: "test-only-key",
        model="candidate-test",
        critic_model="critic-test",
        transport=transport,
        **kwargs,
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.openai.com/v1/responses",
        "https://user:pass@example.test/v1",
        "https://example.test/v1#fragment",
    ],
)
def test_rejects_unsafe_endpoint_before_transport(endpoint):
    with pytest.raises(ValueError, match="invalid_provider_configuration"):
        adapter(RecordingTransport("{}"), endpoint=endpoint)


def test_https_transport_never_follows_redirect(monkeypatch):
    from unittest.mock import Mock
    from urllib.error import HTTPError
    from thesis_trace.adapters.openai_recommendation import adapter as module

    connection = Mock()
    connection.getresponse.return_value.status = 307
    connection.getresponse.return_value.reason = "Redirect"
    factory = Mock(return_value=connection)
    monkeypatch.setattr(module, "HTTPSConnection", factory, raising=False)
    with pytest.raises(HTTPError):
        module._https_transport(
            "https://example.test/v1/responses",
            {"Authorization": "Bearer test-only"},
            {},
            1,
        )
    factory.assert_called_once_with("example.test", port=443, timeout=1)
    connection.request.assert_called_once()
    connection.close.assert_called_once()


def test_distinct_investment_schemas_and_exact_candidate_are_sent():
    candidate, critic = evidence()
    transport = RecordingTransport(candidate)
    provider = adapter(transport)
    assert provider.analyze_investment(request()) == candidate
    payload = transport.calls[0][2]
    schema = payload["text"]["format"]
    assert schema["name"] == "investment_candidate"
    assert schema["strict"] is True
    assert set(schema["schema"]["required"]) == {
        "schema_version",
        "direction",
        "raw_dca_ceiling",
        "claims",
    }
    assert payload["store"] is False
    assert "tools" not in payload
    assert "test-only-key" not in json.dumps(payload)
    transport.output = critic
    assert provider.criticize_investment(request(True)) == critic
    payload = transport.calls[-1][2]
    assert payload["text"]["format"]["name"] == "investment_critic"
    assert set(payload["text"]["format"]["schema"]["required"]) == {
        "schema_version",
        "verdict",
        "candidate_digest",
        "checks",
    }
    sent = json.loads(payload["input"])
    assert sent["candidate_json"] == candidate
    assert sent["candidate_digest"] == hashlib.sha256(candidate.encode()).hexdigest()


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "anomaly-candidate-v1"},
        {"model_version": "changed"},
        {"prompt_version": "changed"},
        {"candidate_text": "{}"},
        {"source_context": (("sources", "[]"), ("sources", "duplicate"))},
    ],
)
def test_invalid_pinned_request_rejects_before_transport(change):
    transport = RecordingTransport("{}")
    with pytest.raises(RuntimeError):
        adapter(transport).analyze_investment(replace(request(), **change))
    assert transport.calls == []


def test_critic_requires_the_original_digest_before_network():
    transport = RecordingTransport("{}")
    with pytest.raises(RuntimeError, match="invalid_critic"):
        adapter(transport).criticize_investment(
            replace(request(True), candidate_digest="0" * 64)
        )
    assert transport.calls == []


def test_limits_encoded_request_and_independent_response_without_truncation():
    transport = RecordingTransport("{}")
    huge = replace(
        request(),
        source_context=(*request().source_context, ("oversize", "文" * 90000)),
    )
    with pytest.raises(RuntimeError, match="input_too_large"):
        adapter(transport).analyze_investment(huge)
    assert transport.calls == []
    for critic in (False, True):
        provider = adapter(RecordingTransport("x" * 65537))
        with pytest.raises(RuntimeError, match="invalid_output"):
            (provider.criticize_investment if critic else provider.analyze_investment)(
                request(critic)
            )
    assert (
        adapter(RecordingTransport("x" * 65536)).analyze_investment(request())
        == "x" * 65536
    )


def test_call_deadline_and_single_flight_discard_late_result():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def transport(*_args):
        calls.append(1)
        started.set()
        try:
            release.wait(2)
            return RecordingTransport("late-output")(*_args)
        finally:
            finished.set()

    provider = adapter(transport, timeout_seconds=0.03)
    before = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="provider_transport_failure"):
            provider.analyze_investment(request())
        assert started.is_set()
        assert time.monotonic() - before < 0.5
        with pytest.raises(RuntimeError, match="provider_transport_failure"):
            provider.analyze_investment(request())
        assert len(calls) == 1
    finally:
        release.set()
        assert finished.wait(1)


def test_slow_anomaly_call_uses_shared_deadline_and_gate():
    from thesis_trace.application.ai_ports import RecommendationProviderRequest

    release, finished = threading.Event(), threading.Event()
    calls = []

    def transport(*args):
        calls.append(1)
        try:
            release.wait(1)
            return RecordingTransport("{}")(*args)
        finally:
            finished.set()

    provider = adapter(transport, timeout_seconds=0.03)
    anomaly = RecommendationProviderRequest(
        "assessment",
        "evidence",
        1,
        (),
        "anomaly-candidate-v1",
        "anomaly-prompt-v1",
        request().model_version,
    )
    before = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="provider_unavailable"):
            provider.analyze(anomaly)
        assert time.monotonic() - before < 0.5
        with pytest.raises(RuntimeError, match="provider_transport_failure"):
            provider.analyze_investment(request())
        assert len(calls) == 1
    finally:
        release.set()
        assert finished.wait(1)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 31, 0, -1])
def test_investment_timeout_must_be_finite_and_at_most_thirty_seconds(timeout):
    with pytest.raises(ValueError, match="invalid_provider_configuration"):
        adapter(RecordingTransport("{}"), timeout_seconds=timeout)


@pytest.mark.parametrize(
    "response",
    [
        {"status": "incomplete", "output": []},
        {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}
            ],
        },
        {"status": "completed", "output": []},
    ],
)
def test_investment_refusal_or_incomplete_is_not_candidate_evidence(response):
    with pytest.raises(RuntimeError, match="invalid_output"):
        adapter(lambda *_args: response).analyze_investment(request())
