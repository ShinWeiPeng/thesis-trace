# ADR-0004: Backend composition-root seam

- Status: accepted
- Date: 2026-08-21
- Decision owner: project owner
- Approval date: 2026-08-21
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
- Related specification: `SPEC-0001`
- Related decisions: `ADR-0002`, `ADR-0003`
- Related review: `architecture/design/e-stage-wave2.md`
- Proposed exception: `DEP001` at `backend_composition->thesis_trace_application`

## Context

`backend_composition` is the release bootstrap that selects concrete adapters and constructs the application. The E-stage slice makes its existing responsibility explicit by constructing `EvidenceStageFlow` and `ResearchStageFacade`. This creates one direct dependency from the L0 composition module to the peer L0 application-orchestration module.

The generic sibling rule rejects every L0-to-L0 edge. Removing this edge without an exception would require merging the composition and orchestration modules. That merge would also create a dependency cycle because the composition root constructs the FastAPI adapter while the adapter invokes public application input contracts, or it would require a broader delivery-boundary refactor unrelated to E-stage behavior.

## Decision

Retain the separate `backend_composition` release bootstrap and grant one exact `DEP001` exception for `backend_composition->thesis_trace_application`.

- The exception permits construction and wiring through public application contracts only.
- `backend_composition` owns no product policy, domain state, command semantics, or application result types.
- No other L0 sibling dependency is permitted by this decision.
- `backend_composition` may separately depend on `research_domain` because L0 composition-to-L1 construction is allowed without an exception.
- FastAPI continues to implement the public application confirmation/query input ports; it does not import Evidence Stage L2 contracts.

## Alternatives considered

### Merge composition and orchestration

This would align the module name with ADR-0002's conceptual composition owner, but it couples framework/adaptor construction to application orchestration and creates a FastAPI-to-application dependency cycle unless the HTTP boundary is redesigned.

### Redesign the delivery boundary now

Splitting the FastAPI adapter behind a new inversion seam could remove the cycle before merging modules. It changes the established walking-skeleton boundary and substantially expands the current E-stage checkpoint.

## Benefits, costs, and tradeoffs

The benefit is an explicit, narrow and machine-auditable release bootstrap seam without expanding the E-stage implementation. The cost is one governed L0 sibling edge.

The decision preserves framework and adapter construction in one release bootstrap and keeps product policy in `thesis_trace_application`. In exchange, the architecture carries one permanent exception that reviewers and tooling must continue to distinguish from ordinary sibling dependencies.

## Risks and mitigations

Mitigations:

- scope the exception to the exact dependency edge;
- keep product orchestration in `thesis_trace_application` and concrete selection in `backend_composition`;
- require Type Catalog references and actual/intended dependency tables to remain synchronized;
- reopen this ADR if another L0 sibling edge is requested or the delivery boundary is redesigned.

The primary risk is treating this exception as permission for additional composition-to-application coupling. The exact rule/location scope and reopen trigger prevent that expansion.

## Compatibility and migration impact

The decision changes no HTTP, application, domain, storage, event, or generated-client contract. Existing release composition remains compatible. A future merge of composition and orchestration, or a delivery-boundary inversion that removes this edge, must remove the manifest exception and supersede this ADR.

## Validation

After explicit project-owner approval, register the exact exception in `architecture/manifest.yaml`, render generated views, and require development and release architecture gates plus Standards review to pass.

## Approval

Approved by the project owner on 2026-08-21 in `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1` with the explicit instruction: `核准 ADR-0004 現有架構內容`.
