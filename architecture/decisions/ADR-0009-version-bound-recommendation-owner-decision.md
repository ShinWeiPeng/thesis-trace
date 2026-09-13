# ADR-0009: Version-bound Recommendation and atomic Owner Decision

- Status: accepted
- Date: 2026-09-05
- Decision owner: project owner
- Related specification: SPEC-0001, REQ-004/005/006/031/033/039/042/043/047/048/049, DEC-079/080/085/095/096/105
- Related algorithms: ALG-0032, ALG-0033, ALG-0034; reuse accepted ALG-0008/0009/0010/0011/0012/0020/0027
- Related review: [Wave 7 design](../design/recommendation-owner-decision-wave7.md)

## Context

Wave 6 publishes immutable Thesis valuation snapshots and maintains Portfolio/Trade state. Recommendation remains a reserved L1 seam. The existing application RecommendationProvider/RecommendationCritic contracts actually carry anomaly schemas: a succeeded anomaly assessment is not a validated investment recommendation.

DEC-105 now defines expiry: undecided/deferred recommendations expire when their bound valuation becomes invalid or a decision-critical input version changes; no independent fixed lifetime is added. Accepted/rejected decisions remain immutable history. A five-minute confirmation challenge is not the Recommendation validity window.

## Decision proposed for approval

Use Candidate A: immutable input admission and isolated AI processing, followed by synchronous, transaction-scoped domain coordination for publication, Owner Decision and Recommendation-related Workflow state.

1. `recommendation_domain` owns analysis-request/job identity, frozen input bindings, strictly validated candidate/critic evidence, publication policy, immutable Recommendation versions, append-only Owner Decisions, current decision projection, expiry policy and persistence demand. It does not own valuations, holdings, trading or Workflow state.
2. `thesis_trace_application` is the shared parent. It obtains exact authorized Research, Thesis and Portfolio projections and maps values/identities into Recommendation-owned contracts. Siblings never import one another or read sibling schemas. Financial formulas remain in Thesis/Portfolio, not in the provider or Recommendation adapter.
3. Owner request admission binds a personal active Thesis/cycle and published valuation, explicitly reconfirms that Recommendation's benchmark source and reason, and pins Evidence, predeclared conditions, peer group, Cost Profile, official prices/classifications/themes, portfolio, minimum-return policy and algorithm/model/prompt/schema/build identities. The browser submits identities and intent, not source values, eligibility or risk results.
4. The admission transaction stores immutable inputs, audit and a typed durable job. The isolated `ai-worker` performs provider/critic calls outside database transactions. Add distinct investment-candidate/critic methods and schemas; do not repurpose the existing anomaly methods or mix outputs. Claude and formal Hard remain gated exactly as before.
5. Publication revalidates actor scope, the entire decision-critical binding and lease. It runs the accepted financial policies for the final candidate size, stores an immutable Portfolio-owned risk snapshot, then atomically appends the Recommendation and its Owner-assigned Action Item through each owner's service/store. No post-commit callback is used as a substitute for reliable automatic materialization.
6. `postgres_atomic_adapter` binds request-scoped owner stores to one transaction behind an application-owned semantic port. It coordinates Access/Research/Thesis/Portfolio/Recommendation/Workflow adapters but writes no sibling table itself and passes no SQLAlchemy object into L0/L1. Stable lock ordering and reference revalidation apply to every competing writer.
7. Accept/reject use ALG-0020 two-step confirmation and a nonblank reason. Confirmation consumption, append-only Decision, current projection, Workflow outcome, audit and receipt commit or roll back together. Deferred is an explicit low-risk versioned command, not autosave; its reminder time never extends input validity. Accepting a recommendation does not create a Trade, reserve cash or place an order.
8. Expiry uses DEC-105. Relevant version changes invalidate only recommendations which bound those inputs; ordinary unrelated notes are not critical input changes. Background reconciliation persists expiry plus Workflow outcome atomically. Every accept/preview path independently rechecks validity, so delayed background work cannot permit stale acceptance. Read-only views distinguish input validity from the persisted decision history and expose no legal accept action when stale.
9. First user-testable Wave 7 scope supports `buy`, `hold`, and `abstain`, including explicit blocked/failure explanations. Target-tranche reduction/exit Recommendation generation is a follow-on checkpoint: it must not be synthesized from Shadow Hard or guessed from historical sells. This is sequencing under DEC-096, not removal of REQ-006. Email, Claude activation, broker order APIs and formal Hard activation remain outside this checkpoint.
10. Use a company Recommendations route with exact record/version deep links and return context to the existing Inbox. Render human-readable source/valuation/risk reasons and decision history; never default to raw JSON. Missing reason, stale input, expiry or unavailable provider must have an accessible explanation and recovery action, not an unexplained disabled button.

## Alternatives and tradeoffs

- Candidate B: synchronous AI in the API. Fewer durable states, but violates isolated AI execution and couples core request availability to provider latency; rejected.
- Candidate C: publish Recommendation, then update Workflow in an in-process callback. Fewer transaction participants, but a crash leaves a permanently missing/stale human task; rejected.
- Candidate D: separate durable Workflow subscriber. Functionally viable, but adds independent delivery lag, receipt, retry/dead-letter and reconciliation contracts. Reconsider when independent durable subscribers are required. Candidate A concentrates the currently required user-visible invariant in one transaction, at the cost of more participants and possible lock contention.
- A cross-schema domain repository is not an alternative: it violates existing owner boundaries.

Selection is based on correctness and topology, not a measured performance advantage. Flow cost assurance is `estimated`; platform capacity/latency assurance remains unclaimed.

## Compatibility, migration and known remediation

Add normalized `recommendation` current/request/job/reference/decision/audit/receipt tables and owner-scoped immutable Portfolio risk snapshot storage, with forced RLS and append-only protections. JSON may hold bounded immutable calculation/critic traces, never the only mutable aggregate authority. Migration is additive; existing data and policies are not reinterpreted. New API/client routes are additive and existing anomaly schemas stay byte-compatible.

The existing `select_dca_multiplier` uses notional as cash outflow without fees. That contradicts accepted ALG-0012 and must be repaired with final-size fee/tax/return and exposure tests before it can support a buy. This is required conformance work, not permission to change caps or historical results.

## Validation and approval boundary

The planned design gate must pass; the complete pre-code catalog must be revalidated whenever implementation introduces a named type, mapping or execution detail. Approval of this ADR is not a runtime PASS. Required implementation evidence is recorded in the linked design: pure policies/Fake Clock, real PostgreSQL RLS/atomicity/leases/concurrency, strict provider contract tests, generated API/client checks, responsive user flow, and two-axis review. No Wave 7 product completion is claimed before these pass and the Owner completes user acceptance.

## Human approval

- Approver: project owner
- Approval date: 2026-09-05
- Approval reference: ongoing SPEC-0001 conversation, explicit instruction `核准 ADR-0009 與 ALG-0032、ALG-0033、ALG-0034`.
- Scope: the current architecture and algorithm contents; no formal Hard, Claude or runtime activation is implied.
