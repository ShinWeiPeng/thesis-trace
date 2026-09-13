from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionItemStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DEFERRED = "deferred"
    COMPLETED = "completed"
    DISMISSED = "dismissed"


class ActionPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class ActionItemType(str, Enum):
    ANOMALY_REVIEW = "anomaly_review"
    RECOMMENDATION_DECISION = "recommendation_decision"


@dataclass(frozen=True, slots=True)
class WorkflowActorContext:
    actor_id: str
    may_create: bool
    may_read: bool
    may_transition: bool


@dataclass(frozen=True, slots=True)
class ActionSourceRef:
    source_domain: str
    source_record_id: str
    source_version: int
    source_owner_id: str
    company_id: str
    company_ticker: str
    company_name: str
    trigger_kind: str
    required_handling: str


@dataclass(frozen=True, slots=True)
class CreateActionItemCommand:
    actor: WorkflowActorContext
    source: ActionSourceRef
    reason: str
    due_at: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class TransitionActionItemCommand:
    actor: WorkflowActorContext
    item_id: str
    expected_version: int
    target_status: ActionItemStatus
    reason: str
    defer_until: str | None
    idempotency_key: str
    server_time: str
    underlying_resolved: bool


@dataclass(frozen=True, slots=True)
class ActionPriorityEvaluation:
    system_priority: ActionPriority
    effective_priority: ActionPriority
    safety_floor: ActionPriority | None
    safety_locked: bool
    rule_ids: tuple[str, ...]
    policy_version: str
    reason: str


@dataclass(frozen=True, slots=True)
class ActionItem:
    item_id: str
    version: int
    item_type: ActionItemType
    source_domain: str
    source_record_id: str
    source_version: int
    company_id: str
    company_ticker: str
    company_name: str
    assignee_user_id: str
    reason: str
    status: ActionItemStatus
    priority: ActionPriorityEvaluation
    created_at: str
    updated_at: str
    due_at: str | None
    defer_until: str | None
    recurrence_of: str | None
    allowed_transitions: tuple[ActionItemStatus, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionInboxSummary:
    urgent: int
    due_today: int
    deferred: int
    all_open: int


@dataclass(frozen=True, slots=True)
class ActionInboxQuery:
    actor: WorkflowActorContext
    search: str | None = None
    company_id: str | None = None
    item_type: str | None = None
    status: str | None = None
    priority: str | None = None
    created_from: str | None = None
    created_to: str | None = None
    due_from: str | None = None
    due_to: str | None = None
    open_only: bool = True
    sort: str = "effective_priority"
    direction: str = "desc"
    page_size: int = 25
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ActionInboxPage:
    summary: ActionInboxSummary
    total_count: int
    items: tuple[ActionItem, ...]
    next_cursor: str | None
    as_of: str
