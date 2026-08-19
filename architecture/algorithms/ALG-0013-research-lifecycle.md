# ALG-0013: Research lifecycle state machines
## Metadata
- Status: proposed
- Owner module: thesis
- Product feature: Thesis, Decision, Trade, Outcome and Reflection lifecycle
- Flow IDs: thesis-lifecycle-flow
- Related ADRs: none
- Source paths: planned thesis policy
- Test and benchmark paths: planned thesis state tests
- Supersedes: none
## Problem and observable success
Allow only auditable legal transitions while preserving immutable decisions and history.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are current version/state, command, actor, reason and linked record versions; output is new current state plus append-only event or rejection.
## Constraints and quantitative acceptance thresholds
Thesis states are draft/active/paused/invalidated/closed; invalidation is immediate; close requires Outcome and Reflection.
## Candidate methods and comparative evidence
Candidates: free status updates; explicit transition tables. Tables are selected for testable invariants.
## Selected method and reasons for rejecting alternatives
Use per-aggregate pure transition functions and optimistic version checks; immutable records get replacement/correction links rather than update.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Validate actor, expected version, source prerequisites and transition table. Invalidation overrides pending Reflection and sets reflection-pending; close rejects until Outcome/Reflection exist. One transaction writes current row/version, history and outbox.
## Parameters, calibration, versioning, and compatibility
Transition policy is versioned; historical events retain old semantics.
## Time and space complexity and resource budgets
O(1) per command excluding linked validation.
## Errors, degradation, fallback, and forbidden behavior
Stale/illegal commands reject without partial writes; never overwrite Recommendation, Decision, Trade or history.
## Validation cases and evidence
Transition matrix, property tests for terminal/immutable behavior, concurrency and transaction rollback integration tests.
## Risks and monitoring
Cross-aggregate prerequisites may race; monitor version conflicts.
## Human approval
Pending non-AI owner approval.
