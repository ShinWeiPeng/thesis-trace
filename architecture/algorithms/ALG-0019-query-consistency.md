# ALG-0019: Inbox query consistency
## Metadata
- Status: accepted
- Owner module: workflow
- Product feature: Filtering, sorting, pagination and summary cards
- Flow IDs: action-inbox-query-flow
- Related ADRs: ADR-0006
- Source paths: `backend/src/thesis_trace/modules/workflow/service.py`, `backend/src/thesis_trace/adapters/postgres_workflow/adapter.py`
- Test and benchmark paths: `backend/tests/test_workflow_postgres.py`, `frontend/src/workflow/routes.test.tsx`, `frontend/e2e/workflow.spec.ts`
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
The v1 whitelist is `effective_priority`, `due_at`, `created_at`, and `updated_at`, each ascending or descending. Default ordering is effective priority severity descending, null-last due time ascending, creation time ascending, then stable item ID ascending. Page size is 1 through 100 with default 25. Search is a case-insensitive Server query over the authorized company's ticker/name and the item reason; filters admit company ID, item type, status, effective priority, created/due time bounds, and open-only. The opaque cursor is authenticated and binds query schema version, actor/scope, normalized filters/search, sort tuple, repeatable-read `as_of`, and last ordering keys. Invalid, altered, expired-scope or mismatched cursors reject. Summary counts (`urgent` = critical/high open, `due_today`, `deferred`, `all_open`) and `total_count` use the identical authorized base relation before pagination in the same repeatable-read transaction.
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
- Approver: project owner
- Approval date: 2026-08-24
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
