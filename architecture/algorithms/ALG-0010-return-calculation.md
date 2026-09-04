# ALG-0010: Target price and annualized net return
## Metadata
- Status: accepted
- Owner module: thesis_domain
- Product feature: Deterministic valuation arithmetic
- Flow IDs: owner_valuation_publication
- Related ADRs: ADR-0008
- Source paths: planned `backend/src/thesis_trace/modules/thesis/valuation.py`
- Test and benchmark paths: planned `backend/tests/test_valuation_policy.py`
- Supersedes: none
## Problem and observable success
Calculate target price and comparable annualized net total return with exact costs and reproducible Decimal traces.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are Decimal forecast, multiple, quantity, prices, dividend, fee minimums/rates, tax, basis and target dates. Currency is TWD for v1; rates are unit fractions. Output includes target, cash flows, days, return, disclaimer and trace.
## Constraints and quantitative acceptance thresholds
No binary floats; round only presentation. Quantity, purchase outflow, terminal inflow and holding days are positive. Cost Profile is version-bound.
## Candidate methods and comparative evidence
Simple price upside omits period, dividends and costs. SPEC selects after-cost annualized total return.
## Selected method and reasons for rejecting alternatives
Use confirmed PE/PB multiplication, explicit cash flows and high-precision Decimal exponentiation verified by golden vectors.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
`target=forecast*multiple`; `buy_notional=buy_price*quantity`; `buy_fee=max(min_buy_fee,buy_notional*buy_rate)`; `purchase_outflow=buy_notional+buy_fee`; `sell_notional=target*quantity`; `sell_fee=max(min_sell_fee,sell_notional*sell_rate)`; `terminal_inflow=sell_notional-sell_fee-sell_notional*tax_rate+cash_dividend`; `annualized=(terminal_inflow/purchase_outflow)**(365/holding_days)-1`. No intermediate display rounding changes feasibility.
## Parameters, calibration, versioning, and compatibility
Bind `valuation-return-v1`, Decimal context/exponent, `actual-days/365-v1` and Cost Profile version. New policies create new results.
## Time and space complexity and resource budgets
`O(1)` bounded Decimal operations; no numeric latency claim.
## Errors, degradation, fallback, and forbidden behavior
Invalid Decimal, overflow/non-convergence, missing inputs, incompatible currency or nonpositive values abstain. Never omit costs, use float or omit the tax disclaimer.
## Validation cases and evidence
Golden hand calculations cover PE/PB, minimum fees, tax/dividend and all horizons; properties cover monotonicity and rounding independence. `pytest backend/tests/test_valuation_policy.py -q` must match stored Decimal strings and independent fixtures.
## Risks and monitoring
Pin runtime/policy and run cross-version golden vectors before Decimal-runtime upgrades.
## Human approval
- Approver: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
