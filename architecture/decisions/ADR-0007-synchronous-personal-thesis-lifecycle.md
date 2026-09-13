# ADR-0007: Synchronous personal Thesis lifecycle checkpoint

- Status: accepted
- Date: 2026-08-29
- Decision owner: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
- Related specification: `SPEC-0001`, `REQ-007`, `REQ-008`, `REQ-031`, `REQ-032`, `REQ-042`, `REQ-043`, `REQ-047`, `REQ-048`, `REQ-049`, `DEC-023`, `DEC-040`, `DEC-080`, `DEC-081`, `DEC-082`, `DEC-083`, `DEC-086`, `DEC-096`
- Related algorithms: `ALG-0013`, `ALG-0020`, `ALG-0021`, `ALG-0027`
- Related review: `architecture/design/thesis-outcome-reflection-wave5.md`

## Context

The next SPEC-0001 risk-first slice must replace the empty `thesis_domain` seam with a user-testable personal Thesis, Outcome and Reflection lifecycle. Owner and Learner may create their own independent Thesis over shared Company and Evidence records; Admin has no research access. The Server must preserve explicit state transitions, optimistic versions, immutable lifecycle history, predeclared invalidation conditions and role-safe company-workspace routes without allowing the browser, AI output, Research, Workflow or a storage adapter to author Thesis state.

The slice also closes the authority gap recorded by ADR-0005: anomaly assessment may bind an immutable Server-owned Thesis invalidation projection, but formal Hard activation remains disabled. Automatic Outcome/Reflection reminders, valuation, Recommendation, Decision, Trade, allocation and notification are later slices.

## Decision

Use Candidate A from the linked review: synchronous Thesis-owned commands and queries coordinated by `thesis_trace_application`, with one PostgreSQL transaction per accepted mutation.

- `thesis_domain` owns `ThesisStatus`, lifecycle cycles, Thesis versions, published invalidation-condition versions, Evidence links, Outcome versions, Reflection draft revisions, completed Reflection versions, transition policy and its persistence demand port.
- A new personal Thesis always starts as `draft`, cycle 1. It is visible and mutable only to its `owner_user_id`; Owner and Learner have identical authority over their own Thesis, while Admin receives the same unavailable behavior as an absent record.
- Activation requires a nonblank title, nonblank narrative and at least one nonblank predeclared invalidation condition. Conditions may be edited in draft or by an explicit versioned save; historical published condition versions remain immutable.
- The legal direct transitions are `draft -> active`, `active -> paused`, and `paused -> active`. `draft|active|paused -> invalidated`, `active|paused|invalidated -> closed`, and `invalidated|closed -> active` are consequential operations and require an exact five-minute, single-use Server confirmation challenge plus a nonblank reason.
- Invalidation commits immediately and marks the current lifecycle cycle `reflection_pending`, even if no Outcome or Reflection exists. Closing rejects unless the current cycle has an Outcome and a completed Reflection.
- Reopening `invalidated` or `closed` starts a new monotonic lifecycle cycle. Previous Outcome, Reflection, invalidation condition and audit versions remain immutable; the new cycle requires its own later Outcome and Reflection before it can close.
- Outcome structured fields use an explicit save. Reflection long text may use the accepted two-second autosave contract, but each accepted autosave creates a draft revision and never completes the Reflection. Completion is an explicit versioned command.
- `thesis_trace_application` maps authenticated actor primitives, validates role-safe Company and Evidence references through Research, coordinates confirmation challenges, and maps Thesis results into HTTP-safe application projections. Sibling domains do not import or write one another's contracts or tables.
- An anomaly request may optionally bind one `thesis_id`, expected Thesis version and published invalidation-condition version. L0 obtains an immutable `ThesisInvalidationProjection` from Thesis and maps only primitives into Research. Missing, stale, unrelated or unauthorized Thesis state fails closed at the invalidation gate. The client and AI cannot submit the authoritative condition text or match result.
- A dedicated PostgreSQL Thesis adapter implements the Thesis-owned port in the `thesis` schema. Every accepted command atomically appends current/version state, immutable history, actor, Server time, reason, policy/build version and idempotency receipt. No cross-schema direct write is permitted.
- The responsive company workspace adds route-addressable Theses and Outcomes/Reflections views backed by the same Server records. URL owns company, tab and selected Thesis identity; form drafts remain volatile except for accepted Server draft revisions.

## Alternatives considered

### Candidate B: durable Thesis lifecycle worker

A worker could serialize every lifecycle command through a queue. This adds pending command state, leases, retries, dead-letter behavior, a new execution unit/channel and eventual UI consistency without external I/O or unbounded computation. The current transition and validation policy is bounded and transactional, so this candidate is rejected.

### Candidate C: one mutable document or browser-owned Thesis store

A JSON document or client global store would make the first UI smaller, but it cannot enforce append-only lifecycle cycles, field-level authority, relational Evidence links, RLS, optimistic conflicts or immutable Outcome/Reflection history. It also creates a second source of truth and is rejected.

### Candidate D: put Thesis lifecycle in Research or Workflow

Research owns shared Evidence and anomaly assessment; Workflow owns human-action tracking. Letting either sibling own personal Thesis state or write the `thesis` schema violates the confirmed ownership model and makes later valuation, Recommendation and allocation boundaries ambiguous. This candidate is rejected.

## Consequences

The checkpoint provides a complete personal research lifecycle and a real Thesis-owned invalidation authority for shadow anomaly assessment. Reopen cycles make repeated research episodes traceable without rewriting earlier outcomes or reflections. Synchronous commands keep the UI result and persisted version consistent.

The cost is explicit version/cycle modeling, a new adapter/schema/grant/RLS surface, confirmation orchestration and autosave conflict handling. The checkpoint does not complete automatic reminder Action Items, formal Hard activation, valuation, Recommendation, Decision, Trade, portfolio or notification requirements; those remain open SPEC-0001 work.

## Risks and mitigations

- Cross-domain Company/Evidence validation could race. L0 binds exact Research record versions and the Thesis transaction rejects stale mappings.
- Reopening could accidentally overwrite prior learning. A new lifecycle cycle is mandatory and all prior Outcome/Reflection versions remain immutable.
- Draft autosave could be mistaken for publication. Draft revisions are separately typed and completion/activation require explicit commands.
- A client could forge a Hard invalidation. The anomaly API accepts only Thesis/version identities; L0 loads the authoritative projection and Research recomputes policy.
- Private Thesis data could leak through company summaries. Server-side RLS and projection filtering occur before counts/cards are computed.

## Compatibility and migration impact

The change adds the `thesis` schema, a Thesis adapter, application flow, HTTP endpoints, generated client contracts and company-workspace routes. Existing Company, Evidence, anomaly and Action Inbox contracts remain compatible. The anomaly request gains optional Thesis binding fields; requests without them retain the current fail-closed missing-invalidation behavior. Existing anomaly records are not reinterpreted.

## Validation

Before source edits, the project owner must explicitly accept this ADR and ALG-0013, ALG-0020, ALG-0021 and ALG-0027, then the schema 2.2.0 planned-manifest design gate must pass. Implementation acceptance requires deterministic transition/property tests, confirmation-challenge and autosave tests, real PostgreSQL version/idempotency/audit/RLS/rollback tests, cross-domain stale-reference tests, API/OpenAPI and generated-client checks, responsive Owner/Learner/Admin Playwright coverage, architecture development/release gates and two-axis Standards/Spec review.

## Approval

Approved by the project owner on 2026-08-29 in `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1` with the explicit instruction: `核准 ADR-0007 與 ALG-0013、ALG-0020、ALG-0021、ALG-0027 現有內容`.
