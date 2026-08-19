# ALG-0020: Consequential-action confirmation challenge
## Metadata
- Status: proposed
- Owner module: access
- Product feature: Two-step high-risk command confirmation
- Flow IDs: consequential-command-flow
- Related ADRs: none
- Source paths: planned Access challenge component and destination-parent transaction orchestration; see `architecture/design/access-wave1.md`
- Test and benchmark paths: planned Access policy tests, PostgreSQL concurrency/rollback tests, API contracts and responsive Playwright confirmation flow
- Supersedes: none
## Problem and observable success
Bind a human-readable preview to exactly one authorized command payload/version for at most five minutes.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are actor, action type, target/version, canonical payload, server time and reason; output challenge or committed command.
## Constraints and quantitative acceptance thresholds
Single use, lifetime <=5 minutes, nonblank reason, role/version/payload revalidation and atomic audit.
## Candidate methods and comparative evidence
Candidates: (A) a client modal flag, (B) a server-stored digest challenge committed separately from the domain command, and (C) a server-stored digest challenge consumed in the same PostgreSQL transaction as the destination-domain mutation and audit. A is forgeable/stale. B can consume a challenge without committing the action, or commit an action after challenge rollback. C is the authoring candidate because it binds single use and domain effect atomically; it remains pending non-AI approval.
## Selected method and reasons for rejecting alternatives
Canonicalize payload, hash binding fields and persist opaque one-time challenge; confirmation reruns all authorization and domain checks.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
`digest=SHA256(actor|action|target|version|canonical_payload|nonce)`. Reject at `now>=expires_at`, used/revoked challenge, digest/version/actor mismatch or blank reason. Success consumes challenge and writes domain/audit/outbox in one transaction; retry returns original result.
## Parameters, calibration, versioning, and compatibility
Canonicalization, hash and expiry policy are versioned.
## Time and space complexity and resource budgets
O(payload size), bounded request payload.
## Errors, degradation, fallback, and forbidden behavior
Never trust preview text/client digest or extend challenge; any changed payload requires new preview.
## Validation cases and evidence
Expiry boundaries, replay, tamper, version race, actor swap and transaction rollback tests.
## Risks and monitoring
Canonicalization mismatch; share server canonicalizer and monitor rejection reasons.
## Human approval
Pending non-AI owner approval.

## Design links
- `architecture/design/access-wave1.md`
- Decisions: `REQ-048`, `AC-042`, `ALG-0027`
