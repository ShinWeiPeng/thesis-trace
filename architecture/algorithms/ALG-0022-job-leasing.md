# ALG-0022: Durable job leasing, serialization, and retry
## Metadata
- Status: proposed
- Owner module: workflow
- Product feature: PostgreSQL durable workers
- Flow IDs: background-job-flow
- Related ADRs: none
- Source paths: planned platform job adapter and application orchestration
- Test and benchmark paths: planned PostgreSQL job integration tests
- Supersedes: none
## Problem and observable success
Run at-least-once work concurrently across independent subjects without stale or duplicate side effects.
## Inputs, outputs, units, ranges, and data-quality assumptions
Job contains type, payload record IDs/versions, available time, attempt, lease, concurrency/idempotency keys and correlation metadata.
## Constraints and quantitative acceptance thresholds
Lost leases are reclaimable; conflicting keys serialize; stale output is preserved as superseded evidence but cannot update current state.
## Candidate methods and comparative evidence
Candidates: in-memory queue; PostgreSQL row-lock/skip-locked leases. PostgreSQL is selected for restart durability and transaction coupling.
## Selected method and reasons for rejecting alternatives
Claim eligible jobs transactionally, acquire concurrency-key ownership, heartbeat bounded leases, validate source versions before commit and retry with explicit policy.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Select due unleased/expired rows ordered by available_at/id using row locks/skip locked. Set owner/expiry/attempt. Only owner with live lease may complete. Recheck input versions; stale result records superseded and emits no side effect. Exceeded attempts moves to DLQ and creates deduplicated operational item.
## Parameters, calibration, versioning, and compatibility
Lease/heartbeat/attempt/backoff/job payload/build compatibility are versioned per job type.
## Time and space complexity and resource budgets
Indexed O(log n + batch); bounded batch/pool/memory.
## Errors, degradation, fallback, and forbidden behavior
Build/payload mismatch, lost lease or unknown job fails closed; never hold DB transaction during external I/O.
## Validation cases and evidence
Real PostgreSQL tests for crashes, lease expiry, parallel keys, duplicates, stale version, DLQ and worker isolation.
## Risks and monitoring
Clock skew/long jobs and hot keys; monitor lease expiry, oldest age and retries.
## Human approval
Pending non-AI owner approval.
