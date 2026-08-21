# ThesisTrace Algorithm Inventory

SPEC-0001 confirms the product behavior, but each record remains `proposed` until a non-AI owner provides approval metadata. Individually approved records are marked `accepted` in their own metadata.

| Record | Feature | Owner module | Screening result |
| --- | --- | --- | --- |
| [ALG-0001](ALG-0001-evidence-canonicalization.md) | Evidence admission, canonicalization, and deduplication | evidence_collection | Required |
| [ALG-0002](ALG-0002-e-stage-derivation.md) | E0-E6 derivation | evidence_stage | Required |
| [ALG-0003](ALG-0003-source-classification.md) | A/B/C source classification and independence | anomaly_assessment | Required |
| [ALG-0004](ALG-0004-clue-scoring.md) | C-clue scoring and routing | anomaly_assessment | Required |
| [ALG-0005](ALG-0005-anomaly-policy.md) | Hard/Soft anomaly policy | anomaly_assessment | Required |
| [ALG-0006](ALG-0006-provider-failover.md) | AI provider retry and failover | recommendation | Required |
| [ALG-0007](ALG-0007-ai-output-validation.md) | AI output validation | thesis_trace_application | Required |
| [ALG-0008](ALG-0008-valuation-benchmarks.md) | Valuation benchmark calculation | portfolio | Required |
| [ALG-0009](ALG-0009-valuation-validity.md) | Valuation validity and abstention | portfolio | Required |
| [ALG-0010](ALG-0010-return-calculation.md) | Target price and return calculation | portfolio | Required |
| [ALG-0011](ALG-0011-exposure-aggregation.md) | Portfolio exposure aggregation | portfolio | Required |
| [ALG-0012](ALG-0012-dca-selection.md) | DCA multiplier selection | portfolio | Required |
| [ALG-0013](ALG-0013-research-lifecycle.md) | Research lifecycle state machines | thesis | Required |
| [ALG-0014](ALG-0014-trade-processing.md) | Trade normalization and allocation | portfolio | Required |
| [ALG-0015](ALG-0015-action-item-dedup.md) | Action-item creation and recurrence | workflow | Required |
| [ALG-0016](ALG-0016-action-priority.md) | Priority and safety lock | workflow | Required |
| [ALG-0017](ALG-0017-action-transitions.md) | Action-item transitions | workflow | Required |
| [ALG-0018](ALG-0018-assignee-resolution.md) | Assignee resolution | workflow | Required |
| [ALG-0019](ALG-0019-query-consistency.md) | Query filtering, ordering, and summaries | workflow | Required |
| [ALG-0020](ALG-0020-confirmation-challenge.md) | Consequential-action confirmation | access | Required |
| [ALG-0021](ALG-0021-draft-autosave.md) | Draft autosave | thesis | Required |
| [ALG-0022](ALG-0022-job-leasing.md) | Durable job leasing and retry | workflow | Required |
| [ALG-0023](ALG-0023-notification-routing.md) | Notification routing and redaction | notification | Required |
| [ALG-0024](ALG-0024-freshness-slo.md) | Freshness SLO measurement | research | Required |
| [ALG-0025](ALG-0025-backup-retention.md) | Backup retention and readiness | notification | Required |
| [ALG-0026](ALG-0026-access-session.md) | Access JWT and session handling | access | Required |
| [ALG-0027](ALG-0027-authorization.md) | Authorization and non-disclosing denial | access | Required |
| [ALG-0028](ALG-0028-policy-lifecycle.md) | Policy activation and re-evaluation | application | Required |
| [ALG-0029](ALG-0029-email-delivery.md) | Email retry and idempotency | notification | Required |
| [ALG-0030](ALG-0030-anomaly-qualification.md) | Anomaly qualification gate | anomaly_assessment | Required |
| [ALG-0031](ALG-0031-claude-qualification.md) | Claude qualification gate | recommendation | Required |

## Screened as not applicable

- Responsive layout, routes, cards, and themes only present server-owned truth; they do not calculate financial or safety decisions.
- Static Compose, Caddy, and Tunnel topology is deployment configuration; automated placement or failover would require re-screening.
- Append-only audit insertion and provenance display are fixed persistence invariants when they perform no ranking, inference, filtering, or compaction.
- Static asset caching and the prohibition on offline domain storage are fixed security constraints, not selection methods.
