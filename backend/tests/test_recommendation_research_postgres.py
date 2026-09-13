from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import os
import uuid

import pytest

from thesis_trace.modules.research import (
    ResearchActorContext,
    ResearchRecommendationFacade,
)
from thesis_trace.modules.research.evidence_stage.contracts import (
    ConfirmDimensionFactsCommand,
    DimensionFacts,
    SourceConfirmation,
    StageActorContext,
)
from thesis_trace.modules.research.evidence_stage.service import EvidenceStageService
from thesis_trace.modules.research.evidence_collection.contracts import (
    ValuationSourceFact,
)
from thesis_trace.platform.database import create_database_engine, database_connection
from thesis_trace.platform.postgres import PostgresEvidenceStore, bootstrap_schema

pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL required",
)


def test_research_source_query_retains_immutable_metadata_and_current_stage_identity():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    engine = create_database_engine(lambda: url)
    owner = str(uuid.uuid4())
    evidence_id, snapshot_id = str(uuid.uuid4()), str(uuid.uuid4())
    source_url = "https://example.test/" + evidence_id
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="rollback-source-test"):
        with database_connection(engine) as connection:
            connection.exec_driver_sql(
                "SELECT set_config('app.user_id',%s,true)", (owner,)
            )
            connection.exec_driver_sql("SELECT set_config('app.role','owner',true)")
            store = PostgresEvidenceStore(lambda: url).for_transaction(connection)
            company = store.create_company(
                "fixture-" + evidence_id, "Source query fixture"
            )
            connection.exec_driver_sql(
                "INSERT INTO research.evidence_intakes(evidence_id,version,company_id,company_version,submitted_url,status) VALUES(%s,2,%s,1,%s,'succeeded')",
                (evidence_id, company.company_id, source_url),
            )
            connection.exec_driver_sql(
                "INSERT INTO research.source_snapshots(snapshot_id,canonical_url,normalization_policy_version,publisher,content_hash,retrieved_at,published_at,excerpt,source_category,lineage) VALUES(%s,%s,'url-normalization-v1','Official publisher',%s,%s,%s,'Exact saved excerpt','A','underlying-report')",
                (snapshot_id, source_url, evidence_id, now, now),
            )
            connection.exec_driver_sql(
                "INSERT INTO research.canonical_sources(source_id,normalization_policy_version,canonical_url) VALUES(%s,'url-normalization-v1',%s)",
                (snapshot_id, source_url),
            )
            connection.exec_driver_sql(
                "INSERT INTO research.source_observations(evidence_id,snapshot_id,submitted_url,source_id) VALUES(%s,%s,%s,%s)",
                (evidence_id, snapshot_id, source_url, snapshot_id),
            )
            facade = ResearchRecommendationFacade(store)
            actor = ResearchActorContext(owner, True, True)
            initial = facade.get_source(actor, evidence_id)
            assert (
                initial.evidence.version == 2
                and initial.evidence.company_id == company.company_id
            )
            assert (
                initial.snapshot_id == snapshot_id
                and initial.excerpt == "Exact saved excerpt"
            )
            assert (
                initial.source_category == "A"
                and initial.lineage == "underlying-report"
            )
            assert initial.retrieved_at == now and initial.published_at == now
            assert initial.stage_version is None
            stages = EvidenceStageService(store=store, clock=lambda: now.isoformat())
            command = ConfirmDimensionFactsCommand(
                StageActorContext(owner, True, True),
                evidence_id,
                snapshot_id,
                0,
                DimensionFacts(
                    SourceConfirmation.OFFICIAL, False, False, False, False, 0
                ),
                "Confirmed source",
                "stage-1",
            )
            stages.confirm(command)
            first = facade.get_source(actor, evidence_id)
            assert (
                first.stage_version == 1
                and first.stage == "E1"
                and first.stage_source_id == snapshot_id
            )
            assert len(first.stage_digest) == 64
            assert facade.get_source(actor, evidence_id) == first
            stages.confirm(
                replace(
                    command,
                    expected_version=1,
                    reason="New confirmation",
                    idempotency_key="stage-2",
                )
            )
            second = facade.get_source(actor, evidence_id)
            assert (
                second.stage_version == 2 and second.stage_digest != first.stage_digest
            )
            assert second.snapshot_id == first.snapshot_id
            fact = ValuationSourceFact(
                evidence_id + ":forecast",
                evidence_id,
                2,
                snapshot_id,
                company.company_id,
                "pe",
                "forecast",
                now.date(),
                Decimal(108),
                confirmed_at=now,
                target_date=now.date().replace(year=2027),
            )
            store.save_valuation_facts(evidence_id, (fact,))
            reference, digest = facade.get_fact_binding(
                actor, evidence_id, fact.fact_id
            )
            assert (
                reference.record_type == "valuation_fact"
                and reference.record_id == fact.fact_id
            )
            assert reference.version == 2 and reference.company_id == company.company_id
            assert len(digest) == 64
            assert facade.get_fact_binding(actor, evidence_id, fact.fact_id) == (
                reference,
                digest,
            )
            raise ValueError("rollback-source-test")
    engine.dispose()
