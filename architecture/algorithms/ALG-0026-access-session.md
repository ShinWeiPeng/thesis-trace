# ALG-0026: Access JWT, session, and emergency identity handling
## Metadata
- Status: proposed
- Owner module: access
- Product feature: Cloudflare Access authentication
- Flow IDs: authenticated-request-flow, emergency-access-flow
- Related ADRs: none
- Source paths: planned Access session component, Cloudflare identity adapter and PostgreSQL Access repository; see `architecture/design/access-wave1.md`
- Test and benchmark paths: planned local RSA/JWKS/full-identity contract tests, fake-clock session tests, PostgreSQL revocation tests and responsive logout/emergency Playwright flows
- Supersedes: none
## Problem and observable success
Accept only independently verified Access JWTs and bind local sessions without extending edge authentication.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are JWT/signature keys/issuer/audience/times/provider subject, allowlist and local session; output internal user/role or denial.
## Constraints and quantitative acceptance thresholds
Google session max 8h; emergency Cloudflare-account session max 30m and every login MFA; identity key is provider+subject, never email alone.
## Candidate methods and comparative evidence
Candidates: (A) trust identity headers/email, (B) verify JWT and key identity by `sub`/email alone, and (C) verify JWT on every request then require a token-bound full identity lookup whose `idp.id`/`idp.type` and provider subject form the stable identity key. A is forgeable. B cannot distinguish provider identities and risks forbidden email merging. C is the authoring candidate and fails closed when full identity lookup is unavailable or inconsistent; it remains pending non-AI approval.
## Selected method and reasons for rejecting alternatives
Verify signature, issuer, audience, validity and allowed identity for every protected request; local session expiry is min(own expiry, JWT expiry).
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Unknown key triggers bounded refresh; when refresh unavailable accept only an unexpired previously verified cached key, else deny. Disabled/replaced identity or logout revokes local sessions. Emergency success audits provider/reason and creates shutdown Action Item.
## Parameters, calibration, versioning, and compatibility
Issuer/audience/clock-skew/cache/session limits and identity mappings are versioned configuration.
## Time and space complexity and resource budgets
O(token size), bounded key cache.
## Errors, degradation, fallback, and forbidden behavior
Fail closed on invalid/expired/ambiguous claims or unverifiable key; no public/local bypass.
## Validation cases and evidence
Forged/wrong audience/issuer/expired/rotation/outage/logout/provider collision/emergency disable tests.
## Risks and monitoring
Key rotation/cache outage; monitor denials without logging tokens.
## Human approval
Pending non-AI owner approval.

## Design links
- `architecture/design/access-wave1.md`
- Decisions: `REQ-008`, `REQ-012`, `REQ-046`, `AC-007`, `AC-011`, `AC-040`
