from __future__ import annotations

from typing import Protocol

from thesis_trace.modules.thesis.contracts import ThesisRecord


class ThesisStorePort(Protocol):
    def get(self, actor_id: str, thesis_id: str) -> ThesisRecord | None: ...

    def list_for_company(self, actor_id: str, company_id: str) -> list[ThesisRecord]: ...

    def commit(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        command_digest: str,
        expected_version: int,
        record: ThesisRecord,
        action: str,
        reason: str,
    ) -> ThesisRecord: ...
