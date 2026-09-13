# Anomaly, Critic, and Fail-closed Slice

- Spec decisions: `DEC-034`, `DEC-035`, `DEC-036`, `DEC-037`, `DEC-084`, `DEC-085`, `DEC-089`, `DEC-090`, `DEC-096`
- Algorithms: `ALG-0003`, `ALG-0004`, `ALG-0005`, `ALG-0007`, `ALG-0030`
- Owning parent: `research_domain` (L1)
- Child: `anomaly_assessment` (L2)
- Flow: `owner_anomaly_assessment`
- Timing class: best-effort
- Review status: Candidate A accepted through ADR-0005 and implemented for the bounded Shadow slice
- Assurance: functional design only; Hard notification remains disabled pending qualification

## Decision boundary

This slice lets an authenticated Owner request a version-bound assessment of immutable Evidence snapshots. The API transaction appends a pending assessment, audit fact, and typed AI job. The independent `ai-worker` claims that job, runs provider-neutral candidate analysis and a strict `RecommendationCritic`, and passes only validated immutable values to Research-owned pure policies. `ALG-0003` preserves A/B/C classification and lineage components, `ALG-0004` scores only critic-validated C clues, and `ALG-0005` produces Hard only when every predeclared-invalidation, source-quorum, independence, conflict, citation, subject, and time gate passes.

The persisted result distinguishes `soft` from `would_be_hard`. Production `hard` publication is impossible until the exact dataset/model/prompt/schema/critic/policy tuple passes `ALG-0030`, completes a false-Hard-free 30-day shadow period on the production Linux Server VM, and has an immutable Owner activation record. The current slice therefore publishes no Hard notification and performs no trade or recommendation side effect.

Until the later Thesis slice supplies a Server-owned immutable predeclared invalidation snapshot through an L0 parent mapping, production assessments fail that gate closed and remain Soft. Fixtures may provide an immutable invalidation snapshot solely to validate the complete deterministic policy; fixture authority never becomes production authority.

## Candidate comparison

### Candidate A: durable AI job with Research-owned final policy

The request transaction writes the assessment, audit, and one typed `anomaly-analysis-v1` job atomically. `ai-worker` leases the job, invokes `RecommendationProvider` and `RecommendationCritic` through application-owned provider-neutral ports, then asks `anomaly_assessment` to evaluate and atomically commit the immutable result. Stale input versions are saved as superseded evidence and cannot update current state.

This candidate follows the already-confirmed process isolation and leased-job decisions. Provider latency cannot block API, collector, or email work. Research owns classification, score, Hard/Soft result, and trace; the versioned offline runner evaluates qualification evidence. Neither provider, critic, worker adapter, nor browser can set policy outcomes.

### Candidate B: synchronous provider and critic calls in the API request

The API could call both models and policy before returning. This removes one pending state and queue, but violates the required AI-worker isolation, couples request availability to provider latency, and cannot satisfy leased stale-result handling. Candidate B is rejected.

### Candidate C: AI worker publishes a model-selected anomaly label

The worker could persist `hard` or `soft` directly from model output. This is structurally smaller but violates deterministic policy ownership and makes schema, critic, or model failure capable of setting a safety result. Candidate C is rejected.

## Boundary Design Table

| ID | Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `access-to-anomaly-actor` | Map a revalidated session into Research assessment authority | `access_domain` | `research_domain` | `thesis_trace_application` | `AuthenticatedActor` | `ResearchActorContext` | `thesis_trace_application` | none | L0 -> Access; L0 -> Research | Access -> Research; Research -> Access |
| `http-to-anomaly-request` | Map bounded HTTP primitives to a typed application request/query | `fastapi_entrypoint` | `thesis_trace_application` | `thesis_trace_application` | adapter-private request DTO | `RequestAnomalyAssessment` / `QueryAnomalyAssessment` | `thesis_trace_application` | none | FastAPI -> L0 | FastAPI -> Research child; Pydantic leakage |
| `research-to-anomaly-command` | Map Research-parent primitives into the child command | `research_domain` | `anomaly_assessment` | `research_domain` | `ResearchAnomalyRequest` | `RequestAssessmentCommand` | `research_domain` | none | Research parent -> child | L0/API -> child contract |
| `snapshot-to-assessment` | Resolve client-selected immutable snapshot identities into Server-owned characteristics, category, and lineage, then bind them to an assessment | `evidence_collection` | `anomaly_assessment` | `research_domain` | snapshot IDs plus immutable stored metadata | `SourceCharacteristicSnapshot` | `research_domain` | source snapshots and observations | PostgreSQL adapter implements the Research-owned port and hydrates the child value | client or either child authors source tier or lineage facts |
| `thesis-invalidation-to-assessment` | Bind a Server-owned predeclared invalidation snapshot when one exists | `thesis_domain` | `research_domain` | `thesis_trace_application` | future immutable invalidation projection | optional primitive invalidation snapshot | `thesis_trace_application` | no private Thesis state | L0 maps L1 projections | Research -> Thesis or Thesis -> Research |
| `assessment-to-postgres` | Atomically append pending work or commit immutable result/audit | `anomaly_assessment` | `postgres_research_adapter` | `research_domain` | `AnomalyAssessmentStorePort` | adapter-private rows | `research_domain` | assessment stream, job lease, immutable result | adapter implements child-owned port | domain -> SQL/ORM/session; adapter computes policy |
| `job-to-ai-worker` | Lease version-bound anomaly work for an isolated process | `anomaly_assessment` | `ai_worker_adapter` | `thesis_trace_application` | `AnomalyAnalysisJob` | adapter-private claimed row | `thesis_trace_application` | opaque lease and retry metadata | adapter implements job port and calls L0 process command | worker -> private tables or child-private mutation |
| `worker-to-provider` | Produce a source-bound candidate without granting policy authority | `thesis_trace_application` | `openai_recommendation_adapter` | `thesis_trace_application` | `RecommendationProviderPort` | provider-private request/response | `thesis_trace_application` | no domain state | adapter implements L0-owned port | provider SDK/types cross L0 boundary |
| `worker-to-critic` | Strictly validate candidate citations, subject, time, invalidation, independence, and conflicts | `thesis_trace_application` | `openai_recommendation_adapter` | `thesis_trace_application` | `RecommendationCriticPort` | provider-private request/response | `thesis_trace_application` | no domain state | adapter implements L0-owned port | critic result directly sets Hard/score |
| `validated-candidate-to-policy` | Map exact validated primitives into pure classification/scoring/anomaly policy | `thesis_trace_application` | `anomaly_assessment` | `research_domain` | `ValidatedAnomalyCandidate` | `EvaluateAssessmentCommand` | `research_domain` | none | L0 -> Research parent -> child | AI adapter -> Research child or storage |
| `assessment-to-react` | Return only the committed Server projection and trace | `thesis_trace_application` | `react_access_adapter` | `thesis_trace_application` | `AnomalyAssessmentResult` | generated OpenAPI DTO | `thesis_trace_application` | none | L0 -> FastAPI -> generated client | browser computes classification, score, or Hard |

## Type Ownership Matrix

| Type | Semantic kind | Owner | Mutation authority | Consumers | Boundary rule |
| --- | --- | --- | --- | --- | --- |
| `SourceTier` | policy enum A/B/C | `anomaly_assessment` | none | source policy, store adapter | ambiguity resolves downward; clue score never changes it |
| `SourceCharacteristicSnapshot` | immutable domain value | `anomaly_assessment` | Server hydration from immutable collector records | classification policy, store | captures publisher, formal-record, editorial, authorship, primary-evidence, and lineage facts; the HTTP request supplies only snapshot identity |
| `ClueFeatureVector` | immutable domain value | `anomaly_assessment` | none | clue policy, trace | exactly five integers 0..2; absent/invalid vector is unscored |
| `ClueRoute` | policy enum | `anomaly_assessment` | none | policy, UI projection | `save_only`, `watch_daily`, or `human_review`; never source promotion |
| `CriticVerdict` | validated domain value | `thesis_trace_application` | strict validator only | Research parent mapping | exact structured PASS plus all named checks; malformed or partial output never constructs this type |
| `RequestAssessmentCommand` | command | `anomaly_assessment` | Owner through Server admission | service/store | contains snapshot IDs/versions and idempotency; no client label/score/Hard field |
| `EvaluateAssessmentCommand` | command | `anomaly_assessment` | AI worker through L0 after validation | service/store | binds job lease and exact input/model/prompt/schema/critic/policy versions |
| `AnomalyDecisionTrace` | immutable policy result | `anomaly_assessment` | pure policies only | record/store/UI projection | ordered source, clue, invalidation, quorum, critic, conflict, qualification gates |
| `AnomalyAssessmentRecord` | versioned aggregate projection | `anomaly_assessment` | store after policy validation | Research parent, PostgreSQL adapter | pending/succeeded/failed/superseded plus immutable result; never crosses L1 directly |
| `AnomalyAnalysisJob` | durable command | `anomaly_assessment` | request transaction and leased worker transitions | PostgreSQL adapter, L0 worker flow | identifiers and version tuple only; no mutable domain object or provider response |
| `AnomalyAnalysisVersions` | immutable configuration | `anomaly_assessment` | composition root only | request service and store | exact build plus provider/critic model, prompt, and schema versions copied into every durable job; blank or unbound values are rejected |
| `AnomalyAssessmentStorePort` | demand-owned port | `anomaly_assessment` | none | PostgreSQL adapter | semantic atomic request/claim/commit/query operations only |
| `RecommendationProviderPort` | provider-neutral output port | `thesis_trace_application` | none | AI worker and provider adapters | exact immutable snapshot in, untrusted structured candidate bytes out |
| `RecommendationCriticPort` | provider-neutral output port | `thesis_trace_application` | none | AI worker and provider adapters | independent strict critic request/result; non-PASS is data, not an exception promoted to Hard |
| `AnomalyAssessmentFlow` / application request/results | application mapping/contracts | `thesis_trace_application` | none | FastAPI, worker entrypoint | hides Research child contracts and provider representations |
| anomaly request/response DTOs | wire representation | `fastapi_entrypoint` | adapter-local | FastAPI/generated client | no authoritative classification, score, or Hard input fields |
| React assessment state | volatile runtime state | `react_access_adapter` | React component | React only | displays pending/result/failure from Server; no durable browser copy |

## State Object Ownership Matrix

| State object | Owner | Lifetime | Mutation authority | Concurrency/version rule | Persistence |
| --- | --- | --- | --- | --- | --- |
| anomaly assessment stream | `anomaly_assessment` | durable per request | Owner admission then leased worker result commit | optimistic input versions; append-only result; stale work becomes superseded | PostgreSQL assessment/version tables |
| anomaly AI job | `anomaly_assessment` | durable until terminal | request transaction creates; current lease holder transitions once | leased claim, attempt, availability, subject concurrency key, idempotency and exact build/version tuple | PostgreSQL job table |
| source/lineage snapshot | `evidence_collection` | durable immutable | collector only | assessment admission resolves exact snapshot IDs to stored category, publisher, and lineage facts | existing source snapshot and observation tables |
| offline qualification evidence | `anomaly_assessment` | versioned repository artifact and one runner invocation | reviewed dataset plus deterministic runner | exact dataset/model/prompt/schema/critic/policy/build tuple; any drift fails the run | committed JSON fixture and CI result; no production activation authority |
| production shadow/activation state (deferred) | future `anomaly_assessment` slice | durable across releases | future shadow recorder and explicit Owner activation command | requires 30 consecutive days and the exact qualified tuple | not implemented; future PostgreSQL records |
| UI assessment view | `react_access_adapter` | component lifetime | current browser interaction | always refreshed from Server record/version | memory only |

No mutable policy state is held in `anomaly_assessment`; all policy functions consume immutable snapshots and explicit versions. Durable mutation is available only through the child-owned store port.

## Actual and intended dependency edges

| Edge | Current | Intended | Rule |
| --- | --- | --- | --- |
| `fastapi_entrypoint -> thesis_trace_application` | present | retained | HTTP implements public application request/query ports |
| `backend_composition -> thesis_trace_application` | present | retained under accepted ADR-0004 | release bootstrap selects adapters only |
| `thesis_trace_application -> research_domain` | present | retained | L0 maps auth, worker, and provider results through Research parent contracts |
| `research_domain -> anomaly_assessment` | present | retained | L1 parent owns and maps its L2 child |
| `backend_composition -> anomaly_assessment` | present | retained | composition constructs child service and store port |
| `postgres_research_adapter -> anomaly_assessment` | present | retained | adapter implements child-owned persistence/job port |
| `ai_worker_adapter -> thesis_trace_application` | present | retained | worker invokes the public L0 process command; it does not mutate Research directly |
| `openai_recommendation_adapter -> thesis_trace_application` | present | retained | adapter implements L0-owned provider/critic ports |
| `anomaly_assessment -> evidence_collection` | absent | forbidden | sibling snapshots cross through Research mapping/store validation |
| `anomaly_assessment -> thesis_domain` | absent | forbidden | future invalidation projection crosses through L0 and Research parent primitives |
| `anomaly_assessment -> provider adapter` | absent | forbidden | L0 owns provider orchestration and validation boundary |
| `ai_worker_adapter -> postgres_research_adapter` | absent | forbidden | worker has no private-table API; only composed ports and L0 command |
| `react_access_adapter -> anomaly_assessment` | absent | forbidden | browser uses generated HTTP contracts only |

## Parent mappings

| Mapping | Parent owner | Input | Output | Failure behavior |
| --- | --- | --- | --- | --- |
| authenticated actor to Research actor | `thesis_trace_application` | `AuthenticatedActor` | Research assessment capabilities | non-Owner request rejected before mutation; Owner/Learner query is role-filtered |
| Evidence snapshots to assessment snapshots | `research_domain` | client-selected source snapshot IDs | immutable Server-hydrated `SourceCharacteristicSnapshot` primitives | absent, wrong-company, inaccessible, stale, or incomplete snapshot rejects admission; client-supplied classification facts are forbidden |
| future Thesis invalidation to Research primitive | `thesis_trace_application` | immutable Thesis invalidation projection | optional version-bound invalidation snapshot | missing or stale value is an explicit failed Hard gate and cannot be supplied by client/AI |
| provider/critic results to validated candidate | `thesis_trace_application` | untrusted provider bytes and critic bytes | exact `ValidatedAnomalyCandidate` primitives | any schema/citation/subject/time/conflict/critic error yields fail-closed result, never partial merge |
| anomaly record to Research result | `research_domain` | `AnomalyAssessmentRecord` | Research-parent primitive projection | L2 enums, job/lease, and persistence contracts stop at L1 |
| Research result to application result | `thesis_trace_application` | Research anomaly projection | role-safe application result | UI receives only committed Server status/trace and never provider raw output |

## Flow and failure contract

1. Revalidate the session and require Owner for a new assessment; Owner or Learner may query a shared role-safe result, while Admin receives unavailable.
2. Resolve succeeded immutable Evidence snapshot IDs against the requested company, derive publisher/category/lineage facts only from stored collector records, and atomically append pending assessment, audit, and `anomaly-analysis-v1` job. The HTTP response returns the committed assessment ID/version and pending status.
3. `ai-worker` leases due work using job type, subject concurrency key, attempt, lease expiry, input versions, idempotency, correlation/causation, and build/policy/model/prompt/schema tuple.
4. Load the same immutable snapshots through public Research contracts, invoke `RecommendationProvider`, validate exact schema/citations, invoke `RecommendationCritic`, and construct a validated candidate only on complete PASS.
5. Run `ALG-0003`, then `ALG-0004` for C only, and finally `ALG-0005`. Missing predeclared invalidation, unresolved lineage, conflict, source mismatch, provider/schema/critic failure, or stale input produces Soft/failure/superseded with a complete trace; none can produce Hard.
6. Commit the immutable result, audit, and terminal job transition atomically. A qualifying deterministic result is stored as `would_be_hard` while formal publication is disabled.
7. Return the latest committed Server projection to the responsive UI. Polling/event invalidation only triggers a query and is never result authority.
8. `ALG-0030` separately proves the versioned 100-case zero-tolerance offline gate. Production shadow evidence, reset tracking, and explicit Owner activation remain a later slice before formal Hard notification can exist.

Provider failures, timeouts, malformed/extra/missing fields, inaccessible citations, non-PASS critic output, conflicting or uncertain source lineage, stale job input, and absent qualification all fail closed. No path performs an automatic trade, publishes an exit recommendation, or sends a formal Hard notification in this slice.

## Validation conditions

Implementation may begin only after ADR-0005 and the linked algorithms are explicitly approved and the schema 2.2.0 design gate passes. A checkpoint requires deterministic golden/property/metamorphic tests, the versioned 100-case dataset runner, provider/critic contract and fault tests, real PostgreSQL atomic request/job/lease/stale-result/RLS evidence, API/OpenAPI generated-client checks, responsive Playwright pending/result/fail-closed rendering, worker-isolation evidence, repository validation, and development/release architecture gates.

Passing the offline dataset does not complete `REQ-007`: the formal Hard capability stays disabled until 30 consecutive production shadow days and a separate explicit Owner activation record exist.
