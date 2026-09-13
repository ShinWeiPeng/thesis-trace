# ALG-0013: Thesis, Outcome and Reflection lifecycle
## Metadata
- Status: accepted
- Owner module: thesis_domain
- Product feature: Personal Thesis, Outcome and Reflection lifecycle
- Flow IDs: personal_thesis_lifecycle
- Related ADRs: ADR-0007
- Source paths: `backend/src/thesis_trace/modules/thesis/contracts.py`, `backend/src/thesis_trace/modules/thesis/service.py`
- Test and benchmark paths: `backend/tests/test_thesis_domain.py`, `backend/tests/test_thesis_postgres.py`
- Supersedes: none
## Problem and observable success
Allow Owner and Learner to operate only their own auditable Thesis lifecycle while preserving immutable cycles, invalidation conditions, Outcomes, Reflections and history. Success means every accepted command produces exactly one legal next version and every rejected, stale, unauthorized or replay-mismatched command produces no partial state.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are authenticated actor/capabilities, current Thesis version/status/cycle, command, reason, idempotency key, exact Company/Evidence versions, condition versions, and current-cycle Outcome/Reflection prerequisites. Output is the committed next projection plus append-only history, or a stable rejection. All times are Server UTC instants; cycle and record versions are positive monotonic integers.
## Constraints and quantitative acceptance thresholds
Thesis states are `draft`, `active`, `paused`, `invalidated`, `closed`. Creation always yields `draft`, version 1, cycle 1. Invalidation is immediate and sets `reflection_pending`. Close requires at least one current-cycle Outcome and one completed current-cycle Reflection. Reopen increments cycle exactly once. Accepted commands append exactly one current Thesis version and one audit fact; idempotent replay returns the original result; stale or mismatched replay writes zero rows.
## Candidate methods and comparative evidence
Candidates are free status assignment, one explicit transition table with lifecycle cycles, or a queued workflow engine. Free assignment cannot prove legal/terminal behavior. A queued engine adds pending states and operational failure paths without external I/O. The explicit pure table plus optimistic transaction is selected for deterministic invariants and immediate UI consistency.
## Selected method and reasons for rejecting alternatives
Use a pure transition function and explicit prerequisite predicates before an optimistic atomic append. Current relational rows serve queries; immutable version/audit rows preserve history. Outcome, completed Reflection and published invalidation conditions are append-only. Reopen creates a new lifecycle cycle rather than mutating the closed/invalidated cycle.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Transition table:

| From | To | Preconditions | Confirmation |
| --- | --- | --- | --- |
| create | `draft` | authorized Owner/Learner; valid Company | direct |
| `draft` | `active` | nonblank title/narrative; at least one published invalidation condition | direct |
| `active` | `paused` | nonblank reason | direct |
| `paused` | `active` | nonblank reason | direct |
| `draft`, `active`, `paused` | `invalidated` | nonblank reason | consequential challenge |
| `active`, `paused`, `invalidated` | `closed` | current-cycle Outcome and completed Reflection; nonblank reason | consequential challenge |
| `invalidated`, `closed` | `active` | activation fields valid; nonblank reason | consequential challenge; increment cycle |

All other pairs reject. `invalidated` cannot be paused and `closed` cannot be invalidated. Invalidation commits regardless of missing Outcome/Reflection. A reopen preserves every prior cycle record, increments `cycle`, clears current-cycle Outcome/Reflection completion, sets `reflection_pending=false`, and publishes no new condition automatically; activation uses the currently explicit published condition set.

Pseudocode:

```text
validate actor owns thesis and role in {owner, learner}
validate command digest/idempotency and expected thesis version
validate exact Company/Evidence references supplied by L0
if transition is consequential:
    validate single-use challenge(actor, action, target_version, payload_digest, now)
validate transition table and target predicates
if target == invalidated: reflection_pending = true
if target == closed: require current_cycle.outcome && current_cycle.reflection_completed
if from in {invalidated, closed} && target == active:
    cycle = cycle + 1
    reflection_pending = false
append current/version/history/audit/idempotency atomically
return committed projection
```

Reflection autosave applies ALG-0021 and appends a draft revision only. It never changes Thesis status or satisfies the close predicate. Outcome and Reflection correction append a new superseding version; tie-breaking always selects the highest committed version within the current cycle.
## Parameters, calibration, versioning, and compatibility
Initial policy version is `thesis-lifecycle-v1`. Historical rows retain their policy/build version. New policies do not reinterpret old cycles. Adding a state or changing a legal edge requires a new algorithm version and architecture review; existing optional anomaly Thesis-binding remains backward compatible because an absent binding fails closed as before.
## Time and space complexity and resource budgets
Transition evaluation is O(1). Evidence-link validation is O(n) for a bounded submitted link set; persistence adds O(1) current/version/audit rows plus O(n) link rows. No numeric latency, throughput, capacity or real-time claim is made.
## Errors, degradation, fallback, and forbidden behavior
Unauthorized, unowned, stale, invalid transition, missing prerequisite, expired/mismatched challenge, bad idempotency replay, unrelated Evidence and autosave conflict reject without partial writes. Never overwrite prior Thesis versions, cycles, conditions, Outcomes, Reflections or audit. Never accept owner identity, Server time, condition match, canonical status or policy result from client/AI. Never make formal Hard, Recommendation, Trade or Workflow changes in this algorithm.
## Validation cases and evidence
Exhaustive state-pair matrix; create/activate/pause/resume/invalidate/close/reopen examples; property tests for monotonic versions/cycles and immutable history; missing Outcome/Reflection close cases; immediate invalidation with pending Reflection; challenge expiry/digest/actor/version/replay cases; Owner/Learner own-record and Admin/cross-user denial; idempotency mismatch; autosave revision/conflict; concurrent optimistic updates; transaction rollback; immutable invalidation projection mapping.
## Risks and monitoring
Cross-domain reference versions and confirmation previews may become stale; reject and monitor conflict counts by stable code. Autosave contention may produce user-visible conflicts; stop further autosave until explicit reload/copy. Reopen-cycle bugs could erase learning history; assert monotonic cycle and immutable prior-cycle rows in database integration tests.
## Human approval
- Approver: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
