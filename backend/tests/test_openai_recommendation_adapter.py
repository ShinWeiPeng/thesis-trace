from __future__ import annotations

import json

import pytest

from thesis_trace.adapters.openai_recommendation.adapter import OpenAIRecommendationAdapter
from thesis_trace.application.ai_ports import (
    AnalysisSource,
    RecommendationCriticRequest,
    RecommendationProviderRequest,
)


SOURCE = AnalysisSource(
    source_snapshot_id="snapshot-a",
    publisher_identity="TWSE",
    source_tier_facts=(True, True, False, False, False),
    underlying_evidence_id=None,
    canonical_url="https://example.com/disclosure",
    excerpt="Company filed a formal material disclosure.",
    retrieved_at="2026-08-21T09:00:00Z",
    published_at="2026-08-21T08:00:00Z",
    observed_at=None,
)


class RecordingTransport:
    def __init__(self, output: str | Exception) -> None:
        self.output = output
        self.calls: list[tuple[str, dict[str, str], dict[str, object], float]] = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        if isinstance(self.output, Exception):
            raise self.output
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": self.output}],
                }
            ],
        }


def test_provider_uses_responses_structured_output_without_storing_or_leaking_key() -> None:
    output = json.dumps({"schema_version": "anomaly-candidate-v1"})
    transport = RecordingTransport(output)
    adapter = OpenAIRecommendationAdapter(
        api_key_provider=lambda: "secret-key",
        model="gpt-test",
        transport=transport,
        timeout_seconds=7,
    )
    request = RecommendationProviderRequest(
        "assessment-1", "evidence-1", 3, (SOURCE,), "anomaly-candidate-v1", "prompt-v1",
        "gpt-test",
    )

    assert adapter.analyze(request) == output

    url, headers, payload, timeout = transport.calls[0]
    assert url == "https://api.openai.com/v1/responses"
    assert headers["Authorization"] == "Bearer secret-key"
    assert timeout == 7
    assert payload["model"] == "gpt-test"
    assert payload["store"] is False
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"]["additionalProperties"] is False
    assert "secret-key" not in json.dumps(payload)
    assert "Company filed" in payload["input"]


def test_critic_uses_a_distinct_exact_schema_and_candidate_input() -> None:
    output = json.dumps({"schema_version": "recommendation-critic-v1", "verdict": "FAIL"})
    transport = RecordingTransport(output)
    adapter = OpenAIRecommendationAdapter(
        api_key_provider=lambda: "secret-key", model="gpt-test", transport=transport
    )

    assert adapter.criticize(
        RecommendationCriticRequest(
            "assessment-1", (SOURCE,), '{"candidate":true}', "recommendation-critic-v1",
            "critic-prompt-v1", "gpt-test",
        )
    ) == output

    payload = transport.calls[0][2]
    assert payload["text"]["format"]["name"] == "recommendation_critic"
    assert set(payload["text"]["format"]["schema"]["required"]) == {
        "schema_version", "verdict", "source_available", "citation_direct_support",
        "subject_matches", "time_reasonable", "invalidation_matches", "b_independence",
        "no_newer_a_refutation",
    }
    assert json.loads(payload["input"])["candidate_json"] == '{"candidate":true}'


def test_transport_and_incomplete_output_fail_with_stable_redacted_errors() -> None:
    secret = "never-echo-this-key"
    transport = RecordingTransport(RuntimeError(f"upstream rejected {secret}"))
    adapter = OpenAIRecommendationAdapter(
        api_key_provider=lambda: secret, model="gpt-test", transport=transport
    )
    request = RecommendationProviderRequest(
        "assessment-1", "evidence-1", 3, (SOURCE,), "anomaly-candidate-v1", "prompt-v1",
        "gpt-test",
    )
    with pytest.raises(RuntimeError, match="provider_unavailable") as captured:
        adapter.analyze(request)
    assert secret not in str(captured.value)

    adapter = OpenAIRecommendationAdapter(
        api_key_provider=lambda: secret,
        model="gpt-test",
        transport=lambda *_args: {"status": "incomplete", "output": []},
    )
    with pytest.raises(RuntimeError, match="invalid_output"):
        adapter.analyze(request)


def test_adapter_rejects_a_job_bound_to_different_model_versions() -> None:
    adapter = OpenAIRecommendationAdapter(
        api_key_provider=lambda: "secret-key", model="gpt-test",
        critic_model="gpt-critic-test", transport=RecordingTransport("{}"),
    )
    provider_request = RecommendationProviderRequest(
        "assessment-1", "evidence-1", 3, (SOURCE,), "anomaly-candidate-v1", "prompt-v1",
        "different-provider-model",
    )
    with pytest.raises(RuntimeError, match="provider_version_mismatch"):
        adapter.analyze(provider_request)

    critic_request = RecommendationCriticRequest(
        "assessment-1", (SOURCE,), "{}", "recommendation-critic-v1", "critic-prompt-v1",
        "different-critic-model",
    )
    with pytest.raises(RuntimeError, match="provider_version_mismatch"):
        adapter.criticize(critic_request)
