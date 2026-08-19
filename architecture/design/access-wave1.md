# Access Wave 1 Architecture Authoring

- Scope: `REQ-008`, `REQ-012`, `REQ-046`, `REQ-048`
- Acceptance: `AC-007`, `AC-011`, `AC-040`, `AC-042`
- Algorithms: `ALG-0020`, `ALG-0026`, `ALG-0027`
- Status: authoring candidate; algorithms and any resulting ADR remain pending non-AI approval

## Responsibility and observable behavior

Wave 1 turns the current Owner-only JWT boundary into the Access vertical slice. Every protected request independently verifies the Cloudflare Access JWT signature, issuer, application audience and expiry. Access then resolves the verified JWT subject through Cloudflare's full identity lookup and maps the provider identity to one stable internal user. An optional opaque ThesisTrace session supports immediate logout and revocation but never extends the Access token lifetime.

Access owns accounts, provider identities, roles, sessions, authorization policy, confirmation challenges and security audit. It does not own research, portfolio, recommendation, trade or Workflow records. Application orchestration maps an authorized principal or one-time confirmation grant into the command/query contract owned by the destination domain.

## Cloudflare identity facts and fail-closed rule

The Access JWT `sub` claim is unique for the email/account within the Cloudflare account; it is not by itself the provider discriminator required by ThesisTrace. The provider discriminator MUST come from the full identity lookup response's `idp.id` and `idp.type`. The adapter therefore verifies the JWT first and then performs or obtains a bounded, token-bound `get-identity` lookup. Both JWKS and get-identity transports use the canonical HTTPS Cloudflare tenant origin, reject every redirect before a second request, bound response size and timeout, require an approved JSON media type, and erase underlying exception chains.

The semantic identity key is `(idp.id, idp.type, provider_subject)`. The full identity lookup MUST correspond to the currently verified token and subject. Lookup unavailable, malformed, expired, inconsistent with the JWT, or missing `idp.id`, `idp.type` or provider subject fails closed. Email is a display/audit attribute and allowlist input only; it MUST NOT merge Google and Cloudflare-account identities or become the durable identity key.

## Boundary Design Table

| Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Verify edge credential | FastAPI HTTP adapter | Cloudflare identity adapter | `thesis_trace_application` L0 | JWT header | `VerifiedAccessToken` or non-disclosing rejection | L0 | adapter-private JWKS cache | L0 composes adapter implementing Access-owned port | Trust identity headers; expose JWT/JWK types to L1 |
| Resolve provider identity | Cloudflare identity adapter | `access_domain` L1 | L0 | token-bound full identity response | `VerifiedProviderIdentity` | L0 | none outside adapter | L0 maps verified semantic value into Access | Infer provider from email or `sub`; accept inconsistent lookup |
| Authenticate request | L0 | Access L1 | L0 | `AuthenticateRequest` | `AuthenticatedPrincipal` or denial | L0 | users, identities, sessions | L0 -> Access public input port | Research/Workflow reading Access tables |
| Issue/validate/revoke session | FastAPI adapter | Access L1 | L0 | start, validate or logout intent | opaque cookie result / principal / revoked result | L0 | session aggregate | adapter carries opaque token only | Cookie extending JWT expiry; token digest in DTO/log |
| Authorize capability | L0 or destination parent | Access L1 | L0 | actor, capability and resource scope | `AuthorizationDecision` | caller's parent | user role/status/policy version | parent maps allowed scope to child command | Client role/owner assertion; sibling direct dependency |
| Install DB scope | Access L1 demand port | PostgreSQL security-context adapter L3 | L0 | `DatabaseSecurityContext` | transaction-local security setup | L0 | PostgreSQL transaction GUC | adapter implements Access-owned port | session-level pooled context; domain SQL setting its own role |
| Administer account/identity | FastAPI adapter | Access L1 | L0 | confirmed identity/role/status command | committed version or stable rejection | L0 | accounts, identities, challenges, audit | Owner-only Access command | Direct CRUD; Admin or client self-escalation |
| Emergency entry | Cloudflare adapter | Access L1 | L0 | verified Cloudflare-account identity plus recovery reason | emergency principal and durable event | L0 | emergency session/use/audit | L0 fans event to Workflow | Access creating Workflow-private row; automatic policy activation |
| Preview consequential action | destination parent | Access challenge component | owning L0/L1 parent | canonical actor/action/target/version/payload impact input | `ConfirmationChallenge` | destination parent owns impact mapping | challenge state | parent coordinates Access and domain | Access inventing domain impact or accepting client summary |
| Confirm consequential action | destination parent | Access + destination domain | owning parent | challenge ID, exact payload and nonblank reason | one-use `ConfirmationGrant`, then domain result | owning parent | challenge, domain state, audit | one shared PostgreSQL transaction | Access commit followed by separate domain commit |

## Type Ownership Matrix

| Type | Owner / level | Kind and visibility | Lifetime / mutability | Authority and consumers | Field roles and compatibility impact |
| --- | --- | --- | --- | --- | --- |
| `IdentityProviderKey(idp_id,idp_type)` | Access L1 | domain value, public | immutable | Cloudflare adapter produces; Access consumes | provider identity; new API/domain contract, no adapter handles |
| `ProviderSubject` / `IdentityKey` | Access L1 | domain identity, public | durable identity, immutable | Access resolves and compares | `(provider key, subject)`; storage/index impact |
| `InternalUserId` | Access L1 | domain identity, public | durable, immutable | Access issues; authorized domains reference | UUID storage and public contract |
| `AccountRole` / `AccountStatus` | Access L1 | policy enums, public | versioned durable value | Access commands mutate | role/status wire and storage enums |
| `VerifiedAccessToken` | Access L1 demand contract | domain value, public to L0 | request lifetime, immutable | Cloudflare adapter creates | subject, issuer, audience, expiry, token binding; no raw token |
| `VerifiedProviderIdentity` | Access L1 | domain value, public | request lifetime, immutable | adapter creates; Access consumes | provider key, subject, email fact, lookup time |
| `AuthenticatedPrincipal` | Access L1 | authorization snapshot, public | request lifetime, immutable | Access creates; L0 maps to domain actor | user, role, identity/session versions, JWT expiry, auth kind |
| `SessionId` / `SessionSnapshot` | Access L1 | domain identity/value | durable/session lifetime | Access mutates, HTTP adapter consumes opaque ID | expiry/revocation/version storage impact |
| `Capability` / `ResourceScope` / `AuthorizationDecision` | Access L1 | policy contracts | request lifetime, immutable | Access decides; parents consume | field/capability projection contract |
| `DatabaseSecurityContext` | Access L1 demand contract | semantic adapter input | transaction lifetime | Access creates; PostgreSQL adapter consumes | user/role/request only; never SQL/GUC handles |
| `ConsequentialActionType` / `TargetReference` | Access L1 challenge component | policy/domain reference | request/challenge lifetime | domain parent supplies | action, record and optimistic version wire/storage impact |
| `ImpactSummary` | destination domain/parent | domain-owned presentation contract | preview lifetime | domain parent creates; UI displays | Access stores immutable copy/digest but does not author semantics |
| `ConfirmationChallenge` / `ConfirmationGrant` | Access L1 | security contract | <=5 minutes / single use | Access creates/consumes; parent uses grant | persisted challenge contains only a token digest; plaintext exists only in the one preview response and volatile dialog state |
| `RecoveryPolicyConfiguration` | Access L1 | fail-closed configuration | process lifetime, immutable | composition supplies; session policy consumes | exact `(idp.id,idp.type,subject)`, policy version and enabled observation; no email authority |
| `AccountActionPreview` / `ConfirmedAccountAction` | Account Administration L2 | application results | one command, immutable | account-action service creates; HTTP adapter maps | server-owned summary/version and opaque committed challenge identity |
| `AccountActionUnitOfWork` / `AccountActionService` | Account Administration L2 | demand port and orchestration service | process lifetime bindings | Access owns policy; PostgreSQL adapter implements the atomic UoW | known actions, authorization, current-state summary, mutation, challenge consume and audit |
| JWT claims, JWK client, cookie and SQL row types | L3 adapters | private adapter binding | adapter/request lifetime | adapter only | forbidden in L0-L2 public contracts |

## State Object Ownership Matrix

| State | Owner | Lifetime / storage | Mutation authority | Readers / leakage rule |
| --- | --- | --- | --- | --- |
| Users, role, status, identity version | Access L1 | durable PostgreSQL | confirmed Access commands | Access policy and RLS context only |
| Provider identities | Access L1 | durable PostgreSQL | confirmed add/disable/replace commands | authentication; never merge by email |
| Sessions | Access L1 | durable PostgreSQL | issue, logout, identity disable/version bump, emergency disable, expiry | authentication query; token digest private |
| Confirmation challenges | Access L1 | durable PostgreSQL | preview creates; confirm atomically consumes/revokes | owning parent through Access port |
| Security audit | Access L1 | append-only PostgreSQL | Access transactional commands/events | authorized security history only |
| Emergency use/disable facts | Access L1 | durable PostgreSQL/config observation | verified emergency entry and Owner repair flow | Access and authorized operations |
| JWKS/full-identity cache | Cloudflare adapter L3 | bounded process state | adapter only | no raw token/identity response leakage |
| Database security context | PostgreSQL adapter L3 | one transaction via `SET LOCAL` | adapter only | RLS; cleared at commit/rollback |
| Composition bindings | L0 | process lifetime in `ApiRuntime` | composition root only | no child mutation authority |

No new mutable file-scope global is permitted. Queries return immutable semantic snapshots, never state handles.

## Ports and events

Access-owned inputs:

- `access.authenticate_request`: `AuthenticateRequest -> AuthenticatedPrincipal | AccessDenied`.
- `access.start_session`, `access.validate_session`, `access.revoke_session`.
- `access.authorize_action`: actor/capability/resource -> decision.
- `access.manage_account`: confirmed identity/role/status command.
- `access.preview_confirmation`, `access.consume_confirmation`.

Access-owned demand ports:

- `access.verified_identity`: independently verified JWT plus token-bound full identity lookup.
- `access.repository`: transactional users/identities/sessions/challenges/audit persistence.
- `access.database_security_context`: transaction-local RLS context.
- `access.clock`, `access.nonce`, `access.digest` for deterministic testing and cryptographic generation.

Single Access output sink emits standard envelopes. Durable events use at-least-once delivery, persistent event ID and idempotency key:

- `access.identity_changed`
- `access.session_revoked`
- `access.emergency_authenticated`
- `access.emergency_disabled`

L0 performs fan-out. `access.emergency_authenticated` requests a Workflow safety-locked close-emergency item through a mapped durable event; Access does not import Workflow contracts or tables.

## Flows

### Authenticated request flow

1. FastAPI receives opaque cookie and Access JWT.
2. Cloudflare adapter verifies signature, issuer, audience and expiry for this request.
3. Adapter performs token-bound full identity lookup and validates `idp.id`, `idp.type`, provider subject and JWT consistency.
4. L0 maps `VerifiedProviderIdentity` to `AuthenticateRequest`.
5. Access resolves active identity/user, validates identity version and optional session, and returns a principal.
6. Access authorizes the requested capability/resource scope.
7. PostgreSQL adapter installs transaction-local user/role/request context; domain query/command executes under matching RLS.
8. Response uses field allowlists. Missing and inaccessible resources share one external status/envelope.

### Session and logout flow

Normal expiry is `min(jwt.exp, issued_at + 8 hours)`; emergency expiry is `min(jwt.exp, issued_at + 30 minutes)`. Every request still repeats steps 2-3 above. Logout atomically sets `revoked_at`; disabled/replaced identity, identity-version mismatch, emergency disable or expiry rejects subsequent use. Cookie contains a random opaque token; only its digest is stored.

### Emergency access flow

Cloudflare emergency policy remains disabled by default and is enabled only through Cloudflare administration. Access accepts only the configured Cloudflare-account `IdentityKey`, requires the full identity lookup/provider facts, an enabled-policy observation and the edge MFA evidence, maps it to the existing Owner user without privilege increase, limits the session to 30 minutes, and on first entry atomically appends an immutable security audit plus a durable `workflow.safety_item.requested` event. The event records only the provider triple, policy version, time, actor and approved recovery reason; Access does not claim that the Workflow Action Item exists until the Workflow consumer is implemented. Policy unavailable, disabled, identity-ambiguous or missing recovery capability remains fail closed; no local/public bypass exists.

### Consequential confirmation flow

The destination domain/parent validates current data and creates a human-readable impact summary. Access canonicalizes the binding fields and persists a random opaque, single-use challenge with actor, action type, target ID/version, payload digest, policy version, issued/expiry times and summary digest. Expiry is at most five minutes.

Confirm requires the exact actor/action/target/version/payload, an unexpired unused challenge and a nonblank reason. For Access-owned account and identity actions, `AccountActionService` owns authorization, current-state lookup and the server summary; `AccountActionUnitOfWork` consumes the challenge, applies the mutation and appends audit in one PostgreSQL transaction. The HTTP adapter only maps typed transport values and has no consume-only fallback. Actor/payload/version/action mismatch, `now >= expires_at`, replay, revocation or concurrent consumption rejects and requires a new preview. A retry of a previously committed idempotency key returns the original result without re-execution.

## PostgreSQL forward migrations and RLS contract

Migration `0002_access_identity_session_confirmation`:

- `access.users(user_id UUID PK, role, status, identity_version, created_at, disabled_at)`.
- `access.identities(identity_id UUID PK, user_id FK, idp_id, idp_type, provider_subject, email_fact, status, version, UNIQUE(idp_id,idp_type,provider_subject))`.
- `access.sessions(session_id UUID PK, user_id, identity_id, token_digest UNIQUE, auth_kind, jwt_expires_at, expires_at, revoked_at, identity_version, created_at, CHECK(expires_at<=jwt_expires_at))`.
- `access.confirmation_challenges(challenge_id UUID PK, actor_user_id, action_type, target_id, target_version, payload_digest, summary_digest, policy_version, nonce_digest, issued_at, expires_at, consumed_at, revoked_at, result_id, CHECK(expires_at<=issued_at+interval '5 minutes'))`.
- `access.security_audit_events(...)` append-only; runtime role has no UPDATE/DELETE grant.
- A transaction-safe active-account capacity constraint locks one `access.account_capacity` singleton row before activation and rejects an eleventh active user. Application counting alone is insufficient.
- Partial indexes cover active identity, session digest/revocation, challenge actor/expiry and security audit subject/time.

Migration `0003_access_rls`:

- The application uses a non-owner, non-`BYPASSRLS` database role; governed tables use `ENABLE` and `FORCE ROW LEVEL SECURITY`.
- PostgreSQL adapter executes `SET LOCAL app.user_id`, `app.role`, `app.request_id` inside each transaction. Missing/malformed context matches no rows. Context MUST disappear on commit and rollback before a pooled connection is reused.
- Every write policy has both `USING` and `WITH CHECK`. Owner can access owned investment data; Learner gets shared Evidence and own manual Thesis; Admin gets explicit account/operational rows but no Owner/Learner portfolio or private research.
- Filtering occurs before lookup/count. Missing and inaccessible IDs return the same `resource_not_available` response class and field projection; internal audit may retain the denial reason.

Migration `0004_recovery_session_policy_binding` adds the observed recovery policy version to recovery sessions. Runtime API and collector roles never invoke migration DDL; startup performs only an exact read-only version/name/checksum compatibility probe after the one-shot migration job succeeds.

## TDD seams

1. `VerifiedIdentityPort`: local RSA/JWKS signature, issuer, audience, expiry, key rotation/outage/cache, redirect rejection, JSON media/size bounds, token-bound full identity response, missing/inconsistent `idp` fields, provider/email collision.
2. Access service with fake clock/nonce: 8-hour, 30-minute and exact five-minute boundaries; logout, identity disable/replace, emergency disable, version mismatch and replay.
3. Real PostgreSQL account capacity: 9->10 succeeds; concurrent eleventh activation fails; disable then replacement succeeds.
4. Real PostgreSQL RLS: Owner, two Learners and Admin across select/insert/update/count; cross-user ID probing; identical missing/inaccessible envelope; `SET LOCAL` leakage after commit and rollback.
5. Confirmation: preview/confirm golden path, actor/action/payload/version swap, blank reason, expiry, replay, two concurrent consumers, optimistic conflict and injected rollback. Low-risk draft proves no challenge.
6. Emergency: policy-disabled, wrong account member, absent MFA evidence, provider ambiguity and 30-minute boundaries; first entry produces one audit/event; disable revokes all emergency sessions.
7. API/OpenAPI and Playwright desktop/mobile: session state/logout, role-specific navigation and forbidden-field absence; explicit consequential-action summary, reason, confirm/cancel and stale-version UX.

## Acceptance mapping

| Acceptance | Evidence |
| --- | --- |
| `AC-007` | Cloudflare policy export, real JWT/full-identity contract tests, session clock tests, 10-account concurrent constraint, API role matrix, real RLS isolation and non-disclosure, desktop/mobile logout |
| `AC-011` | Full hostname/path policy and tunnel checks, signature/issuer/audience/expiry/JWKS rotation/outage tests, forged-header rejection, secret scan, origin/port evidence |
| `AC-040` | Disabled emergency policy export, guided Owner-only MFA drill, 30-minute session tests, provider mapping/no escalation, immutable audit + durable Workflow event, repair/disable revocation, no-bypass evidence |
| `AC-042` | Canonical digest/property tests, fake-clock five-minute boundary, role/version/payload/replay/concurrency/rollback tests, atomic PostgreSQL evidence and responsive confirmation UI |

## Dependencies and risks

- Cloudflare policy export and representative full identity responses must prove the token-bound `idp.id`/`idp.type` discriminator. Absence or inconsistency is `BLOCKED`, never repaired with email matching.
- Emergency close-item completion depends on Workflow safety-lock ownership. Before Workflow is implemented, Access can commit only its typed durable event; `AC-040` remains incomplete.
- Atomic confirmation requires a shared PostgreSQL transaction/UoW coordinated by the destination parent. Separate Access and domain commits are forbidden.
- Primary risks are application-policy/RLS drift, pooled GUC leakage, provider ambiguity, canonicalization drift, session-token theft and active-account races. Each has a required integration or property-test seam above.
