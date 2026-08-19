# ALG-0009: Valuation validity and abstention
## Metadata
- Status: proposed
- Owner module: portfolio
- Product feature: Valuation input expiration and eligibility
- Flow IDs: valuation-publication-flow
- Related ADRs: none
- Source paths: planned portfolio valuation policy
- Test and benchmark paths: planned valuation tests
- Supersedes: none
## Problem and observable success
Prevent a target price or buy recommendation from using stale, incomplete, unconfirmed or inapplicable assumptions.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs include method, target date, as-of, forecast, source/Owner confirmations, new-report and material-event times, cost profile and minimum return. Output valid or abstain with trace.
## Constraints and quantitative acceptance thresholds
Periods are 6/12/24 calendar months; expiration is the earliest of new quarterly report, material event, or 90 days.
## Candidate methods and comparative evidence
Candidates: lazy warning; deterministic validity gate. Gate is selected because warnings could still issue unsafe recommendations.
## Selected method and reasons for rejecting alternatives
Require every prerequisite before publication and recompute validity from explicit time inputs.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
`expires_at=min(saved_at+90d, next_report_time, material_event_time)` over present values. Invalid when evaluation time >= expiry. Abstain for unconfirmed method/source/forecast, invalid target alignment, absent cost profile/minimum return, nonpositive holding days or inapplicable PE/PB.
## Parameters, calibration, versioning, and compatibility
Calendar/time-zone and expiry policy are versioned; time comes from input, never an implicit clock.
## Time and space complexity and resource budgets
O(1).
## Errors, degradation, fallback, and forbidden behavior
Ambiguous time or missing prerequisite abstains; no silent defaults except the user-visible 12-month draft default before confirmation.
## Validation cases and evidence
Boundary tests at just before/at/after expiry, leap dates, equal triggers and every missing prerequisite.
## Risks and monitoring
Late event ingestion can delay invalidation; monitor expiry Action Items and freshness.
## Human approval
Pending non-AI owner approval.
