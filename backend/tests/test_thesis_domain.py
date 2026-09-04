from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from thesis_trace.modules.thesis.contracts import (
    CompleteReflectionCommand,
    CreateThesisCommand,
    SaveReflectionDraftCommand,
    SaveOutcomeCommand,
    ThesisActorContext,
    ThesisResearchReference,
    ThesisStatus,
    TransitionThesisCommand,
)
from thesis_trace.modules.thesis.service import ThesisService


NOW = datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc)
ACTOR = ThesisActorContext("owner-1", may_manage_personal_thesis=True)
COMPANY = ThesisResearchReference("company", "company-1", 1, "company-1")


class MemoryThesisStore:
    def __init__(self) -> None:
        self.records = {}
        self.receipts = {}
        self.audit = []

    def get(self, actor_id: str, thesis_id: str):
        record = self.records.get(thesis_id)
        return record if record is not None and record.owner_user_id == actor_id else None

    def list_for_company(self, actor_id: str, company_id: str):
        return [value for value in self.records.values() if value.owner_user_id == actor_id and value.company_id == company_id]

    def commit(self, *, actor_id, idempotency_key, command_digest, expected_version, record, action, reason):
        receipt_key = (actor_id, idempotency_key)
        receipt = self.receipts.get(receipt_key)
        if receipt is not None:
            digest, thesis_id = receipt
            if digest != command_digest:
                raise ValueError("idempotency_conflict")
            return self.records[thesis_id]
        current = self.records.get(record.thesis_id)
        current_version = 0 if current is None else current.version
        if current_version != expected_version:
            raise ValueError("version_conflict")
        self.records[record.thesis_id] = record
        self.receipts[receipt_key] = (command_digest, record.thesis_id)
        self.audit.append((record.thesis_id, record.version, action, reason))
        return record


def create(service: ThesisService):
    return service.create(
        CreateThesisCommand(
            actor=ACTOR,
            company=COMPANY,
            title="AI 伺服器需求持續成長",
            narrative="先進封裝與伺服器產品組合改善將支持長期現金流。",
            invalidation_conditions=("伺服器營收連續兩季衰退",),
            evidence_refs=(),
            reason="建立研究假設",
            idempotency_key="create-1",
        ),
        now=NOW,
    )


def test_personal_thesis_lifecycle_preserves_prior_cycle_learning() -> None:
    store = MemoryThesisStore()
    service = ThesisService(store, id_factory=lambda: "thesis-1")

    draft = create(service)
    assert (draft.status, draft.version, draft.cycle) == (ThesisStatus.DRAFT, 1, 1)

    active = service.transition(
        TransitionThesisCommand(ACTOR, draft.thesis_id, 1, ThesisStatus.ACTIVE, "發布假設", "activate-1"), now=NOW
    )
    invalidated = service.transition(
        TransitionThesisCommand(ACTOR, active.thesis_id, 2, ThesisStatus.INVALIDATED, "硬失效條件成立", "invalidate-1", "challenge-1"), now=NOW
    )
    assert invalidated.reflection_pending is True

    with pytest.raises(ValueError, match="close_prerequisites_missing"):
        service.transition(
            TransitionThesisCommand(ACTOR, invalidated.thesis_id, 3, ThesisStatus.CLOSED, "結束研究", "close-early", "challenge-2"), now=NOW
        )

    with_outcome = service.save_outcome(
        SaveOutcomeCommand(ACTOR, invalidated.thesis_id, 3, NOW, "需求下降，原假設不成立。", (), "記錄結果", "outcome-1"), now=NOW
    )
    reflected = service.complete_reflection(
        CompleteReflectionCommand(
            ACTOR,
            with_outcome.thesis_id,
            4,
            "伺服器需求會持續成長",
            "過度依賴單一管理層指引",
            "缺少終端客戶庫存資料",
            "加入跨來源庫存與訂單驗證",
            "完成反思",
            "reflection-1",
        ),
        now=NOW,
    )
    closed = service.transition(
        TransitionThesisCommand(ACTOR, reflected.thesis_id, 5, ThesisStatus.CLOSED, "閉環完成", "close-1", "challenge-3"), now=NOW
    )
    reopened = service.transition(
        TransitionThesisCommand(ACTOR, closed.thesis_id, 6, ThesisStatus.ACTIVE, "新證據支持重啟", "reopen-1", "challenge-4"), now=NOW
    )

    assert (reopened.status, reopened.cycle, reopened.version) == (ThesisStatus.ACTIVE, 2, 7)
    assert reopened.outcome is None
    assert reopened.reflection is None
    assert reopened.reflection_pending is False
    assert len(store.audit) == 7


def test_personal_scope_and_idempotency_fail_closed() -> None:
    store = MemoryThesisStore()
    service = ThesisService(store, id_factory=lambda: "thesis-1")
    draft = create(service)

    replay = create(service)
    assert replay == draft

    other = replace(ACTOR, actor_id="learner-2")
    with pytest.raises(LookupError, match="resource_unavailable"):
        service.get(other, draft.thesis_id)
    with pytest.raises(PermissionError, match="resource_unavailable"):
        service.transition(
            TransitionThesisCommand(other, draft.thesis_id, 1, ThesisStatus.ACTIVE, "嘗試修改", "cross-owner"), now=NOW
        )


def test_reflection_autosave_returns_a_complete_reloadable_draft_snapshot() -> None:
    store = MemoryThesisStore()
    service = ThesisService(store, id_factory=lambda: "thesis-1")
    draft = create(service)

    first = service.save_reflection_draft(
        SaveReflectionDraftCommand(
            ACTOR, draft.thesis_id, 0, "original_assumption", "原始假設", "draft-1"
        ),
        now=NOW,
    )
    second = service.save_reflection_draft(
        SaveReflectionDraftCommand(
            ACTOR, draft.thesis_id, 1, "judgment_errors", "判斷錯誤", "draft-2"
        ),
        now=NOW,
    )

    assert first.reflection_draft is not None
    assert second.reflection_draft is not None
    assert second.reflection_draft.revision == 2
    assert second.reflection_draft.original_assumption == "原始假設"
    assert second.reflection_draft.judgment_errors == "判斷錯誤"
    assert second.reflection_draft.missing_evidence == ""
    assert second.reflection_draft.improvement == ""

    with pytest.raises(ValueError, match="idempotency_conflict"):
        service.create(
            replace(
                CreateThesisCommand(ACTOR, COMPANY, "不同標題", "不同內容", ("不同條件",), (), "建立", "create-1"),
            ),
            now=NOW,
        )
