# ALG-0017: Action-item transitions and deferred wake-up
## Metadata
- Status: accepted
- Owner module: workflow
- Product feature: Action Item lifecycle
- Flow IDs: action-item-transition-flow
- Related ADRs: ADR-0006
- Source paths: `backend/src/thesis_trace/modules/workflow/service.py`, `backend/src/thesis_trace/adapters/postgres_workflow/adapter.py`
- Test and benchmark paths: `backend/tests/test_workflow_domain.py`, `backend/tests/test_workflow_postgres.py`
- Supersedes: none
## Problem and observable success
Validate state changes, wake deferred work and preserve terminal history.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are current state/version, safety lock, server time, defer time, material source change and command; output transition/event or rejection.
## Constraints and quantitative acceptance thresholds
Safety-locked items permit pending/in_progress and verified completed only; terminal states never reopen.
## Candidate methods and comparative evidence
Candidates: scheduled status mutation; explicit state machine plus idempotent wake command. The latter is selected for retries/audit.
## Selected method and reasons for rejecting alternatives
Pure transition table validates command; a durable wake job changes deferred to pending at due time or immediately on material escalation.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
For non-safety items the v1 transition table is:

| From | Allowed target states |
| --- | --- |
| `pending` | `in_progress`, `deferred`, `completed`, `dismissed` |
| `in_progress` | `pending`, `deferred`, `completed`, `dismissed` |
| `deferred` | `pending`, `in_progress`, `completed`, `dismissed` |
| `completed` | none |
| `dismissed` | none |

Safety-locked items allow only `pending -> in_progress`, `in_progress -> pending`, and Server-verified `pending|in_progress -> completed`; they reject defer, dismiss and unverified complete. Deferred requires `defer_until > server_time`. Dismissed and completed require a nonblank reason. At `server_time>=defer_until`, an idempotent Server wake command transitions once to pending. Material priority/content change cancels defer. A duplicate idempotency key with the same expected version/command returns the committed result; changed retry data or a stale version rejects. Later evidence after a terminal state invokes ALG-0015 and never reopens the item.
## Parameters, calibration, versioning, and compatibility
Transition policy/server-time semantics are versioned.
## Time and space complexity and resource budgets
O(1) plus indexed due-item claim.
## Errors, degradation, fallback, and forbidden behavior
Stale version, unauthorized actor or unsafe defer/dismiss/complete rejects atomically.
## Validation cases and evidence
Full transition matrix, due-time boundaries, retry/concurrency, escalation and terminal invariants.
## Risks and monitoring
Worker delay can postpone wake-up; monitor oldest due deferred item.
## Human approval
- Approver: project owner
- Approval date: 2026-08-24
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
