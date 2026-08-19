# ALG-0003: Source classification and independence
## Metadata
- Status: proposed
- Owner module: research
- Product feature: A/B/C source model
- Flow IDs: evidence-evaluation-flow
- Related ADRs: none
- Source paths: planned research policy
- Test and benchmark paths: planned research policy tests
- Supersedes: none
## Problem and observable success
Classify raw sources and determine whether B sources are genuinely independent.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are publisher identity, source type, authorship, citations and lineage; outputs are A/B/C and an independence graph with reasons.
## Constraints and quantitative acceptance thresholds
Classification and independence labels in the 100-case qualification set must match annotations 100%.
## Candidate methods and comparative evidence
Candidates: publisher-only allowlist; evidence-characteristic rules plus lineage graph. The latter is selected because the same publisher can issue different source types and syndication defeats counts.
## Selected method and reasons for rejecting alternatives
Use fixed A authority rules, B editorial/authorship/verifiable-evidence rules, else C; collapse sources sharing an anonymous claim or underlying report into one independence component.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
A if an authoritative first party emits a formal record; B if editorial responsibility, attribution and verifiable primary evidence all hold; otherwise C. Two B items count independently only if publishers and underlying-evidence components differ. Ambiguity resolves downward.
## Parameters, calibration, versioning, and compatibility
Authority registry and rule version are immutable and effective-dated.
## Time and space complexity and resource budgets
Classification O(sources); lineage components O(vertices+edges).
## Errors, degradation, fallback, and forbidden behavior
Unresolved publisher or lineage becomes C/not-independent. Scores never promote C to A/B.
## Validation cases and evidence
Fixtures cover official, editorial, repost, shared anonymous claim, shared report and conflicting sources; graph tests cover cycles and ordering.
## Risks and monitoring
Publisher identity drift and hidden syndication; monitor manual reclassifications.
## Human approval
Pending non-AI owner approval.
