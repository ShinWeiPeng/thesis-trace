# ALG-0002: E0-E6 sequential-gate derivation
## Metadata
- Status: proposed
- Owner module: research
- Product feature: Evidence maturity stage
- Flow IDs: evidence-evaluation-flow
- Related ADRs: none
- Source paths: planned research policy
- Test and benchmark paths: planned research policy tests
- Supersedes: none
## Problem and observable success
Derive a reproducible summary stage without allowing AI to set it.
## Inputs, outputs, units, ranges, and data-quality assumptions
Input is an immutable source snapshot and five dimension facts; output is E0-E6, gate trace and abstain/error reason.
## Constraints and quantitative acceptance thresholds
Every selected stage and prerequisite must be supported; correction, withdrawal, or invalidation recomputes from snapshots and may lower the stage.
## Candidate methods and comparative evidence
Candidates were weighted scoring and sequential gates. Confirmed SPEC selects sequential gates for explainability and missing-evidence safety.
## Selected method and reasons for rejecting alternatives
Evaluate ordered gates E1 through E6, stopping before the first unmet gate; weighted scoring is rejected because it can mask missing prerequisites.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Start E0. E1 requires official or two independent credible sources; E2 product/technology/capacity/partnership; E3 contract/order/customer/shipment; E4 identifiable revenue; E5 identifiable profit/cash flow; E6 E5-class impact for at least two consecutive quarters. A higher-stage fact may jump only when every prior predicate is true. Conflicts abstain and emit trace.
## Parameters, calibration, versioning, and compatibility
Predicates and policy version are immutable inputs; historical evaluations retain their version.
## Time and space complexity and resource budgets
O(number of facts plus lineage edges), with bounded trace per evaluation.
## Errors, degradation, fallback, and forbidden behavior
Missing, stale, conflicting, or inaccessible evidence cannot satisfy a gate. AI candidates never directly mutate stage.
## Validation cases and evidence
Golden vectors cover each boundary, jump, downgrade and conflict; properties include no stage above the first failed gate and deterministic permutation invariance.
## Risks and monitoring
Incorrect fact classification can contaminate gates; monitor abstentions and post-correction downgrades.
## Human approval
Pending non-AI owner approval.
