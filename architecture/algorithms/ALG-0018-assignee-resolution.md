# ALG-0018: Action-item assignee resolution
## Metadata
- Status: proposed
- Owner module: workflow
- Product feature: Automatic private Action Item ownership
- Flow IDs: action-item-creation-flow
- Related ADRs: none
- Source paths: planned workflow ownership policy
- Test and benchmark paths: planned workflow/access integration tests
- Supersedes: none
## Problem and observable success
Assign each item to the one authorized user without accepting client/AI choice.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are source-data owner, item class, roles, user status and primary Admin record; output assignee or unassigned operational exception.
## Constraints and quantitative acceptance thresholds
Portfolio/personal recommendations/trades go to data Owner; Learner personal work stays theirs; operations go to the unique active primary Admin.
## Candidate methods and comparative evidence
Candidates: caller-selected assignee; deterministic ownership mapping. Mapping is selected to prevent disclosure/escalation.
## Selected method and reasons for rejecting alternatives
Resolve from server-owned source semantics and active identities in one transaction.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Personal source→source owner if active/authorized; Learner-derived personal work→Learner; operational→exactly one primary Admin. Zero or multiple legal candidates yields no item exposure, stores exception, and alerts via available operational channel. Admin replacement reassigns only open operational items.
## Parameters, calibration, versioning, and compatibility
Item classification and role policy are versioned.
## Time and space complexity and resource budgets
O(1) indexed lookups plus O(open operational items) for reassignment.
## Errors, degradation, fallback, and forbidden behavior
Never fall back to another user, requester, arbitrary Admin or AI/client input.
## Validation cases and evidence
Role/status matrix, absent/multiple Admin, suspension and reassignment transaction/RLS tests.
## Risks and monitoring
Misclassified source ownership could disclose data; alert every unassigned exception.
## Human approval
Pending non-AI owner approval.
