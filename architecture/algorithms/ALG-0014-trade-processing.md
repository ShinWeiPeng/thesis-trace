# ALG-0014: Trade normalization and allocation
## Metadata
- Status: proposed
- Owner module: portfolio
- Product feature: CSV/manual trade import and bucket accounting
- Flow IDs: trade-import-flow
- Related ADRs: none
- Source paths: planned portfolio trade policy
- Test and benchmark paths: planned trade tests
- Supersedes: none
## Problem and observable success
Normalize, preview, deduplicate and allocate confirmed executions without hidden FIFO behavior.
## Inputs, outputs, units, ranges, and data-quality assumptions
Canonical fields include broker reference, security, side, quantity, price, fees, tax and execution time; allocations name active Thesis or independent buckets.
## Constraints and quantitative acceptance thresholds
Allocation sum equals executed quantity; sells cannot exceed named buckets; corrections and company actions append records.
## Candidate methods and comparative evidence
Candidates: automatic FIFO; explicit bucket allocation. SPEC selects explicit allocation for Thesis traceability.
## Selected method and reasons for rejecting alternatives
Canonicalize first, compute fingerprint, preview, require confirmation, then atomically persist trade and allocations.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Reject nonpositive quantity/price or invalid security/time. `fingerprint=hash(canonical broker ref/side/security/time/qty/price)`; existing fingerprint is idempotent. Buys require allocation total=quantity; sells validate each selected bucket. Split/reduction/dividend shares distribute proportionally using a versioned remainder rule.
## Parameters, calibration, versioning, and compatibility
CSV canonical schema, fingerprint and fractional/remainder convention are versioned.
## Time and space complexity and resource budgets
O(rows + allocations log allocations).
## Errors, degradation, fallback, and forbidden behavior
Unknown CSV schema fails; no broker credentials/order API; no cross-Thesis automatic FIFO.
## Validation cases and evidence
Golden CSV/manual cases, duplicates, oversells, rounding remainders, corrections and concurrent confirmation.
## Risks and monitoring
Broker format drift; monitor parser rejection and reconciliation mismatch.
## Human approval
Pending non-AI owner approval.
