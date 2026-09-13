"""Private Core mappings; immutable trace documents are not aggregate authority."""

from dataclasses import asdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from thesis_trace.modules.recommendation.contracts import (
    BoundRecommendationInput,
    OwnerDecision,
    RecommendationActor,
    RecommendationCandidate,
    RecommendationInputSnapshot,
    RecommendationRecord,
    RecommendationSource,
)


def _tables() -> dict[str, sa.Table]:
    metadata = sa.MetaData()

    def table(
        name, *, texts=(), integers=(), numerics=(), times=(), arrays=(), documents=()
    ):
        return sa.Table(
            name,
            metadata,
            *(sa.Column(key, sa.Text) for key in texts),
            *(sa.Column(key, sa.Integer) for key in integers),
            *(sa.Column(key, sa.Numeric) for key in numerics),
            *(sa.Column(key, sa.DateTime(timezone=True)) for key in times),
            *(sa.Column(key, ARRAY(sa.Text)) for key in arrays),
            *(sa.Column(key, JSONB) for key in documents),
            schema="recommendation",
        )

    identity = ("owner_user_id", "recommendation_id")
    return {
        "admissions": table(
            "admissions",
            texts=(
                "owner_user_id",
                "input_id",
                "thesis_id",
                "company_id",
                "valuation_id",
                "portfolio_snapshot_id",
                "source_selection_reason",
                "benchmark_source",
                "input_digest",
                "idempotency_key",
                "command_digest",
            ),
            integers=("cycle", "binding_count", "source_count"),
            times=("admitted_at",),
            arrays=("gate_reasons",),
            documents=("versions", "analysis_context"),
        ),
        "admission_bindings": table(
            "admission_bindings",
            texts=("owner_user_id", "input_id", "owner_domain", "record_id", "digest"),
            integers=("ordinal", "version"),
            times=("valid_until",),
        ),
        "admission_sources": table(
            "admission_sources",
            texts=(
                "owner_user_id",
                "input_id",
                "snapshot_id",
                "publisher",
                "excerpt",
                "canonical_url",
                "source_category",
                "lineage",
            ),
            integers=("ordinal",),
            times=("published_at", "observed_at", "retrieved_at"),
        ),
        "jobs": table(
            "jobs",
            texts=(
                "job_id",
                "owner_user_id",
                "input_id",
                "thesis_id",
                "kind",
                "state",
                "lease_token",
                "error_code",
            ),
            integers=("cycle", "attempt"),
            times=("lease_expires_at", "available_at", "updated_at"),
        ),
        "records": table(
            "records",
            texts=(
                *identity,
                "thesis_id",
                "company_id",
                "valuation_id",
                "portfolio_snapshot_id",
                "source_selection_reason",
                "benchmark_source",
                "candidate_direction",
                "candidate_schema_version",
                "candidate_digest",
                "direction",
                "policy_version",
                "critic_evidence",
            ),
            integers=(
                "version",
                "cycle",
                "binding_count",
                "source_count",
                "claim_count",
            ),
            numerics=(
                "raw_dca_ceiling",
                "final_multiplier",
                "annualized_return",
                "minimum_return",
            ),
            times=("admitted_at", "published_at"),
            arrays=("input_gate_reasons", "reasons"),
            documents=("calculation_trace", "provenance", "analysis_context"),
        ),
        "input_bindings": table(
            "input_bindings",
            texts=(*identity, "owner_domain", "record_id", "digest"),
            integers=("version", "ordinal", "input_version"),
            times=("valid_until",),
        ),
        "sources": table(
            "sources",
            texts=(
                *identity,
                "snapshot_id",
                "publisher",
                "excerpt",
                "canonical_url",
                "source_category",
                "lineage",
            ),
            integers=("version", "ordinal"),
            times=("published_at", "observed_at", "retrieved_at"),
        ),
        "claims": table(
            "claims",
            texts=(*identity, "claim_text"),
            integers=("version", "ordinal"),
            arrays=("supporting_snapshot_ids",),
        ),
        "decisions": table(
            "decisions",
            texts=(*identity, "status", "reason", "policy_version", "confirmation_id"),
            integers=("version", "sequence"),
            times=("recorded_at", "defer_until"),
            documents=("input_checks",),
        ),
        "receipts": table(
            "receipts",
            texts=(*identity, "idempotency_key", "command_digest"),
            integers=("version", "decision_sequence"),
        ),
        "audit_events": table(
            "audit_events",
            texts=(
                *identity,
                "event_id",
                "action",
                "reason",
                "correlation_id",
                "causation_id",
                "policy_version",
                "build_version",
            ),
            integers=("version", "before_sequence", "after_sequence"),
            times=("occurred_at",),
        ),
    }


def _identity(table: sa.Table, actor: str, recommendation_id: str, version: int):
    return sa.and_(
        table.c.owner_user_id == actor,
        table.c.recommendation_id == recommendation_id,
        table.c.version == version,
    )


def _decision(row: Any) -> OwnerDecision:
    return OwnerDecision(
        row["recommendation_id"],
        row["version"],
        row["sequence"],
        row["status"],
        row["reason"],
        row["owner_user_id"],
        row["recorded_at"],
        row["defer_until"],
        row["policy_version"],
        tuple(tuple(pair) for pair in row["input_checks"]),
        row["confirmation_id"],
    )


def _load(
    connection: sa.Connection,
    tables: dict[str, sa.Table],
    actor: str,
    recommendation_id: str,
    version: int,
) -> RecommendationRecord | None:
    header = tables["records"]
    row = (
        connection.execute(
            sa.select(header).where(
                _identity(header, actor, recommendation_id, version)
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None

    def children(name):
        table = tables[name]
        return (
            connection.execute(
                sa.select(table)
                .where(_identity(table, actor, recommendation_id, version))
                .order_by(table.c.ordinal)
            )
            .mappings()
            .all()
        )

    bindings = tuple(
        BoundRecommendationInput(
            item["owner_domain"],
            item["record_id"],
            item["input_version"],
            item["digest"],
            item["valid_until"],
        )
        for item in children("input_bindings")
    )
    sources = tuple(
        RecommendationSource(
            item["snapshot_id"],
            item["publisher"],
            item["excerpt"],
            item["canonical_url"],
            item["published_at"],
            item["observed_at"],
            item["retrieved_at"],
            item["source_category"],
            item["lineage"],
        )
        for item in children("sources")
    )
    claims = tuple(
        (item["claim_text"], tuple(item["supporting_snapshot_ids"]))
        for item in children("claims")
    )
    if (len(bindings), len(sources), len(claims)) != (
        row["binding_count"],
        row["source_count"],
        row["claim_count"],
    ):
        raise ValueError("recommendation_record_incomplete")
    inputs = RecommendationInputSnapshot(
        RecommendationActor(actor, True),
        row["thesis_id"],
        row["cycle"],
        bindings,
        sources,
        row["valuation_id"],
        row["portfolio_snapshot_id"],
        row["source_selection_reason"],
        tuple(row["input_gate_reasons"]),
        row["company_id"],
        row["benchmark_source"],
        row["admitted_at"],
        tuple(tuple(pair) for pair in row["analysis_context"] or ()),
    )
    candidate = RecommendationCandidate(
        row["candidate_direction"],
        row["raw_dca_ceiling"],
        claims,
        row["candidate_schema_version"],
        row["candidate_digest"],
    )
    return RecommendationRecord(
        recommendation_id,
        version,
        inputs,
        candidate,
        row["final_multiplier"],
        row["published_at"],
        row["policy_version"],
        row["direction"],
        tuple(row["reasons"]),
        row["annualized_return"],
        row["minimum_return"],
        tuple(tuple(pair) for pair in row["calculation_trace"]),
        tuple(tuple(pair) for pair in row["provenance"]),
        row["critic_evidence"],
    )


def _insert(
    connection: sa.Connection, tables: dict[str, sa.Table], record: RecommendationRecord
) -> None:
    inputs = record.inputs
    identity = dict(
        owner_user_id=inputs.actor.actor_id,
        recommendation_id=record.recommendation_id,
        version=record.version,
    )
    connection.execute(
        tables["records"]
        .insert()
        .values(
            **identity,
            thesis_id=inputs.thesis_id,
            cycle=inputs.cycle,
            company_id=inputs.company_id,
            valuation_id=inputs.valuation_id,
            portfolio_snapshot_id=inputs.portfolio_snapshot_id,
            source_selection_reason=inputs.source_selection_reason,
            benchmark_source=inputs.benchmark_source,
            input_gate_reasons=list(inputs.gate_reasons),
            admitted_at=inputs.admitted_at,
            analysis_context=inputs.analysis_context,
            candidate_direction=record.candidate.direction,
            raw_dca_ceiling=record.candidate.raw_dca_ceiling,
            candidate_schema_version=record.candidate.schema_version,
            candidate_digest=record.candidate.digest,
            direction=record.direction,
            final_multiplier=record.final_multiplier,
            reasons=list(record.reasons),
            annualized_return=record.annualized_return,
            minimum_return=record.minimum_return,
            published_at=record.published_at,
            policy_version=record.policy_version,
            calculation_trace=record.calculation_trace,
            provenance=record.provenance,
            critic_evidence=record.critic_evidence,
            binding_count=len(inputs.bindings),
            source_count=len(inputs.sources),
            claim_count=len(record.candidate.claims),
        )
    )
    for ordinal, item in enumerate(inputs.bindings):
        connection.execute(
            tables["input_bindings"]
            .insert()
            .values(
                **identity,
                ordinal=ordinal,
                owner_domain=item.owner_domain,
                record_id=item.record_id,
                input_version=item.version,
                digest=item.digest,
                valid_until=item.valid_until,
            )
        )
    for ordinal, item in enumerate(inputs.sources):
        connection.execute(
            tables["sources"]
            .insert()
            .values(**identity, ordinal=ordinal, **asdict(item))
        )
    for ordinal, (text, source_ids) in enumerate(record.candidate.claims):
        connection.execute(
            tables["claims"]
            .insert()
            .values(
                **identity,
                ordinal=ordinal,
                claim_text=text,
                supporting_snapshot_ids=list(source_ids),
            )
        )


def _load_input(
    connection: sa.Connection, tables: dict[str, sa.Table], actor: str, input_id: str
):
    header = tables["admissions"]
    row = (
        connection.execute(
            sa.select(header).where(
                header.c.owner_user_id == actor, header.c.input_id == input_id
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None

    def children(name):
        table = tables[name]
        return (
            connection.execute(
                sa.select(table)
                .where(table.c.owner_user_id == actor, table.c.input_id == input_id)
                .order_by(table.c.ordinal)
            )
            .mappings()
            .all()
        )

    bindings = tuple(
        BoundRecommendationInput(
            item["owner_domain"],
            item["record_id"],
            item["version"],
            item["digest"],
            item["valid_until"],
        )
        for item in children("admission_bindings")
    )
    sources = tuple(
        RecommendationSource(
            item["snapshot_id"],
            item["publisher"],
            item["excerpt"],
            item["canonical_url"],
            item["published_at"],
            item["observed_at"],
            item["retrieved_at"],
            item["source_category"],
            item["lineage"],
        )
        for item in children("admission_sources")
    )
    if (len(bindings), len(sources)) != (row["binding_count"], row["source_count"]):
        raise ValueError("recommendation_admission_incomplete")
    inputs = RecommendationInputSnapshot(
        RecommendationActor(actor, True),
        row["thesis_id"],
        row["cycle"],
        bindings,
        sources,
        row["valuation_id"],
        row["portfolio_snapshot_id"],
        row["source_selection_reason"],
        tuple(row["gate_reasons"]),
        row["company_id"],
        row["benchmark_source"],
        row["admitted_at"],
        tuple(tuple(pair) for pair in row["analysis_context"] or ()),
    )
    return inputs, tuple(tuple(pair) for pair in row["versions"]), row["input_digest"]


def _insert_input(
    connection: sa.Connection,
    tables: dict[str, sa.Table],
    inputs: RecommendationInputSnapshot,
    *,
    input_id: str,
    digest: str,
    versions: tuple[tuple[str, str], ...],
    idempotency_key: str,
    command_digest: str,
) -> None:
    identity = dict(owner_user_id=inputs.actor.actor_id, input_id=input_id)
    connection.execute(
        tables["admissions"]
        .insert()
        .values(
            **identity,
            thesis_id=inputs.thesis_id,
            cycle=inputs.cycle,
            company_id=inputs.company_id,
            valuation_id=inputs.valuation_id,
            portfolio_snapshot_id=inputs.portfolio_snapshot_id,
            source_selection_reason=inputs.source_selection_reason,
            benchmark_source=inputs.benchmark_source,
            gate_reasons=list(inputs.gate_reasons),
            admitted_at=inputs.admitted_at,
            analysis_context=inputs.analysis_context,
            input_digest=digest,
            versions=versions,
            idempotency_key=idempotency_key,
            command_digest=command_digest,
            binding_count=len(inputs.bindings),
            source_count=len(inputs.sources),
        )
    )
    for ordinal, item in enumerate(inputs.bindings):
        connection.execute(
            tables["admission_bindings"]
            .insert()
            .values(**identity, ordinal=ordinal, **asdict(item))
        )
    for ordinal, item in enumerate(inputs.sources):
        connection.execute(
            tables["admission_sources"]
            .insert()
            .values(**identity, ordinal=ordinal, **asdict(item))
        )
