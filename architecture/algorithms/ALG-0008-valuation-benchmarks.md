# ALG-0008: Valuation benchmark calculation
## Metadata
- Status: proposed
- Owner module: portfolio
- Product feature: Company-history and peer-group PE/PB candidates
- Flow IDs: valuation-publication-flow
- Related ADRs: none
- Source paths: planned portfolio valuation policy
- Test and benchmark paths: planned valuation tests
- Supersedes: none
## Problem and observable success
Produce separate reproducible company-history and peer-group distributions without hidden weighting.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are method, dated monthly samples, EPS/BVPS, peer snapshot and exclusions. Outputs are valid samples, exclusions, median, P75 and abstention reason.
## Constraints and quantitative acceptance thresholds
History candidate requires at least three years; preferred baseline uses at least five years. Peer group is 5..12 confirmed Taiwan-listed companies and requires at least five valid peers.
## Candidate methods and comparative evidence
Candidates: mean/standard deviation; median/P75. SPEC selects median/P75 for robustness and explicit optimistic comparison.
## Selected method and reasons for rejecting alternatives
Filter invalid/nonpositive denominators, sort decimal samples, compute median and nearest-rank/interpolated P75 as a versioned convention; never merge history and peers.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
PE excludes EPS<=0; PB excludes BVPS<=0. Target company and stale/incomplete peers are excluded. Fewer than required samples abstains. Even sample median is arithmetic midpoint; P75 convention must be fixed in policy and golden vectors.
## Parameters, calibration, versioning, and compatibility
Quantile convention, valid-period rules, method and peer snapshot are versioned.
## Time and space complexity and resource budgets
O(n log n) time, O(n) space for sorted samples.
## Errors, degradation, fallback, and forbidden behavior
Missing source or validity metadata abstains; do not impute, automatically weight, or combine results.
## Validation cases and evidence
Golden odd/even medians and P75 boundaries; properties cover ordering invariance and exclusion correctness.
## Risks and monitoring
Quantile convention ambiguity; publish it explicitly and monitor abstention reasons.
## Human approval
Pending non-AI owner approval.
