from __future__ import annotations

import json

from thesis_trace.application.ai_ports import (
    RecommendationCriticPort,
    RecommendationProviderPort,
)
from thesis_trace.application.flows.anomaly_assessment import AnomalyJobProcessor
from thesis_trace.modules.research import ResearchAnomalyFacade
from thesis_trace.modules.research.anomaly_assessment.contracts import (
    AnomalyClass,
    RequestAssessmentCommand,
    SourceCharacteristicSnapshot,
)
from thesis_trace.modules.research.anomaly_assessment.service import AnomalyAssessmentService
from thesis_trace.platform.in_memory import InMemoryEvidenceStore


OFFICIAL = SourceCharacteristicSnapshot(
    "snapshot-a", "TWSE", authoritative_first_party=True, formal_record=True,
    canonical_url="https://example.com/disclosure", excerpt="material disclosure",
    retrieved_at="2026-08-21T09:00:00Z", published_at="2026-08-21T08:00:00Z",
)


class Provider(RecommendationProviderPort):
    def __init__(self, output: str | Exception) -> None:
        self.output = output
        self.calls = 0
        self.last_request = None

    def analyze(self, request) -> str:
        self.calls += 1
        self.last_request = request
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


class Critic(RecommendationCriticPort):
    def __init__(self, output: str | Exception) -> None:
        self.output = output
        self.calls = 0
        self.last_request = None

    def criticize(self, request) -> str:
        self.calls += 1
        self.last_request = request
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def _provider_candidate(**overrides: object) -> str:
    value = {
        "schema_version": "anomaly-candidate-v1",
        "direct_supporting_snapshot_ids": ["snapshot-a"],
        "clue_features": None,
        "has_source_conflict": False,
        "newer_authoritative_refutation": False,
        "price_or_volume_only": False,
        "novel_unsupported_event": False,
        **overrides,
    }
    return json.dumps(value)


def _critic_verdict(**overrides: object) -> str:
    value = {
        "schema_version": "recommendation-critic-v1",
        "verdict": "PASS",
        "source_available": True,
        "citation_direct_support": True,
        "subject_matches": True,
        "time_reasonable": True,
        "invalidation_matches": True,
        "b_independence": True,
        "no_newer_a_refutation": True,
        **overrides,
    }
    return json.dumps(value)


def _processor(provider: Provider, critic: Critic, *, invalidation: bool = False):
    store = InMemoryEvidenceStore()
    store.current_evidence_versions["evidence-1"] = 3
    service = AnomalyAssessmentService(
        store=store, clock=lambda: "2026-08-21T10:00:00+00:00"
    )
    requested = service.request(
        RequestAssessmentCommand(
            "owner-1", True, "evidence-1", 3, (OFFICIAL,), "review", "worker-1"
        )
    )
    processor = AnomalyJobProcessor(
        research=ResearchAnomalyFacade(service),
        provider=provider,
        critic=critic,
        invalidation_match=lambda _assessment_id: invalidation,
    )
    return processor, store, requested.assessment_id


def test_worker_only_produces_would_be_hard_after_exact_candidate_critic_and_server_invalidation() -> None:
    provider = Provider(_provider_candidate())
    critic = Critic(_critic_verdict())
    processor, store, assessment_id = _processor(provider, critic, invalidation=True)

    assert processor.run_once() is True

    result = store.get_anomaly_assessment(assessment_id)
    assert result is not None and result.trace is not None
    assert result.trace.anomaly_class is AnomalyClass.WOULD_BE_HARD
    assert provider.calls == critic.calls == 1
    assert provider.last_request.model_version == "test-provider-model"
    assert provider.last_request.prompt_version == "anomaly-prompt-v1"
    assert critic.last_request.model_version == "test-critic-model"
    assert critic.last_request.prompt_version == "recommendation-critic-prompt-v1"


def test_missing_server_invalidation_keeps_valid_model_output_soft() -> None:
    processor, store, assessment_id = _processor(
        Provider(_provider_candidate()), Critic(_critic_verdict())
    )

    assert processor.run_once() is True

    result = store.get_anomaly_assessment(assessment_id)
    assert result is not None and result.trace is not None
    assert result.trace.anomaly_class is AnomalyClass.SOFT
    assert "predeclared_invalidation" in result.trace.failure_codes


def test_malformed_extra_provider_field_fails_closed_without_invoking_critic() -> None:
    provider = Provider(_provider_candidate(anomaly_class="would_be_hard"))
    critic = Critic(_critic_verdict())
    processor, store, assessment_id = _processor(provider, critic, invalidation=True)

    assert processor.run_once() is True

    result = store.get_anomaly_assessment(assessment_id)
    assert result is not None and result.trace is not None
    assert result.trace.anomaly_class is AnomalyClass.SOFT
    assert critic.calls == 0


def test_missing_citation_evidence_fails_closed_without_invoking_critic() -> None:
    provider = Provider(_provider_candidate())
    critic = Critic(_critic_verdict())
    store = InMemoryEvidenceStore()
    store.current_evidence_versions["evidence-1"] = 3
    service = AnomalyAssessmentService(
        store=store, clock=lambda: "2026-08-21T10:00:00+00:00"
    )
    source_without_excerpt = SourceCharacteristicSnapshot(
        "snapshot-a", "TWSE", authoritative_first_party=True, formal_record=True,
        canonical_url="https://example.com/disclosure", retrieved_at="2026-08-21T09:00:00Z",
        published_at="2026-08-21T08:00:00Z",
    )
    requested = service.request(
        RequestAssessmentCommand(
            "owner-1", True, "evidence-1", 3, (source_without_excerpt,), "review", "worker-2"
        )
    )
    processor = AnomalyJobProcessor(
        research=ResearchAnomalyFacade(service), provider=provider, critic=critic,
        invalidation_match=lambda _assessment_id: True,
    )

    assert processor.run_once() is True
    result = store.get_anomaly_assessment(requested.assessment_id)
    assert result is not None and result.trace is not None
    assert result.trace.anomaly_class is AnomalyClass.SOFT
    assert critic.calls == 0


def test_provider_or_critic_failure_is_a_committed_soft_trace_not_worker_crash() -> None:
    for provider_output, critic_output in (
        (TimeoutError("provider timeout"), _critic_verdict()),
        (_provider_candidate(), "{}"),
        (_provider_candidate(), _critic_verdict(verdict="FAIL")),
    ):
        processor, store, assessment_id = _processor(
            Provider(provider_output), Critic(critic_output), invalidation=True
        )
        assert processor.run_once() is True
        result = store.get_anomaly_assessment(assessment_id)
        assert result is not None and result.trace is not None
        assert result.trace.anomaly_class is AnomalyClass.SOFT
