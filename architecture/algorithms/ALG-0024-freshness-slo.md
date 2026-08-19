# ALG-0024: Official-source freshness SLO measurement
## Metadata
- Status: proposed
- Owner module: research
- Product feature: Rolling freshness reporting
- Flow IDs: source-collection-flow
- Related ADRs: none
- Source paths: planned research metrics policy
- Test and benchmark paths: planned freshness fixture tests
- Supersedes: none
## Problem and observable success
Measure canonical completion latency consistently while separating external outages.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are eligible events, validated publication/observation timestamps, commit time and outage intervals; outputs are numerator, denominator, percentiles, basis and alerts over rolling 30 UTC days.
## Constraints and quantitative acceptance thresholds
Reachable events: >=95% within 10 minutes and >=99% within 30; any >30 minutes, two missed five-minute polls or uncleared recovered backlog creates an Action Item.
## Candidate methods and comparative evidence
Candidates: HTTP latency; end-to-end publication-to-canonical-commit latency. The latter is selected because it measures user-visible freshness.
## Selected method and reasons for rejecting alternatives
Prefer reasonable source publication time; otherwise first successful response containing event. Completion is committed canonical evidence plus required durable follow-up.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Latency=`commit-start`. Events whose scheduled fetch lies in classified connection/rate-limit/parse-service outage are excluded from reachable denominator but reported separately. Percentiles use a fixed versioned convention. Boundaries at exactly 10/30 minutes pass.
## Parameters, calibration, versioning, and compatibility
Eligibility, timestamp reasonableness, outage taxonomy, window and percentile convention are versioned.
## Time and space complexity and resource budgets
O(events log events) for exact report; bounded rolling aggregation may be benchmarked before substitution.
## Errors, degradation, fallback, and forbidden behavior
Never count HTTP receipt/in-memory queue as complete or discard slow events.
## Validation cases and evidence
At least 100 deterministic events covering boundaries, congestion, restart, duplicate and outage/recovery.
## Risks and monitoring
Bad source timestamps distort metrics; always expose measurement basis.
## Human approval
Pending non-AI owner approval.
