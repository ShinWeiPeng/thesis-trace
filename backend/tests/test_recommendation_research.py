from datetime import datetime, timezone
from dataclasses import replace

import pytest

from thesis_trace.modules.research import (
    ResearchActorContext,
    ResearchRecommendationFacade,
    ResearchRecommendationSource,
    ResearchRecordReference,
)


def source():
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    return ResearchRecommendationSource(
        ResearchRecordReference("evidence", "evidence-1", 2, "2330"),
        "snapshot-1",
        "https://example.test/report",
        "Publisher",
        "Necessary excerpt",
        "A",
        "report-1",
        now,
        None,
        now,
        None,
        None,
        None,
        None,
    )


class Query:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def get_recommendation_source(self, evidence_id):
        self.calls += 1
        return self.value


def test_research_parent_exposes_immutable_source_without_an_e_stage_threshold():
    expected = source()
    facade = ResearchRecommendationFacade(Query(expected))
    result = facade.get_source(ResearchActorContext("owner", True, True), "evidence-1")
    assert result == expected
    assert result.stage is None
    assert result.source_category == "A" and result.lineage == "report-1"


@pytest.mark.parametrize(
    "value",
    [
        None,
        replace(
            source(), evidence=ResearchRecordReference("evidence", "another", 2, "2330")
        ),
    ],
)
def test_missing_or_mismatched_source_is_unavailable(value):
    with pytest.raises(LookupError, match="resource_unavailable"):
        ResearchRecommendationFacade(Query(value)).get_source(
            ResearchActorContext("owner", True, True), "evidence-1"
        )


def test_read_capability_is_checked_before_store_access():
    query = Query(source())
    with pytest.raises(PermissionError, match="resource_unavailable"):
        ResearchRecommendationFacade(query).get_source(
            ResearchActorContext("owner", False, False), "evidence-1"
        )
    assert query.calls == 0
