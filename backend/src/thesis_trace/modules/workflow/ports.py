from __future__ import annotations

from typing import Protocol

from .contracts import (
    ActionInboxPage,
    ActionInboxQuery,
    ActionItem,
    ActionItemStatus,
)


class ActionItemStorePort(Protocol):
    def create(
        self,
        item: ActionItem,
        *,
        fingerprint: str,
        idempotency_key: str,
        command_digest: str,
    ) -> ActionItem: ...

    def get(self, actor_id: str, item_id: str) -> ActionItem: ...

    def query(self, query: ActionInboxQuery) -> ActionInboxPage: ...

    def transition(
        self,
        current: ActionItem,
        *,
        target_status: ActionItemStatus,
        reason: str,
        defer_until: str | None,
        idempotency_key: str,
        command_digest: str,
        occurred_at: str,
    ) -> ActionItem: ...
