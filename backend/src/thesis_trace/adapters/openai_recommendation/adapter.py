from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen

from thesis_trace.application.ai_ports import (
    AnalysisSource,
    RecommendationCriticRequest,
    RecommendationProviderRequest,
)


_CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "direct_supporting_snapshot_ids",
        "clue_features",
        "has_source_conflict",
        "newer_authoritative_refutation",
        "price_or_volume_only",
        "novel_unsupported_event",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "anomaly-candidate-v1"},
        "direct_supporting_snapshot_ids": {
            "type": "array", "items": {"type": "string"}, "uniqueItems": True
        },
        "clue_features": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "timeliness", "traceability", "specificity", "corroboration",
                        "invalidation_relevance",
                    ],
                    "properties": {
                        key: {"type": "integer", "minimum": 0, "maximum": 2}
                        for key in (
                            "timeliness", "traceability", "specificity", "corroboration",
                            "invalidation_relevance",
                        )
                    },
                },
            ]
        },
        "has_source_conflict": {"type": "boolean"},
        "newer_authoritative_refutation": {"type": "boolean"},
        "price_or_volume_only": {"type": "boolean"},
        "novel_unsupported_event": {"type": "boolean"},
    },
}

_CRITIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "verdict", "source_available", "citation_direct_support",
        "subject_matches", "time_reasonable", "invalidation_matches", "b_independence",
        "no_newer_a_refutation",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "recommendation-critic-v1"},
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
        "source_available": {"type": "boolean"},
        "citation_direct_support": {"type": "boolean"},
        "subject_matches": {"type": "boolean"},
        "time_reasonable": {"type": "boolean"},
        "invalidation_matches": {"type": "boolean"},
        "b_independence": {"type": "boolean"},
        "no_newer_a_refutation": {"type": "boolean"},
    },
}


def _source_value(source: AnalysisSource) -> dict[str, object]:
    return {
        "source_snapshot_id": source.source_snapshot_id,
        "publisher_identity": source.publisher_identity,
        "source_tier_facts": list(source.source_tier_facts),
        "underlying_evidence_id": source.underlying_evidence_id,
        "canonical_url": source.canonical_url,
        "excerpt": source.excerpt,
        "retrieved_at": source.retrieved_at,
        "published_at": source.published_at,
        "observed_at": source.observed_at,
    }


def _https_transport(
    url: str, headers: dict[str, str], payload: dict[str, object], timeout: float
) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read(1_048_577)
    if len(body) > 1_048_576:
        raise RuntimeError("provider_unavailable")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise RuntimeError("invalid_output")
    return value


class OpenAIRecommendationAdapter:
    """Call Responses structured outputs while returning only untrusted JSON bytes."""

    def __init__(
        self,
        *,
        api_key_provider: Callable[[], str],
        model: str,
        critic_model: str | None = None,
        endpoint: str = "https://api.openai.com/v1/responses",
        timeout_seconds: float = 30,
        transport: Callable[
            [str, dict[str, str], dict[str, object], float], dict[str, object]
        ] = _https_transport,
    ) -> None:
        if not callable(api_key_provider) or not model.strip() or timeout_seconds <= 0:
            raise ValueError("invalid_provider_configuration")
        self._api_key_provider = api_key_provider
        self._model = model.strip()
        self._critic_model = (critic_model or model).strip()
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @staticmethod
    def _output_text(response: dict[str, object]) -> str:
        if response.get("status") != "completed" or response.get("error") not in (None, {}):
            raise RuntimeError("invalid_output")
        output = response.get("output")
        if not isinstance(output, list):
            raise RuntimeError("invalid_output")
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str):
                        texts.append(text)
                elif isinstance(part, dict) and part.get("type") == "refusal":
                    raise RuntimeError("invalid_output")
        if len(texts) != 1 or not texts[0].strip():
            raise RuntimeError("invalid_output")
        return texts[0]

    def _call(
        self,
        *,
        model: str,
        instructions: str,
        input_value: dict[str, object],
        schema_name: str,
        schema: dict[str, Any],
    ) -> str:
        try:
            key = self._api_key_provider().strip()
            if not key:
                raise RuntimeError("provider_unavailable")
            response = self._transport(
                self._endpoint,
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                {
                    "model": model,
                    "store": False,
                    "instructions": instructions,
                    "input": json.dumps(input_value, ensure_ascii=False, separators=(",", ":")),
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": schema_name,
                            "strict": True,
                            "schema": schema,
                        }
                    },
                },
                self._timeout_seconds,
            )
        except RuntimeError as error:
            if str(error) == "invalid_output":
                raise
            raise RuntimeError("provider_unavailable") from None
        except Exception:
            raise RuntimeError("provider_unavailable") from None
        return self._output_text(response)

    def analyze(self, request: RecommendationProviderRequest) -> str:
        if request.model_version != self._model:
            raise RuntimeError("provider_version_mismatch")
        return self._call(
            model=request.model_version,
            instructions=(
                "Analyze only the supplied immutable source snapshots. Cite snapshot IDs "
                "only when their excerpts directly support the candidate. Do not classify "
                "Hard or Soft and do not infer a predeclared invalidation condition."
            ),
            input_value={
                "assessment_id": request.assessment_id,
                "evidence_id": request.evidence_id,
                "evidence_version": request.evidence_version,
                "schema_version": request.schema_version,
                "prompt_version": request.prompt_version,
                "sources": [_source_value(item) for item in request.sources],
            },
            schema_name="anomaly_candidate",
            schema=_CANDIDATE_SCHEMA,
        )

    def criticize(self, request: RecommendationCriticRequest) -> str:
        if request.model_version != self._critic_model:
            raise RuntimeError("provider_version_mismatch")
        return self._call(
            model=request.model_version,
            instructions=(
                "Independently verify every required citation, subject, time, invalidation, "
                "source-independence, and newer-authoritative-refutation check. Return FAIL "
                "when any fact is missing, uncertain, inaccessible, or conflicting."
            ),
            input_value={
                "assessment_id": request.assessment_id,
                "schema_version": request.schema_version,
                "prompt_version": request.prompt_version,
                "candidate_json": request.candidate_json,
                "sources": [_source_value(item) for item in request.sources],
            },
            schema_name="recommendation_critic",
            schema=_CRITIC_SCHEMA,
        )
