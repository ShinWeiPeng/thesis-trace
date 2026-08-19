from __future__ import annotations

from datetime import datetime, timezone
import os
import time

from thesis_trace.modules.research.evidence_collection.contracts import FetchedSource
from thesis_trace.modules.research.evidence_collection.service import EvidenceCollector
from thesis_trace.platform.postgres import PostgresEvidenceStore


class FixtureSource:
    def fetch(self, url: str) -> FetchedSource:
        now = datetime.now(timezone.utc).isoformat()
        return FetchedSource(
            canonical_url=url, publisher="acceptance.fixture", content=b"official fixture disclosure",
            retrieved_at=now, published_at=now, observed_at=now, excerpt="official fixture disclosure",
            source_category="A", lineage=url,
        )


def main() -> int:
    database_url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    collector = EvidenceCollector(store=PostgresEvidenceStore(lambda: database_url), source_fetcher=FixtureSource())
    deadline = time.monotonic() + 60
    processed = 0
    while time.monotonic() < deadline:
        if collector.run_once():
            processed += 1
            if processed == 2:
                return 0
        time.sleep(0.1)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
