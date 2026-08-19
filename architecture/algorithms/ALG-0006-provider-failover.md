# ALG-0006: AI provider retry and failover
## Metadata
- Status: proposed
- Owner module: recommendation
- Product feature: Provider-neutral AI orchestration
- Flow IDs: recommendation-analysis-flow
- Related ADRs: none
- Source paths: planned recommendation orchestration
- Test and benchmark paths: planned provider contract tests
- Supersedes: none
## Problem and observable success
Continue only across a provider-wide OpenAI outage and never publish mixed or invalid results.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are immutable snapshot/version tuple, provider health observations, retry state and Claude qualification; output is selected provider or fail-closed result.
## Constraints and quantitative acceptance thresholds
Claude receives production failover only after ALG-0031 passes; the entire identical snapshot is rerun.
## Candidate methods and comparative evidence
Candidates: fallback on any error; versioned circuit breaker for provider-wide failure. Circuit breaker is selected to avoid laundering content/schema failures through another model.
## Selected method and reasons for rejecting alternatives
Retry according to provider policy, open only on provider-wide health evidence, then route new eligible jobs to qualified Claude.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Single timeout, rate limit, content rejection, schema failure or critic rejection never opens the breaker. When open, start Claude from the original snapshot; never combine partial outputs. New jobs return to OpenAI only after recovery closes it; an in-flight job never switches back.
## Parameters, calibration, versioning, and compatibility
Threshold/window/cooldown/retry policy and provider/model versions are immutable and recorded.
## Time and space complexity and resource budgets
O(1) decision per attempt; bounded attempts and timeouts.
## Errors, degradation, fallback, and forbidden behavior
Unqualified Claude or both providers failing yields no recommendation and an Action Item.
## Validation cases and evidence
State-machine tests cover isolated errors, widespread outage, cooldown, half-open recovery, snapshot identity and mid-flight behavior.
## Risks and monitoring
Bad outage classification can amplify load; monitor breaker transitions and fail-closed counts.
## Human approval
Pending non-AI owner approval.
