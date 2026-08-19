# ALG-0005: Hard and Soft anomaly policy
## Metadata
- Status: proposed
- Owner module: research
- Product feature: Anomaly determination
- Flow IDs: anomaly-evaluation-flow
- Related ADRs: none
- Source paths: planned research policy
- Test and benchmark paths: planned anomaly qualification tests
- Supersedes: none
## Problem and observable success
Permit Hard only for predeclared invalidations with strong independent evidence and a passing critic.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are Thesis invalidation condition, classified sources, lineage, conflicts and critic result; output Hard or Soft with trace.
## Constraints and quantitative acceptance thresholds
Qualification requires 40/40 Hard positives and zero Hard among 60 negatives, then a false-Hard-free 30-day shadow.
## Candidate methods and comparative evidence
Candidates: model classification; deterministic quorum after critic validation. The latter is selected for fail-closed safety.
## Selected method and reasons for rejecting alternatives
Require condition match plus one direct A or two independent B and structured critic PASS; model-only classification is rejected.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Hard iff predeclared condition matches AND (`direct_A>=1` OR `independent_B_components>=2`) AND every critic check passes AND no newer A directly refutes. Otherwise Soft. Price/volume-only and novel unsupported events are Soft.
## Parameters, calibration, versioning, and compatibility
Policy, prompt, critic schema and dataset versions bind every result; material changes invalidate qualification.
## Time and space complexity and resource budgets
O(sources+lineage edges); critic latency is bounded by job timeout.
## Errors, degradation, fallback, and forbidden behavior
Any missing field, timeout, conflict, schema error or uncertain independence degrades to Soft. Never trade automatically.
## Validation cases and evidence
Versioned 100-case suite, property tests for evidence-order invariance, fault injection and production shadow evidence.
## Risks and monitoring
False Hard is the dominant risk; any occurrence resets shadow qualification.
## Human approval
Pending non-AI owner approval.
