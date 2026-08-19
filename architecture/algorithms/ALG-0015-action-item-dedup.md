# ALG-0015: Action-item creation, deduplication, and recurrence
## Metadata
- Status: proposed
- Owner module: workflow
- Product feature: Action Inbox creation
- Flow IDs: action-item-creation-flow
- Related ADRs: none
- Source paths: planned workflow policy
- Test and benchmark paths: planned workflow tests
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
If identical fingerprint exists, no-op. If a materially new trigger remains actionable, create new ID and link the most recent relevant terminal item via recurrence_of/continues; never reopen terminal items. Concurrent ties settle by unique constraint/reread.
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
Pending non-AI owner approval.
