# ALG-0015: Action-item creation, deduplication, and recurrence
## Metadata
- Status: accepted
- Owner module: workflow
- Product feature: Action Inbox creation
- Flow IDs: action-item-creation-flow
- Related ADRs: ADR-0006
- Source paths: `backend/src/thesis_trace/modules/workflow/service.py`, `backend/src/thesis_trace/adapters/postgres_workflow/adapter.py`
- Test and benchmark paths: `backend/tests/test_workflow_domain.py`, `backend/tests/test_workflow_postgres.py`
- Supersedes: none
## Problem and observable success
Create one actionable item per material trigger/version without mutating closed history.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are creation rule, source record/version, normalized trigger content and prior items; output is no-op or new item with recurrence relation.
## Constraints and quantitative acceptance thresholds
Same source version/fingerprint never creates duplicate open or new items; version-only changes without material fingerprint change do not recur.
## Candidate methods and comparative evidence
Candidates: source-ID uniqueness; rule/source-version/material fingerprint. The compound key is selected to distinguish recurrence from delivery retries.
## Selected method and reasons for rejecting alternatives
Hash rule version, source identity, semantic trigger and required handling; enforce database uniqueness.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
The v1 fingerprint is the SHA-256 digest of a length-delimited canonical tuple `(creation_rule_version, source_domain, source_record_id, source_version_semantics, trigger_kind, normalized_required_handling)`. For `manual-anomaly-review-v1`, `source_version_semantics` is the exact immutable assessment version and `normalized_required_handling` is the Server-derived anomaly class/route; client title or free text never changes the fingerprint. If an identical creation-rule/source/fingerprint exists, return that item as a no-op. If a materially new trigger remains actionable, create a new ID and link the most recent relevant terminal item via `recurrence_of`/`continues`; never reopen terminal items. Concurrent ties settle by unique constraint and reread under the same authorization scope. Reusing an idempotency key with different canonical command data rejects.
## Parameters, calibration, versioning, and compatibility
Canonical fingerprint fields and creation rule are versioned.
## Time and space complexity and resource budgets
O(trigger size + indexed lookup).
## Errors, degradation, fallback, and forbidden behavior
Missing owner/source/version fails closed as operational exception; never hide or rewrite source records.
## Validation cases and evidence
Retry/concurrency, source version only, material change and multiple terminal-history fixtures; fingerprint determinism properties.
## Risks and monitoring
Overbroad fingerprints suppress work; monitor suppressed/materially reopened counts.
## Human approval
- Approver: project owner
- Approval date: 2026-08-24
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
