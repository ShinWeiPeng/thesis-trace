# ALG-0033: Append-only Owner Decision and input-bound expiry

## Metadata

- Status: accepted
- Owner module: recommendation_domain
- Product feature: Owner Decision, legal transitions, and DEC-105 expiry
- Flow IDs: owner_recommendation_decision, recommendation_expiry_reconciliation
- Related ADRs: ADR-0009
- Source paths: planned `backend/src/thesis_trace/modules/recommendation/policy.py`, `service.py`, `ports.py`
- Test and benchmark paths: planned `backend/tests/test_recommendation_decision.py`, `test_recommendation_postgres.py`
- Supersedes: none

## Problem and observable success

Ensure a stale recommendation cannot be accepted, preserve all prior decisions and bind consequential actions to the exact human-reviewed version. DEC-105 is the approved product rule; this record proposes its implementation policy, not new permission to overwrite history.

## Inputs, outputs, units, ranges, and data-quality assumptions

Inputs: authenticated Owner, Recommendation ID/version, current decision sequence, immutable critical-input bindings, current owner projections, Server UTC time, optional future defer time, reason, idempotency key, and a confirmation challenge for accepted/rejected. Output: one new immutable Decision event/current projection, or stable rejection; an exact retry returns the original receipt. No Decision yet is an absence, not a fifth persisted Decision enum.

## Constraints and quantitative acceptance thresholds

Decision values: `accepted|rejected|deferred|expired`. Accepted/rejected/expired are terminal for that Recommendation version. No independent recommendation TTL. Expiry boundary is `now >= bound valuation expiry` or any bound critical version no longer current/valid. Missing validity evidence prevents acceptance. Challenge expiry alone never changes Recommendation validity. Exactly one winning mutation/receipt per expected sequence; no partial challenge/domain/Workflow state.

## Candidate methods and comparative evidence

In-place history mutation violates REQ-031. A fixed seven/day/week TTL is unsupported and conflicts with DEC-105. Background-only validation permits stale acceptance while a worker is delayed. Append-only transitions plus synchronous current-input revalidation and background expiry persistence are selected.

## Selected method and reasons for rejecting alternatives

Separate immutable recommendation content, immutable decisions, current decision projection and current input validity. Read-only queries may report invalid inputs immediately but never mutate history. Commands and the reconciler append the expiry fact atomically; the UI cannot treat an old deferred projection as permission to accept.

## Exact behavior, formula or pseudocode, boundaries, and tie-breaking

| Current decision | Allowed next | Additional requirements |
| --- | --- | --- |
| absent | accepted, rejected | valid bound inputs; exact single-use challenge; nonblank reason |
| absent | deferred | valid inputs; explicit save/reason; future defer time |
| deferred | accepted, rejected | same validity/challenge requirements |
| deferred | deferred | valid inputs; new future reminder time and expected sequence |
| absent, deferred | expired | Server-established input invalidity/version change; automatic reason and evidence |
| accepted, rejected, expired | none | exact idempotent retry only; a new recommendation has its own lifecycle |

For each new mutation: revalidate Owner scope; match request digest/receipt; lock current stream and relevant input versions; check expected decision sequence and Recommendation version; obtain transaction-time validity. For absent/deferred with invalid inputs, append one expired fact with cause/ref/version/time and atomically reconcile Workflow, without consuming an acceptance challenge. Return a clear expired outcome. For valid inputs, validate the requested edge, reason and challenge, then append decision/projection/audit/receipt and Workflow outcome in one commit. A challenge/digest/actor mismatch never authorizes the requested action or consumes that challenge.

At preview and confirm, resolve the full critical tuple again. A change between the two invalidates the preview and, for unfinalized recommendations, causes expiry rather than silently attaching the old decision to a new recommendation. A pure challenge timeout with unchanged inputs requires only a new preview. Repeated expiry causes do not append another terminal decision. Concurrent accepted-versus-expired paths serialize with the source writers: whichever valid transaction wins determines history; a subsequent source change never changes an already accepted/rejected fact.

The expiry worker scans undecided/deferred records in stable cursor order and revalidates through L0 owner Ports; no cross-schema query in Recommendation persistence. Worker delay does not extend availability. Deferral arrival means ready for human attention, not automatic acceptance or a fresh validity window. Generating a new Recommendation never mutates an earlier version or revives expired decisions.

## Parameters, calibration, versioning, and compatibility

Persist `recommendation-decision-v1` and `recommendation-expiry-v1`, critical-binding identity, reason, actor/system causation, Server time and confirmation metadata when applicable. Keep accepted ALG-0020's at-most-five-minute challenge. Persisted history is never recomputed under a new policy.

## Time and space complexity and resource budgets

Transition lookup O(1); validity comparison O(number of bound critical inputs), expiry scan cursor-bounded. No full-history scan per decision. Best-effort background reconciliation; no expiry-notification latency guarantee. Immediate command admission safety is independent of worker speed.

## Errors, degradation, fallback, and forbidden behavior

Expired, version_conflict, resource_unavailable, invalid_transition, missing_reason, invalid_defer_time, challenge_expired and idempotency_mismatch are explicit. Unavailable dependency/database means no decision commit, not assume-valid. No automatic trading, no client authority, no extending validity by deferral, no accepted-to-expired transition, no unconfirmed mutation on GET.

## Validation cases and evidence

Exhaustive state-pair tests, no-decision cases, Fake Clock immediately before/equal/after expiry, changed critical versions individually, unchanged valid inputs beyond arbitrary elapsed days, unrelated note edits, challenge-only timeout, deferred reminders after expiry, exact replay and changed digest, duplicate worker expiry, role changes, concurrency with input writer, concurrent acceptance/rejection/expiry, transaction failure at every participant and immutable UPDATE/DELETE rejection. Commands: `pytest backend/tests/test_recommendation_decision.py -q`; real PostgreSQL suite required for races/rollback/RLS. Every forbidden transition and stale acceptance must write zero requested-decision rows. Proposed tests have not run yet.

## Risks and monitoring

Implementation evidence (2026-09-05): pure `RecommendationService.plan_decision` and expiry tests pass within the combined 86-test Recommendation suite; see [Wave 7 checkpoint](../design/recommendation-owner-decision-wave7.md#first-policy-implementation-checkpoint--2026-09-05). This seam returns a plan only. Challenge enforcement, append-only persistence, receipts, concurrency and Workflow atomicity remain unimplemented/unverified and cannot be inferred from these tests.

Missing version bindings and mismatched transaction clocks are primary risks. Track expiry reason classes, current-input read failures and optimistic conflicts, never sensitive contents. UI distinguishes recorded decision history from present input validity and offers regenerate/re-preview as appropriate.

## Human approval

DEC-105 product rule approved by the user with `採用` on 2026-09-05 in the ongoing SPEC-0001 conversation.

- Approver: project owner
- Approval date: 2026-09-05
- Approval reference: ongoing SPEC-0001 conversation, explicit instruction `核准 ADR-0009 與 ALG-0032、ALG-0033、ALG-0034`.
