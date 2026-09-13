from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from thesis_trace.modules.recommendation.contracts import (
    BoundRecommendationInput,
    OwnerDecision,
    RecommendationActor,
    RecommendationCandidate,
    RecommendationInputSnapshot,
    RecommendationRecord,
    RecommendationSource,
)


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strict_object(raw: str, error: str) -> dict:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(error)
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(error)

    try:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 65536:
            raise ValueError(error)
        value = json.loads(
            raw, object_pairs_hook=unique_keys, parse_constant=reject_constant
        )
        if not isinstance(value, dict):
            raise ValueError(error)
        return value
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ValueError(error) from None


def _source_ids(sources: tuple[RecommendationSource, ...], now: datetime) -> set[str]:
    if not _aware(now) or not isinstance(sources, tuple) or not 1 <= len(sources) <= 32:
        raise ValueError("invalid_candidate_sources")
    result = set()
    for source in sources:
        if (
            not isinstance(source, RecommendationSource)
            or not _text(source.snapshot_id)
            or not _text(source.publisher)
            or not _text(source.canonical_url)
            or not _text(source.excerpt)
            or len(source.excerpt) > 2048
            or source.snapshot_id in result
            or source.source_category is not None
            and source.source_category not in ("A", "B", "C")
            or source.lineage is not None
            and not _text(source.lineage)
            or not _aware(source.retrieved_at)
            or source.retrieved_at > now
            or (source.published_at is None and source.observed_at is None)
            or any(
                value is not None and (not _aware(value) or value > now)
                for value in (source.published_at, source.observed_at)
            )
        ):
            raise ValueError("invalid_candidate_sources")
        result.add(source.snapshot_id)
    return result


class RecommendationService:
    """Owner-scoped Recommendation policy; no storage or framework authority."""

    @staticmethod
    def admission_digest(
        inputs: RecommendationInputSnapshot, versions: tuple[tuple[str, str], ...]
    ) -> str:
        """Canonical v1 digest binds immutable input values and actual execution identities."""
        if (
            not isinstance(inputs, RecommendationInputSnapshot)
            or not isinstance(inputs.actor, RecommendationActor)
            or not _text(inputs.actor.actor_id)
            or inputs.actor.may_manage is not True
            or not _text(inputs.thesis_id)
            or not _text(inputs.company_id)
            or not _text(inputs.valuation_id)
            or type(inputs.cycle) is not int
            or inputs.cycle < 1
            or not _aware(inputs.admitted_at)
            or not _text(inputs.source_selection_reason)
            or inputs.benchmark_source
            not in ("company_history", "peer_group", "abstain")
            or not isinstance(inputs.gate_reasons, tuple)
            or any(not _text(value) for value in inputs.gate_reasons)
            or not isinstance(inputs.bindings, tuple)
        ):
            raise ValueError("invalid_admission_inputs")
        if (
            not isinstance(inputs.analysis_context, tuple)
            or any(
                not isinstance(pair, tuple)
                or len(pair) != 2
                or any(not _text(value) for value in pair)
                for pair in inputs.analysis_context
            )
            or len(dict(inputs.analysis_context)) != len(inputs.analysis_context)
            or set(dict(inputs.analysis_context))
            != {"thesis", "conditions", "valuation", "thesis_record_version"}
        ):
            raise ValueError("invalid_analysis_context")
        if RecommendationService.expiry_reasons(
            inputs.bindings, inputs.bindings, now=inputs.admitted_at
        ):
            raise ValueError("superseded_inputs")
        _source_ids(inputs.sources, inputs.admitted_at)
        required = {
            "provider",
            "model",
            "prompt",
            "critic_model",
            "critic_prompt",
            "build",
            "candidate_schema",
            "critic_schema",
            "minimum_return_policy",
            "risk_policy",
            "cost_profile_policy",
            "sizing_policy",
            "return_policy",
        }
        if (
            not isinstance(versions, tuple)
            or any(
                not isinstance(pair, tuple)
                or len(pair) != 2
                or any(not _text(value) for value in pair)
                for pair in versions
            )
            or len(dict(versions)) != len(versions)
            or not required <= dict(versions).keys()
        ):
            raise ValueError("invalid_admission_versions")

        def encode(value):
            if isinstance(value, datetime) and _aware(value):
                return value.astimezone(timezone.utc).isoformat()
            raise ValueError("invalid_admission_inputs")

        try:
            payload = json.dumps(
                {
                    "schema": "recommendation-input-v1",
                    "inputs": asdict(inputs),
                    "versions": sorted(versions),
                },
                default=encode,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, UnicodeError, RecursionError):
            raise ValueError("invalid_admission_inputs") from None
        if len(payload) > 262144:
            raise ValueError("input_too_large")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def plan_publication(
        *,
        actor: RecommendationActor,
        recommendation_id: str,
        version: int,
        inputs: RecommendationInputSnapshot,
        current: tuple[BoundRecommendationInput, ...],
        raw_candidate: str,
        raw_critic: str,
        selected_multiplier: Decimal,
        annualized_return: Decimal | None,
        minimum_return: Decimal | None,
        calculation_trace: tuple[tuple[str, str], ...],
        provenance: tuple[tuple[str, str], ...],
        now: datetime,
    ) -> RecommendationRecord:
        """Pure result plan; the parent must fence and atomically persist it."""
        if (
            not isinstance(inputs, RecommendationInputSnapshot)
            or not isinstance(actor, RecommendationActor)
            or actor.may_manage is not True
            or not _text(actor.actor_id)
            or actor != inputs.actor
        ):
            raise ValueError("resource_unavailable")
        if (
            not _text(recommendation_id)
            or type(version) is not int
            or version < 1
            or not _text(inputs.thesis_id)
            or not _text(inputs.company_id)
            or type(inputs.cycle) is not int
            or inputs.cycle < 1
            or not _text(inputs.valuation_id)
            or not _text(inputs.source_selection_reason)
            or inputs.benchmark_source
            not in ("company_history", "peer_group", "abstain")
            or not isinstance(inputs.bindings, tuple)
            or not isinstance(inputs.sources, tuple)
            or not isinstance(inputs.gate_reasons, tuple)
            or any(not _text(reason) for reason in inputs.gate_reasons)
            or not _aware(now)
            or not _aware(inputs.admitted_at)
            or inputs.admitted_at > now
        ):
            raise ValueError("invalid_publication_inputs")
        if RecommendationService.expiry_reasons(inputs.bindings, current, now=now):
            raise ValueError("superseded_inputs")
        candidate = RecommendationService.validate_candidate(
            raw_candidate, sources=inputs.sources, now=now
        )
        if not RecommendationService.validate_critic(raw_critic, candidate=candidate):
            raise ValueError("critic_rejected")
        if (
            not isinstance(selected_multiplier, Decimal)
            or not selected_multiplier.is_finite()
            or selected_multiplier
            not in (Decimal(0), Decimal("0.5"), Decimal(1), Decimal("1.5"))
            or selected_multiplier > candidate.raw_dca_ceiling
        ):
            raise ValueError("invalid_sizing_result")
        for name, pairs in (("trace", calculation_trace), ("provenance", provenance)):
            if (
                not isinstance(pairs, tuple)
                or not pairs
                or any(
                    not isinstance(pair, tuple)
                    or len(pair) != 2
                    or any(not _text(value) for value in pair)
                    for pair in pairs
                )
                or len({pair[0] for pair in pairs}) != len(pairs)
            ):
                raise ValueError(f"invalid_publication_{name}")
            try:
                if len(json.dumps(pairs, ensure_ascii=False).encode("utf-8")) > 262144:
                    raise ValueError(f"invalid_publication_{name}")
            except UnicodeError:
                raise ValueError(f"invalid_publication_{name}") from None
        required_versions = {
            "provider",
            "model",
            "prompt",
            "build",
            "minimum_return_policy",
            "risk_policy",
            "cost_profile_policy",
        }
        if not required_versions <= {key for key, _ in provenance}:
            raise ValueError("invalid_publication_provenance")
        reasons = list(inputs.gate_reasons)
        if not _text(inputs.portfolio_snapshot_id):
            reasons.append("portfolio_snapshot_unavailable")
        if inputs.benchmark_source == "abstain":
            reasons.append("benchmark_abstained")
        if minimum_return is None:
            reasons.append("minimum_return_unconfigured")
        elif not isinstance(minimum_return, Decimal) or not minimum_return.is_finite():
            reasons.append("minimum_return_invalid")
        if candidate.direction == "buy":
            if selected_multiplier == 0:
                reasons.append("no_feasible_size")
            if (
                not isinstance(annualized_return, Decimal)
                or not annualized_return.is_finite()
            ):
                reasons.append("final_size_return_unavailable")
            elif (
                isinstance(minimum_return, Decimal)
                and minimum_return.is_finite()
                and annualized_return < minimum_return
            ):
                reasons.append("minimum_return_not_met")
        direction = "abstain" if reasons else candidate.direction
        return RecommendationRecord(
            recommendation_id,
            version,
            inputs,
            candidate,
            selected_multiplier if direction == "buy" else Decimal(0),
            now,
            "recommendation-publication-v1",
            direction,
            tuple(dict.fromkeys(reasons)),
            annualized_return
            if isinstance(annualized_return, Decimal) and annualized_return.is_finite()
            else None,
            minimum_return
            if isinstance(minimum_return, Decimal) and minimum_return.is_finite()
            else None,
            calculation_trace,
            provenance,
            raw_critic,
        )

    @staticmethod
    def validate_critic(raw: str, *, candidate: RecommendationCandidate) -> bool:
        value = _strict_object(raw, "invalid_critic")
        if (
            set(value) != {"schema_version", "verdict", "candidate_digest", "checks"}
            or value["schema_version"] != "investment-critic-v1"
            or value["verdict"] not in ("PASS", "FAIL")
            or value["candidate_digest"] != candidate.digest
            or not isinstance(value["checks"], list)
            or len(value["checks"]) != len(candidate.claims)
        ):
            raise ValueError("invalid_critic")
        boolean_fields = (
            "source_available",
            "direct_support",
            "subject_matches",
            "time_reasonable",
        )
        seen = set()
        passed = value["verdict"] == "PASS"
        for check in value["checks"]:
            if (
                not isinstance(check, dict)
                or set(check)
                != {"claim_index", "supporting_snapshot_ids", *boolean_fields}
                or type(check["claim_index"]) is not int
                or not 0 <= check["claim_index"] < len(candidate.claims)
                or check["claim_index"] in seen
                or not isinstance(check["supporting_snapshot_ids"], list)
                or check["supporting_snapshot_ids"]
                != list(candidate.claims[check["claim_index"]][1])
                or any(type(check[field]) is not bool for field in boolean_fields)
            ):
                raise ValueError("invalid_critic")
            seen.add(check["claim_index"])
            passed = passed and all(check[field] for field in boolean_fields)
        return passed

    @staticmethod
    def validate_candidate(
        raw: str, *, sources: tuple[RecommendationSource, ...], now: datetime
    ) -> RecommendationCandidate:
        source_ids = _source_ids(sources, now)
        value = _strict_object(raw, "invalid_candidate")
        if (
            set(value) != {"schema_version", "direction", "raw_dca_ceiling", "claims"}
            or value["schema_version"] != "investment-candidate-v1"
            or value["direction"] not in ("buy", "hold", "abstain")
            or value["raw_dca_ceiling"] not in ("0", "0.5", "1", "1.5")
            or (value["direction"] == "buy") == (value["raw_dca_ceiling"] == "0")
            or not isinstance(value["claims"], list)
            or not 1 <= len(value["claims"]) <= 32
        ):
            raise ValueError("invalid_candidate")
        for claim in value["claims"]:
            if (
                not isinstance(claim, dict)
                or set(claim) != {"text", "supporting_snapshot_ids"}
                or not _text(claim["text"])
                or len(claim["text"]) > 2048
                or not isinstance(claim["supporting_snapshot_ids"], list)
                or not 1 <= len(claim["supporting_snapshot_ids"]) <= len(source_ids)
                or any(not _text(item) for item in claim["supporting_snapshot_ids"])
                or len(set(claim["supporting_snapshot_ids"]))
                != len(claim["supporting_snapshot_ids"])
                or not set(claim["supporting_snapshot_ids"]) <= source_ids
            ):
                raise ValueError("invalid_candidate")
        return RecommendationCandidate(
            value["direction"],
            Decimal(value["raw_dca_ceiling"]),
            tuple(
                (claim["text"], tuple(claim["supporting_snapshot_ids"]))
                for claim in value["claims"]
            ),
            value["schema_version"],
            hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def plan_decision(
        *,
        actor: RecommendationActor,
        owner_id: str,
        recommendation_id: str,
        recommendation_version: int,
        previous: OwnerDecision | None,
        expected_sequence: int,
        bound: tuple[BoundRecommendationInput, ...],
        current: tuple[BoundRecommendationInput, ...],
        target_status: str,
        reason: str,
        now: datetime,
        defer_until: datetime | None = None,
    ) -> OwnerDecision | None:
        """Pure transition plan, never a persisted or confirmed decision."""
        if (
            actor.may_manage is not True
            or not actor.actor_id
            or actor.actor_id != owner_id
        ):
            raise ValueError("resource_unavailable")
        if (
            not recommendation_id
            or type(recommendation_version) is not int
            or recommendation_version < 1
            or type(expected_sequence) is not int
            or expected_sequence < 0
            or expected_sequence != (previous.sequence if previous else 0)
            or (
                previous is not None
                and (
                    previous.recommendation_id != recommendation_id
                    or previous.recommendation_version != recommendation_version
                )
            )
        ):
            raise ValueError("version_conflict")
        if target_status not in {"accepted", "rejected", "deferred", "expired"}:
            raise ValueError("invalid_transition")
        if previous is not None and previous.status in {
            "accepted",
            "rejected",
            "expired",
        }:
            if target_status == "expired":
                return None
            raise ValueError("invalid_transition")
        if previous is not None and previous.status != "deferred":
            raise ValueError("invalid_transition")
        expiry = RecommendationService.expiry_reasons(bound, current, now=now)
        if expiry:
            target_status = "expired"
            reason = "; ".join(expiry)
            defer_until = None
        elif target_status == "expired":
            return None
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("missing_reason")
        if target_status == "deferred":
            if not _aware(defer_until) or defer_until <= now:
                raise ValueError("invalid_defer_time")
        else:
            defer_until = None
        return OwnerDecision(
            recommendation_id,
            recommendation_version,
            expected_sequence + 1,
            target_status,
            reason.strip(),
            actor.actor_id,
            now,
            defer_until,
            "recommendation-expiry-v1" if expiry else "recommendation-decision-v1",
            tuple(
                (
                    json.dumps(
                        [item.owner_domain, item.record_id], separators=(",", ":")
                    ),
                    json.dumps(
                        {
                            "version": item.version,
                            "digest": item.digest,
                            "valid_until": item.valid_until.isoformat()
                            if item.valid_until
                            else None,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
                for item in current
            ),
        )

    @staticmethod
    def expiry_reasons(
        bound: tuple[BoundRecommendationInput, ...],
        current: tuple[BoundRecommendationInput, ...],
        *,
        now: datetime,
    ) -> tuple[str, ...]:
        if not bound or not _aware(now):
            raise ValueError("input_validity_unavailable")
        for group in (bound, current):
            seen = set()
            for item in group:
                if (
                    not isinstance(item, BoundRecommendationInput)
                    or not _text(item.owner_domain)
                    or not _text(item.record_id)
                    or type(item.version) is not int
                    or item.version < 1
                    or not _text(item.digest)
                    or (item.valid_until is not None and not _aware(item.valid_until))
                ):
                    raise ValueError("input_validity_unavailable")
                key = (item.owner_domain, item.record_id)
                if key in seen:
                    raise ValueError("input_validity_unavailable")
                seen.add(key)
        by_key = {(item.owner_domain, item.record_id): item for item in current}
        reasons = []
        for item in bound:
            key = (item.owner_domain, item.record_id)
            latest = by_key.get(key)
            if latest is None:
                raise ValueError("input_validity_unavailable")
            if (latest.version, latest.digest) != (
                item.version,
                item.digest,
            ):
                reasons.append(f"input_version_changed:{key[0]}:{key[1]}")
            elif any(
                boundary is not None and now >= boundary
                for boundary in (item.valid_until, latest.valid_until)
            ):
                reasons.append(f"input_expired:{key[0]}:{key[1]}")
        return tuple(reasons)
