# E0-E6 Owner-confirmed Stage Slice

- Spec decisions: `DEC-021`, `DEC-022`, `DEC-096`, `DEC-100`
- Algorithm: `ALG-0002`
- Owning parent: `research_domain` (L1)
- Child: `evidence_stage` (L2)
- Flow: `owner_confirmed_evidence_stage`
- Timing class: best-effort
- Review status: Candidate A approved through ADR-0003
- Assurance: functional design only; no numeric performance claim

## Decision boundary

This slice lets an authenticated Owner confirm a complete version of the five E-stage dimensions for one succeeded Evidence source snapshot. The Server validates authority, evidence and snapshot linkage, expected version and reason, derives E0-E6 through `ALG-0002`, and atomically appends the confirmed facts, gate trace, canonical stage and audit record. Owner and Learner queries may read the Server projection; Admin, client-computed values and unconfirmed AI candidates have no write authority.

The first implementation does not run AI or critic logic, emit notification events, send notifications, or create a separate stage worker. Those remain later slices. `research.evidence_stage_changed` stays a future architecture contract and must not be declared as emitted until a durable outbox publisher and delivery evidence exist.

## Candidate comparison

### Candidate A: synchronous confirmation transaction

After authorization, `evidence_stage` evaluates the pure sequential-gate policy and calls its demand-owned persistence port. One PostgreSQL transaction checks the expected version and snapshot relation, appends the immutable fact/stage version and audit record, then returns the committed projection. `research.evidence_stage_changed` is publishable only after commit.

This candidate gives the command response a single authoritative version, makes conflicts fail before any partial write, and adds no queue or eventual-consistency state. The pure evaluation cost is bounded by six gates and has no external I/O.

### Candidate B: durable stage-evaluation job

The confirmation transaction would append facts and enqueue work; a worker would later derive and persist the stage. This separates computation from command latency, but introduces an intermediate pending state, job versioning, lease/retry/dead-letter behavior, another execution mapping and UI polling ambiguity. Those costs are not justified for six deterministic predicates.

Candidate B becomes relevant only if a future policy requires external I/O or measured computation that cannot fit the synchronous best-effort request boundary.

## Boundary Design Table

| ID | Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `access-to-research-actor` | Map verified session identity into Research-parent authority | `access_domain` | `research_domain` | `thesis_trace_application` | `AuthenticatedActor` | `ResearchActorContext` | `thesis_trace_application` | none | L0 -> Access; L0 -> Research parent | Access -> Research; Research -> Access |
| `research-to-stage-actor` | Map Research-parent capabilities into the child stage actor | `research_domain` | `evidence_stage` | `research_domain` | `ResearchActorContext` | `StageActorContext` | `research_domain` | none | Research parent -> Evidence Stage child | L0/API -> Evidence Stage child contract |
| `http-to-application-stage-command` | Map an Owner HTTP intent into a typed L0 command | `fastapi_entrypoint` | `thesis_trace_application` | `thesis_trace_application` | adapter-private request DTO | `ConfirmEvidenceStageRequest` | `thesis_trace_application` | none | adapter -> L0 | FastAPI/Pydantic -> Research or Evidence Stage |
| `research-parent-to-stage-command` | Map L0 primitives through the Research parent into child semantic facts | `thesis_trace_application` | `evidence_stage` | `research_domain` | `ResearchStageConfirmationRequest` | `ConfirmDimensionFactsCommand` | `research_domain` | none | L0 -> Research parent -> Evidence Stage child | L0 -> Evidence Stage child contract |
| `evidence-snapshot-to-stage` | Validate that the selected immutable snapshot belongs to the Evidence stream | `evidence_collection` | `evidence_stage` | `research_domain` | `CollectedSourceSnapshot` identity | `EvidenceStageRecord.source_snapshot_id` primitive | `research_domain` | immutable snapshot relation | Research parent maps sibling facts | either L2 sibling imports the other sibling's private types |
| `stage-to-postgres` | Atomically append confirmed facts, derived stage, trace and audit | `evidence_stage` | `postgres_research_adapter` | `research_domain` | `EvidenceStageStorePort` semantic values | adapter-private rows | `research_domain` | stage-version stream and snapshot relation | adapter implements Stage-owned port | domain -> SQL/ORM/session; adapter computes stage |
| `stage-record-to-research-result` | Hide the L2 aggregate behind a Research-parent projection | `evidence_stage` | `research_domain` | `research_domain` | `EvidenceStageRecord` | `ResearchStageResult` | `research_domain` | none | Evidence Stage child -> Research parent | L0/API -> `EvidenceStageRecord` |
| `stage-response-to-react` | Return role-safe Server stage projection | `thesis_trace_application` | `responsive_web_adapter` | `thesis_trace_application` | `EvidenceStageResult` | generated OpenAPI DTO | `thesis_trace_application` | none | Research parent -> L0 -> adapter | browser writes canonical stage or retains protected domain data |

## Type Ownership Matrix

| Type | Semantic kind | Owner | Mutation authority | Consumers | Boundary rule |
| --- | --- | --- | --- | --- | --- |
| `EvidenceStage` | policy enum E0-E6 | `evidence_stage` | none | stage policy, PostgreSQL adapter | parent maps to primitive projection; no duplicate enum is authoritative |
| `SourceConfirmation` | policy enum | `evidence_stage` | none | stage policy, PostgreSQL adapter, Research parent mapping | values are `unverified`, `official`, `two_independent_credible` |
| `DimensionFacts` | immutable domain value | `evidence_stage` | none after construction | policy and store port | contains facts, never SQL/Pydantic objects |
| `ConfirmDimensionFactsCommand` | command | `evidence_stage` | Owner through Server admission | stage policy, PostgreSQL adapter, Research parent | actor and expected version are mandatory; never imported by L0/API |
| `GateResult` | immutable trace value | `evidence_stage` | policy only at evaluation | stage projection/store | one result per E1-E6 gate |
| `StageEvaluation` | policy result | `evidence_stage` | `ALG-0002` policy | service/store | stage plus complete trace or abstention |
| `EvidenceStageRecord` | versioned aggregate projection | `evidence_stage` | store only after policy validation | stage policy, PostgreSQL adapter, Research parent | binds snapshot, actor, reason, times and policy version; never crosses to L0/API |
| `EvidenceStageStorePort` | demand-owned port | `evidence_stage` | none | PostgreSQL adapter | exposes semantic atomic confirm/query operations only |
| `ResearchStageFacade` | parent orchestration facade | `research_domain` | none | L0 application flow, composition root | maps Research-local primitives and actor capabilities into L2 contracts; owns no stage state |
| `ResearchStageConfirmationRequest` / `ResearchStageQuery` | parent command/query | `research_domain` | none | Research parent and L0 application flow | only typed L0-to-Research stage inputs; exclude L2 types |
| `ResearchStageFacts` / `ResearchStageGate` / `ResearchStageResult` | parent result values | `research_domain` | none | Research parent and L0 application flow | map `EvidenceStageRecord` into primitives before crossing the L1 boundary |
| `ConfirmEvidenceStageRequest` / `QueryEvidenceStageRequest` | application command/query | `thesis_trace_application` | none | L0 and FastAPI | typed adapter-to-L0 inputs; no child-domain contract exposure |
| `EvidenceStageFactsResult` / `EvidenceStageGateResult` / `EvidenceStageResult` | application result values | `thesis_trace_application` | none | L0 and FastAPI | map the Research-parent result into the API-facing application projection |
| `EvidenceStatusSnapshot` | query projection | `evidence_intake` | none | L0/API/UI | adds an optional immutable `source_snapshot_id`; wire-compatible nullable field used only after collection succeeds |
| `DimensionFactsBody` | request wire representation | `fastapi_entrypoint` | adapter-local | FastAPI only | maps bounded wire facts into parent primitives; v1 admits `unverified` or `official`, while two-independent-credible fails closed until two snapshot references can be bound |
| `EvidenceStageConfirmationBody` | request wire representation | `fastapi_entrypoint` | adapter-local | FastAPI only | deliberately has no canonical `stage` field |
| `GateResultResponse` | response wire representation | `fastapi_entrypoint` | adapter-local | FastAPI/generated client | maps stable gate/result codes after Server evaluation |
| `EvidenceStageResponse` | response wire representation | `fastapi_entrypoint` | adapter-local | FastAPI/generated client | exposes committed Server record/version; never accepted as input |
| React stage form state | runtime UI state | `responsive_web_adapter` | React component | React only | volatile; never canonical and never browser-persisted |

## State Object Ownership Matrix

| State object | Owner | Lifetime | Mutation authority | Concurrency/version rule | Persistence |
| --- | --- | --- | --- | --- | --- |
| confirmed fact/stage stream | `evidence_stage` | durable per Evidence | Owner command admitted by Server; PostgreSQL adapter commits | optimistic `expected_version`; append-only versions; one next version per Evidence | `research.evidence_stage_versions` |
| immutable source snapshot relation | `evidence_collection` | durable | collector transaction only | selected snapshot must already belong to the Evidence stream | existing source snapshot/observation tables |
| stage audit fact | `evidence_stage` | durable append-only | same confirmation transaction | actor, Server time, reason, record/version cannot be rewritten | stage version plus audit event |
| gate trace | `evidence_stage` | durable with stage version | `ALG-0002` policy only | exactly E1-E6 in order for a non-abstained evaluation | JSON/structured adapter representation |
| stage form draft | `responsive_web_adapter` | component lifetime | current browser interaction | discarded on navigation/error/success; not authority | memory only |

The policy service has no mutable process-global or request-shared runtime state. Therefore the manifest needs no new mutable `state_objects` entry; durable state is accessed only through the Stage-owned port.

## Actual and intended dependency edges

| Edge | Current | Intended | Rule |
| --- | --- | --- | --- |
| `fastapi_entrypoint -> thesis_trace_application` | present | retained | HTTP adapter implements the public application confirmation/query input ports |
| `backend_composition -> thesis_trace_application` | present | retained by accepted ADR-0004 composition-root seam | release bootstrap constructs the application flow without owning its policy; the DEP001 exception is limited to this exact edge |
| `backend_composition -> research_domain` | present | allowed | release bootstrap constructs the Research parent facade and injects its child service |
| `research_domain -> evidence_stage` | present | allowed | parent owns and orchestrates child |
| `thesis_trace_application -> research_domain` | present | retained | L0 maps authenticated command/query |
| `backend_composition -> evidence_stage` | present | allowed | composition wires service to PostgreSQL adapter |
| `postgres_research_adapter -> evidence_stage` | present | allowed | adapter implements Stage-owned port |
| `evidence_stage -> evidence_collection` | absent | forbidden | sibling facts cross through Research mapping/store validation |
| `evidence_stage -> access_domain` | absent | forbidden | actor mapping and authorization stay at L0/parent boundary |
| `evidence_stage -> fastapi_entrypoint` | absent | forbidden | framework-free domain contract |
| `responsive_web_adapter -> evidence_stage` | absent | forbidden | generated HTTP contract and L0 boundary only |

## Parent mappings

| Mapping | Parent owner | Input | Output | Failure behavior |
| --- | --- | --- | --- | --- |
| authenticated actor to Research actor | `thesis_trace_application` | `AuthenticatedActor` | `ResearchActorContext` | reject non-Owner writes before Research mutation |
| Research actor to stage actor | `research_domain` | `ResearchActorContext` | `StageActorContext` | child sees only server-derived capabilities, never Access types |
| Evidence/snapshot selection to stage target | `research_domain` | Evidence ID, selected snapshot ID | validated stage stream target | absent, failed, unrelated or unauthorized records are indistinguishable/unavailable |
| stage aggregate to Research result | `research_domain` | `EvidenceStageRecord` | `ResearchStageResult` | L2 enums and aggregate contracts stop at the L1 parent |
| Research result to application result | `thesis_trace_application` | `ResearchStageResult` | `EvidenceStageResult` | Owner gets confirm controls; Learner read-only; Admin unavailable |

## Flow and failure contract

1. Revalidate the session and require Owner for confirmation; query allows Owner or Learner.
2. Map `ConfirmEvidenceStageRequest` to `ResearchStageConfirmationRequest`; the Research parent alone maps that command into `ConfirmDimensionFactsCommand`, without trusting any client-derived stage.
3. Validate nonblank reason, expected version, succeeded Evidence and snapshot membership.
4. Run `ALG-0002` over immutable facts. Missing prerequisites yield the highest passed sequential stage; contradictory/invalid facts abstain and do not commit.
5. Atomically append the next facts/stage version and audit record under PostgreSQL row/advisory serialization.
6. Map `EvidenceStageRecord` to `ResearchStageResult`, then to `EvidenceStageResult`, and return the committed Server projection. Any later event is only an invalidation signal, never UI truth.

Stale version, non-Owner mutation, unrelated snapshot, missing reason, invalid fact combination or abstention writes nothing. Repeating an idempotency key returns the original committed result; a different command against the old version returns `version_conflict`.

## Validation conditions

Implementation may begin only after ADR-0003 is explicitly accepted and the design-phase architecture gate passes. Completion requires deterministic unit/example/property tests for E0-E6 and abstention, API/OpenAPI authority and conflict tests, real PostgreSQL version/audit/RLS/rollback tests, generated-client verification, responsive Playwright Owner confirmation/read-only rendering, repository validation and the development architecture gate.

Validation evidence on 2026-08-20: all E0-E6 boundary vectors and idempotency conflicts passed; the full backend suite passed with real PostgreSQL; actual NOBYPASSRLS roles proved Owner insert, Learner read-only and Admin-unavailable behavior; OpenAPI/generated-client checks, frontend unit/build, desktop/mobile Playwright, repository validation and the development architecture gate passed.
