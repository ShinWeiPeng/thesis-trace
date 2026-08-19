# ALG-0017: Action-item transitions and deferred wake-up
## Metadata
- Status: proposed
- Owner module: workflow
- Product feature: Action Item lifecycle
- Flow IDs: action-item-transition-flow
- Related ADRs: none
- Source paths: planned workflow state policy
- Test and benchmark paths: planned workflow state tests
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
Deferred requires future `defer_until`; dismissed requires reason. At `server_time>=defer_until`, transition once to pending. Material priority/content change cancels defer. Duplicate idempotency key/version is no-op; terminal later evidence invokes ALG-0015.
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
Pending non-AI owner approval.
