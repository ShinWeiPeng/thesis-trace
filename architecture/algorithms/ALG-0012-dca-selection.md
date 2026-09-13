# ALG-0012: DCA multiplier selection
## Metadata
- Status: accepted
- Owner module: portfolio_domain
- Product feature: Risk-constrained DCA sizing
- Flow IDs: owner_portfolio_management, owner_trade_confirmation
- Related ADRs: ADR-0008
- Source paths: planned `backend/src/thesis_trace/modules/portfolio/policy.py`
- Test and benchmark paths: planned `backend/tests/test_portfolio_policy.py`
- Supersedes: none
## Problem and observable success
Select the highest allowed multiplier fitting cash and every cap. This slice returns feasibility only; it does not publish Recommendation or trade.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are positive Decimal base amount, raw suggestion ceiling, immutable Portfolio snapshot and policy versions. Output is `1.5x|1x|0.5x|0x` plus traces/reasons.
## Constraints and quantitative acceptance thresholds
Never exceed cash, 10% security or 30% class/theme caps. Any current breach forces `0x` for added buys. Equality is feasible.
## Candidate methods and comparative evidence
Continuous optimization adds arbitrary rounding. Ordered discrete feasibility is required and deterministic.
## Selected method and reasons for rejecting alternatives
Test `[1.5,1,0.5,0]` descending, skip values above the raw ceiling, and return the first fully feasible candidate.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
For each candidate compute costs, reject outflow above cash, run ALG-0011 and require every exposure `<=` cap. `0x` is fail closed. Candidate order is the only tie-break.
## Parameters, calibration, versioning, and compatibility
Bind `dca-selection-v1`, multiplier set/order, caps, Cost Profile, exposure policy and snapshot versions.
## Time and space complexity and resource budgets
At most four `O(holdings + memberships)` evaluations.
## Errors, degradation, fallback, and forbidden behavior
Missing/invalid input, current breach or abstaining exposure returns `0x`. Never round into feasibility, exceed raw suggestion, auto-place or auto-sell.
## Validation cases and evidence
Golden cases cover each multiplier, cap/cash equality, overlapping themes and monotonicity. `pytest backend/tests/test_portfolio_policy.py -q` must match candidate sequence and trace.
## Risks and monitoring
Preserve inputs and monitor `0x` reasons; an incomplete snapshot always fails closed.
## Human approval
- Approver: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
