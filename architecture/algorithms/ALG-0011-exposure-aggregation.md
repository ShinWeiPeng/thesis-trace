# ALG-0011: Portfolio exposure aggregation
## Metadata
- Status: proposed
- Owner module: portfolio
- Product feature: NAV and post-trade exposure
- Flow IDs: recommendation-publication-flow
- Related ADRs: none
- Source paths: planned portfolio risk policy
- Test and benchmark paths: planned portfolio risk tests
- Supersedes: none
## Problem and observable success
Aggregate all allocation buckets so post-trade security, official-industry and custom-theme exposure is complete and immutable.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are holdings, cash, official closing prices/dates/sources, classifications, themes and proposed trade; outputs are NAV and exposure ratios.
## Constraints and quantitative acceptance thresholds
Security cap 10%; every official industry and custom theme cap 30%; complete holdings/cash/prices and one official classification per security are mandatory.
## Candidate methods and comparative evidence
Candidates: per-Thesis exposure; security-wide aggregation across buckets. SPEC selects complete aggregation because caps apply to economic exposure.
## Selected method and reasons for rejecting alternatives
Aggregate quantities by security, value at most recent official close, add investable cash, apply proposed trade, then aggregate by classification/theme.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
`NAV=sum(qty*price)+cash`; `security_exposure=post_security_value/post_NAV`; each classification exposure is `sum(post values in class)/post_NAV`; a security counts fully in each assigned theme. Missing/zero NAV abstains; `>` cap blocks while equality passes.
## Parameters, calibration, versioning, and compatibility
Caps, classification snapshots, price policy and decimal precision are immutable/versioned.
## Time and space complexity and resource budgets
O(holdings + memberships), O(securities + classes).
## Errors, degradation, fallback, and forbidden behavior
Never use partial holdings, stale/nonofficial prices or net across themes; never expose private portfolio values in email.
## Validation cases and evidence
Golden multi-Thesis cases, exact-cap boundaries, multi-theme counting, missing data and order-invariance properties.
## Risks and monitoring
Stale classifications/prices; monitor abstention and snapshot age.
## Human approval
Pending non-AI owner approval.
