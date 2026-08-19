# ALG-0031: Claude failover qualification gate
## Metadata
- Status: proposed
- Owner module: recommendation
- Product feature: Claude backup-provider enablement
- Flow IDs: provider-qualification-flow
- Related ADRs: none
- Source paths: planned recommendation qualification policy
- Test and benchmark paths: versioned provider dataset and shadow evidence
- Supersedes: none
## Problem and observable success
Keep Claude out of production failover until offline and consecutive shadow results meet decision-critical safety thresholds.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are 30 Owner-annotated cases, model/prompt/policy/schema/critic versions, primary/Claude results for shadow snapshots and Owner approval; output qualified/not-qualified.
## Constraints and quantitative acceptance thresholds
At least 29/30 decision-critical agreement; zero safety-critical discrepancy, false Hard, bad citation, unsupported claim, schema/policy violation or missed abstain; then 10 consecutive production shadow tasks with zero major/safety/citation/schema/critic failure.
## Candidate methods and comparative evidence
Candidates: provider availability check; stratified offline plus consecutive shadow comparison. The latter is selected because availability says nothing about semantic safety.
## Selected method and reasons for rejecting alternatives
Run immutable identical snapshots independently, compare structured critical fields, and keep Claude outputs non-authoritative until approval.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Offline passes only when all zero-tolerance gates and >=29 agreement pass. Shadow task counts only with identical input/prompt/policy/schema; any failure resets consecutive count to zero. Material version change invalidates approval and both gates. Qualification requires immutable Owner approval record.
## Parameters, calibration, versioning, and compatibility
Dataset, comparator/major-discrepancy rubric and all provider artifacts are versioned and hashed.
## Time and space complexity and resource budgets
O(30 case outputs + 10 shadow outputs), bounded by snapshot limits.
## Errors, degradation, fallback, and forbidden behavior
Missing comparison, partial provider output or unapproved version is not qualified; shadow never changes production state.
## Validation cases and evidence
Meta-tests cover 28/29/30 boundaries, every zero-tolerance fault, consecutive reset and version invalidation.
## Risks and monitoring
Small datasets may miss drift; post-qualification validation still applies to every output.
## Human approval
Pending non-AI owner approval.
