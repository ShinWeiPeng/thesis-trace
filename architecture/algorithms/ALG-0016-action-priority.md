# ALG-0016: Action priority and safety lock
## Metadata
- Status: accepted
- Owner module: workflow
- Product feature: Action Inbox priority
- Flow IDs: action-item-creation-flow, action-item-transition-flow
- Related ADRs: ADR-0006
- Source paths: `backend/src/thesis_trace/modules/workflow/service.py`, `backend/src/thesis_trace/adapters/postgres_workflow/adapter.py`
- Test and benchmark paths: `backend/tests/test_workflow_domain.py`, `backend/tests/test_workflow_postgres.py`
- Supersedes: none
## Problem and observable success
Assign explainable priority and prevent overrides from weakening safety work.
## Inputs, outputs, units, ranges, and data-quality assumptions
Input is typed trigger snapshot, optional Owner override and policy version; output system/effective priority, rule IDs, reason and safety-lock floor.
## Constraints and quantitative acceptance thresholds
Priorities are critical/high/normal/low. Hard anomaly and specified evidence invalidations floor at critical; transaction/risk-data failures floor at high.
## Candidate methods and comparative evidence
Candidates: AI ranking; explicit ordered rules. Rules are selected because priority is safety-relevant.
## Selected method and reasons for rejecting alternatives
Evaluate all matching rules, select the highest severity, then clamp an allowed personal override to the safety floor.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Order `critical>high>normal>low`; ties retain all matching rule IDs in stable ID order. Effective priority is max(system safety floor, allowed override). Only resolving/superseding/correcting the underlying condition removes a lock.

The first approved rule set is `action-priority-v1`:

| Rule ID | Trigger | System priority | Safety floor / lock |
| --- | --- | --- | --- |
| `workflow.formal-hard-anomaly-v1` | formally activated Hard anomaly | critical | critical / locked |
| `workflow.active-thesis-evidence-invalidation-v1` | A/B correction, withdrawal, invalidation or stage degradation invalidates/lowers an active Thesis | critical | critical / locked |
| `workflow.trade-integrity-v1` | confirmed execution missing import/reconciliation/allocation or violates holdings | high | high / locked |
| `workflow.risk-input-unavailable-v1` | missing/stale holdings, investable cash or official price prevents risk calculation | high | high / locked |
| `workflow.shadow-anomaly-review-v1` | shadow `would_be_hard` or succeeded `human_review` route before formal activation | high | none / unlocked |
| `workflow.manual-tracking-v1` | other authorized manual tracking | normal | none / unlocked |

Unknown automatic triggers fail closed to a high operational exception and are not exposed as an assigned item until ownership is resolved. A shadow `would_be_hard` must never be treated as formal Hard or safety-locked solely because it is Server-generated.
## Parameters, calibration, versioning, and compatibility
Rule set/floors are immutable policy versions; old evaluations are not overwritten.
## Time and space complexity and resource budgets
O(number of rules).
## Errors, degradation, fallback, and forbidden behavior
Unknown trigger or policy failure uses safe default/high operational review; AI/client cannot set priority.
## Validation cases and evidence
Golden rule cases, tie ordering, override bounds and property that override never falls below floor.
## Risks and monitoring
Rule overlap may create noise; monitor distribution and overrides.
## Human approval
- Approver: project owner
- Approval date: 2026-08-24
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
