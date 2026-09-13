"""Demand-owned worker seam, shared by a Fake provider and the real HTTP adapter.

The HTTP transport is injected: this does not certify live provider quality.
"""

from urllib.error import URLError

import pytest

from thesis_trace.adapters.openai_recommendation.adapter import (
    OpenAIRecommendationAdapter,
)
from test_openai_recommendation_adapter import RecordingTransport
from test_recommendation_publication import evidence
from test_recommendation_worker import Store, run


@pytest.fixture(params=["fake", "openai-adapter"])
def provider_seam(request):
    def bind(candidate, critic, unavailable=False):
        if request.param == "fake":

            def analyze(_):
                if unavailable:
                    raise RuntimeError("provider_transport_failure")
                return candidate

            return analyze, lambda _: critic

        provider = OpenAIRecommendationAdapter(
            api_key_provider=lambda: "test-only-key",
            model="fixture-model",
            critic_model="fixture-critic",
            transport=RecordingTransport(
                URLError("test offline") if unavailable else candidate
            ),
        )
        checker = OpenAIRecommendationAdapter(
            api_key_provider=lambda: "test-only-key",
            model="fixture-model",
            critic_model="fixture-critic",
            transport=RecordingTransport(critic),
        )
        return provider.analyze_investment, checker.criticize_investment

    return bind


def test_exact_source_bound_outputs_reach_atomic_publication(provider_seam):
    store = Store()
    provider, critic = provider_seam(*evidence())
    assert run(store, provider=provider, critic=critic)
    assert store.calls == ["claim", "load", "renew", "renew", "publish"]
    assert store.failures == []


def test_untrusted_output_never_reaches_publication(provider_seam):
    store = Store()
    provider, critic = provider_seam("{}", evidence()[1])
    run(store, provider=provider, critic=critic)
    assert "publish" not in store.calls
    assert store.failures and store.failures[0]["transient"] is False


def test_transport_failure_is_retryable_without_publication(provider_seam):
    store = Store()
    provider, critic = provider_seam(*evidence(), unavailable=True)
    run(store, provider=provider, critic=critic)
    assert "publish" not in store.calls
    assert store.failures == [
        {"error_code": "provider_transport_failure", "transient": True}
    ]
