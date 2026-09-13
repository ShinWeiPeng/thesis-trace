# ALG-0027: Authorization and non-disclosing denial
## Metadata
- Status: accepted
- Owner module: access
- Product feature: Role, ownership and RLS isolation
- Flow IDs: authenticated-request-flow
- Related ADRs: none
- Source paths: planned Access authorization component, transaction-local PostgreSQL security-context adapter and RLS migrations; see `architecture/design/access-wave1.md`
- Test and benchmark paths: planned role/capability property tests, real PostgreSQL RLS matrix and pool-leak tests, API non-disclosure tests and responsive role-boundary Playwright flows
- Supersedes: none
## Problem and observable success
Apply identical server-side role/ownership rules across routes without revealing inaccessible record existence.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are internal actor, role, action, resource owner/class and requested fields; output allowed field set or non-disclosing denial.
## Constraints and quantitative acceptance thresholds
Owner gets personal research/recommendation/trade; Learner shared evidence and own manual Thesis; Admin account/operations but no other portfolios; max ten active accounts.
## Candidate methods and comparative evidence
Candidates: (A) UI filtering, (B) application-only authorization, and (C) application capability/field policy plus transaction-local PostgreSQL identity and matching forced RLS. A is client-controlled. B leaves direct/query mistakes without a storage backstop. C is selected because both layers fail closed and can be cross-checked.
## Selected method and reasons for rejecting alternatives
Compute server capability/field projection, establish transaction-local DB identity and rely on matching RLS predicates.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Deny unless explicit role+action+ownership rule allows. Query/count after scope filtering. Missing and inaccessible object return the same external status/envelope/timing class; audit reason internally. Fields are allowlisted per role before serialization.
## Parameters, calibration, versioning, and compatibility
Role/capability/field policy and RLS migration versions are recorded.
## Time and space complexity and resource budgets
O(1) policy plus scoped indexed query.
## Errors, degradation, fallback, and forbidden behavior
Missing identity/context or RLS setup fails closed; never authorize from client-hidden UI.
## Validation cases and evidence
Role/action/resource matrix at API and real PostgreSQL RLS, field absence, ID probing and transaction-context leakage tests.
## Risks and monitoring
Policy/RLS drift; contract tests compare both layers.
## Human approval
- Approver: project owner
- Approval date: 2026-08-29
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`

## Design links
- `architecture/design/access-wave1.md`
- Decisions: `REQ-008`, `REQ-012`, `AC-007`, `AC-011`
