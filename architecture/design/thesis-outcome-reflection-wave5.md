# Thesis, Outcome and Reflection Wave 5

- Spec decisions: `DEC-023`, `DEC-040`, `DEC-080`, `DEC-081`, `DEC-082`, `DEC-083`, `DEC-086`, `DEC-096`
- Algorithms: `ALG-0013`, `ALG-0020`, `ALG-0021`, `ALG-0027`
- Owning domain: `thesis_domain` (L1)
- Application flow: `personal_thesis_lifecycle`
- Timing class: best-effort
- Review status: Candidate A proposed through ADR-0007
- Assurance: functional design only; no numeric performance claim

## Decision boundary

This bounded vertical slice lets an authenticated Owner or Learner create, read and operate only their own Thesis within a shared Company context, link shared Evidence by immutable identity/version, publish predeclared invalidation conditions, record Outcomes, draft and complete Reflections, and close or reopen lifecycle cycles. Admin has no Thesis projection. Server commands own state, policy, versions, time, audit and confirmation; the browser submits intent only.

The checkpoint excludes valuation, Recommendation, Decision, Trade/allocation, automatic Outcome/Reflection Action Items, notifications and formal Hard activation. It does provide the immutable Thesis invalidation projection needed by the existing shadow anomaly gate.

## Candidate comparison

### Candidate A: synchronous Thesis-owned transaction

L0 validates Access and exact Research references, maps primitives into a Thesis command, and invokes a Thesis-owned policy/service. A dedicated adapter atomically validates expected versions and commits current state, immutable version/history rows, idempotency and audit. Consequential transitions first use the existing Server challenge mechanism. The command returns one committed projection.

This keeps a bounded state-machine operation immediately consistent and introduces no new process, queue, lease or pending state. The only I/O is bounded PostgreSQL and role-safe sibling queries completed before the Thesis transaction.

### Candidate B: durable lifecycle command worker

Queueing lifecycle commands isolates request work but adds an unnecessary pending lifecycle, retry ambiguity, new execution unit/channel and eventual consistency. No external provider or measured expensive computation justifies it.

### Candidate C: mutable document/client store

One mutable Thesis JSON record or a browser domain store reduces tables and mappings but cannot prove relational references, RLS, immutable cycles, field-specific autosave, optimistic concurrency and append-only Outcome/Reflection history. It is rejected.

## Boundary Design Table

| ID | Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `access-to-thesis-actor` | Map the revalidated account into personal Thesis capabilities | `access_domain` | `thesis_domain` | `thesis_trace_application` | `AuthenticatedActor` | `ThesisActorContext` | `thesis_trace_application` | current account/role/version | L0 -> Access; L0 -> Thesis | Access -> Thesis; client chooses owner |
| `research-to-thesis-context` | Validate shared Company and Evidence identities without transferring ownership | `research_domain` | `thesis_domain` | `thesis_trace_application` | role-safe Company/Evidence projections | `ThesisResearchReference` primitives | `thesis_trace_application` | immutable Company/Evidence IDs and versions | L0 -> Research; L0 -> Thesis | Thesis -> Research; Thesis adapter reads Research tables |
| `http-to-thesis-command` | Map generated HTTP intent into explicit create/save/transition/outcome/reflection commands | `fastapi_entrypoint` | `thesis_trace_application` | `thesis_trace_application` | adapter-private DTOs | application request types | `thesis_trace_application` | none | FastAPI -> L0 | arbitrary PATCH; FastAPI -> Thesis private contracts |
| `thesis-to-confirmation` | Preview and consume exact consequential lifecycle operations | `thesis_domain` | `confirmation_challenge` | `thesis_trace_application` | `ThesisTransitionPreview` | `ConfirmationChallenge` | `thesis_trace_application` | target Thesis version and payload digest | L0 -> Thesis; L0 -> Access confirmation | Thesis -> Access child; challenge mutates Thesis |
| `confirmed-thesis-transaction` | Consume one exact challenge and commit the matching Thesis transition in one PostgreSQL transaction | `thesis_trace_application` | Access and Thesis owner adapters | `backend_composition` | `ThesisConfirmedTransitionPort` primitives | owner-adapter transaction methods | `postgres_atomic_adapter` | one Access challenge row plus one Thesis stream/version/history/audit | composition -> atomic adapter -> Access/Thesis adapters | L0 or application imports SQL/session types; either owner adapter reads or writes its sibling schema; challenge commit precedes Thesis commit |
| `thesis-to-postgres` | Commit current/version/history/audit/idempotency state atomically | `thesis_domain` | `postgres_thesis_adapter` | `thesis_domain` | `ThesisStorePort` | adapter-private rows | `thesis_domain` | only `thesis` schema | adapter implements Thesis port | domain imports SQL; other adapter writes Thesis tables |
| `thesis-invalidation-to-research` | Bind an immutable published invalidation condition to shadow anomaly evaluation | `thesis_domain` | `research_domain` | `thesis_trace_application` | `ThesisInvalidationProjection` | `ResearchInvalidationInput` | `thesis_trace_application` | immutable Thesis/condition version | L0 -> Thesis; L0 -> Research | Thesis -> Research; Research -> Thesis; client/AI authors projection |
| `thesis-result-to-react` | Return role-safe cards/detail/cycle history through generated contracts | `thesis_trace_application` | `react_thesis_adapter` | `thesis_trace_application` | application result | generated OpenAPI DTO | `thesis_trace_application` | none | Thesis -> L0 -> FastAPI -> React | browser computes lifecycle or stores canonical Thesis |

## Type Ownership Matrix

| Type | Semantic kind | Owner | Declaration | Visibility | Lifetime/mutability | Authority and consumers | Boundary/storage rule |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ThesisStatus` | policy enum | `thesis_domain` | `modules/thesis/contracts.py` | module-public | immutable | ALG-0013; adapter stores value | only `draft`, `active`, `paused`, `invalidated`, `closed` |
| `ThesisActorContext` | domain value | `thesis_domain` | `modules/thesis/contracts.py` | module-public | one command, immutable | L0 maps actor/capabilities | contains no Access type |
| `ThesisResearchReference` | domain value | `thesis_domain` | `modules/thesis/contracts.py` | module-public | persisted reference, immutable | L0 maps Server-validated Company/Evidence IDs | stable IDs/versions only; no Research DTO |
| `InvalidationCondition` | domain value | `thesis_domain` | `modules/thesis/contracts.py` | module-public | published version immutable | Thesis owner explicit save | condition ID, version, summary and active flag; client cannot set match result |
| `ThesisRecord` | aggregate projection | `thesis_domain` | `modules/thesis/contracts.py` | module-public | versioned immutable projection | service/store | binds owner, company, status, cycle, timestamps and reflection-pending |
| `ThesisCycle` | domain value | `thesis_domain` | `modules/thesis/contracts.py` | module-public | durable immutable version | ALG-0013 | monotonic cycle; previous cycle never reopens or mutates |
| `ThesisOutcome` | domain value | `thesis_domain` | `modules/thesis/contracts.py` | module-public | append-only version | personal Thesis owner | current-cycle observed result, observation time and evidence references |
| `ReflectionDraftRevision` | draft value | `thesis_domain` | `modules/thesis/contracts.py` | module-public | append-only revision | accepted autosave only | never satisfies close prerequisite |
| `ThesisReflection` | domain value | `thesis_domain` | `modules/thesis/contracts.py` | module-public | completed version immutable | explicit complete command | original assumption, judgment errors, missing evidence and improvement |
| create/save/transition/outcome/reflection commands | commands | `thesis_domain` | `modules/thesis/contracts.py` | module-public | one request, immutable | authorized owner through L0 | expected version, reason and idempotency required as applicable |
| `ThesisTransitionPreview` | query | `thesis_domain` | `modules/thesis/contracts.py` | module-public | five-minute operation context | Thesis policy, L0 confirmation mapping | exact before/after, target version and digest input |
| `ThesisInvalidationProjection` | composition boundary value | `thesis_domain` | `modules/thesis/contracts.py` | module-public | published version immutable | Thesis service query; L0 consumes | authoritative text/version never accepted from HTTP anomaly request |
| `ThesisStorePort` | demand-owned port | `thesis_domain` | `modules/thesis/ports.py` | module-public | process binding, immutable | service and PostgreSQL adapter | semantic atomic methods; no SQL/session types |
| `ThesisService` | policy | `thesis_domain` | `modules/thesis/service.py` | module-public | process lifetime, immutable | L0/composition | applies ALG-0013 and owns no mutable global |
| `ThesisConfirmedTransitionPort` | composition demand port | `thesis_trace_application` | `application/contracts.py` | module-public | process binding, immutable | L0 transition flow; composition implements | primitive command data only; no SQL connection or adapter type |
| `PostgresConfirmedThesisTransition` | composition binding | `backend_composition` | `bootstrap/application.py` | private | API process lifetime, immutable | composition only | opens the owner-scoped shared transaction by calling Access and Thesis adapter seams; owns no state |
| application request/result/flow types | composition mappings | `thesis_trace_application` | `application/flows/thesis_lifecycle.py` | module-public | request/result lifetime | FastAPI/composition | copy primitives across L1 boundaries |
| HTTP/generated DTOs | wire representations | adapters | API/generated client | adapter-private | request/response lifetime | FastAPI/React only | no owner, Server time, policy result or invalidation match input |
| React route/form state | runtime UI state | `react_thesis_adapter` | `frontend/src/thesis/*` | private | volatile, owner-mutable | current browser only | URL owns route; drafts are memory unless Server accepts revision |

All Python semantic contracts use in-process Python representation; HTTP uses versioned JSON/OpenAPI; PostgreSQL uses schema-qualified relational columns plus JSON only for bounded immutable summaries. There is no C ABI or cross-process shared-memory representation.

## State Object Ownership Matrix

| State object | Owner | Lifetime | Mutation authority | Concurrency/version rule | Persistence |
| --- | --- | --- | --- | --- | --- |
| Thesis current stream | `thesis_domain` | durable | accepted Thesis command | optimistic expected version; one monotonic version | `thesis.theses` plus `thesis.thesis_versions` |
| lifecycle cycles | `thesis_domain` | durable append-only | reopen/transition policy | monotonic cycle number; prior cycle immutable | `thesis.lifecycle_cycles` |
| invalidation condition versions | `thesis_domain` | durable append-only | explicit personal-owner save | published version bound to Thesis version/cycle | `thesis.invalidation_conditions` |
| Thesis-Evidence links | `thesis_domain` | durable | personal owner after L0 validation | unique Thesis/Evidence/version link; removal appends history | `thesis.evidence_links` |
| Outcome versions | `thesis_domain` | durable append-only | personal owner explicit save | current cycle only; historical versions immutable | `thesis.outcomes` |
| Reflection draft revisions | `thesis_domain` | durable append-only | accepted explicit/autosave request | expected draft version and idempotency | `thesis.reflection_draft_revisions` |
| completed Reflection versions | `thesis_domain` | durable append-only | explicit completion | one current completed version per cycle; correction appends | `thesis.reflections` |
| lifecycle audit | `thesis_domain` | durable append-only | same mutation transaction | actor/time/reason/before-after/correlation immutable | `thesis.audit_events` |
| idempotency receipts | `thesis_domain` | durable | adapter in same transaction | actor/key/digest unique; mismatch rejects | `thesis.command_receipts` |
| consequential transition transaction | `backend_composition` | one request transaction | Access challenge owner plus Thesis store owner under coordinator | exact actor/action/target/version/payload/token; replay returns the recorded Thesis stream without another mutation | Access and Thesis schemas commit or roll back together |
| company/tab/selected Thesis route | `react_thesis_adapter` | browser route lifetime | router | reconstructed from Server on reload | URL only |
| unsent form/autosave text | `react_thesis_adapter` | component lifetime | current browser | conflict stops autosave; no offline replay | volatile memory only |

The service retains no mutable global, static, thread-local or shared-process policy object; durable state is reachable only through the Thesis-owned port.

## Actual and intended dependency edges

| Edge | Current | Intended | Rule |
| --- | --- | --- | --- |
| `thesis_trace_application -> thesis_domain` | declared/planned | implemented | L0 coordinates personal commands and queries |
| `thesis_trace_application -> research_domain` | present | retained | validate shared Company/Evidence and map invalidation projection |
| `thesis_trace_application -> access_domain` | present | retained | session/role and confirmation challenge orchestration |
| `fastapi_entrypoint -> thesis_trace_application` | present | retained/extended | explicit command/query endpoints only |
| `backend_composition -> thesis_domain` | absent | added | construct service with Thesis adapter |
| `backend_composition -> postgres_thesis_adapter` | absent | added | select concrete persistence binding |
| `backend_composition -> postgres_access_adapter` | present | retained/extended | bind the Access-owned challenge transaction seam without exposing SQL to L0 |
| `backend_composition -> postgres_atomic_adapter` | absent | added | select the cross-owner transaction coordinator behind an application port |
| `postgres_atomic_adapter -> postgres_access/postgres_thesis adapters` | absent | added | own request-scoped connection sharing entirely within L3 |
| `postgres_thesis_adapter -> thesis_domain` | absent | added | adapter implements demand-owned port |
| `react_thesis_adapter -> fastapi_entrypoint` | absent | generated HTTP only | no Python/domain import |
| `thesis_domain -> research_domain` | absent | forbidden | sibling reference validation/mapping stays at L0 |
| `research_domain -> thesis_domain` | absent | forbidden | anomaly consumes L0-mapped immutable primitives |
| `workflow_domain -> thesis_domain` | absent | forbidden | future reminders use a durable L0 mapping |
| `postgres_research_adapter -> thesis_domain` | absent | forbidden | no cross-schema adapter write/read shortcut |

## Parent mappings

| Mapping | Parent owner | Input | Output | Failure behavior |
| --- | --- | --- | --- | --- |
| authenticated actor to Thesis actor | `thesis_trace_application` | `AuthenticatedActor` | `ThesisActorContext` | Admin/unowned access is uniformly unavailable |
| Research references to Thesis primitives | `thesis_trace_application` | role-safe Company/Evidence projections | `ThesisResearchReference` | absent, stale, unrelated or unauthorized reference writes nothing |
| Thesis transition to confirmation preview | `thesis_trace_application` | `ThesisTransitionPreview` | confirmation challenge impact summary/digest | any state/version change invalidates challenge |
| confirmed challenge to Thesis transaction | `postgres_atomic_adapter` | exact challenge token and primitive transition command | one domain `ThesisRecord` result | invalid/expired/replayed-with-different-data/stale requests roll back both schemas; accepted replay returns the committed stream |
| Thesis invalidation to Research input | `thesis_trace_application` | `ThesisInvalidationProjection` | primitive `ResearchInvalidationInput` | missing/stale/unowned/unpublished projection fails closed |
| Thesis aggregate to application result | `thesis_trace_application` | Thesis projection | role-safe API result | private fields are filtered before card counts/summaries |
| application result to responsive route | `thesis_trace_application` | generated response | Thesis card/detail/cycle view | mutation failure reloads current Server version and preserves local text for copy |

## Lifecycle and failure contract

1. Create a personal `draft` in cycle 1 after Access and Company validation. The Server sets owner, IDs, time, version and policy version.
2. Save draft narrative, invalidation conditions and Evidence links with expected version/idempotency. Activation requires title, narrative and at least one published condition.
3. Apply the direct transition table in ALG-0013. Stale, illegal or unowned commands commit nothing.
4. For invalidated, closed or reopen, preview the exact current transition, issue a five-minute challenge, then revalidate actor/action/version/payload/reason and commit the Thesis change plus consumed challenge/audit atomically.
5. Invalidation immediately sets `reflection_pending=true`. Close requires a current-cycle Outcome and completed Reflection.
6. Reopen increments the cycle, preserves prior records and resets current-cycle Outcome/Reflection prerequisites.
7. Save Outcome only through an explicit command. Autosave Reflection text after two idle seconds only when online; every accepted revision is auditable and not complete. Explicit completion validates all four Reflection sections.
8. Query lists/details only after owner/RLS filtering. Shared Evidence is referenced, never copied into the Thesis schema.
9. For an optionally Thesis-bound anomaly request, load the exact published invalidation projection and map it through L0. Research still applies deterministic source/quorum/critic policy; formal Hard remains disabled.

Every rejection leaves current state, version, history and idempotency unchanged. No Thesis mutation changes Evidence, anomaly or Action Item state.

## Static flow-cost review

Candidate A uses at most one Access/session query, bounded Research reference queries and one Thesis transaction for a mutation; ordinary Thesis queries use one owner-scoped relational read. Candidate B adds queue persistence, claim, retry/dead-letter and eventual UI refresh. Both are best-effort with no numeric latency or throughput claim. Candidate A has fewer execution/failure transitions and preserves immediate command consistency.

## Validation conditions

Product source edits may begin only after ADR-0007 and ALG-0013, ALG-0020, ALG-0021 and ALG-0027 receive explicit non-AI approval and the planned schema 2.2.0 manifest passes the design gate. Completion requires transition-table and invariant unit/property tests, confirmation/autosave tests, real PostgreSQL schema/grant/RLS/version/idempotency/audit/rollback evidence, stale Research-reference and invalidation-mapping tests, API/OpenAPI/generated-client verification, responsive Owner/Learner/Admin Playwright flows, architecture development/release gates and two-axis review. Automatic reminders and formal Hard activation must remain explicitly unclaimed.

## Pre-commit remediation: complete Reflection draft snapshots

The accepted field-triggered autosave interaction remains unchanged, but every
accepted `ReflectionDraftRevision` now represents the complete four-field draft
at that revision. The command still names the changed field so the Server can
apply ALG-0021 conflict rules; the returned/query projection contains all four
texts so reload, copy, compare and conflict recovery never depend on browser
memory or on replaying only the latest changed field.

| Matrix | Decision |
| --- | --- |
| Boundary | React sends one changed field and expected revision; Thesis merges it into the current complete draft and returns a complete immutable revision. |
| Type ownership | `ReflectionDraftRevision` remains Thesis-owned and replaces `field/text` with the four Reflection text values plus revision, cycle and Server save time. |
| State ownership | Complete draft revisions remain append-only Thesis state; the latest current-cycle revision is the query authority. |
| Dependencies | Existing React -> generated HTTP -> L0 -> Thesis -> Thesis PostgreSQL adapter edges are unchanged. |
| Parent mapping | L0 maps the wire field update into the existing Thesis command and maps the complete Thesis projection back to HTTP. |

Candidate A, selected here, stores a complete snapshot per revision. Candidate B
would reconstruct the draft by replaying field deltas; it adds ordering and
missing-history failure modes to every read and is rejected. This is a
best-effort bounded write with no new execution unit, queue or real-time claim.
