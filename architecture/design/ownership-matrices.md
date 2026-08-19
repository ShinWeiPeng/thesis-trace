# Wave 0 Ownership and Boundary Design

Status: proposed design input for the schema/standard 2.2.0 architecture package.

Scope: DEC-079, DEC-087, and DEC-096 through DEC-098. This document defines the
minimum ownership model for the authenticated Owner Company/Evidence intake
walking skeleton. The architecture manifest remains the machine-readable source
of truth once it is created; this file must not be treated as a substitute for a
successful design-phase architecture gate.

## Wave 0 implemented platform and process ownership

| Capability / runtime object | Semantic owner | Concrete owner | Lifetime | Secret handling / mutation authority |
| --- | --- | --- | --- | --- |
| Evidence admission transaction and durable collection job | `evidence_intake` / `evidence_collection` | `postgres_research_adapter` | One PostgreSQL connection and transaction per operation | The adapter retains only `DatabaseUrlProvider`; the database URL is resolved per connection and all adapter failures are redacted. |
| Database secret reference | `backend_composition` | `runtime_configuration_adapter` | Process-scoped file reference; resolved text is operation-scoped | Only `FileSecretProvider` reads `THESIS_TRACE_DATABASE_URL_FILE`; direct environment values fail closed and provider representations are redacted. |
| Collector polling loop | `evidence_collection` | `backend_composition` | Collector process | `compose_collector_worker` alone selects PostgreSQL and restricted-fetch adapters; the entrypoint only invokes the returned worker. |
| Collector readiness | `backend_composition` | `collector_worker_adapter` | One health probe | The entrypoint invokes `compose_collector_healthcheck`; it cannot construct or inspect the database adapter. |
| Restricted network retrieval | `evidence_collection` | `restricted_source_fetch_adapter` | One bounded fetch/redirect chain | Only approved public HTTPS addresses reach the pinned transport; stable failures cross the port. |
| Cloudflare Access verification | `access_domain` | `CloudflareJwtVerifier` wired by `backend_composition` | Verifier is process-scoped; token/claims are request-scoped | Verification fails closed and returns only `AuthenticatedActor`; the collector has no identity bypass. |

Actual and intended dependency edges for the implemented slice are identical:

- entrypoints -> `backend_composition` factories;
- `backend_composition` -> FastAPI, Access, Evidence collector, PostgreSQL,
  restricted-fetch, and runtime-configuration adapters;
- PostgreSQL -> the Evidence Intake and Evidence Collection demand-owned ports;
- restricted-fetch -> the Evidence Collection source-fetch port;
- no platform adapter selects another concrete platform adapter, retains a
  resolved database secret, or crosses an L1/L2 sibling boundary.

## Module and parent map

| Module | Level | Role | Parent | Walking-skeleton responsibility |
| --- | --- | --- | --- | --- |
| `thesis_trace_application` | L0 | orchestration | System | Own cross-domain flows and mappings. It does not own L1 mutable domain state. |
| `backend_composition` | L0 | composition | System | Construct the release application and wire functional contracts to concrete adapters. This is the only module allowed to reference concrete adapters. |
| `access_domain` | L1 | domain | `thesis_trace_application` | Establish an authenticated internal actor and authorize Owner-only evidence intake. |
| `research_domain` | L1 | domain | `thesis_trace_application` | Coordinate Company Catalog, Evidence Intake, and Evidence Collection without exposing their private persistence. |
| `thesis_domain` | L1 | domain | `thesis_trace_application` | Planned Thesis lifecycle, Valuation, Outcome, and Reflection ownership; not executed by this skeleton. |
| `portfolio_domain` | L1 | domain | `thesis_trace_application` | Planned Holdings, Trades, Allocation, Exposure, and Risk Snapshot ownership; not executed by this skeleton. |
| `recommendation_domain` | L1 | domain | `thesis_trace_application` | Planned recommendation and Owner-decision ownership; not executed by this skeleton. |
| `workflow_domain` | L1 | domain | `thesis_trace_application` | Planned Action Inbox ownership; not executed by this skeleton. |
| `notification_domain` | L1 | domain | `thesis_trace_application` | Planned notification policy ownership; not executed by this skeleton. |
| `request_identity` | L2 | component | `access_domain` | Convert verified identity facts into an internal actor contract. |
| `authorization_policy` | L2 | component | `access_domain` | Decide whether the actor may perform the Owner-only command. |
| `company_catalog` | L2 | component | `research_domain` | Create or resolve the Company selected for evidence intake. |
| `evidence_intake` | L2 | component | `research_domain` | Admit an Evidence URL and atomically persist received state, audit fact, and durable collection work. |
| `evidence_collection` | L2 | component | `research_domain` | Process one leased collection attempt and commit a success, retry, failure, or dead-letter transition. |
| `evidence_stage` | L2 | component | `research_domain` | Planned E0-E6 deterministic policy; excluded from the first skeleton flow. |
| `anomaly_assessment` | L2 | component | `research_domain` | Planned anomaly policy; excluded from the first skeleton flow. |
| `fastapi_entrypoint` | L3+ | adapter | Unparented technical module | Map HTTP/OpenAPI wire contracts to L0 commands and queries. |
| `react_web_adapter` | L3+ | adapter | Unparented technical module | Present Server-owned state and submit user intent through the generated client. |
| `openapi_client_generator` | L3+ | adapter/generator | Unparented technical module | Own generated-production TypeScript client declarations. |
| `cloudflare_access_jwt_adapter` | L3+ | adapter | Unparented technical module | Verify JWT signature, issuer, audience, validity, and allowed identity, failing closed. |
| `postgres_research_adapter` | L3+ | adapter | Unparented technical module | Implement Research persistence and transaction contracts with PostgreSQL/SQLAlchemy. |
| `postgres_audit_adapter` | L3+ | adapter | Unparented technical module | Map semantic audit facts to append-only storage within the caller-owned transaction. |
| `postgres_outbox_queue_adapter` | L3+ | adapter | Unparented technical module | Persist, lease, retry, acknowledge, and dead-letter durable jobs. |
| `restricted_http_collector_adapter` | L3+ | adapter | Unparented technical module | Fetch approved sources with bounded, SSRF-safe network behavior. |
| `system_clock_adapter` | L3+ | adapter | Unparented technical module | Supply trustworthy Server time through a demand-owned port. |
| `uuid_adapter` | L3+ | adapter | Unparented technical module | Supply identifiers through a demand-owned port. |
| `observability_adapter` | L3+ | adapter | Unparented technical module | Emit redacted operational signals without domain content or secrets. |

The `api`, `collector_worker`, and `web_ui` runtime executables are execution
units, not logical Modules. The API and collector use the same versioned backend
image. The collector executable is not a second release composition root.

## Type Ownership Matrix

All L0-L2 contracts below are immutable semantic types. They must not contain
JWT claims, HTTP objects, SQLAlchemy models/sessions, database rows, browser
objects, or other wire/storage/framework representations. Declaration paths and
symbols are assigned in the manifest before source implementation.

| Type | Owner | Level | Semantic kind and field roles | Visibility / lifetime / mutability | Mutation authority and consumers | Referenced project types | ABI, wire, and storage impact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ActorId` | `access_domain` | L1 | Domain identity value | Public; request/value lifetime; immutable | Created by Access; L0 and authorized domains consume | None | No wire/storage representation implied |
| `Role` | `access_domain` | L1 | Domain enum: Owner, Learner, Admin | Public; value lifetime; immutable | Access owns values; authorization policy and L0 consume | None | API/DB adapters map explicitly |
| `AuthenticatedActor` | `access_domain` | L1 | Contract DTO: actor identity, role, identity version | Public; request lifetime; immutable | Access creates; L0 consumes | `ActorId`, `Role` | Must not expose JWT/header fields |
| `OwnerAdmissionQuery` | `authorization_policy` | L2 | Query contract: actor and requested capability | Public; request lifetime; immutable | L0 creates; Access reads | `AuthenticatedActor` | No direct wire/storage impact |
| `AuthorizationDecision` | `authorization_policy` | L2 | Contract result: allowed or stable rejection code | Public; request lifetime; immutable | Access creates; L0 consumes | None | No direct wire/storage impact |
| `CompanyId` | `company_catalog` | L2 | Domain identity value | Public; aggregate/value lifetime; immutable | Catalog creates; Research contracts consume | None | Adapter maps to storage/API primitive |
| `CompanyVersion` | `company_catalog` | L2 | Optimistic-concurrency value | Public; aggregate/value lifetime; immutable | Catalog advances; callers compare | None | Adapter maps to storage/API primitive |
| `CompanyRef` | `company_catalog` | L2 | Contract reference to a specific Company version | Public; request/event lifetime; immutable | Catalog creates; Evidence Intake consumes via Research parent mapping | `CompanyId`, `CompanyVersion` | No storage model leakage |
| `CreateCompanyCommand` | `company_catalog` | L2 | Command DTO: actor, approved company identity fields, idempotency key | Public; request lifetime; immutable | L0 submits; Catalog validates and handles | `ActorId` | FastAPI maps wire request explicitly |
| `CompanySnapshot` | `company_catalog` | L2 | Query result: Company identity and current version | Public; response lifetime; immutable | Catalog creates; L0/UI query path consumes | `CompanyId`, `CompanyVersion` | API adapter maps to response schema |
| `CompanyCreated` | `company_catalog` | L2 | Domain event payload for committed creation | Public; durable-event lifetime; immutable | Catalog emits after commit; Research output sink consumes | `CompanyRef` | Persistent envelope mapped by adapter |
| `EvidenceId` | `evidence_intake` | L2 | Domain identity value | Public; aggregate/value lifetime; immutable | Evidence Intake creates; Research/Collection contracts consume | None | Adapter maps to storage/API primitive |
| `EvidenceVersion` | `evidence_intake` | L2 | Optimistic-concurrency value | Public; aggregate/value lifetime; immutable | Evidence owner advances; callers compare | None | Adapter maps to storage/API primitive |
| `EvidenceUrl` | `evidence_intake` | L2 | Validated semantic URL value | Public; aggregate/value lifetime; immutable | Evidence Intake validates; collector consumes | None | Not an HTTP client URL object |
| `EvidenceLifecycleStatus` | `evidence_intake` | L2 | Domain enum: received, processing, succeeded, failed, retrying, dead-letter | Public; aggregate lifetime; owner-mutable through legal transitions | Evidence owner changes; queries expose snapshots | None | Persisted/API values require explicit mappings |
| `SubmitEvidenceUrlCommand` | `evidence_intake` | L2 | Command DTO: actor, Company reference, URL, idempotency key | Public; request lifetime; immutable | L0 submits; Evidence Intake validates and handles | `ActorId`, `CompanyRef`, `EvidenceUrl` | FastAPI maps wire request explicitly |
| `EvidenceAccepted` | `evidence_intake` | L2 | Immediate accepted result: record and version | Public; response lifetime; immutable | Evidence Intake creates; L0/API consumes | `EvidenceId`, `EvidenceVersion` | API adapter maps to response schema |
| `EvidenceStatusQuery` | `evidence_intake` | L2 | Side-effect-free query for an authorized record/version | Public; request lifetime; immutable | L0 submits; Evidence owner reads | `ActorId`, `EvidenceId` | No persistence handle exposed |
| `EvidenceStatusSnapshot` | `evidence_intake` | L2 | Immutable query snapshot: identity, version, status, safe failure details and provenance summary when available | Public; response lifetime; immutable | Evidence owner creates; L0/UI consumes | `EvidenceId`, `EvidenceVersion`, `EvidenceLifecycleStatus` | API adapter maps; Server remains authoritative |
| `EvidenceReceived` | `evidence_intake` | L2 | At-least-once event payload for committed received state | Public; durable-event lifetime; immutable | Evidence Intake emits after commit; Research parent maps | `EvidenceId`, `EvidenceVersion`, `CompanyRef`, `EvidenceUrl` | Stored in an adapter-owned event envelope |
| `CollectionRequest` | `evidence_intake` | L2 | Durable work contract: record/version, subject key, idempotency key | Public; durable-job lifetime; immutable | Evidence Intake produces; Research parent maps to Collection command | `EvidenceId`, `EvidenceVersion` | Queue row mapping remains adapter-private |
| `EvidenceAuditFact` | `evidence_intake` | L2 | Append-only semantic audit contract: actor, action, subject/version, reason | Public to its persistence port; transaction lifetime; immutable | Evidence Intake produces; audit adapter consumes through the port | `ActorId`, `EvidenceId`, `EvidenceVersion` | Audit storage shape remains private |
| `CollectionAttemptId` | `evidence_collection` | L2 | Domain identity for one attempt | Public; attempt lifetime; immutable | Collection creates; events and ports consume | None | Adapter maps to queue/storage primitive |
| `CollectionLeaseToken` | `evidence_collection` | L2 | Opaque semantic lease token | Public but opaque; lease lifetime; immutable | Queue adapter creates, Collection presents; no dereference authority transfers | None | Must not expose a DB lock or row object |
| `CollectedSourceSnapshot` | `evidence_collection` | L2 | Immutable source result: canonical URL, publisher, content hash, times, excerpt, source category, lineage | Public; aggregate/event lifetime; immutable | Collection validates/creates; Evidence owner persists | `EvidenceUrl` | Raw bytes and HTTP representations excluded |
| `CollectionFailure` | `evidence_collection` | L2 | Safe failure contract: stable code and retryability | Public; attempt/event lifetime; immutable | Collection creates; UI sees only approved fields | None | Must not include secrets or raw exception text |
| `CollectEvidenceCommand` | `evidence_collection` | L2 | Command DTO: record/version, attempt, lease and URL | Public; attempt lifetime; immutable | Research parent/worker submits; Collection handles | `EvidenceId`, `EvidenceVersion`, `CollectionAttemptId`, `CollectionLeaseToken`, `EvidenceUrl` | No queue/HTTP binding exposed |
| `CollectionOutcome` | `evidence_collection` | L2 | Accepted-work completion result union | Public; attempt lifetime; immutable | Collection creates; worker orchestration consumes | `CollectedSourceSnapshot`, `CollectionFailure` | Adapter mappings are explicit |
| `EvidenceCollectionSucceeded` | `evidence_collection` | L2 | Event payload emitted after successful state commit | Public; durable-event lifetime; immutable | Collection emits; Research output sink consumes | `EvidenceId`, `EvidenceVersion`, `CollectedSourceSnapshot` | Persistent envelope mapped by adapter |
| `EvidenceCollectionFailed` | `evidence_collection` | L2 | Event payload emitted after retry/failure/dead-letter commit | Public; durable-event lifetime; immutable | Collection emits; Research output sink consumes | `EvidenceId`, `EvidenceVersion`, `CollectionFailure` | Persistent envelope mapped by adapter |
| `EvidenceIntakeUnitOfWorkPort` | `evidence_intake` | L2 | Demand-owned interface for atomic current-state, audit, and outbox commit | Public port; request lifetime; immutable interface | Evidence Intake calls; PostgreSQL adapter implements | `EvidenceAuditFact`, `CollectionRequest` | No SQLAlchemy/session type in signature |
| `EvidenceStatusRepositoryPort` | `evidence_intake` | L2 | Demand-owned side-effect-free snapshot query port | Public port; request lifetime; immutable interface | Evidence owner calls; PostgreSQL adapter implements | `EvidenceStatusQuery`, `EvidenceStatusSnapshot` | Storage representation remains private |
| `CollectionJobPort` | `evidence_collection` | L2 | Demand-owned leased claim/ack/retry/dead-letter interface | Public port; worker lifetime; immutable interface | Collection worker flow calls; queue adapter implements | `CollectEvidenceCommand`, `CollectionLeaseToken` | Queue row and lock representations remain private |
| `SourceFetchPort` | `evidence_collection` | L2 | Demand-owned restricted source acquisition interface | Public port; attempt lifetime; immutable interface | Collection calls; restricted HTTP adapter implements | `EvidenceUrl`, `CollectedSourceSnapshot`, `CollectionFailure` | HTTP objects never cross the port |
| `ClockPort` | consuming functional module | L1/L2 | Demand-owned time interface | Public port; process lifetime; immutable interface | Consumer calls; clock adapter implements | None | No OS clock binding exposed |
| `IdGeneratorPort` | consuming functional module | L1/L2 | Demand-owned identity-generation interface | Public port; process lifetime; immutable interface | Consumer calls; UUID adapter implements | None | No library generator object exposed |
| `ResearchOutputSink` | `research_domain` | L1 | The single functional output sink for Research events | Public port; process lifetime; immutable interface | Research publishes outside internal locks; parent/adapter implements fan-out | Research-owned event types | Subscriber collection remains outside Research |
| `AuthenticatedEvidenceSubmission` | `thesis_trace_application` | L0 | Private mapping between admitted actor and Research command | Private; request lifetime; immutable | L0 alone creates/consumes | `AuthenticatedActor`, `SubmitEvidenceUrlCommand` | Never appears in a child public API |
| `EvidenceDispatchMapping` | `research_domain` | L1 | Private mapping from committed intake event to collection command | Private; dispatch lifetime; immutable | Research parent alone creates/consumes | `EvidenceReceived`, `CollectEvidenceCommand` | Never appears in an L2 public API |

The following adapter types are required when corresponding named declarations
exist. They are private to their L3+ owners: `AccessJwtClaimsWire`,
`SqlAlchemyCompanyRow`, `SqlAlchemyEvidenceRow`, `SqlAlchemyAuditRow`,
`SqlAlchemyOutboxRow`, and `HttpFetchResponseWire`. Generated OpenAPI schemas
and client declarations belong to the `openapi_client_generator`
`generated-production` boundary and must never be copied or hand-edited into a
functional module.

## State Object Ownership Matrix

PostgreSQL rows are persisted domain/storage records, not runtime state objects
for this matrix. They are governed through aggregate ownership, port contracts,
and adapter-private storage mappings. The manifest `state_objects` inventory
must cover every mutable static/file-scope/thread-local object, every `extern`
object, and every object whose address crosses a module boundary.

| State object | Complete private type | Owner | Lifetime / storage | Mutability | Read authority | Write authority | Public leakage / pointer escape |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `api_runtime` | `BackendApplicationRuntime` | `backend_composition` | API process; private process-lifetime composition state | Owner-mutable only during startup/shutdown | `backend_composition` | `backend_composition` | No public leakage; child modules receive only ports |
| `collector_runtime` | `CollectorWorkerRuntime` | `backend_composition` | Collector process; private process-lifetime composition state | Owner-mutable only during startup/shutdown | `backend_composition` | `backend_composition` | No public leakage; worker flow receives semantic ports |
| `postgres_pool_runtime` | `SqlAlchemyEngineBinding` | `postgres_research_adapter` | Process lifetime; adapter-private framework state | Adapter-mutable | Owning PostgreSQL adapter only | Owning PostgreSQL adapter only | Engine/session objects never cross a functional boundary |
| `jwt_key_cache_runtime` | `AccessKeyCacheRuntime` | `cloudflare_access_jwt_adapter` | Process lifetime; adapter-private cache | Adapter-mutable | JWT adapter only | JWT adapter only | No key/cache pointer escapes; stale/unverifiable state fails closed |
| `web_query_cache_runtime` | `WebQueryCacheRuntime` | `react_web_adapter` | Browser page lifetime; adapter-private memory | Adapter-mutable | React adapter only | React adapter only | Never authoritative and never persisted with sensitive domain data |

Request-scoped units of work, SQLAlchemy sessions, command values, and one-job
lease values are not State Object Matrix entries unless implementation gives
them static/thread-local storage or passes their mutable address across a module
boundary. Module globals are prohibited. Any future long-lived scheduler,
circuit-breaker, lease registry, or subscriber registry requires an explicit
owner and State Object Matrix row before implementation.

## Allowed dependency edges

- `thesis_trace_application -> access_domain`
- `thesis_trace_application -> research_domain`
- `access_domain -> request_identity`
- `access_domain -> authorization_policy`
- `research_domain -> company_catalog`
- `research_domain -> evidence_intake`
- `research_domain -> evidence_collection`
- `research_domain -> evidence_stage` and `anomaly_assessment` only when those
  planned components enter an approved slice
- An L3+ adapter may depend on the demand-owned public port it implements.
- `backend_composition` may depend on L0/L1 public contracts and concrete L3+
  adapters solely to construct and wire the system.
- `fastapi_entrypoint` may depend on L0 input/query contracts; the React client
  may depend on generated OpenAPI contracts.

## Forbidden dependency edges

- `access_domain <-> research_domain` and all other L1 sibling dependencies.
- Direct dependencies between `company_catalog`, `evidence_intake`, and
  `evidence_collection`; `research_domain` performs their mapping and
  orchestration.
- Any L0-L2 functional module depending on FastAPI, SQLAlchemy, Psycopg, httpx,
  React, browser APIs, JWT libraries, PostgreSQL tables, or another concrete
  L3+ implementation.
- API or worker entrypoints reading or writing a domain's private tables.
- React/UI state deciding authoritative authorization, lifecycle status,
  deduplication, or collection success.
- An adapter-owned wire, framework, or storage representation appearing in an
  L0-L2 public contract.
- A functional module owning subscriber collections or publishing callbacks
  while holding its internal lock.
- Persisting an audit event or outbox job after the domain transaction as a
  best-effort second write.

## Required parent-owned boundary mappings

| Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Authenticated Owner evidence submission | `access_domain` | `research_domain` | `thesis_trace_application` | `AuthenticatedActor`, `AuthorizationDecision` | `SubmitEvidenceUrlCommand` | `thesis_trace_application` | No private child state | L0 to each L1 public port | Access-to-Research direct call |
| Company selection to Evidence intake | `company_catalog` | `evidence_intake` | `research_domain` | `CompanySnapshot`/`CompanyRef` | `SubmitEvidenceUrlCommand` | `research_domain` | Company and Evidence only through their ports | Research parent to each child | L2 sibling dependency |
| React request to L0 command | `react_web_adapter` | `thesis_trace_application` | `backend_composition` | Generated OpenAPI wire request | L0 application input contract | `fastapi_entrypoint` | No domain private state | React to client to HTTP adapter to L0 | React to DB/worker/domain private APIs |
| Atomic Evidence acceptance | `evidence_intake` | PostgreSQL technical capability | `research_domain` | Evidence state, `EvidenceAuditFact`, `CollectionRequest` | `EvidenceIntakeUnitOfWorkPort` | `postgres_research_adapter` | Adapter-private transaction/session and rows | Evidence to demand-owned port; adapter implements | Evidence to SQLAlchemy/tables or split transactions |
| Committed Evidence to collection work | `evidence_intake` | `evidence_collection` | `research_domain` | `EvidenceReceived`, `CollectionRequest` | `CollectEvidenceCommand` | `research_domain` | Durable outbox/queue only through its port | Parent to both child ports | Evidence Intake to Collection direct call |
| Collection to external URL | `evidence_collection` | External source | `research_domain` | `EvidenceUrl` and fetch policy | `SourceFetchPort` result | `restricted_http_collector_adapter` | Adapter-private HTTP connection state | Collection to demand port; adapter to approved network | Unrestricted fetch or HTTP object leakage |
| Collection result to UI status | `evidence_collection` | `evidence_intake` query state | `research_domain` | Success/failure event | Legal Evidence transition and `EvidenceStatusSnapshot` | `research_domain` | Evidence state only through its owner | Parent maps result after commit; UI queries Server | Success publication before snapshot commit |

## Lifecycle and delivery constraints

- Command syntax and admission are synchronous. Stable immediate rejections
  include `invalid_url`, `unauthenticated`, `forbidden`,
  `company_version_conflict`, and `unavailable`.
- Accepted evidence intake immediately returns its Server record/version. Later
  completion or execution failure is reported through output events and query
  state.
- Cross-module events carry `event_type`, `source`, `correlation_id`,
  `stream_id`, `sequence`, and `payload`. At-least-once durable delivery also
  carries a persistent event ID and retry metadata.
- The domain lifecycle is `received -> validated -> processing -> succeeded |
  failed`; durable work extends it with `accepted -> retrying -> cancelled |
  dead-letter` where applicable.
- The producer commits state before publishing success or failure. One Evidence
  stream is serialized and non-reentrant; unrelated Evidence streams may run
  concurrently.
- URL/content deduplication, redirect handling, correction semantics, restricted
  source admission, lease expiry, idempotency, and stale-version rejection are
  algorithm-bearing behavior. Their Algorithm Design Records must be complete
  and human-approved before being marked accepted.

## Pre-code gate notes

- Exactly one release composition root must be declared and verified. Runtime
  worker entrypoints do not multiply that root.
- Every named Python and TypeScript production declaration, including Protocols,
  models, schemas, aliases, and enums, must have exactly one Type Catalog owner.
- The OpenAPI generator owns generated-production declarations; generated files
  are never hand-edited to satisfy the catalog.
- The five-minute polling and ten-/thirty-minute freshness objectives are soft
  SLOs, not CPU real-time guarantees. If declared as a soft-real-time workload,
  the required candidate scheduling study and human risk acceptance remain a
  gate and cannot be inferred.
- DEC-097 requires algorithm screening and flow review for the whole confirmed
  product architecture, including planned modules. Completing this skeleton
  matrix alone does not make the design-phase gate pass.
