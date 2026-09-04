from __future__ import annotations

from typing import Protocol

from thesis_trace.modules.portfolio.contracts import CanonicalCsvPreview, OfficialSecuritySnapshot, PortfolioRecord


class BrokerStatementParserPort(Protocol):
    def preview(self, content: str) -> CanonicalCsvPreview: ...


class PortfolioStorePort(Protocol):
    def get(self, actor_id: str) -> PortfolioRecord | None: ...

    def get_official_security(self, actor_id: str, security_id: str) -> OfficialSecuritySnapshot | None: ...

    def commit(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        command_digest: str,
        expected_version: int,
        record: PortfolioRecord,
        action: str,
        reason: str,
    ) -> PortfolioRecord: ...
