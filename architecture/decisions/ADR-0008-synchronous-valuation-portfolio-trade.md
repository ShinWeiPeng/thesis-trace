# ADR-0008: Synchronous Valuation, Portfolio and Trade checkpoint

- Status: accepted
- Date: 2026-08-29
- Decision owner: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
- Related specification: `SPEC-0001`, `REQ-005`, `REQ-006`, `REQ-009`, `REQ-031`, `REQ-032`, `REQ-042`, `REQ-043`, `REQ-048`, `DEC-079`, `DEC-080`, `DEC-082`, `DEC-096`, `DEC-101`, `DEC-102`, `DEC-103`, `DEC-104`
- Related algorithms: `ALG-0008`, `ALG-0009`, `ALG-0010`, `ALG-0011`, `ALG-0012`, `ALG-0014`
- Related review: `architecture/design/valuation-portfolio-trade-wave6.md`

## Context and problem

Wave 6 must replace the Portfolio placeholder and add user-testable Valuation, Cost Profile, cash, holdings, Trades, Allocation and Exposure without moving Valuation out of Thesis, allowing sibling schema access, or letting the browser compute financial authority. Valuation publication and confirmed Trade/allocation/correction are consequential actions that must atomically consume an exact Access challenge with the destination-domain change.

## Decision

Use Candidate A from the linked review: synchronous child-owned policy and persistence coordinated by `thesis_trace_application`.

- `thesis_domain` owns Valuation drafts, peer selections, immutable published snapshots, validity, target/return calculations and ALG-0008/0009/0010 traces.
- `portfolio_domain` owns versioned Cost Profiles and cash, classifications/themes, canonical Trades, allocations, holding ledger, company actions, exposure/risk snapshots and ALG-0011/0012/0014 traces.
- L0 maps exact immutable Research facts and Portfolio Cost Profile values into Thesis-owned valuation input; it maps active Thesis allocation projections into Portfolio-owned targets. Siblings never import contracts or read tables directly.
- Unpublished valuation drafts and ordinary Cost Profile/cash data use explicit versioned saves. Publishing a Valuation snapshot and confirming a Trade/allocation/correction/company action use a five-minute, single-use challenge with a nonblank reason.
- `backend_composition` binds challenge consumption and the destination Thesis or Portfolio mutation in one PostgreSQL transaction through owner adapter seams. L0 sees no SQL/session object.
- The dedicated PostgreSQL Portfolio adapter uses only the `portfolio` schema under forced RLS. Thesis valuation persistence remains in the Thesis adapter/schema.
- The responsive UI adds route-addressable Valuation and Portfolio/Trades projections backed only by generated HTTP contracts. It never computes benchmark, return, holdings, allocation, exposure or feasibility authority.
- This slice does not publish Recommendation or Owner Decision and never calls a broker order API. A broker-specific parser remains absent until a real sample is approved.

## Alternatives considered

### One cross-schema repository

This reduces mapping code but violates owner-schema, demand-owned Port and sibling-dependency invariants and is rejected.

### Durable valuation/trade worker

This isolates request work but adds pending commands, leases, retry/dead-letter behavior, another execution channel and eventual UI consistency for bounded pure policies and PostgreSQL transactions. It is rejected.

## Benefits, costs and tradeoffs

The design keeps Valuation attached to each personal Thesis, makes Portfolio totals authoritative across all buckets, preserves exact transaction/audit history and reuses the established confirmation boundary. It costs explicit L0 mappings, two owner adapters, immutable snapshots/traces and more relational/version modeling.

## Risks and mitigations

- Stale Research, Thesis or Cost Profile inputs could publish an obsolete result. Every preview and confirmation binds exact versions and revalidates them in the destination transaction.
- Allocation could diverge from broker holdings. ALG-0014 conserves confirmed quantity, rejects over-allocation/oversell and records corrections/company actions append-only.
- Decimal or percentile differences could change results. Policies bind explicit versions, DEC-101 interpolation, DEC-102 month-end clamping and golden vectors.
- Private Portfolio data could leak. Server RLS/projection filtering occurs before serialization; email remains outside this slice and cannot receive Portfolio fields.

## Compatibility and migration impact

The change appends Thesis valuation tables/endpoints, a `portfolio` schema and adapter, Portfolio/Trade endpoints, generated contracts and responsive routes. Existing Thesis, Research, Workflow and anomaly contracts remain compatible. Existing records are not reinterpreted; all policies and snapshots are version-bound.

## Validation and observable pass conditions

- planned architecture manifest passes the schema 2.2.0 design gate before source edits;
- all six algorithm records receive explicit non-AI approval;
- Decimal golden/property tests prove DEC-101/102/104, fee/tax/return and cap boundaries;
- trade/allocation tests prove fingerprint idempotency, explicit buckets, no FIFO, corrections and DEC-103 conservation/tie-breaking;
- real PostgreSQL tests prove RLS, grants, optimistic versions, confirmation atomicity, immutable history and rollback;
- API/OpenAPI/generated client and responsive Owner/Learner/Admin tests pass;
- development/release architecture gates and two-axis review pass;
- user-operated acceptance confirms Valuation and Trade/Exposure flows before the slice is complete.

## Approval

Approved by the project owner on 2026-08-29 in `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1` with the explicit instruction: `核准 ADR-0008 與 ALG-0008、ALG-0009、ALG-0010、ALG-0011、ALG-0012、ALG-0014 現有內容`.
