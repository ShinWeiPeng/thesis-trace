# ALG-0034: Recommendation-derived Action Items

## Metadata

- Status: accepted
- Owner module: workflow_domain
- Product feature: Owner decision task materialization and reconciliation
- Flow IDs: owner_recommendation_analysis, owner_recommendation_decision, recommendation_expiry_reconciliation
- Related ADRs: ADR-0009
- Source paths: planned extensions to `backend/src/thesis_trace/modules/workflow/contracts.py`, `policy.py`, `service.py`, `ports.py`
- Test and benchmark paths: planned `backend/tests/test_recommendation_workflow.py`, `test_recommendation_postgres.py`
- Supersedes: none; anomaly ALG-0015 through ALG-0019 behavior remains unchanged

## Problem and observable success

Every actionable published Recommendation has one traceable Owner task; a recorded decision and task resolution cannot diverge after a crash. Workflow never authors a Recommendation or Decision.

## Inputs, outputs, units, ranges, and data-quality assumptions

L0 maps Recommendation identity/version, owner/company, publication or decision event identity, decision sequence, Server reason/time and optional reminder time into Workflow-owned values. Source refs carry no AI-selected assignee, priority or safety status. Output is a Workflow-owned task or idempotent reconciliation result.

## Constraints and quantitative acceptance thresholds

Unique automatic source fingerprint includes Recommendation ID/version and trigger kind. Zero duplicate open items on retry. Owner-only scope. Accepted/rejected/expired history cannot be changed through an Inbox operation. Critical financial details never go to email in this checkpoint.

## Candidate methods and comparative evidence

Browser creation duplicates state and fails with closed tabs. Post-commit callbacks have a crash gap. Durable subscriber is viable but adds independent lag/retry semantics. Same-transaction parent coordination is selected for this user-visible invariant; sibling repositories remain forbidden.

## Selected method and reasons for rejecting alternatives

Extend Workflow's source policy with a `recommendation_decision` type while retaining its existing state machine, assignee filtering, priority evaluation and query snapshot contract. The parent supplies semantic facts; Workflow evaluates its own transitions.

## Exact behavior, formula or pseudocode, boundaries, and tie-breaking

- Publication of actionable buy/hold creates a `pending` task assigned to the Recommendation Owner, normal priority under `workflow.recommendation-decision-v1`. It is not formal Hard and has no safety lock. Policy abstention/failure remains visible in the company analysis history but is not falsely presented as a recommendation to accept.
- Fingerprint plus receipt uniqueness makes publication/replay idempotent. A user-dismissed task is not recreated for the same source version merely by refresh; dismissal never rejects the underlying Recommendation.
- Start, defer and dismiss are task-layer actions. Task deferral does not author a deferred Owner Decision. The decision form is in the company workspace, not the Inbox panel. The UI labels these operations distinctly.
- A domain deferred Decision atomically updates the linked open task's reminder; it never reopens a task already dismissed by the Owner. At reminder time a valid open deferred task returns to pending under the existing Workflow rules. Invalid input takes the expiry path instead.
- Accepted/rejected/expired Decision atomically resolves any linked open task with a Server-derived outcome and reason. A previously completed/dismissed task retains its immutable history; no terminal history rewrite or duplicate transition is performed. Current decision truth is obtained from the source record.
- Completing the task directly cannot accept/reject the source. For an unresolved domain-decision task, manual completion requires the real domain outcome; dismiss remains task-only where permitted by existing non-safety policy.
- Decision/expiry processing and each owner's audit/receipt share the transaction described by ADR-0009. Any participant failure rolls back the whole unit. Query counts/list/detail use the same authorized committed snapshot; stale input availability is clearly separate from recorded task status until reconciliation.

## Parameters, calibration, versioning, and compatibility

Persist source version, trigger policy/version, decision sequence, reason and idempotency identity. Existing anomaly fingerprints and priority/history values are unchanged. No new email template or global priority policy is enabled by this record.

## Time and space complexity and resource budgets

Indexed source lookup and one task transition per publication/decision; no fan-out to other accounts. Bounded cursor-based reminder/expiry reconciliation. No numeric background latency or capacity claim.

## Errors, degradation, fallback, and forbidden behavior

Missing/foreign Owner, invalid source version, invalid transition and stale task conflict fail closed without leaking existence. Source-authoritative decision reconciliation must reload the latest task version and retry only the bounded database unit, never overwrite terminal task history. No sibling direct call or cross-schema write; no task-only operation creates a Decision or Trade.

## Validation cases and evidence

Publication duplicates, exact version recurrence, foreign Owner/Learner/Admin denial, dismissed-before-decision, completion without a Decision, task defer versus domain defer, reminder/expiry race, source decision with concurrently changed task version, atomic rollback, and consistent Inbox counts. Commands: `pytest backend/tests/test_recommendation_workflow.py -q`; real PostgreSQL combined suite and responsive Inbox-to-company-return E2E. Expected: exactly one task per trigger, no partial decision/task changes, and original return context preserved. Evidence pending implementation.

## Risks and monitoring

Implementation evidence (2026-09-05): Workflow domain tests cover actionable source admission, exact-version deduplication, dismissal preservation, source-only completion and deferred/terminal reconciliation. A separate PostgreSQL database passes six new/existing adapter tests covering persistence, active/matching transaction binding, rollback and real NOBYPASSRLS read/write isolation. This is evidence for the Workflow participant only, not for an implemented combined Recommendation Decision transaction or UI. See the [current Wave 7 checkpoint](../design/recommendation-owner-decision-wave7.md#sizing-publication-planning-and-workflow-checkpoint--2026-09-05).

Task status and source decision are different concepts. Use explicit labels and source links to avoid implying that dismissing a task rejects advice. Observe reconciliation failures by opaque source/task IDs and stable codes only.

## Human approval

- Approver: project owner
- Approval date: 2026-09-05
- Approval reference: ongoing SPEC-0001 conversation, explicit instruction `核准 ADR-0009 與 ALG-0032、ALG-0033、ALG-0034`.
