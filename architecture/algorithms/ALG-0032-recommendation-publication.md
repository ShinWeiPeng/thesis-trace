# ALG-0032: Source-bound Recommendation publication

## Metadata

- Status: accepted
- Owner module: recommendation_domain
- Product feature: Strict investment-candidate validation and immutable Recommendation publication
- Flow IDs: owner_recommendation_analysis
- Related ADRs: ADR-0009
- Source paths: planned `backend/src/thesis_trace/modules/recommendation/contracts.py`, `service.py`, `policy.py`, `ports.py`; parent `application/contracts.py`
- Test and benchmark paths: planned `backend/tests/test_recommendation_policy.py`, `test_recommendation_postgres.py`, `test_recommendation_provider_contract.py`
- Supersedes: none; does not change anomaly ALG-0007

## Problem and observable success

Publish a new immutable recommendation only from an exact source/valuation/portfolio binding and fully validated provider/critic evidence. A failed or stale analysis never becomes an actionable buy. An anomaly critic PASS is not an investment critic PASS.

## Inputs, outputs, units, ranges, and data-quality assumptions

Inputs: authenticated Owner, active personal Thesis/cycle and published conditions; immutable Research sources with publisher/time/lineage; published valuation and explicit per-request source choice/reason; immutable Portfolio/risk/Cost Profile/official-price/classification/theme binding; finite Decimal calculation results; active minimum annualized-return policy; model/prompt/schema/build/policy versions. Full holdings remain Portfolio-owned and available only through authorized snapshot queries.

AI receives source excerpts and research/valuation context, not authority to set official facts, method, source selection, target prices, fees, caps or Owner Decision. Candidate schema `investment-candidate-v1` has exactly `schema_version`, `direction`, `raw_dca_ceiling`, `claims`. Direction is `buy|hold|abstain`; ceiling is one of the strings `0`, `0.5`, `1`, `1.5`. Claims are nonblank text plus nonempty unique supporting snapshot IDs, all drawn from the pinned input. Unknown fields/types/enums, booleans used as numeric values, duplicate keys, unknown citations and oversized responses reject rather than repair.

Critic schema `investment-critic-v1` has exactly `schema_version`, `verdict`, `candidate_digest`, `checks`. Checks must contain one result for each candidate claim, bound to the same claim index and citations, with boolean source availability, direct support, subject consistency and time consistency. Require exact claim coverage, matching candidate digest, all checks true and verdict `PASS`. Adapter schemas carry explicit size/count limits tied to the admitted source set; implementation must validate them before provider I/O and test boundary rejection.

Output: immutable `buy|hold|abstain` recommendation with references, final multiplier, Server calculation trace, reason codes, validated claims, critic evidence and provenance; or an analysis failure/superseded record with no actionable Recommendation. A policy abstention is distinct from malformed AI output.

## Constraints and quantitative acceptance thresholds

- Zero published buys after any schema/citation/critic/authority/staleness failure.
- Zero partial cross-domain publication/Action Item commits and zero duplicate publications for the same job completion.
- Use accepted 10% security/30% industry/theme caps, cost and annualized-return formulas; no single-recommendation override.
- Final multiplier is never above the raw ceiling. Missing deployment minimum return is fail closed, not an invented default.
- No formal Hard exit, automatic Trade, order or cash reservation. No new E-stage threshold is inferred.

## Candidate methods and comparative evidence

Model-authored financial output is rejected because AI has no policy authority. Parent composition of trusted owner policies plus strict source/critic validation retains the already accepted formulas and independent snapshot ownership. Copying the anomaly schema is rejected because its clue/invalidation fields cannot establish a Recommendation claim's validity.

## Selected method and reasons for rejecting alternatives

Validate untrusted candidate/critic structure exactly, then apply Recommendation publication predicates over parent-mapped owner results. Portfolio alone calculates sizing/exposure and Thesis alone calculates return/validity. No free-form model repair or partial provider-output merge is permitted.

## Exact behavior, formula or pseudocode, boundaries, and tie-breaking

1. Admit the Owner intent and exact input references; save request, immutable binding, audit and durable job together. Explicit source selection must match the selected published valuation, otherwise require a new valuation publication.
2. Load the pinned inputs in the AI worker, call the provider, strictly validate candidate, call critic with the exact candidate digest, strictly validate every claim check. Any failure saves safe failure evidence; it must not be silently converted to a successful model-backed hold.
3. `hold` or `abstain` requires raw ceiling zero. A malformed contradictory combination rejects. An eligible `buy` requires a positive ceiling; policy rejection of a schema-valid buy produces a zero-multiplier abstention with all blocking reasons, not an unsafe buy.
4. L0 asks Portfolio to evaluate the candidate sizes using the base notional from the selected published valuation's quantity and buy price. For each permitted multiplier descending, use the corresponding analytical quantity and actual Cost Profile fees (including minima), cash and post-cost NAV. Re-evaluate the same final-size net return in Thesis; never reuse the larger draft's fee-sensitive annualized return. No rounding may turn an infeasible candidate feasible. Analytical sizing is not an executable broker order; actual Trades retain their existing whole-share validation.
5. Require current valid valuation, Owner-confirmed method/forecast/source, complete official data, cost/return policy and every risk gate. Preserve independent company-history/peer results and differences. Invalid valuation supplies no new target price. A buy below the minimum return fails closed.
6. Under one transaction, revalidate lease, actor and all bound critical versions, persist the Portfolio-owned frozen risk snapshot, append the Recommendation/version and audit, and invoke Workflow's own publication rule through L0. Commit before returning success. Stale work records superseded evidence only; no current recommendation or Action Item is published from it.
7. Every exact retry returns the original result; changed-payload idempotency reuse rejects. Later source/policy changes never rewrite the immutable result; apply ALG-0033 to current decision availability.

The version tuple includes every input actually consumed: Thesis cycle/condition version; linked Evidence/fact/snapshot versions; valuation/forecast/peer selection; holdings/cash/official-price/classification/theme/Cost Profile; minimum-return and algorithm-policy versions. Unrelated notes and formatting changes are not dependencies. Human-readable bindings must accompany the machine tuple.

## Parameters, calibration, versioning, and compatibility

Initial publication policy `recommendation-publication-v1`; separate candidate and critic versions above. Preserve model/provider/prompt/build/digest metadata per attempt. Existing anomaly requests and qualifications are unchanged. The linked Wave 7 execution contract pins the proposed 32-source/claim limits, excerpt/text and encoded-body caps, 1000-job admission cap, 300-second fenced lease, total 30-second calls, three-attempt transport-only retry and cooperative worker iteration. These are explicit admission/reliability settings, not measured capacity. Real PostgreSQL, bounded transport and shared-worker evidence are required before implementation acceptance.

## Time and space complexity and resource budgets

For S pinned sources, C claims and H holdings/theme memberships, validation is O(S+C+citations), sizing at most four O(H) passes plus the existing valuation computation. Store one immutable reference set, bounded claim/critic evidence and owner snapshots. No recursive analysis or unbounded provider fan-out. No numeric latency/throughput claim; adapter payload and job limits must be explicit pre-code configuration, not silent runtime defaults.

## Errors, degradation, fallback, and forbidden behavior

Non-Owner/unowned records are uniformly unavailable. Missing/invalid data, provider unavailable, invalid candidate/critic, source conflict, stale binding, lost lease, transaction failure and idempotency mismatch are distinct safe error codes. No credentials, prompts, holdings or response bodies in logs. Claude remains disabled absent its existing qualification/activation gates. Never promote Shadow Hard into an exit recommendation.

## Validation cases and evidence

Golden candidate/critic vectors; missing/extra/duplicate keys and claim coverage; invalid numeric strings; unknown/source-conflicting citations; anomaly-schema substitution; timeout/non-PASS; changed digest; same-source-set replay; every multiplier and cap equality; fee-minimum and final-size annualized-return regressions; stale source/Cost Profile/price/Thesis/role before commit; exact retry and conflicting retry; one-transaction risk snapshot/Recommendation/Workflow rollback; Owner-only queries; no Trade/cash mutation. Planned commands: `pytest backend/tests/test_recommendation_policy.py backend/tests/test_recommendation_provider_contract.py -q` and real PostgreSQL `test_recommendation_postgres.py`. Tests must prove all zero-tolerance constraints, not just HTTP success. Evidence: test output and build/spec/manifest-bound results; none executed for this proposed algorithm yet.

## Risks and monitoring

Implementation evidence (2026-09-05): the combined candidate/critic and pure decision-policy suite has 86 passing tests. See [Wave 7 checkpoint](../design/recommendation-owner-decision-wave7.md#first-policy-implementation-checkpoint--2026-09-05) for exact scope and regression failures. Publication, fees/returns, transport, atomic persistence and runtime safety are not yet validated; the earlier planned test inventory is not a completion claim.

Follow-up evidence (2026-09-05): adding the pure publication-plan tests brings the combined Recommendation suite to 110 passing tests. Fee-aware Portfolio sizing and exact cap comparison vectors now pass. The full host suite has 285 passed / 38 skipped. These supersede the earlier checkpoint only for pure sizing/publication predicates; actual publication, final-size return recomputation in L0, worker transport and combined persistence remain unfinished. See the [current checkpoint](../design/recommendation-owner-decision-wave7.md#sizing-publication-planning-and-workflow-checkpoint--2026-09-05).

Watch safe category counts for stale jobs, missing configuration, invalid schema/citations, critic rejection, expiry and transaction contention. Return actionable UI explanations. Dependency omissions could allow stale advice; mutation tests must change each binding independently. Cost sizing has the ADR-0009 conformance repair, but it must still be mapped to final-size return and fenced persistence before buy publication.

## Human approval

- Approver: project owner
- Approval date: 2026-09-05
- Approval reference: ongoing SPEC-0001 conversation, explicit instruction `核准 ADR-0009 與 ALG-0032、ALG-0033、ALG-0034`.
