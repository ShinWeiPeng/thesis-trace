# ALG-0004: C-clue scoring and routing
## Metadata
- Status: accepted
- Owner module: anomaly_assessment
- Product feature: Explainable clue triage
- Flow IDs: evidence-evaluation-flow
- Related ADRs: ADR-0005
- Source paths: `backend/src/thesis_trace/modules/research/anomaly_assessment/policy.py`
- Test and benchmark paths: `backend/tests/test_anomaly_policy.py`, `backend/tests/fixtures/anomaly-qualification-v1.json`
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
- Approver: project owner
- Approval date: 2026-08-21
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
