# ALG-0012: DCA multiplier selection
## Metadata
- Status: proposed
- Owner module: portfolio
- Product feature: Risk-constrained DCA sizing
- Flow IDs: recommendation-publication-flow
- Related ADRs: none
- Source paths: planned portfolio risk policy
- Test and benchmark paths: planned portfolio risk tests
- Supersedes: none
## Problem and observable success
Choose the highest permitted DCA multiplier that fits cash and exposure caps.
## Inputs, outputs, units, ranges, and data-quality assumptions
Input is base amount, immutable portfolio snapshot and raw suggestion; output is one of 1.5x,1x,0.5x,0x with trace.
## Constraints and quantitative acceptance thresholds
Never exceed investable cash, 10% security or 30% industry/theme caps; existing breach forces 0x for added buys.
## Candidate methods and comparative evidence
Candidates: continuous optimization; ordered discrete feasibility. SPEC selects discrete search for deterministic explainability.
## Selected method and reasons for rejecting alternatives
Test `[1.5,1,0.5,0]` in descending order and return the first fully feasible candidate.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
For each multiplier calculate transaction costs and ALG-0011 post-trade exposures. Feasible means outflow<=cash and all exposures<=caps. Missing inputs or existing cap breach returns 0x. Equality is feasible.
## Parameters, calibration, versioning, and compatibility
Multiplier set, caps and cost/exposure policy versions bind output.
## Time and space complexity and resource budgets
O(4*(holdings+memberships)); bounded.
## Errors, degradation, fallback, and forbidden behavior
Never round a failing candidate into feasibility or auto-place/sell a trade.
## Validation cases and evidence
Golden cases for every multiplier, exact boundaries, cross-Thesis holdings, monotonicity as cash/cap headroom decreases.
## Risks and monitoring
Incorrect snapshot makes sizing unsafe; monitor abstain/0x causes.
## Human approval
Pending non-AI owner approval.
