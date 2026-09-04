# ALG-0008: Valuation benchmark calculation
## Metadata
- Status: accepted
- Owner module: thesis_domain
- Product feature: Company-history and peer-group PE/PB candidates
- Flow IDs: owner_valuation_publication
- Related ADRs: ADR-0008
- Source paths: planned `backend/src/thesis_trace/modules/thesis/valuation.py`
- Test and benchmark paths: planned `backend/tests/test_valuation_policy.py`
- Supersedes: none
## Problem and observable success
Produce separate, source-bound and reproducible company-history and peer-group distributions without hidden weighting. The same ordered Decimal inputs and policy version yield the same exclusions, median, P75, coverage label and trace.
## Inputs, outputs, units, ranges, and data-quality assumptions
Input is PE or PB, dated monthly target-company samples, a versioned 5–12-member Taiwan-listed peer selection, each member's ratio/source/validity facts, and policy version. Ratios use Decimal. Output contains sorted valid samples, exclusions with stable reason codes, median, P75, coverage, sources and trace.
## Constraints and quantitative acceptance thresholds
PE excludes EPS `<= 0`; PB excludes BVPS `<= 0`. Company history below 36 valid monthly samples abstains; 36–59 yields median and P75 labeled `limited_history`; 60 or more yields `standard_history`. Peer selection contains 5–12 unique confirmed Taiwan-listed companies, excludes the target, and requires five valid same-method peers after filtering. The two populations never merge.
## Candidate methods and comparative evidence
Mean/standard deviation is outlier-sensitive. Median plus P75 is required. Nearest-rank creates sample-count jumps; DEC-101 selects inclusive linear interpolation.
## Selected method and reasons for rejecting alternatives
Filter deterministically, sort Decimal samples, calculate median and inclusive-linear P75, and preserve coverage plus every exclusion. Never impute, weight or merge.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
For sorted `x[1..n]`, odd median is the middle item and even median is the arithmetic midpoint. P75 uses one-based `h = 1 + (n - 1) * 0.75`; integer `h` selects that item, otherwise interpolate `x[floor(h)] + frac(h) * (x[ceil(h)] - x[floor(h)])`. Tied values use stable sample identity only for trace ordering. Invalid, missing, stale, target-company, duplicate and method-mismatch inputs have distinct exclusion codes.
## Parameters, calibration, versioning, and compatibility
Bind `valuation-benchmark-v1`, `inclusive-linear-p75-v1`, method, coverage thresholds, peer snapshot and source versions. Historical outputs are immutable.
## Time and space complexity and resource budgets
`O(n log n)` time and `O(n)` space; no numeric performance claim.
## Errors, degradation, fallback, and forbidden behavior
Missing provenance, invalid Decimal, insufficient samples or unresolved peer identity abstains. Do not impute, use float, hide exclusions, auto-select a source or combine populations.
## Validation cases and evidence
Golden vectors cover medians, 5/12 peers, interpolation and duplicates. Boundaries cover 35/36/59/60 samples and 4/5/12/13 peers. Properties cover order invariance and exclusion correctness. `pytest backend/tests/test_valuation_policy.py -q` passes only when exact Decimal values, labels, exclusions and traces match.
## Risks and monitoring
Monitor abstention, limited-history use and exclusion reason counts without logging private valuation inputs.
## Human approval
- Approver: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
