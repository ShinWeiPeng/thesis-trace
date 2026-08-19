# ALG-0007: AI output validation
## Metadata
- Status: proposed
- Owner module: recommendation
- Product feature: Candidate fact and recommendation validation
- Flow IDs: recommendation-analysis-flow, anomaly-evaluation-flow
- Related ADRs: none
- Source paths: planned recommendation policy
- Test and benchmark paths: planned critic/provider contract tests
- Supersedes: none
## Problem and observable success
Convert untrusted model output into a candidate input only when structure and citations are provably valid.
## Inputs, outputs, units, ranges, and data-quality assumptions
Input is model JSON, exact schema, immutable sources and critic response; output is validated candidate or rejection trace.
## Constraints and quantitative acceptance thresholds
Safety, citation, schema and critic gates require 100% pass; AI never directly sets deterministic results.
## Candidate methods and comparative evidence
Candidates: permissive parsing/repair; strict schema plus deterministic source checks and critic. Strict validation is selected to fail closed.
## Selected method and reasons for rejecting alternatives
Validate exact schema, types/enums, citation existence/direct support, subject/time coherence, policy bounds, then require structured critic PASS.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Run gates in fixed order and collect a trace. Any failure rejects the entire decision-critical output; no partial merge or auto-repair. Noncritical prose may be omitted but never substitute for a required field.
## Parameters, calibration, versioning, and compatibility
Schema, prompt, model, source snapshot, critic and policy versions bind the result.
## Time and space complexity and resource budgets
O(output size + cited source size), bounded by request and snapshot limits.
## Errors, degradation, fallback, and forbidden behavior
Malformed/unknown fields, inaccessible citation or critic non-PASS fail closed.
## Validation cases and evidence
Fixtures cover malformed JSON, extra/missing fields, invented citations, wrong subject/time, conflict and critic timeout.
## Risks and monitoring
Validator/schema drift can reject valid outputs; monitor gate-specific failure rates.
## Human approval
Pending non-AI owner approval.
