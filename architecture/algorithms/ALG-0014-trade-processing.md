# ALG-0014: Trade normalization and allocation
## Metadata
- Status: accepted
- Owner module: portfolio_domain
- Product feature: CSV/manual Trade import, corrections, company actions and bucket accounting
- Flow IDs: owner_trade_confirmation
- Related ADRs: ADR-0008
- Source paths: planned `backend/src/thesis_trace/modules/portfolio/trades.py`
- Test and benchmark paths: planned `backend/tests/test_trade_policy.py`
- Supersedes: none
## Problem and observable success
Normalize, preview, deduplicate and allocate executions without hidden FIFO, while every correction/company action reconciles buckets to the broker-confirmed total.
## Inputs, outputs, units, ranges, and data-quality assumptions
Canonical fields are source kind, optional broker reference, security, side, integer shares, Decimal price/fees/tax, execution time and source-row identity. Allocations name validated active Thesis or independent buckets. Company actions supply confirmed post-action whole shares and optional Decimal cash-in-lieu.
## Constraints and quantitative acceptance thresholds
Quantity/price are positive; allocations equal executed quantity; sells name buckets and cannot exceed them. Corrections/actions append. No broker credential or order API exists.
## Candidate methods and comparative evidence
FIFO loses attribution. Explicit buckets are required. DEC-103 selects largest remainder over manual or independent-bucket residual allocation.
## Selected method and reasons for rejecting alternatives
Canonicalize, fingerprint, preview, require exact confirmation, then atomically append Trade/allocation/ledger/audit/receipt. Use largest remainder for actions.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Reject invalid security/time/value, mismatch or oversell. `fingerprint=hash(policy_version,source_kind,broker_ref_or_row_id,side,security,time,quantity,price)`; same digest replays and different digest conflicts. Sells never draw another bucket; corrections append reversing/correcting relations. For pre-action quantities `q_i`, total `Q`, and confirmed post-action shares `T`, compute `a_i=T*q_i/Q`, base `floor(a_i)`, then distribute remaining shares by descending fractional remainder with stable bucket ID ascending for ties. Allocate cash by `cash*q_i/Q` with Decimal. Persist quotas, order, inputs and output. Zero `Q` abstains.
## Parameters, calibration, versioning, and compatibility
Bind `trade-normalization-v1`, canonical CSV/fingerprint policy and `largest-remainder-bucket-v1`. Broker-specific parsers require sample-backed future adapters. History remains immutable.
## Time and space complexity and resource budgets
`O(rows + allocations log allocations)` time and `O(rows + allocations)` preview space.
## Errors, degradation, fallback, and forbidden behavior
Unknown CSV, stale/inactive bucket, ambiguity or confirmation failure writes nothing. Never FIFO, mutate history, save broker credentials or order.
## Validation cases and evidence
Golden CSV/manual, duplicate/replay/conflict, buy/sell, incomplete/over allocation, oversell, correction and concurrency. DEC-103 covers exact/remainder/tie/reduction/dividend/cash cases; properties require nonnegative buckets and conserved total. `pytest backend/tests/test_trade_policy.py -q` must match fingerprints and traces.
## Risks and monitoring
Monitor parser rejection, duplicate conflict and reconciliation mismatch without logging private quantities/amounts.
## Human approval
- Approver: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
