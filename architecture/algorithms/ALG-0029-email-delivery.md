# ALG-0029: Email delivery retry and idempotency
## Metadata
- Status: proposed
- Owner module: notification
- Product feature: Gmail at-least-once delivery
- Flow IDs: email-delivery-flow
- Related ADRs: none
- Source paths: planned notification email adapter
- Test and benchmark paths: planned email contract/job tests
- Supersedes: none
## Problem and observable success
Deliver an authorized rendered email once in effect despite at-least-once worker retries.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are delivery key, template/version, safe field map, recipient identity/authorization and attempt/provider result; output delivered/retrying/dead-letter.
## Constraints and quantitative acceptance thresholds
Retry delays are 1, 5 and 30 minutes; exhausted delivery enters DLQ; one recipient, no CC/BCC.
## Candidate methods and comparative evidence
Candidates: send then mark; durable intent with stable idempotency/provider reconciliation. Durable intent is selected to bound duplicates after crashes.
## Selected method and reasons for rejecting alternatives
Persist rendered digest and key before send, reauthorize at each attempt, reuse stable provider/client identifier, and record provider message ID.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Attempt 1 sends immediately; retryable failures schedule +1m,+5m,+30m; after final retry DLQ. Permanent auth/template errors fail closed. Existing delivered key is no-op. Ambiguous send result reconciles by stored key/provider ID before retry.
## Parameters, calibration, versioning, and compatibility
Retry schedule, error taxonomy, Gmail contract and template version are recorded.
## Time and space complexity and resource budgets
O(1) per attempt; bounded payload.
## Errors, degradation, fallback, and forbidden behavior
Do not send after authorization loss or rebuild body from mutable domain data.
## Validation cases and evidence
Fake Gmail covers retry classes, crash windows, ambiguous result, revocation, duplicate job and DLQ.
## Risks and monitoring
Provider lacks perfect idempotency; monitor duplicate/reconciliation metrics without storing body.
## Human approval
Pending non-AI owner approval.
