# ADR-0001: Modular Event Architecture for the First Walking Skeleton

- Status: proposed
- Date: 2026-08-18
- Decision owner: project owner
- Approval: pending non-AI approval
- Related specification: `SPEC-0001`, `DEC-079`, `DEC-096`, `DEC-097`, `DEC-098`
- Related review: `architecture/design/walking-skeleton-flow-review.md`

## Context

ThesisTrace is a modular monolith deployed as one FastAPI application with PostgreSQL, plus independent worker processes and a responsive React client. Its first user-visible slice must accept an authenticated Owner's Evidence URL for a selected or newly created Company, atomically preserve admission state, audit and durable work, retrieve the source in an independent collector, preserve immutable provenance/deduplication, and expose only Server-authoritative status to the UI.

The design must preserve L0/L1/L2 sibling boundaries, demand-owned ports, framework-free functional contracts, commit-before-publication, at-least-once delivery and explicit failure behavior. It must not pre-implement AI, E0-E6, anomaly, Thesis, valuation or Recommendation responsibilities.

## Decision

Adopt the modular event boundaries described in the linked flow review and use Candidate A, a typed durable collector job that also serves as the first slice's outbox work item.

- `thesis_trace_application` is the L0 composition/orchestration owner and the only release composition root.
- `access_domain` and `research_domain` are L1 siblings; L0 maps `VerifiedPrincipal` into `ResearchActorContext`.
- `company_catalog` and `evidence_intake` are L2 children of Research; Research maps Company references into Evidence targets.
- Functional modules own their commands, queries, events and external demand ports. React, FastAPI, Cloudflare JWT, PostgreSQL, HTTP/DNS and worker representations remain adapter-private.
- The admission transaction atomically persists the Evidence intake in `received`, append-only audit entry and typed collector job. It returns the committed `intake_id/version` immediately.
- The collector uses leased, at-least-once claims and idempotent terminal transitions. It commits canonical snapshot/provenance or retry/failure/dead-letter state before publishing the corresponding event.
- The UI never treats an event or local state as domain truth; events or polling only trigger a versioned Server query.
- Persistent events use stable IDs, correlation/causation context, stream sequence and retry metadata. Same-stream work is serialized; different intake streams may run concurrently.

## Alternatives considered

### Candidate A: durable job-as-outbox

The collector claims the typed durable job written by the admission transaction. This has one durable queue boundary and the smallest crash/recovery surface that satisfies DEC-098.

### Candidate B: domain outbox plus dispatcher and collector queue

A dispatcher transforms a durable domain outbox event into a separate collector job. This better isolates multiple durable subscribers, but adds an execution unit, durable channel, claim/commit pair, queue wait, serialized contract and failure/recovery path. The first slice has only one durable consumer, so those costs are not justified yet.

## Rationale

Both candidates pass functional admission when fully contracted. Candidate A is selected because it meets atomicity, reliability, ownership and worker-isolation requirements with fewer load-bearing transitions. Candidate B remains the preferred reconsideration trigger when two or more subscribers require independent durable retry, offset, scaling or deployment.

This selection is based on functional topology and static cost comparison. Assurance is `estimated`; it does not establish a platform latency, throughput, capacity, memory or real-time winner.

## Consequences

Positive consequences:

- The first slice proves a complete production-shaped flow without speculative dispatcher infrastructure.
- Admission cannot leave intake, audit or durable work partially committed.
- Framework, wire and storage types cannot leak into L0-L2 contracts.
- Collector crashes and duplicate delivery are recoverable through lease and idempotency rules.
- URL/content deduplication and provenance remain Server-owned.

Costs and constraints:

- A future independently durable subscriber may require migration to Candidate B and a new ADR/flow review.
- The job contract must be explicitly versioned because it is both durable work and the initial outbox boundary.
- Queue, lease, retry, fetch and deduplication parameters must be confirmed before implementation claims operational readiness.
- All platform performance/capacity claims remain `BLOCKED` until release-equivalent evidence exists.

## Validation and acceptance

This ADR remains `proposed`; Codex cannot approve it. Before product source edits, the project owner must approve the architecture package and the schema 2.2.0 design-phase architecture gate must pass.

Implementation acceptance requires:

- atomic PostgreSQL transaction/outbox rollback tests;
- leased claim, crash recovery, retry and dead-letter tests;
- normalized-URL/content-hash concurrency and deduplication tests;
- restricted source-fetch and sanitized-error contract tests;
- Cloudflare JWT fail-closed tests;
- API/OpenAPI record/version contract tests;
- responsive Playwright status flow tests;
- development architecture gate and generated-view stale checks.

Runtime calibration is required before claiming numeric latency, throughput, capacity or resource headroom. Missing target/build binding, queue capacity, retry/lease parameters, fetch bounds, isolation/uniqueness details, SSRF policy or load/error-path coverage yields `BLOCKED`, not a performance PASS.

## Reconsideration triggers

Reopen this decision when:

- at least two durable subscribers need independent retry, offset, scaling or deployment;
- a measured bottleneck shows the selected queue topology cannot meet an approved product budget;
- a storage or deployment constraint prevents atomic intake/audit/job commit;
- contract evolution cannot preserve compatible versioned jobs;
- the formal manifest or runtime evidence contradicts an assumption in the flow review.
