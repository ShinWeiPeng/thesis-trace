from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from thesis_trace.application.contracts import ThesisLifecycleFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research.evidence_intake.contracts import CompanyRecord, EvidenceRecord, EvidenceStatus
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.modules.thesis.contracts import ThesisActorContext, TransitionThesisCommand
from test_thesis_domain import MemoryThesisStore


NOW = datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc)


class ResearchStub:
    def get_company(self, company_id: str):
        return CompanyRecord("company-1", "TT", "Thesis Trace", 2) if company_id == "company-1" else None

    def get_record(self, evidence_id: str):
        if evidence_id != "evidence-1":
            return None
        return EvidenceRecord("evidence-1", 3, "company-1", 2, "https://example.com", EvidenceStatus.SUCCEEDED)


def flow() -> ThesisLifecycleFlow:
    return ThesisLifecycleFlow(
        ThesisService(MemoryThesisStore(), id_factory=lambda: "thesis-1"),
        ResearchStub(),
        clock=lambda: NOW,
    )


def test_flow_maps_authenticated_actor_and_validates_research_versions() -> None:
    actor = AuthenticatedActor("owner-1", Role.OWNER, 1)
    subject = flow()
    created = subject.create(actor, {
        "company_id": "company-1",
        "company_version": 2,
        "title": "AI server demand",
        "narrative": "Demand supports durable cash flow.",
        "invalidation_conditions": ["Server revenue declines"],
        "evidence_refs": [{"record_id": "evidence-1", "version": 3}],
        "reason": "Create thesis",
        "idempotency_key": "create-1",
    })

    assert created["thesis_id"] == "thesis-1"
    assert created["status"] == "draft"
    assert subject.list_for_company(actor, "company-1") == [created]

    with pytest.raises(ValueError, match="research_version_conflict"):
        subject.create(actor, {
            "company_id": "company-1", "company_version": 1,
            "title": "Stale", "narrative": "Stale", "invalidation_conditions": ["Stale"],
            "evidence_refs": [], "reason": "Stale", "idempotency_key": "stale",
        })

    with pytest.raises(ValueError, match="research_version_conflict"):
        subject.create(actor, {
            "company_id": "company-1", "company_version": 2,
            "title": "Stale evidence", "narrative": "Stale", "invalidation_conditions": ["Stale"],
            "evidence_refs": [{"record_id": "evidence-1", "version": 2}],
            "reason": "Stale", "idempotency_key": "stale-evidence",
        })


def test_admin_has_no_personal_thesis_projection() -> None:
    with pytest.raises(PermissionError, match="resource_unavailable"):
        flow().list_for_company(AuthenticatedActor("admin-1", Role.ADMIN, 1), "company-1")


def test_consequential_transition_uses_confirmed_transaction_port() -> None:
    actor = AuthenticatedActor("owner-1", Role.OWNER, 1)
    service = ThesisService(MemoryThesisStore(), id_factory=lambda: "thesis-1")

    class Confirmations:
        def preview(self, *_args):
            return "challenge-token", SimpleNamespace(expires_at=NOW)

    class ConfirmedTransitions:
        calls = 0

        def execute(self, **values):
            self.calls += 1
            assert values["challenge_token"] == "challenge-token"
            return service.transition(TransitionThesisCommand(
                ThesisActorContext(actor.actor_id, True), values["thesis_id"], values["expected_version"],
                values["target"], values["reason"], values["idempotency_key"], "challenge-1",
            ), now=values["now"])

    coordinator = ConfirmedTransitions()
    subject = ThesisLifecycleFlow(
        service, ResearchStub(), confirmations=Confirmations(),
        confirmed_transitions=coordinator, clock=lambda: NOW,
    )
    draft = subject.create(actor, {
        "company_id": "company-1", "company_version": 2, "title": "T", "narrative": "N",
        "invalidation_conditions": ["C"], "evidence_refs": [], "reason": "Create", "idempotency_key": "create",
    })
    active = subject.transition(actor, draft["thesis_id"], {
        "expected_version": 1, "target_status": "active", "reason": "Activate", "idempotency_key": "activate",
    })
    preview = subject.preview_transition(actor, active["thesis_id"], {
        "expected_version": 2, "target_status": "invalidated",
    })
    invalidated = subject.transition(actor, active["thesis_id"], {
        "expected_version": 2, "target_status": "invalidated", "reason": "Condition met",
        "idempotency_key": "invalidate", "challenge_token": preview["challenge_token"],
    })

    assert invalidated["status"] == "invalidated"
    assert coordinator.calls == 1
