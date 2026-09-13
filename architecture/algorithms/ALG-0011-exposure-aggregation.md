# ALG-0011: Portfolio exposure aggregation
## Metadata
- Status: accepted
- Owner module: portfolio_domain
- Product feature: NAV and post-trade exposure
- Flow IDs: owner_portfolio_management, owner_trade_confirmation
- Related ADRs: ADR-0008
- Source paths: planned `backend/src/thesis_trace/modules/portfolio/policy.py`
- Test and benchmark paths: planned `backend/tests/test_portfolio_policy.py`
- Supersedes: none
## Problem and observable success
Aggregate every bucket so post-trade security, official-industry and custom-theme exposure is complete, deterministic and snapshot-bound.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are all owner holdings, cash, official closing prices/dates/sources, one official industry per security, confirmed themes and optional proposed trade. Outputs are NAV and Decimal exposures with exact references.
## Constraints and quantitative acceptance thresholds
Security cap is 10%; each official industry and theme cap is 30%. Complete holdings, cash, prices and classifications are mandatory. A security counts fully in every theme. Equality passes; `>` blocks.
## Candidate methods and comparative evidence
Per-Thesis exposure understates concentration. Complete cross-bucket aggregation is required.
## Selected method and reasons for rejecting alternatives
Aggregate by security, value at official close, apply trade/cash flow, then aggregate every class/theme independently.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
`pre_NAV=sum(qty*close)+cash`. A buy adds quantity and subtracts full outflow; a sell subtracts quantity and adds after-cost proceeds. `post_NAV=sum(post_qty*close)+post_cash`. Each exposure is its post-value sum divided by post_NAV. Missing/nonpositive NAV abstains. Any existing breach makes added buys infeasible.
## Parameters, calibration, versioning, and compatibility
Bind `exposure-policy-v1`, caps, price/source, classifications/themes, Cost Profile and Decimal policy. Historical snapshots are immutable.
## Time and space complexity and resource budgets
`O(holdings + memberships)` time and `O(securities + classes)` space.
## Errors, degradation, fallback, and forbidden behavior
Incomplete inputs abstain. Never use partial/stale/nonofficial data, per-Thesis-only totals, theme netting or Portfolio values in email.
## Validation cases and evidence
Golden multi-bucket cases, exact caps, overlapping themes, fee/cash changes, missing data and order invariance. `pytest backend/tests/test_portfolio_policy.py -q` must match NAV/exposure traces and hard-cap outcomes.
## Risks and monitoring
Monitor abstention and snapshot age/source codes without logging amounts.
## Human approval
- Approver: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
