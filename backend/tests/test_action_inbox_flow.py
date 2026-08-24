from __future__ import annotations

from dataclasses import replace

import pytest

from thesis_trace.application.flows.anomaly_assessment import (
    ActionInboxFlow,
    CreateAnomalyReviewActionRequest,
)
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research import (
    ResearchAnomalyGate,
    ResearchAnomalyResult,
    ResearchAnomalyTrace,
)


class ResearchStub:
    def __init__(self, result: ResearchAnomalyResult) -> None:
        self.result = result

    def get(self, _actor, _assessment_id: str) -> ResearchAnomalyResult:
        return self.result


class WorkflowSpy:
    def __init__(self) -> None:
        self.command = None

    def create(self, command):
        self.command = command
        from thesis_trace.modules.workflow.contracts import (
            ActionItem,
            ActionItemStatus,
            ActionItemType,
            ActionPriority,
            ActionPriorityEvaluation,
        )
        return ActionItem(
            "item-1", 1, ActionItemType.ANOMALY_REVIEW, command.source.source_domain,
            command.source.source_record_id, command.source.source_version,
            command.source.company_id, command.source.company_ticker, command.source.company_name,
            command.source.source_owner_id, command.reason, ActionItemStatus.PENDING,
            ActionPriorityEvaluation(ActionPriority.HIGH, ActionPriority.HIGH, None, False,
                                     ("workflow.shadow-anomaly-review-v1",), "action-priority-v1", "Review"),
            "2026-08-24T00:00:00+00:00", "2026-08-24T00:00:00+00:00", None, None, None,
            (ActionItemStatus.IN_PROGRESS,),
        )


def anomaly() -> ResearchAnomalyResult:
    return ResearchAnomalyResult(
        assessment_id="assessment-1", version=2, evidence_id="evidence-1", evidence_version=3,
        source_snapshot_ids=("snapshot-1",), status="succeeded",
        requested_at="2026-08-24T00:00:00+00:00",
        trace=ResearchAnomalyTrace("would_be_hard", ("A",), None, None,
                                   (ResearchAnomalyGate("traceability", True, "passed"),), "policy-v1"),
        failure_code=None, actor_id="owner-1", company_id="company-1",
        company_ticker="TT", company_name="Thesis Trace",
    )


def test_action_flow_resolves_server_authority_from_exact_anomaly() -> None:
    workflow = WorkflowSpy()
    flow = ActionInboxFlow(research=ResearchStub(anomaly()), workflow=workflow, clock=lambda: "2026-08-24T01:00:00+00:00")
    actor = AuthenticatedActor("owner-1", Role.OWNER, 1)

    result = flow.create(actor, CreateAnomalyReviewActionRequest(
        "assessment-1", 2, "Review the anomaly", None, "create-1"
    ))

    assert result.item_id == "item-1"
    assert workflow.command.source.source_owner_id == "owner-1"
    assert workflow.command.source.company_ticker == "TT"
    assert workflow.command.source.required_handling == "would_be_hard"


def test_action_flow_rejects_stale_non_actionable_or_wrong_owner_sources() -> None:
    actor = AuthenticatedActor("owner-1", Role.OWNER, 1)
    request = CreateAnomalyReviewActionRequest("assessment-1", 2, "Review", None, "create-1")
    variants = (
        replace(anomaly(), version=3),
        replace(anomaly(), status="pending"),
        replace(anomaly(), actor_id="owner-2"),
        replace(anomaly(), trace=replace(anomaly().trace, anomaly_class="soft", clue_route="save_only")),
    )
    for source in variants:
        with pytest.raises((LookupError, PermissionError, ValueError)):
            ActionInboxFlow(
                research=ResearchStub(source), workflow=WorkflowSpy(),
                clock=lambda: "2026-08-24T01:00:00+00:00",
            ).create(actor, request)
