# ADR-0003: Synchronous Owner-confirmed E-stage boundary

- Status: accepted
- Date: 2026-08-20
- Decision owner: project owner
- Approval date: 2026-08-20
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
- Related specification: `SPEC-0001`, `DEC-021`, `DEC-022`, `DEC-096`, `DEC-100`
- Related algorithm: `ALG-0002`
- Related review: `architecture/design/e-stage-wave2.md`

## Context

The next SPEC-0001 slice must add deterministic E0-E6 derivation without giving the browser, Admin, Learner or unconfirmed AI output canonical write authority. Confirmed facts, source snapshot linkage, actor, Server time, reason, record/version, gate trace and audit must stay consistent.

## Decision

Add `evidence_stage` as an L2 child of `research_domain`. Use the synchronous confirmation transaction described as Candidate A in the linked review:

- L0 revalidates the authenticated actor and maps only Owner confirmation commands into Research.
- `evidence_stage` owns confirmed dimension facts, `EvidenceStage`, the `ALG-0002` policy, gate trace, versioned record and persistence demand port.
- The PostgreSQL adapter atomically validates expected version and snapshot membership, then appends confirmed facts, derived stage, gate trace and audit.
- Queries expose Server-authoritative stage projections to Owner and Learner; Admin receives no Research projection.
- The browser submits facts and reason but never submits or computes the canonical stage.
- No background stage job is introduced while evaluation is six pure deterministic gates with no external I/O.

## Alternatives considered

A durable stage-evaluation job would isolate computation from the HTTP request, but adds pending/evaluation states, a queue, lease/retry/dead-letter behavior, another execution mapping and eventual consistency. Reconsider it only if a future accepted policy introduces external I/O or measured computation that cannot remain synchronous.

## Consequences

The stage and facts share one authoritative version and transaction, conflicts fail without partial state, and the UI receives an immediately queryable result. The cost is that confirmation availability follows PostgreSQL request-path availability and a future expensive policy would require a topology review.

## Validation

Before source edits, the schema 2.2.0 design gate must pass with the boundary, ownership, dependency and parent mappings in the linked review. Implementation acceptance requires deterministic policy tests, PostgreSQL transaction/version/audit/RLS evidence, API/OpenAPI tests, generated client checks, responsive Playwright coverage and the development architecture gate.

## Approval

The project owner explicitly approved the current architecture content in the recorded approval reference.
