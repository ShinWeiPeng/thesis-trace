# ALG-0023: Notification routing and redaction
## Metadata
- Status: proposed
- Owner module: notification
- Product feature: Daily and immediate notifications
- Flow IDs: notification-planning-flow
- Related ADRs: none
- Source paths: planned notification policy
- Test and benchmark paths: planned notification tests
- Supersedes: none
## Problem and observable success
Map domain events to daily/immediate/no-email notifications using only allowlisted fields.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are typed event, Action Item, recipient authorization at enqueue/send and Asia/Taipei schedule; output is template/version and safe field map.
## Constraints and quantitative acceptance thresholds
E2-E6 first attainment/normal upgrade enters 21:00 digest; corrections/withdrawals/downgrades/invalidations, Hard anomaly and recommendation/retraction are immediate. Forbidden content occurrence must be zero.
## Candidate methods and comparative evidence
Candidates: free-form/AI rendering; typed allowlist templates. Allowlist is selected for privacy.
## Selected method and reasons for rejecting alternatives
Use event-to-template table and explicit field extractors; unrepresentable input degrades to generic reminder.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Classify event by stable type/policy; dedup by recipient+event/action+template version. Reauthorize single recipient at send. Allowed fields are company/name or ticker, item type, priority/time, generic prompt and opaque HTTPS Action Item link. All else is omitted.
## Parameters, calibration, versioning, and compatibility
Routing table, timezone and templates are immutable/versioned.
## Time and space complexity and resource budgets
O(events), bounded digest size with deterministic continuation.
## Errors, degradation, fallback, and forbidden behavior
No AI text, attachments, external images, tracking, CC/BCC, tokens or financial/research body data.
## Validation cases and evidence
Golden routing/calendar cases, forbidden-field corpus, authorization revocation and duplicate/retry tests.
## Risks and monitoring
Template regression may leak data; snapshot-test rendered MIME and central redaction.
## Human approval
Pending non-AI owner approval.
