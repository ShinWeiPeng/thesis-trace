# ADR-0001: Adopt modular event architecture

- Status: accepted
- Date: 2026-08-18
- Approver: project owner
- Approval date: 2026-08-20
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`

## Context

thesis-trace needs explicit module boundaries, data flow, event behavior, and machine-checkable dependency rules.

## Decision

Adopt the pinned modular event architecture described by `architecture/manifest.yaml`.

## Alternatives considered

- Documentation-only governance.
- Framework-specific layering.
- Unconstrained per-change architecture decisions.

## Benefits, costs, and tradeoffs

The standard improves traceability, testing, and replaceability. It adds manifest, Type Catalog, adapter, validation, and generated-view maintenance.

## Risks and mitigations

Avoid over-abstraction by requiring ports only at module and external-technology boundaries.

## Compatibility and migration

For existing projects, preserve exact known violations in a baseline and prevent new violations.

## Validation

Run the project checker and applicable language analyzers. All MUST diagnostics must be resolved, baselined as pre-existing, or covered by a user-approved ADR.
