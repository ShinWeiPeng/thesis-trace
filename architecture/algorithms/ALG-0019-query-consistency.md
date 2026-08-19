# ALG-0019: Inbox query consistency
## Metadata
- Status: proposed
- Owner module: workflow
- Product feature: Filtering, sorting, pagination and summary cards
- Flow IDs: action-inbox-query-flow
- Related ADRs: none
- Source paths: planned workflow query service
- Test and benchmark paths: planned query integration tests
- Supersedes: none
## Problem and observable success
Return summary counts and page results from the same authorization scope and query point.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are actor scope, filters, search, sort, cursor and database snapshot; outputs are counts, rows, next cursor and as-of.
## Constraints and quantitative acceptance thresholds
Server alone computes priority/counts; stable pagination cannot omit/duplicate rows during equal sort values.
## Candidate methods and comparative evidence
Candidates: independent count/list requests; one server query contract and transaction snapshot. The latter is selected for consistency.
## Selected method and reasons for rejecting alternatives
Apply authorization and filters once, derive aggregates and ordered rows in one read transaction.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Whitelist sort fields/directions; append stable `id` tie-breaker. Cursor binds filter/sort/scope/as-of digest and last keys. Invalid cursor rejects. Counts use the identical base relation before pagination.
## Parameters, calibration, versioning, and compatibility
Query/cursor schema and collation are versioned.
## Time and space complexity and resource budgets
Indexed O(log n + page size); counts database-dependent and benchmarked on representative data.
## Errors, degradation, fallback, and forbidden behavior
No client-side hidden-data recount; unauthorized/nonexistent targets share non-disclosing response.
## Validation cases and evidence
PostgreSQL tests for ties, concurrent inserts, scopes, cursor tampering and count/list agreement.
## Risks and monitoring
Large filtered counts may be slow; monitor query latency/plans.
## Human approval
Pending non-AI owner approval.
