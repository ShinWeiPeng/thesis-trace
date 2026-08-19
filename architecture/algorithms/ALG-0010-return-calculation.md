# ALG-0010: Target price and annualized net return
## Metadata
- Status: proposed
- Owner module: portfolio
- Product feature: Deterministic valuation arithmetic
- Flow IDs: valuation-publication-flow
- Related ADRs: none
- Source paths: planned portfolio valuation policy
- Test and benchmark paths: planned valuation tests
- Supersedes: none
## Problem and observable success
Calculate target value and comparable net annualized return with exact transaction-cost treatment.
## Inputs, outputs, units, ranges, and data-quality assumptions
Decimal forecast EPS/BVPS, target PE/PB, quantity, prices, dividends, fee/tax rules, as-of and target date. Currency units and rates must be explicit.
## Constraints and quantitative acceptance thresholds
No binary floats; round only presentation. Holding days must be positive.
## Candidate methods and comparative evidence
Candidates: simple price upside; after-cost annualized total return. SPEC selects the latter for period comparability.
## Selected method and reasons for rejecting alternatives
Use confirmed PE/PB multiplication and cash-flow formula including fees, tax and dividends.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
`target=forecast*multiple`; `purchase_outflow=buy_notional+max(min_buy_fee,buy_notional*buy_rate)`; `terminal_inflow=sell_notional-max(min_sell_fee,sell_notional*sell_rate)-sell_notional*tax_rate+cash_dividend`; `return=(terminal_inflow/purchase_outflow)^(365/holding_days)-1`. Invalid denominator/date abstains.
## Parameters, calibration, versioning, and compatibility
Decimal precision, exponent implementation, fee/tax profile and day-count convention are versioned.
## Time and space complexity and resource budgets
O(1), bounded high-precision decimal operations.
## Errors, degradation, fallback, and forbidden behavior
Missing inputs, overflow, invalid decimal or nonpositive cash flow abstains. Never omit costs or personal-tax disclaimer.
## Validation cases and evidence
Golden hand calculations, minimum-fee boundaries, leap year, zero/negative cases and precision properties.
## Risks and monitoring
Decimal exponent portability; cross-check golden vectors across supported runtime versions.
## Human approval
Pending non-AI owner approval.
