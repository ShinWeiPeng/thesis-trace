# ALG-0016: Action priority and safety lock
## Metadata
- Status: proposed
- Owner module: workflow
- Product feature: Action Inbox priority
- Flow IDs: action-item-creation-flow, action-item-transition-flow
- Related ADRs: none
- Source paths: planned workflow priority policy
- Test and benchmark paths: planned workflow policy tests
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
Pending non-AI owner approval.
