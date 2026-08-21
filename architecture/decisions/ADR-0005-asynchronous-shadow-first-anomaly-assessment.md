# ADR-0005: Asynchronous shadow-first anomaly assessment

- Status: accepted
- Date: 2026-08-21
- Decision owner: project owner
- Related specification: `SPEC-0001`, `DEC-034`, `DEC-035`, `DEC-036`, `DEC-037`, `DEC-084`, `DEC-085`, `DEC-089`, `DEC-090`, `DEC-096`
- Related algorithms: `ALG-0003`, `ALG-0004`, `ALG-0005`, `ALG-0007`, `ALG-0030`
- Related review: `architecture/design/anomaly-critic-wave3.md`

## Context and problem

The next SPEC-0001 slice must add source classification, C-clue scoring, strict critic validation, deterministic Hard/Soft policy, and qualification evidence without allowing AI, a worker adapter, or the browser to set a safety result. Provider latency must not block API, collection, or email execution. A production Hard result also depends on a predeclared Thesis invalidation and three enablement gates that cannot yet be satisfied by implementation alone: a versioned 100-case zero-tolerance suite, 30 consecutive production shadow days, and explicit Owner activation.

## Decision

Add `anomaly_assessment` as an L2 child of `research_domain` and use Candidate A from the linked review: a durable, version-bound AI job processed by the isolated `ai-worker`, followed by Research-owned pure deterministic policy and an atomic result commit.

- The request transaction appends a pending assessment, audit fact, and typed `anomaly-analysis-v1` job atomically.
- `thesis_trace_application` owns provider-neutral `RecommendationProviderPort` and `RecommendationCriticPort` contracts and maps only strictly validated immutable values through the Research parent.
- `anomaly_assessment` owns A/B/C classification, lineage independence, C-clue score/route, Hard/Soft policy, complete decision trace, immutable assessment versions, and anomaly qualification state.
- The PostgreSQL adapter implements the assessment-owned store/job port; the worker never reads or writes private tables directly.
- Provider or critic output cannot set source tier, clue score, anomaly class, qualification, notification, recommendation, or trade state.
- Missing or stale snapshots, missing predeclared invalidation, unresolved lineage, conflicts, malformed schema, inaccessible citations, provider failure, critic non-PASS, or stale work all fail closed without Hard.
- Until `ALG-0030` passes its offline and production-shadow gates and an immutable Owner activation exists, a deterministic Hard candidate is persisted only as `would_be_hard`. The slice emits no formal Hard notification, exit recommendation, or trade side effect.
- Until the later Thesis slice supplies a Server-owned immutable predeclared invalidation snapshot through L0 mapping, production assessments remain Soft at that gate. Test fixtures may exercise the complete pure policy but confer no production authority.

## Alternatives considered

### Synchronous provider/critic calls in the API process

This removes a queue and pending state, but couples request availability to provider latency and contradicts the confirmed isolated-worker and leased stale-result contracts.

### Worker-owned or model-owned anomaly label

This reduces mapping code, but lets untrusted output or adapter behavior determine a safety result and violates explicit pure-policy ownership.

### Delay every anomaly capability until the full Thesis slice

This avoids a temporary missing-invalidation Soft gate, but postpones the highest-risk source, critic, fail-closed, dataset, and shadow instrumentation work that `DEC-096` intentionally schedules earlier.

## Benefits, costs, and tradeoffs

The design isolates slow AI I/O, makes every safety decision replayable from immutable versions, and allows offline qualification and production shadow evidence to begin without enabling formal Hard behavior. It also creates a stable parent mapping for the later Thesis invalidation snapshot.

The costs are a durable pending/job lifecycle, more explicit application/Research mappings, provider and critic contract validation, and a period where production assessments cannot become Hard because the Thesis authority and qualification gates are intentionally absent.

## Risks and mitigations

- A hidden stale-input race could publish an obsolete result. The result transaction rechecks every input version and saves stale output only as superseded evidence.
- A provider-wide outage could be confused with bad content. Provider breaker behavior is versioned; content/schema/citation/critic failures never trigger fallback or Hard.
- A/B classification could overstate weak metadata. Ambiguity resolves downward and the exact characteristic/lineage trace is retained.
- Qualification could be mistaken for activation. Offline PASS, shadow PASS, and Owner activation are separate immutable states; none is inferred from another.
- The future Thesis boundary could be bypassed with client input. The API contract accepts no predeclared-invalidation authority field; L0 maps only a Server-owned immutable projection.

## Compatibility and migration impact

The design appends new APIs, PostgreSQL tables, job type, generated client declarations, worker wiring, and Research projections. Existing Company, Evidence, E-stage, Access, and collector contracts remain compatible. Formal Hard notification remains disabled, so no existing notification or Recommendation behavior changes.

## Validation and observable pass conditions

- schema 2.2.0 design gate passes before source edits;
- `ALG-0003`, `ALG-0004`, `ALG-0005`, `ALG-0007`, and `ALG-0030` have explicit non-AI approval metadata;
- deterministic golden/property/metamorphic tests and the exact versioned 100-case runner pass 40/40 Hard positives, 0/60 false Hard, and 100% classification/lineage/score/critic labels;
- provider and critic contract tests prove every malformed, timeout, citation, subject, time, conflict, and non-PASS path fails closed;
- real PostgreSQL tests prove atomic admission/audit/job, leased recovery, idempotency, stale-result supersession, immutable result, and RLS behavior;
- generated OpenAPI/client, frontend component/build, and responsive Playwright tests pass;
- process isolation proves AI delay does not block API or collection work;
- development and release architecture gates and two-axis review pass.

These checks create an implementation checkpoint, not formal Hard activation. `REQ-007` remains incomplete until 30 consecutive production shadow days and a separate explicit Owner enablement are recorded.

## Approval

Approved by the project owner on 2026-08-21 in `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1` with the explicit instruction: `核准 ADR-0005 與 ALG-0003、ALG-0004、ALG-0005、ALG-0007、ALG-0030 現有內容`.
