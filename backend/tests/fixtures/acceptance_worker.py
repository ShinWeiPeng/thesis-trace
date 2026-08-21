from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time

from thesis_trace.modules.research.evidence_collection.contracts import FetchedSource
from thesis_trace.modules.research.evidence_collection.service import EvidenceCollector
from thesis_trace.application.flows.anomaly_assessment import AnomalyJobProcessor
from thesis_trace.modules.research import ResearchAnomalyFacade
from thesis_trace.modules.research.anomaly_assessment.service import AnomalyAssessmentService
from thesis_trace.platform.postgres import PostgresEvidenceStore


class FixtureSource:
    def fetch(self, url: str) -> FetchedSource:
        now = datetime.now(timezone.utc).isoformat()
        return FetchedSource(
            canonical_url=url, publisher="acceptance.fixture", content=b"official fixture disclosure",
            retrieved_at=now, published_at=now, observed_at=now, excerpt="official fixture disclosure",
            source_category="A", lineage=url,
        )


class FixtureProvider:
    def analyze(self, request) -> str:
        return json.dumps({
            "schema_version": "anomaly-candidate-v1",
            "direct_supporting_snapshot_ids": [request.sources[0].source_snapshot_id],
            "clue_features": None,
            "has_source_conflict": False,
            "newer_authoritative_refutation": False,
            "price_or_volume_only": False,
            "novel_unsupported_event": False,
        })


class FixtureCritic:
    def criticize(self, _request) -> str:
        return json.dumps({
            "schema_version": "recommendation-critic-v1", "verdict": "PASS",
            "source_available": True, "citation_direct_support": True,
            "subject_matches": True, "time_reasonable": True,
            "invalidation_matches": True, "b_independence": True,
            "no_newer_a_refutation": True,
        })


def main() -> int:
    database_url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    store = PostgresEvidenceStore(lambda: database_url)
    collector = EvidenceCollector(store=store, source_fetcher=FixtureSource())
    anomaly = AnomalyJobProcessor(
        research=ResearchAnomalyFacade(
            AnomalyAssessmentService(
                store=store, clock=lambda: datetime.now(timezone.utc).isoformat()
            )
        ),
        provider=FixtureProvider(),
        critic=FixtureCritic(),
    )
    deadline = time.monotonic() + 60
    collected = 0
    assessed = 0
    while time.monotonic() < deadline:
        if collector.run_once():
            collected += 1
        if anomaly.run_once():
            assessed += 1
        if collected == 2 and assessed == 2:
            return 0
        time.sleep(0.1)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
