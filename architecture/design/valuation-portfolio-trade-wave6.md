# Valuation, Portfolio, Trade and Exposure Wave 6

- Spec decisions: `DEC-025` through `DEC-032`, `DEC-079` through `DEC-082`, `DEC-089`, `DEC-090`, `DEC-096`, `DEC-101` through `DEC-104`
- Algorithms: `ALG-0008`, `ALG-0009`, `ALG-0010`, `ALG-0011`, `ALG-0012`, `ALG-0014`
- Owning domains: `thesis_domain` for Valuation; `portfolio_domain` for Cost Profile, Holdings, Trades, Allocation, Exposure and Risk Snapshot
- Application flows: `owner_valuation_publication`, `owner_portfolio_management`, `owner_trade_confirmation`
- Timing class: best-effort
- Review status: Candidate A accepted through ADR-0008
- Assurance: estimated functional topology and static cost comparison; no numeric performance claim

## Responsibility and observable behavior

This slice gives an authenticated Owner one Server-authoritative path to save unpublished valuation inputs, compare independent company-history and peer-group candidates, publish an immutable Valuation snapshot after a two-step confirmation, maintain a versioned Cost Profile and investable cash, preview and confirm canonical/manual trades with explicit bucket allocations, apply append-only corrections and company actions, and inspect holdings plus security/industry/theme exposure. Learner and Admin receive no Portfolio projection; valuation remains personal Thesis state.

Recommendation and Owner Decision publication remain outside this slice. `ALG-0012` produces a deterministic risk-feasibility result that the later Recommendation slice may bind; it does not publish a Recommendation or place a trade.

## Candidate comparison

### Candidate A: synchronous owner transactions coordinated by L0

`thesis_trace_application` maps Access, Research, Thesis and Portfolio-owned immutable projections into consumer-owned commands. Unpublished valuation drafts save directly in Thesis. Valuation publication and Trade/allocation/correction/company-action confirmation use the existing five-minute Access challenge and one destination-owner PostgreSQL transaction. Thesis owns valuation state and calculation trace; Portfolio owns Cost Profile, cash, classifications, trades, allocations, holdings and risk snapshots. No sibling reads another schema.

### Candidate B: one cross-schema valuation/portfolio repository

One repository could join Thesis, Research and Portfolio tables and commit composite records with less mapping code. It fails functional admission because the repository would own no domain semantics, expose storage representation across siblings and bypass demand-owned Ports and RLS ownership.

### Candidate C: durable worker for valuation and trade commands

A worker would serialize commands through jobs and retries. The algorithms are bounded pure Decimal policies and the only I/O is owner-scoped PostgreSQL. Queueing adds pending state, leases, retry/dead-letter semantics and eventual UI consistency without a provider or measured expensive computation. It is rejected for this slice.

Candidate A is selected. Its assurance is `estimated`; selection rests on ownership, atomicity and fewer failure transitions, not a latency or capacity claim.

## Boundary Design Table

| ID | Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `access-to-valuation-actor` | Map a revalidated Owner into valuation capability | `access_domain` | `thesis_domain` | `thesis_trace_application` | `AuthenticatedActor` | `ValuationActorContext` | `thesis_trace_application` | current actor/role/session | L0 -> Access; L0 -> Thesis | Access -> Thesis; client selects owner |
| `research-to-valuation-facts` | Map source-bound company history, forecast and peer facts into Thesis-owned inputs | `research_domain` | `thesis_domain` | `thesis_trace_application` | `ValuationSourceFact` plus immutable Evidence/snapshot identity | `ValuationSample` and forecast primitives | `thesis_trace_application` | exact fact/Evidence/snapshot versions | L0 -> Research; L0 -> Thesis | browser submits values; Thesis -> Research; Thesis adapter reads Research tables |
| `portfolio-cost-to-valuation` | Supply a versioned Owner Cost Profile without transferring Portfolio state | `portfolio_domain` | `thesis_domain` | `thesis_trace_application` | `CostProfileSnapshot` | `ValuationCostInput` | `thesis_trace_application` | immutable Cost Profile version | L0 -> Portfolio; L0 -> Thesis | Thesis -> Portfolio; cross-schema join |
| `confirmed-valuation-transaction` | Consume one exact challenge and publish one immutable Valuation snapshot | `thesis_trace_application` | Access, Research, Portfolio and Thesis owner adapters | `backend_composition` | exact draft, Cost Profile, Evidence, source snapshot and fact binding | owner adapter transaction seams | `postgres_atomic_adapter` | one challenge plus locked source/cost/draft versions and valuation audit | composition -> atomic adapter -> Access/Research/Portfolio/Thesis adapters | L0 imports SQL/session types; stale source/cost publish; partial challenge consumption |
| `thesis-valuation-to-application` | Map Valuation draft, candidates, validity and trace into role-safe application values | `thesis_domain` | `thesis_trace_application` | `thesis_trace_application` | `ValuationRecord` | `ValuationFlowResult` | `thesis_trace_application` | none | L0 -> Thesis; FastAPI -> L0 | FastAPI/React -> Thesis contracts |
| `access-to-portfolio-actor` | Map a revalidated Owner into Portfolio capability | `access_domain` | `portfolio_domain` | `thesis_trace_application` | `AuthenticatedActor` | `PortfolioActorContext` | `thesis_trace_application` | current actor/role/session | L0 -> Access; L0 -> Portfolio | Access -> Portfolio; Learner/Admin projection |
| `thesis-to-allocation-target` | Validate active Thesis bucket identity and ownership | `thesis_domain` | `portfolio_domain` | `thesis_trace_application` | `ThesisAllocationProjection` | `AllocationTarget` | `thesis_trace_application` | Thesis ID/version/status/owner/security | L0 -> Thesis; L0 -> Portfolio | Portfolio -> Thesis; Portfolio adapter reads Thesis tables |
| `confirmed-trade-transaction` | Consume an exact challenge and append trade/allocation/holding/audit state atomically | `thesis_trace_application` | Access and Portfolio owner adapters | `backend_composition` | `ConfirmedTradePort` primitives | owner adapter transaction seams | `postgres_atomic_adapter` | challenge plus Portfolio stream/receipt/audit | composition -> atomic adapter -> Access/Portfolio adapters | L0 imports SQL/session types; either adapter writes sibling schema |
| `portfolio-to-application` | Return Cost Profile, holdings, trade preview/history and exposure snapshots | `portfolio_domain` | `thesis_trace_application` | `thesis_trace_application` | Portfolio projections | `PortfolioFlowResult` | `thesis_trace_application` | none | L0 -> Portfolio; FastAPI -> L0 | browser computes holdings/exposure; adapter-private rows leak |

## Type Ownership Matrix

| Type group | Owner | Kind and visibility | Lifetime/mutability | Authority and consumers | ABI/wire/storage impact |
| --- | --- | --- | --- | --- | --- |
| `ValuationMethod`, `ValuationHorizon`, `ValuationSource`, `ValuationCoverage` | `thesis_domain` | policy enums, module-public | immutable | Thesis policy; L0/adapter store values | Python contract; explicit JSON/OpenAPI values; schema-qualified columns |
| `ValuationSample`, `ValuationDistribution`, `ValuationCandidate`, `ValuationDecisionTrace` | `thesis_domain` | domain values, module-public | immutable evaluation | ALG-0008/0009/0010 and Thesis store | Decimal serialized as strings; immutable JSON trace plus normalized metadata |
| `ValuationSourceFact` | `research_domain` | domain value, module-public | durable immutable source fact | trusted collection/normalization boundary; L0 read-only consumer | normalized Research row keyed by Evidence and fact ID; never client-authored |
| `ValuationDraft`, `ValuationRecord`, valuation commands and preview | `thesis_domain` | domain/command/query values, module-public | draft version mutable only by accepted command; published record immutable | Owner through L0; Thesis service/store | no Research/Portfolio DTO or framework type |
| `ValuationStorePort` | `thesis_domain` | demand-owned port, module-public | process binding | Thesis service and PostgreSQL Thesis adapter | semantic methods only; no SQL/session type |
| `PortfolioActorContext`, `HoldingBucketKind`, `AllocationTarget` | `portfolio_domain` | policy/domain values, module-public | one command or durable reference | L0 maps owner and active Thesis primitives | no Access/Thesis DTO; stable IDs and versions only |
| `CostProfileSnapshot`, `InvestableCashVersion`, `OfficialClassification`, `RiskTheme` | `portfolio_domain` | versioned domain values, module-public | append-only versions | Owner and Portfolio policy | Decimal strings on wire; normalized Portfolio tables |
| `CanonicalTrade`, `TradeAllocation`, `TradePreview`, `TradeRecord`, `CorporateActionRecord` | `portfolio_domain` | command/domain/query values, module-public | preview transient; confirmed records append-only | ALG-0014; Portfolio service/store | canonical JSON/OpenAPI; schema-qualified relational storage |
| `HoldingSnapshot`, `ExposureSnapshot`, `DcaSelection` | `portfolio_domain` | immutable domain values, module-public | one evaluation/snapshot | ALG-0011/0012; L0 and later Recommendation mapping | private amounts omitted from email; Decimal strings on wire |
| `PortfolioStorePort`, `BrokerStatementParserPort` | `portfolio_domain` | demand-owned ports, module-public | process binding | PostgreSQL adapter; future broker parser adapter | no broker SDK, CSV library or SQL types |
| application request/result/confirmed-port types | `thesis_trace_application` | composition mappings, module-public | request lifetime | FastAPI/composition | primitives only; distinct from child contracts |
| HTTP/generated DTOs | `fastapi_entrypoint` | wire representations, private | request/response lifetime | FastAPI and generated client | versioned JSON/OpenAPI; no authority fields |
| PostgreSQL row/transaction bindings | destination adapters / `backend_composition` | storage/adapter bindings, private | transaction or process lifetime | composition and owning adapter only | never enter L0-L2 public contracts |
| React route/form state | React Thesis/Portfolio adapters | runtime UI state, private | volatile | current browser only | URL stores route identity; no domain data in persistent browser storage |

Every listed contract references only primitive/standard types or same-owner project types. There is no C ABI or shared-memory representation.

## State Object Ownership Matrix

| State object | Owner | Lifetime | Mutation authority | Concurrency/version rule | Persistence |
| --- | --- | --- | --- | --- | --- |
| valuation drafts and peer selections | `thesis_domain` | durable versioned | personal Owner explicit save | expected version and idempotency | `thesis.valuation_drafts` and peer rows |
| valuation source facts | `research_domain` | durable immutable source-snapshot lifetime | trusted collector/normalizer | Evidence version + snapshot ID + fact ID | `research.valuation_source_facts` |
| published valuation snapshots/traces | `thesis_domain` | durable immutable | confirmed publish transaction | challenge-bound exact draft/source/Cost Profile versions | `thesis.valuation_snapshots` and trace rows |
| Cost Profiles and investable cash | `portfolio_domain` | durable append-only versions | Owner explicit save | expected version; effective time immutable | `portfolio.cost_profiles`, `portfolio.investable_cash_versions` |
| official classifications and custom themes | `portfolio_domain` | durable versioned | Server source / Owner confirmation | immutable effective snapshot | Portfolio classification/theme tables |
| trades, corrections and company actions | `portfolio_domain` | durable append-only | confirmed command | fingerprint/idempotency/expected version | `portfolio.trades`, correction/action rows |
| allocations and holding ledger | `portfolio_domain` | durable append-only | same confirmed transaction | allocations conserve quantity; no cross-bucket FIFO | allocation and ledger rows |
| exposure/risk snapshots | `portfolio_domain` | durable immutable | deterministic policy evaluation | bind exact holdings/cash/prices/classifications/policy | Portfolio snapshot rows |
| Portfolio audit and receipts | `portfolio_domain` | durable append-only | same owner transaction | actor/key/digest unique | Portfolio audit/receipt rows |
| consequential transaction coordinator | `backend_composition` | one request | Access plus destination store owner under coordinator | all-or-nothing challenge and destination commit | one PostgreSQL transaction |
| route/form state | React adapters | page/route lifetime | browser | reload from Server; conflict stops submit | URL and volatile memory only |

No new mutable file-scope, static, thread-local, `extern`, address-passed or process-global policy object is introduced; manifest `state_objects` therefore remains empty.

## Actual and intended dependency edges

| Edge | Current | Intended | Rule |
| --- | --- | --- | --- |
| `thesis_trace_application -> thesis_domain` | present | extend | coordinate valuation commands/queries |
| `thesis_trace_application -> portfolio_domain` | declared placeholder | implement | coordinate Owner portfolio/trade queries and commands |
| `thesis_trace_application -> research_domain` | present | extend | resolve exact valuation/company/price source facts |
| `thesis_trace_application -> access_domain` | present | extend | authorization and challenges |
| `backend_composition -> portfolio_domain` | absent | add | construct Portfolio service |
| `backend_composition -> postgres_portfolio_adapter` | absent | add | select concrete Portfolio persistence |
| `backend_composition -> postgres_atomic_adapter` | absent | add | select atomic confirmation coordinator without SQL/session exposure |
| `postgres_atomic_adapter -> Access/Research/Thesis/Portfolio adapters` | absent | add | own request-scoped cross-adapter database transaction binding |
| `postgres_portfolio_adapter -> portfolio_domain` | absent | add | implement demand-owned store port |
| `fastapi_entrypoint -> thesis_trace_application` | present | extend | explicit valuation/portfolio/trade endpoints |
| React adapters -> generated HTTP | Thesis only | extend/add Portfolio adapter | no Python/domain import |
| `thesis_domain <-> portfolio_domain` | absent | forbidden | all mapping remains at L0 |
| `postgres_thesis_adapter <-> portfolio schema` | absent | forbidden | adapter stays owner-scoped |
| `postgres_portfolio_adapter <-> thesis/research schema` | absent | forbidden | no cross-schema shortcut |

## Parent mappings

| Mapping | Parent owner | Input | Output | Failure behavior |
| --- | --- | --- | --- | --- |
| actor to valuation/portfolio actor | `thesis_trace_application` | authenticated Access actor | child-owned actor contexts | non-Owner Portfolio access is uniformly unavailable |
| Research facts to Valuation input | `thesis_trace_application` | source/version-bound facts | `ValuationEvidenceInput` | missing/stale/unconfirmed facts abstain or reject publish |
| Cost Profile to Valuation cost input | `thesis_trace_application` | immutable `CostProfileSnapshot` | child-owned Decimal primitives | absent/stale profile prevents publish-for-Recommendation |
| active Thesis to allocation target | `thesis_trace_application` | exact owner/security/status projection | `AllocationTarget` | inactive/stale/unowned/mismatched Thesis rejects preview/confirm |
| challenge to destination transaction | `postgres_atomic_adapter` | token plus exact payload digest/version | committed valuation or trade record | mismatch/expiry/stale/replay rolls back all state |
| domain result to API result | `thesis_trace_application` | child projection | role-safe application result | private Portfolio data filtered before serialization |

## Flow review

### `owner_valuation_publication`

The synchronous path is Access authorize -> L0 resolves Server-ingested Research facts and Portfolio Cost Profile -> Thesis runs ALG-0008/0009/0010 -> L0 obtains confirmation bound to exact fact/Evidence/snapshot/Cost versions -> composition locks and revalidates those versions in the same PostgreSQL transaction that consumes the challenge and appends the Thesis snapshot/audit -> L0 queries committed result. Draft saves omit confirmation. Data is bounded by unique calendar months spanning at least 36 months, 5–12 peers and immutable source facts; the browser submits fact identities rather than dates, multiples, denominators, forecasts or invalidation event times. There is no Queue, retry, external provider call or new execution context.

### `owner_portfolio_management`

Access authorize -> Portfolio saves/queries Cost Profile, cash, classifications/themes or returns holdings/exposure. Each mutation is one owner transaction. The flow is best-effort and has no numeric budget.

### `owner_trade_confirmation`

Access authorize -> Portfolio canonicalizes and fingerprints -> L0 validates Thesis allocation targets -> Portfolio runs ALG-0014 and ALG-0011/0012 preview -> L0 obtains confirmation -> Portfolio adapter atomically consumes challenge and appends trade/allocation/ledger/audit/receipt -> L0 returns committed holdings/exposure. CSV/manual parsing is bounded; a real broker-specific parser remains absent until a sample exists.

Candidate A adds no Thread, Task, worker, Queue, channel, scheduler decision, real-time workload, data-layout tuning or microarchitecture choice. Existing `linux_server_functional` API-process mapping is extended. Static assurance is `estimated`; stronger performance evidence is not decision-relevant because SPEC defines no latency/throughput/resource threshold and candidates B/C already lose functional admission or add failure transitions.

## Evolution scenarios

| Scenario | Candidate A change locality | Candidate B/C cost avoided |
| --- | --- | --- |
| Add a market-data source | Research adapter/fact mapping and its contract tests | no storage joins added to Thesis/Portfolio |
| Add a broker parser | new L3+ implementation of Portfolio-owned parser contract | Portfolio semantics remain unchanged |
| Add a Recommendation consumer | L0 maps immutable Valuation/Exposure snapshots into Recommendation-owned input | no Thesis/Portfolio direct dependency |
| Add an Action Item subscriber | later durable post-commit L0/outbox design | current sync command does not pretend crash-safe fan-out |
| Add a deployment variant | composition selects adapters; contracts/flows stay stable | no queue topology or worker migration forced |

## Algorithm screening

| Feature | Result | Owner | Record | Evidence state | Public contract impact |
| --- | --- | --- | --- | --- | --- |
| company-history and peer benchmarks | triggered: filtering/statistics/thresholds | `thesis_domain` | `ALG-0008` | accepted golden/property vectors | valuation trace and snapshot |
| validity and abstention | triggered: safety/failure thresholds | `thesis_domain` | `ALG-0009` | accepted boundary/Fake Clock vectors | validity result/errors |
| target price and annualized return | triggered: Decimal formula and costs | `thesis_domain` | `ALG-0010` | accepted hand-calculated vectors | valuation result |
| exposure aggregation | triggered: aggregation/hard caps | `portfolio_domain` | `ALG-0011` | accepted property/golden vectors | risk snapshot |
| DCA selection | triggered: ordered constrained search | `portfolio_domain` | `ALG-0012` | accepted monotonicity/boundary vectors | feasibility result only |
| trade normalization/allocation | triggered: dedup/allocation/correction policy | `portfolio_domain` | `ALG-0014` | accepted CSV/manual/property vectors | trade preview/record |
| route presentation | not applicable: no ranking/policy; renders Server contract | React adapters | none | component/accessibility tests | adapter only |
| owner-scoped query projection | not applicable: direct validated read | owning domains | none | PostgreSQL/RLS/API tests | query DTO only |

## Validation conditions

Before product source edits, ADR-0008 and ALG-0008 through ALG-0012 plus ALG-0014 require explicit non-AI approval, and the planned schema 2.2.0 manifest must pass the design gate. Implementation then follows TDD and requires pure policy golden/property tests, real PostgreSQL RLS/transaction/idempotency/rollback evidence, confirmation-challenge atomicity, migration/grant checks, API/OpenAPI/generated-client checks, responsive Owner/Learner/Admin flows, architecture development/release gates and two-axis review. User-operated acceptance is required before this slice is claimed complete.

## Spec-review remediation checkpoint

The pre-acceptance two-axis review found implementation drift from the accepted tables above. The following mappings are therefore reaffirmed before remediation source edits:

| Review finding | Boundary/owner used by the remediation | Fail-closed behavior |
| --- | --- | --- |
| Browser supplied official close, industry and themes | `portfolio_domain` resolves an owner-scoped `OfficialSecuritySnapshot` through `PortfolioStorePort`; HTTP contains only the security ID | missing, stale or incomplete official facts reject the preview; the immutable fact snapshot is copied into holdings and trade preview |
| Existing cap breach blocked a reducing sell | ALG-0011 compares pre/post exposure for sells; buys still require every hard cap to pass | a sell may only keep or reduce every breached exposure and may never create a new breach |
| Allocation bucket was an unchecked string | L0 maps exact active owner Thesis records to Portfolio `allowed_bucket_ids`; `independent` is the only non-Thesis bucket | inactive, closed, foreign, missing or wrong-company targets reject preview and confirmation |
| Valuation accepted browser-authored values and publication did not bind all source/cost versions | Research owns immutable `ValuationSourceFact`; HTTP submits only Evidence/fact identities; L0 maps facts and composition locks Research, Portfolio and Thesis reads in the confirmed transaction | absent/stale/wrong-company facts, invalid monthly span, changed Evidence/snapshot/Cost Profile/draft, invalid peer eligibility or expired inputs abstain/reject publication |
| CSV enum had no canonical parser | Portfolio-owned parser maps the documented header to the same `CanonicalTrade`; API exposes parse-only preview before normal trade preview/confirmation | malformed headers, rows, dates, Decimals or duplicate fingerprints return stable row errors and never mutate Portfolio |
| CSV dedup stopped at one uploaded file | Portfolio compares the canonical fingerprint against every immutable prior Trade during confirmed mutation | a repeated trade with a new request idempotency key is rejected without changing cash, holdings or history |
| Later Cost Profile saves rebuilt an incomplete projection | Portfolio uses an immutable replace operation that preserves Trade, correction and company-action streams | a cost version can change only the profile and record metadata; append-only histories remain present |
| Historical imports compared official price date to execution date | Portfolio validates latest official close freshness against Server evaluation time and stores that snapshot in the preview/holding | historical execution time cannot reject a current official price; missing/future/stale official data still rejects preview |
| Trade existed only in the global Portfolio route | React maps `/companies/{company_id}/trades` to the same Owner Portfolio API with company-scoped presentation | no duplicate Trade store or client projection is created; non-Owner access stays unavailable |

The existing Boundary Design Table, Type Ownership Matrix, State Object Ownership Matrix, dependency edges and parent mappings remain authoritative. No sibling dependency or cross-schema adapter access is introduced.

## Pre-commit remediation: relational persistence and visible confirmation data

The accepted Candidate A topology is retained with these implementation
corrections:

| Matrix | Decision |
| --- | --- |
| Boundary Design | Canonical CSV validation feeds each accepted row into the existing canonical Trade preview/confirmation boundary; it does not create a second import repository or client-owned Trade state. |
| Type Ownership | Existing Portfolio Trade and exposure contracts remain authoritative. No broker-specific parser implementation is added; `BrokerStatementParserPort` remains reserved as required by REQ-009. |
| State Object Ownership | Portfolio current state is reconstructed from normalized owner rows, Cost Profile, cash, holdings and append-only Trade/allocation/correction/company-action rows. Thesis current valuation metadata is relational while bounded immutable calculation traces may remain JSON. The migration copies existing aggregate JSON under the schema-owning migration role and removes the legacy Portfolio aggregate/version tables before commit, so they cannot remain a second writable authority. |
| Dependencies | PostgreSQL Thesis and Portfolio adapters depend only on their owner domain plus SQLAlchemy/Psycopg. General aggregate/current-state persistence uses declared SQLAlchemy Core tables; reviewed driver SQL is limited to transaction-scoped settings, advisory locking and test cleanup. They no longer import Access contracts or the Research PostgreSQL adapter. |
| Parent mappings | `postgres_atomic_adapter` creates request-scoped destination stores over the connection owned by the confirmed-operation transaction; `backend_composition` only constructs this adapter behind application ports. No mutable `ContextVar` binds destination adapters and no SQLAlchemy type crosses an L0/L1 contract. |

For the confirmed transaction seam, Candidate A creates a request-scoped
destination store over the already-open SQLAlchemy connection. Candidate B is
the current process-global `ContextVar` binding; it hides mutable transaction
state and is rejected. Candidate C passes a Session through functional Ports;
it leaks framework authority into L0/L1 and is rejected. Candidate A preserves
one transaction, RLS, optimistic versions and immediate UI consistency without
adding a thread, queue or retry lifecycle.

The forward migration is verified against both an empty database and a populated
pre-normalization snapshot. Because existing tables use FORCE RLS and immutable
UPDATE/DELETE triggers, the NOBYPASSRLS schema-owning migration role opens a
transaction-local maintenance window with owner-only `ALTER TABLE`, performs the
backfill, retires the legacy Portfolio JSON tables, and restores FORCE RLS plus
all retained append-only triggers before commit. Runtime API/worker roles have
neither table-owner nor DDL authority and cannot open that window.

Confirmation dialogs render the complete Server `impact_summary`, and the
Portfolio projection renders Server `security_exposure`, `industry_exposure`
and `theme_exposure`. Valuation and Outcomes/Reflections receive stable direct
URLs under the selected Thesis. These presentation changes add no domain state
or algorithm.
