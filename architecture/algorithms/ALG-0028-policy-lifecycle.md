# ALG-0028: Policy release, activation, and re-evaluation
## Metadata
- Status: proposed
- Owner module: application
- Product feature: Versioned deterministic policy governance
- Flow IDs: policy-activation-flow, policy-reevaluation-flow
- Related ADRs: none
- Source paths: planned application policy registry
- Test and benchmark paths: planned policy lifecycle tests
- Supersedes: none
## Problem and observable success
Activate one immutable policy version per family without rewriting historical decisions.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are released versions/build identity, current active version, validation evidence, actor/reason/challenge and optional open-record snapshot; output activation or linked new evaluations.
## Constraints and quantitative acceptance thresholds
Exactly one active version per family; activation is Owner-confirmed high-risk action; rollback activates another released version.
## Candidate methods and comparative evidence
Candidates: mutable runtime rule configuration; immutable build-owned versions with activation log. Immutable versions are selected for reproducibility.
## Selected method and reasons for rejecting alternatives
Use transactional active pointer plus append-only activation event; explicit re-evaluation creates new linked results.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Reject unreleased/unvalidated version or stale current pointer. On confirmation atomically switch pointer and audit old/new/effective time/reason/evidence. New events use active-at-evaluation. Re-evaluation never updates old result; it stores difference and may create a new Action Item.
## Parameters, calibration, versioning, and compatibility
Every policy declares family/version/build/compatibility/evidence digest.
## Time and space complexity and resource budgets
O(1) activation; O(selected records) explicit re-evaluation.
## Errors, degradation, fallback, and forbidden behavior
No edit-in-place, implicit mass recomputation or rollback by destructive data change.
## Validation cases and evidence
Concurrent activation, stale challenge, rollback, historical immutability and linked difference tests.
## Risks and monitoring
Wrong activation affects new work; require evidence preview and audit alerts.
## Human approval
Pending non-AI owner approval.
