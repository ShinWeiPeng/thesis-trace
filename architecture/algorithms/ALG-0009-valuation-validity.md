# ALG-0009: Valuation validity and abstention
## Metadata
- Status: accepted
- Owner module: thesis_domain
- Product feature: Valuation input expiration and eligibility
- Flow IDs: owner_valuation_publication
- Related ADRs: ADR-0008
- Source paths: planned `backend/src/thesis_trace/modules/thesis/valuation.py`
- Test and benchmark paths: planned `backend/tests/test_valuation_policy.py`
- Supersedes: none
## Problem and observable success
Prevent target price or later buy Recommendation from using stale, incomplete, unconfirmed or inapplicable assumptions. Every abstention exposes stable reasons and exact versions.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are method, 6/12/24-month horizon, basis time/date, forecast and confirmation, selected benchmark/result, report/event times, Cost Profile and minimum return. Output is valid or abstain plus target date, expiry, reasons and trace.
## Constraints and quantitative acceptance thresholds
Horizon is exactly 6, 12 or 24 calendar months. Forecast expires at the earliest of saved time plus 90 days, next quarterly report or relevant material event. Evaluation at or after expiry is invalid. Method/source/forecast/Cost Profile/minimum return and positive holding days are mandatory before publication for Recommendation use.
## Candidate methods and comparative evidence
Warning-only could publish unsafe values. A deterministic gate is selected. Calendar overflow and expiry equality require exact policies.
## Selected method and reasons for rejecting alternatives
Compute prerequisites from explicit versioned inputs and injected evaluation time. Apply DEC-102 month-end clamping and fail closed.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
`target_date = add_calendar_months_clamped(basis_date, horizon)`; a missing day uses the target month's final day without overflow. `expires_at = min(saved_at + 90 days, next_report_time?, material_event_time?)`; equal causes are all retained in stable order. Invalid when `evaluation_time >= expires_at`. Missing, unconfirmed, abstain, inapplicable, insufficient, stale or nonpositive-day inputs abstain.
## Parameters, calibration, versioning, and compatibility
Bind `valuation-validity-v1`, `calendar-month-clamp-v1`, timezone/calendar and input versions. Time is an argument, never an implicit clock.
## Time and space complexity and resource budgets
`O(1)` time and space.
## Errors, degradation, fallback, and forbidden behavior
Ambiguous timezone, invalid date/Decimal or missing prerequisite abstains. Only an unpublished draft may visibly default to 12 months; publication never silently defaults.
## Validation cases and evidence
Fake-clock tests cover before/at/after expiry, equal triggers, month ends, leap years, all horizons and nonpositive days. `pytest backend/tests/test_valuation_policy.py -q` must match exact target dates, causes and abstention codes.
## Risks and monitoring
Late report/event ingestion delays invalidation; monitor stale/expired reason counts.
## Human approval
- Approver: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
