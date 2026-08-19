# ALG-0004: C-clue scoring and routing
## Metadata
- Status: proposed
- Owner module: research
- Product feature: Explainable clue triage
- Flow IDs: evidence-evaluation-flow
- Related ADRs: none
- Source paths: planned research policy
- Test and benchmark paths: planned research policy tests
- Supersedes: none
## Problem and observable success
Prioritize unverified clues without treating them as verified evidence.
## Inputs, outputs, units, ranges, and data-quality assumptions
Five critic-validated integer features—timeliness, traceability, specificity, independent corroboration, Thesis/invalidation relevance—each range 0..2. Output score 0..10 and route.
## Constraints and quantitative acceptance thresholds
Exact integer sum; annotated scoring/routing cases must be 100% correct.
## Candidate methods and comparative evidence
Candidates: weighted probabilistic score; fixed equal-weight sum. SPEC selects fixed sum for auditability and calibration-free behavior.
## Selected method and reasons for rejecting alternatives
Sum five validated features; weighted scoring is rejected because no calibration evidence exists.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
`score=sum(features)`. 0..4 save only; 5..7 watchlist/daily summary; 8..10 immediate human review and A/B search. Missing/out-of-range/critic failure means no score and human review, never promotion.
## Parameters, calibration, versioning, and compatibility
Feature rubric and thresholds are policy-versioned; existing results are immutable.
## Time and space complexity and resource budgets
O(1) time and space.
## Errors, degradation, fallback, and forbidden behavior
Never count the score toward Hard quorum or generate hard sell.
## Validation cases and evidence
Golden boundary scores 0,4,5,7,8,10; properties assert sum range and monotonicity for valid feature increases.
## Risks and monitoring
AI feature proposals may drift; track critic rejection and human disagreement.
## Human approval
Pending non-AI owner approval.
