# Action Inbox and Company Context Wave 4

- Spec decisions: `DEC-040`, `DEC-041`, `DEC-042`, `DEC-043`, `DEC-045`, `DEC-047`, `DEC-048`, `DEC-049`, `DEC-050`, `DEC-096`
- Algorithms: `ALG-0015`, `ALG-0016`, `ALG-0017`, `ALG-0018`, `ALG-0019`
- Owning domain: `workflow_domain` (L1)
- Application flow: `owner_anomaly_review_action`
- Timing class: best-effort
- Review status: Candidate A proposed through ADR-0006
- Assurance: functional design only; no numeric performance claim

## Decision boundary

This bounded vertical slice lets the authenticated Owner create one Server-authoritative manual Action Item from an immutable anomaly-assessment version, then query, open, defer, dismiss, complete, or mark that item in progress through the same responsive inbox and company context. The Server resolves the anomaly, Evidence, Company, assignee, priority, safety floor, fingerprint and allowed transitions; the browser submits only intent and never authors those facts.

This checkpoint does not claim every `REQ-033` automatic trigger, deferred wake worker, policy-wide reevaluation, automatic notification, Thesis/Trade/Outcome trigger, or the complete company workspace. In particular, a shadow `would_be_hard` result is not a formal Hard anomaly and is therefore high-priority but not safety-locked. Later automatic materialization must introduce a durable post-commit anomaly event subscriber before it may claim crash-safe automatic Action Item creation.

## Candidate comparison

### Candidate A: synchronous, user-initiated anomaly-review item

L0 resolves the immutable anomaly and its Evidence/Company context through the Research parent, maps only Server-owned primitives into `workflow_domain`, and invokes a Workflow-owned synchronous creation command. `workflow_domain` applies `ALG-0015`, `ALG-0016`, and `ALG-0018`; a dedicated PostgreSQL adapter atomically commits the item, priority evaluation and append-only audit. Query and transition commands apply `ALG-0017` and `ALG-0019` through the same domain-owned port.

This produces a complete, user-testable UI/API/PostgreSQL slice without pretending that a post-commit call is an automatic reliable subscriber. The immutable source version means the validation-to-create interval cannot rewrite the source; a missing, stale, unauthorized or non-actionable assessment fails closed.

### Candidate B: automatic anomaly-result subscriber

The anomaly result transaction would append a durable event; a separate Workflow consumer would claim it, map it through L0, and idempotently create the item. This is the required shape for future automatic creation, but it adds an outbox contract, claim/retry/dead-letter lifecycle, worker execution unit, channel and operational evidence. Those elements are not yet needed to validate the first manual Action Inbox path.

### Candidate C: direct browser or Research-table Action Item creation

Browser-local items, client-authored priority/assignee/source facts, or direct writes from the Research PostgreSQL adapter into Workflow tables are rejected. They create duplicate authority, bypass Workflow policy, or couple sibling domain storage.

## Boundary Design Table

| ID | Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `anomaly-to-action-context` | Resolve an immutable anomaly assessment into actionable Company/Evidence primitives | `research_domain` | `workflow_domain` | `thesis_trace_application` | `ResearchAnomalyResult` plus Server-resolved Company projection | `CreateActionItemCommand` | `thesis_trace_application` | immutable anomaly, Evidence and Company rows | L0 -> Research; L0 -> Workflow | Research -> Workflow; Workflow -> Research |
| `actor-to-workflow-assignee` | Map the revalidated Owner into the only legal personal assignee for this bounded item class | `access_domain` | `workflow_domain` | `thesis_trace_application` | `AuthenticatedActor` | `WorkflowActorContext` | `thesis_trace_application` | current active account/version | L0 -> Access; L0 -> Workflow | client/AI chooses assignee; Workflow imports Access types |
| `http-to-action-command` | Map generated HTTP intent into an application command without authority fields | `fastapi_entrypoint` | `thesis_trace_application` | `thesis_trace_application` | adapter-private request DTO | `CreateAnomalyReviewActionRequest` | `thesis_trace_application` | none | FastAPI -> L0 | FastAPI -> PostgreSQL or Research/Workflow private contracts |
| `workflow-to-postgres` | Commit Action Item, evaluation and audit atomically | `workflow_domain` | `postgres_workflow_adapter` | `workflow_domain` | `ActionItemStorePort` semantic values | adapter-private rows | `workflow_domain` | Workflow item/evaluation/audit tables | adapter implements Workflow-owned port | domain imports SQL; Research adapter writes Workflow tables |
| `inbox-query-to-react` | Return counts, page, cursor and as-of from one Server snapshot | `thesis_trace_application` | `react_workflow_adapter` | `thesis_trace_application` | application result | generated OpenAPI DTO | `thesis_trace_application` | none | Workflow -> L0 -> FastAPI -> generated client | browser recounts hidden data or computes priority |
| `action-to-company-route` | Preserve Action Item and list query while opening Company context | `react_workflow_adapter` | `react_workflow_adapter` | `thesis_trace_application` | Server route target | responsive route state | `react_workflow_adapter` | volatile navigation state only | generated DTO -> route | browser persistent domain cache |

## Type Ownership Matrix

| Type | Semantic kind | Owner | Mutation authority | Consumers | Boundary rule |
| --- | --- | --- | --- | --- | --- |
| `ActionItemStatus`, `ActionPriority`, `ActionItemType` | policy enums | `workflow_domain` | none | Workflow policy/store; parent maps primitives | browser values are wire-only and never authority |
| `WorkflowActorContext` | immutable domain value | `workflow_domain` | L0 mapping only | Workflow service | contains actor ID and capabilities, not Access types |
| `ActionSourceRef` | immutable domain value | `workflow_domain` | Server mapping only | Workflow service/store | binds source domain, record ID, version, fingerprint and Company |
| `CreateActionItemCommand` | command | `workflow_domain` | authenticated intent admitted by L0 | Workflow service/store | excludes client priority, safety lock and assignee |
| `TransitionActionItemCommand` | command | `workflow_domain` | legal assignee through Server | Workflow service/store | expected version, idempotency and required reason/time are mandatory |
| `ActionPriorityEvaluation` | policy result | `workflow_domain` | `ALG-0016` only | Workflow service/store/query | preserves system/effective priority, floor, rule IDs/version and explanation |
| `ActionItem` | versioned aggregate projection | `workflow_domain` | Workflow service plus store commit | Workflow facade, PostgreSQL adapter | terminal history is immutable; source records are never mutated |
| `ActionInboxQuery`, `ActionInboxPage` | query and result | `workflow_domain` | Server query policy only | L0/FastAPI via primitive mapping | counts and rows share one authorization scope/as-of |
| `ActionItemStorePort` | demand-owned port | `workflow_domain` | none | PostgreSQL Workflow adapter | semantic create/query/transition operations only |
| application requests/results | composition mappings | `thesis_trace_application` | none | FastAPI and Workflow facade | cross L1 boundaries using primitives, never private domain types |
| HTTP DTOs and generated client DTOs | wire representations | adapters | adapter-local | FastAPI/React | no assignee, system-priority or safety authority on input |
| React inbox route state | volatile runtime state | `react_workflow_adapter` | current component/router | React only | query encoded in route; no domain persistence |

## State Object Ownership Matrix

| State object | Owner | Lifetime | Mutation authority | Concurrency/version rule | Persistence |
| --- | --- | --- | --- | --- | --- |
| Action Item stream | `workflow_domain` | durable | Workflow policy after authorized command | optimistic version; terminal states never reopen | `workflow.action_items` |
| material trigger fingerprint | `workflow_domain` | durable | `ALG-0015` only | unique creation-rule/source/fingerprint identity | indexed columns on item |
| priority evaluation history | `workflow_domain` | durable append-only | `ALG-0016` only | new evaluation version; historical terminal item values unchanged | `workflow.action_priority_evaluations` |
| Action Item audit | `workflow_domain` | durable append-only | same create/transition transaction | actor, reason, from/to status, version and Server time immutable | `workflow.audit_events` |
| inbox read snapshot | PostgreSQL transaction under Workflow authority | one query | database MVCC | counts and page use one repeatable-read as-of | not persisted separately |
| filter/detail/navigation state | `react_workflow_adapter` | route/component lifetime | browser interaction | URL encodes selected item and query; reload reconstructs from Server | memory and URL only |

The domain services retain no mutable global, static, thread-local or cross-address-space object; the manifest therefore needs no mutable `state_objects` entry for this slice.

## Actual and intended dependency edges

| Edge | Current | Intended | Rule |
| --- | --- | --- | --- |
| `thesis_trace_application -> research_domain` | present | retained | L0 resolves immutable source context |
| `thesis_trace_application -> workflow_domain` | declared, planned | implemented | L0 maps actor/source primitives and coordinates the two siblings |
| `fastapi_entrypoint -> thesis_trace_application` | present | retained | HTTP implements application input ports |
| `backend_composition -> workflow_domain` | absent | added | composition constructs Workflow service/facade |
| `backend_composition -> postgres_workflow_adapter` | absent | added | composition selects concrete Workflow persistence |
| `postgres_workflow_adapter -> workflow_domain` | absent | added | adapter implements domain-owned port |
| `react_workflow_adapter -> fastapi_entrypoint` | HTTP only | added through generated client | no domain import |
| `research_domain -> workflow_domain` | absent | forbidden | sibling mapping belongs to L0 |
| `postgres_research_adapter -> workflow_domain` | absent | forbidden | Research storage cannot create Workflow state |
| `workflow_domain -> research_domain` | absent | forbidden | Workflow consumes mapped immutable primitives only |

## Parent mappings

| Mapping | Parent owner | Input | Output | Failure behavior |
| --- | --- | --- | --- | --- |
| authenticated actor to Workflow actor | `thesis_trace_application` | `AuthenticatedActor` | `WorkflowActorContext` | reject non-Owner creation and any non-assignee mutation |
| anomaly assessment to Action source | `thesis_trace_application` | role-safe Research anomaly/Evidence/Company projection | `ActionSourceRef` | absent, stale, non-actionable or unauthorized source is uniformly unavailable |
| Workflow aggregate to application result | `thesis_trace_application` | Workflow parent projection | API-safe primitive result | hidden/absent item returns the same unavailable response |
| application result to responsive route | `thesis_trace_application` | page/detail DTO | generated-client React view | Server rejection discards optimistic UI state and reloads current version |

## Flow and failure contract

1. Revalidate the session and require Owner creation authority.
2. Query the exact anomaly assessment/version through Research and resolve its Evidence/Company context. Only `succeeded` results whose route requires human review or whose class is `would_be_hard` are actionable in this checkpoint.
3. Map Server primitives into Workflow. Run `ALG-0015`, `ALG-0016`, and `ALG-0018`; a shadow `would_be_hard` receives system priority `high`, rule `workflow.shadow-anomaly-review`, and no safety lock.
4. Atomically insert the item, initial evaluation and audit. A duplicate idempotency key or identical fingerprint returns the existing item; mismatched retry data rejects.
5. Query summary counts and ordered rows under `ALG-0019` from one repeatable-read transaction and return one as-of/cursor contract.
6. Apply `ALG-0017` transitions with expected version, Server time, assignee authorization and append-only audit. This checkpoint has no safety-locked source type, but the state machine must still reject forbidden safety transitions in unit/contract tests.
7. Render the responsive summary/list/detail route. Wide layout retains the list and opens a side detail; narrow layout uses a full detail page whose URL retains the encoded list query and return location.

Every rejected create or transition writes no partial item or audit. Dismiss and complete never modify the anomaly or Evidence source. Client/AI supplied assignee, priority, safety or source facts are forbidden by the request schema.

## Static flow-cost review

Candidate A adds one Research query plus one Workflow transaction to a user command, then one indexed repeatable-read query per inbox refresh. Candidate B adds a durable event append, worker claim, retry/dead-letter lifecycle and eventual UI refresh. Both are best-effort and no numeric latency or throughput budget is claimed. Candidate A has fewer execution units and failure transitions for the bounded manual path; automatic triggers remain a separate Candidate-B follow-up.

## Validation conditions

Product source edits may begin only after ADR-0006 and ALG-0015 through ALG-0019 receive explicit non-AI approval and the schema 2.2.0 design gate passes. Completion of this checkpoint requires deterministic policy/state tests, real PostgreSQL uniqueness/version/audit/RLS/query-snapshot tests, API/OpenAPI authority tests, generated-client verification, responsive desktop/mobile Playwright coverage, repository validation, development and release architecture gates, and two-axis Standards/Spec review. The handoff must label unimplemented automatic triggers and full company-workspace tabs as later SPEC-0001 work.
