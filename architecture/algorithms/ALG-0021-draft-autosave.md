# ALG-0021: Draft autosave
## Metadata
- Status: accepted
- Owner module: thesis
- Product feature: Long-text draft autosave
- Flow IDs: draft-autosave-flow
- Related ADRs: none
- Source paths: planned thesis draft feature
- Test and benchmark paths: planned draft API/UI tests
- Supersedes: none
## Problem and observable success
Save eligible long text after two seconds of inactivity without overwriting concurrent server revisions or persisting offline data.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are eligible field, text, expected version, idempotency key, connectivity and debounce time; output is revision/status/conflict.
## Constraints and quantitative acceptance thresholds
Only Thesis narrative/notes, general notes and unfinished Reflection text qualify; debounce is 2 seconds; every accepted save creates a revision.
## Candidate methods and comparative evidence
Candidates: interval/local offline queue; trailing debounce with server versioning. The latter is selected to prevent hidden writes and offline leakage.
## Selected method and reasons for rejecting alternatives
Keep draft volatile in UI, submit trailing-edge save with expected version/idempotency, and stop on conflict.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Reset timer on input; after 2s submit latest text. One request at a time per field; newer edit follows accepted save. On conflict stop automatic saves and retain text for compare/copy/reload. Offline retains only page memory and requires explicit retry.
## Parameters, calibration, versioning, and compatibility
Eligibility, debounce, bounded navigation wait and API schema are versioned.
## Time and space complexity and resource budgets
O(text size) per save; one volatile copy per active field.
## Errors, degradation, fallback, and forbidden behavior
Never use localStorage/IndexedDB/service worker or mark saved before server success.
## Validation cases and evidence
Fake-timer burst tests, concurrent version conflict, network loss/recovery, idempotent retry and unload warning Playwright cases.
## Risks and monitoring
Large drafts/churn; cap payload and monitor save conflicts/failures.
## Human approval
- Approver: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
