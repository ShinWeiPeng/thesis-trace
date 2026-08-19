# Company/Evidence Intake Walking-Skeleton Flow Review

- Spec decision: `DEC-098`
- Owning module: `thesis_trace_application` (L0)
- Trigger: an authenticated Owner selects or creates a Company and submits an Evidence URL
- Timing class: best-effort
- Review status: Candidate A recommended for the first slice
- Model assurance: `estimated`; platform performance and capacity claims remain `BLOCKED`

## Responsibility and observable behavior

The walking skeleton proves one production-shaped path through the responsive Web UI, generated OpenAPI client, FastAPI boundary, Access identity verification, Research command/query contracts, a PostgreSQL transaction, append-only audit, durable work, an independent collector worker, restricted source retrieval, immutable provenance, and a Server-authoritative UI status.

An accepted submission returns an `intake_id`, `version`, and `received` state. The UI subsequently queries that record and may display only Server-reported `received`, `processing`, `retrying`, `succeeded`, `failed`, or `dead-letter` state. This slice does not run AI, E0-E6 stage derivation, anomaly policy, Thesis, valuation, or Recommendation logic.

## Candidate A: typed durable job-as-outbox

The admission transaction writes the Evidence intake, append-only audit entry, and a typed collector job. That job is the durable outbox work item and is claimed directly by the collector worker.

| Step | Module / boundary | Contract | Context and delivery | Commit, side effect, and error path |
| --- | --- | --- | --- | --- |
| A1 | `responsive_web_adapter` -> `fastapi_http_adapter` | generated OpenAPI request | HTTP, synchronous | Sends Company selection/creation and Evidence URL intent; transport failure leaves no Server state. |
| A2 | L0 -> `access_domain` | `VerifyAccessIdentityQuery` | synchronous query | Verifies signature, issuer, audience, expiry, allowed identity and role. Rejection stops before Research state is accessed. |
| A3 | `thesis_trace_application` -> `research_domain` | `ResearchActorContext` mapping | in-process, synchronous | L0 maps `VerifiedPrincipal`; Access and Research do not depend on each other. |
| A4 | `research_domain` -> `company_catalog` / `evidence_intake` | `CompanyReference`, `SubmitEvidenceUrlCommand` | in-process command admission | Checks actor, Company/version and URL syntax/policy. Immediate rejection writes no intake or job. |
| A5 | `research_domain` -> `postgres_research_adapter` | `ResearchTransactionRequest.commit_received_intake` | PostgreSQL transaction | Atomically writes intake `received`, audit entry and typed collector job. Any failure rolls back all three. |
| A6 | `research_domain` -> L0 output sink | `EvidenceIntakeReceived` | at-least-once, after commit | Persistent `event_id`; HTTP returns `202` with Server record/version. Publication failure cannot roll back the commit and is reported to the L0 error port. |
| A7 | `collector_worker_adapter` -> `evidence_intake` | `CollectorJobClaimRequest`, `ProcessEvidenceIntakeCommand` | asynchronous leased claim | A valid lease changes the intake to `processing`; stale lease/version is rejected. Expired leases are reclaimable. |
| A8 | `evidence_intake` -> `restricted_source_fetch_adapter` | `RestrictedSourceRetrievalRequest` | asynchronous external I/O | Adapter reapplies scheme, address, redirect, media-type, size and deadline restrictions. Transient errors retry; policy failures are terminal. |
| A9 | `evidence_intake` -> `postgres_research_adapter` | `ResearchTransactionRequest.commit_processing_result` | PostgreSQL transaction | Atomically commits canonical source/snapshot/provenance and terminal state, or retry/dead-letter state, together with audit and job transition. |
| A10 | `research_domain` -> L0 output sink | result `ResearchEvent` | at-least-once, after commit | Emits succeeded, retrying, failed or dead-letter outcome. Same-stream processing is serialized; other intakes may run concurrently. |
| A11 | UI -> query API | `GetEvidenceIntakeQuery` | synchronous query | Event or bounded polling only invalidates cached data. The query response remains the source of truth. |

### Candidate A static cost model

- Admission critical path: one JWT verification, validation/mapping, one database transaction, and one HTTP response serialization.
- Collector success path: one leased claim transaction, one external fetch, and one result transaction.
- The durable job carries identifiers and policy references, not fetched content, avoiding a large queue payload copy.
- Expected bottlenecks are external-source latency, database connection/lock contention, and queue backlog.
- No numeric latency, throughput, queue capacity, memory, or resource limit is inferred because the specification and target measurements do not yet supply them.

## Candidate B: domain outbox, dispatcher, and separate collector queue

The admission transaction writes the intake, audit entry, and a domain outbox event. A separate dispatcher claims that event and idempotently materializes a collector job in another durable queue; the collector then claims the job and follows Candidate A's retrieval/result path.

| Step | Structural difference | Additional contract and failure behavior |
| --- | --- | --- |
| B1-B6 | Admission remains identical except the transaction writes `DomainOutboxEvent` rather than the collector job. | The HTTP response remains valid after the admission commit even if dispatch has not occurred. |
| B7 | A dispatcher execution unit claims the outbox event. | Requires lease, retry, dead-letter and heartbeat behavior distinct from collector behavior. |
| B8 | Dispatcher materializes `CollectorJob`. | `event_id -> collector_job_id` must be unique; crash before or after commit must not duplicate work. |
| B9-B13 | Collector claim, fetch, result commit, event and UI query match A7-A11. | Both outbox backlog and collector-job backlog require recovery, observability and tests. |

### Candidate B static cost model

- Adds one execution unit, one durable channel, at least one additional claim/commit pair, another queue wait, and another serialized contract version.
- It improves locality when multiple durable subscribers require independent retry, offset, deployment, or scaling policies.
- The first walking skeleton has one durable consumer, so that extensibility benefit is not currently required.

## Functional admission and recommendation

Both candidates preserve semantic ownership, legal dependency direction, commit-before-publication, explicit failure propagation, per-stream ordering, at-least-once delivery, and idempotency. Candidate A is recommended because it satisfies DEC-098 with fewer durable transitions and fewer crash/recovery states. Candidate B is not rejected as invalid; it is deferred until at least two durable subscribers require independent retry or deployment semantics.

This is a topology and reliability recommendation, not a claim that Candidate A is a platform performance winner. Changing to Candidate B requires a new flow review and an ADR/manifest update.

## Boundary Design Table

| ID | Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `access-to-research-actor` | Map verified identity to Research authority | `access_domain` | `research_domain` | `thesis_trace_application` | `VerifiedPrincipal` | `ResearchActorContext` | `thesis_trace_application` | none | L0 -> Access; L0 -> Research | Access -> Research; Research -> Access |
| `company-selection-to-intake` | Map a Company selection/version to an Evidence target | `company_catalog` | `evidence_intake` | `research_domain` | `CompanyReference` | `EvidenceCompanyTarget` | `research_domain` | none | Research -> Company Catalog; Research -> Evidence Intake | either L2 sibling -> the other sibling |
| `http-to-company` | Map HTTP payload to Company command/query | `fastapi_http_adapter` | `company_catalog` | `thesis_trace_application` | adapter-private `CompanyHttpRequest` | `CreateCompanyCommand` / `SearchCompaniesQuery` | `thesis_trace_application` | none | L0 -> adapter; L0 -> Company Catalog | Company Catalog -> FastAPI; framework type leakage |
| `http-to-evidence-intake` | Map HTTP payload to submit/query intent | `fastapi_http_adapter` | `evidence_intake` | `thesis_trace_application` | adapter-private `EvidenceIntakeHttpRequest` | `SubmitEvidenceUrlCommand` / `GetEvidenceIntakeQuery` | `thesis_trace_application` | none | L0 -> adapter; L0 -> Evidence Intake | Evidence Intake -> FastAPI; framework type leakage |
| `research-to-postgres` | Atomically save domain state, audit and durable work | `research_domain` | `postgres_research_adapter` | `thesis_trace_application` | `ResearchTransactionRequest` | adapter-private storage mapping | `thesis_trace_application` | adapter-private pool/unit of work | adapter implements Research-owned port | domain -> ORM/SQL/session; adapter mutates domain objects |
| `worker-to-evidence` | Map a leased job to a processing command | `collector_worker_adapter` | `evidence_intake` | `thesis_trace_application` | adapter-private claimed row | `ProcessEvidenceIntakeCommand` | `thesis_trace_application` | adapter-private worker loop and lease client | L0 wires adapter to Evidence port | worker imports Evidence private types |
| `evidence-to-source-fetch` | Retrieve a URL under the versioned restriction policy | `evidence_intake` | `restricted_source_fetch_adapter` | `thesis_trace_application` | `RestrictedSourceRetrievalRequest` | adapter-private HTTP request | `thesis_trace_application` | adapter-private DNS/HTTP runtime | adapter implements Evidence-owned port | Evidence imports HTTP/DNS types; adapter bypasses policy |
| `research-event-to-ui-query` | Turn a committed event into query invalidation | `research_domain` | `responsive_web_adapter` | `thesis_trace_application` | `ResearchEvent` | `InvalidateEvidenceIntakeQuery` | `thesis_trace_application` | none | L0 fan-out; UI queries API | event payload becomes UI truth; UI mutates domain state |

## Delivery, failure, and deduplication contracts

- Before acceptance: invalid JWT/identity/role, URL, Company visibility/version, or unavailable transaction returns a stable rejection and creates no partial state.
- After acceptance: completion and failure are visible through committed state and events, not by rewriting the original HTTP response.
- Every persistent at-least-once event has `event_id`, `event_type`, `source`, `correlation_id`, `stream_id`, `sequence`, `occurred_at`, payload and retry metadata.
- A job claim carries a lease token, expiry and attempt. Only the current lease holder may commit a result.
- A crash before result commit is recovered by lease expiry. Repetition after commit is absorbed by intake/version transition, persistent event ID and canonical uniqueness constraints.
- The same normalized URL must not create a second canonical source. Different URLs with the same content hash may add lineage observations but must not create a second immutable content snapshot.
- Transient DNS, timeout, rate-limit and recoverable upstream failures enter `retrying`. SSRF-policy, prohibited address/scheme/port, redirect-policy, maximum-size and unsupported-media failures enter a non-secret terminal `failed` state. Retry exhaustion enters `dead-letter`.
- Public errors never include raw exception text, response bodies, credentials, secrets, or internal network details.

## Evolution review

| Change scenario | Candidate A impact | Candidate B impact |
| --- | --- | --- |
| Add a source adapter | Adapter registry, composition, contract tests | Same |
| Add a private processing stage | Evidence module, job payload/version, migration and tests | Same plus dispatcher mapping when payload changes |
| Add an in-process subscriber | L0 fan-out and tests | L0 fan-out and tests |
| Add a durable subscriber with independent retry | Requires topology/ADR/manifest change | Add subscriber queue and dispatcher mapping locally |
| Add a platform variant | Composition/deployment plus validation profile | Same, with dispatcher deployment and capacity also governed |

## Assurance and blockers

The functional comparison is `estimated`: it is a greenfield static derivation and has no release-equivalent target measurement. Stronger evidence is not needed to select the smaller logical topology for this best-effort slice, but all platform performance, capacity and operational reserve claims remain `BLOCKED` until the following are fixed and validated:

- target CPU, runtime/framework versions, compiler/build and release composition;
- queue capacity, lease duration, retry schedule and overload behavior;
- fetch deadline, maximum bytes, redirect count and accepted media types;
- database isolation level and exact canonical URL/content uniqueness constraints;
- UI invalidation mechanism and bounded polling behavior;
- versioned SSRF/DNS-rebinding policy;
- load, crash/restart, duplicate delivery, maximum-payload, redirect and error-path evidence.

## Validation conditions

Candidate A may enter implementation only when its manifest relationships validate in the design-phase gate. The walking skeleton is accepted only with:

1. Cloudflare JWT contract tests covering signature, issuer, audience, expiry, allowlisted identity and fail-closed key failure.
2. PostgreSQL integration tests proving intake, audit and job are atomic under both commit and injected rollback.
3. Lease/restart tests proving reclaim after crash, stale-lease rejection and same-stream serialization.
4. Deduplication constraint tests for repeated normalized URL, repeated content hash and concurrent submissions.
5. Restricted-fetch adapter tests for scheme, port, private/link-local/metadata addresses, DNS rebinding, redirect, size, media type, timeout and sanitized failure.
6. API/OpenAPI tests proving `202` receipt and role-filtered record/version queries.
7. Responsive Playwright tests proving Server-authoritative received/processing/succeeded/failed states, refresh recovery, narrow reflow and no client-only completion.
8. Architecture gate and generated-view stale check with exact command, exit code and minimal raw evidence.
