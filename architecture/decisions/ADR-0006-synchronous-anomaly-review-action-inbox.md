# ADR-0006: Synchronous anomaly-review Action Inbox checkpoint

- Status: accepted
- Date: 2026-08-24
- Decision owner: project owner
- Approval date: 2026-08-24
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
- Related specification: `SPEC-0001`, `REQ-032` through `REQ-042`, `DEC-040` through `DEC-050`, `DEC-096`
- Related algorithms: `ALG-0015`, `ALG-0016`, `ALG-0017`, `ALG-0018`, `ALG-0019`
- Related review: `architecture/design/action-inbox-wave4.md`

## Context

The next risk-first vertical slice must begin the Action Inbox and company-context experience without letting the browser, AI output, Research domain, or a storage adapter author Workflow state. The current anomaly assessment is immutable and role-safe, but formal Hard is intentionally disabled. Automatic Action Item creation would require a new durable post-commit event consumer; calling Workflow after an anomaly transaction would leave a crash gap and cannot be described as reliable automatic materialization.

## Decision

Use Candidate A from the linked review for the first user-testable Workflow checkpoint: a synchronous, user-initiated creation command that links one immutable actionable anomaly-assessment version to one Server-authoritative Action Item.

- `thesis_trace_application` resolves the authorized anomaly, Evidence and Company context through the Research parent, then maps only Server-owned primitives into `workflow_domain`.
- `workflow_domain` owns Action Item types, creation fingerprint, priority evaluation, safety floor, assignment, lifecycle, query consistency, recurrence relation and its persistence demand port.
- A dedicated PostgreSQL Workflow adapter atomically commits item/evaluation/audit state and executes one-snapshot summary/list/detail queries under RLS.
- The HTTP request accepts item/source identity, expected source version, optional due time, reason and idempotency key. It accepts no assignee, system priority, effective priority, safety lock or source facts.
- The bounded source rule admits succeeded anomaly results requiring human review. Shadow `would_be_hard` is `high` with rule `workflow.shadow-anomaly-review-v1` and is not safety-locked because it is not formal Hard.
- The same Action Item ID and list query are represented in the route. Wide layout retains the list with side detail; narrow layout uses a full detail route and restores the list query/position.
- Dismissal or completion terminates only the Workflow item and never mutates the anomaly, Evidence or audit history.
- Automatic anomaly creation, other domain triggers, deferred wake processing, policy-wide reevaluation, notification and the remaining company-workspace tabs stay outside this checkpoint. Automatic creation must use a durable post-commit subscriber and a separately governed execution/channel design.

## Alternatives considered

### Automatic durable anomaly-result subscriber now

This is the correct eventual architecture for automatic creation, but it adds an outbox event, consumer contract, leased worker, retry/dead-letter semantics, execution unit/channel and operational evidence before the first user path can be validated.

### Post-commit in-process Workflow call

This is smaller but can permanently miss an Action Item if the worker exits after the anomaly commit and before Workflow creation. Idempotency solves duplicates, not that crash gap, so this alternative is rejected for automatic behavior.

### Direct Research adapter or browser creation

Writing Workflow tables from the Research PostgreSQL adapter or retaining a browser-local inbox violates sibling ownership and Server authority and is rejected.

## Consequences

The checkpoint proves the complete Workflow domain, PostgreSQL, API, generated client and responsive inbox route with a real immutable source. It also keeps automatic-delivery reliability claims honest and gives later trigger subscribers one stable Workflow input contract.

The cost is that the Owner explicitly creates the first anomaly-review item. Therefore this checkpoint does not complete every automatic trigger in `REQ-033`, the full company workspace in `REQ-042`, or all related acceptance criteria. Those remain open SPEC-0001 work.

## Validation

Before source edits, the project owner must explicitly accept this ADR and ALG-0015 through ALG-0019, then the schema 2.2.0 design gate must pass. Implementation acceptance requires deterministic policy/state tests, real PostgreSQL uniqueness/version/audit/RLS/query-snapshot tests, API/OpenAPI tests, generated-client verification, responsive desktop/mobile Playwright, architecture development/release gates and two-axis review.

## Approval

Approved by the project owner on 2026-08-24 in `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1` with the explicit instruction: `核准 ADR-0006 與 ALG-0015、ALG-0016、ALG-0017、ALG-0018、ALG-0019 現有內容`.
