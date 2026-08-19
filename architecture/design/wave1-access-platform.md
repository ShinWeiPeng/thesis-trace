# Wave 1 Access Platform Architecture Contract

- Status: **proposed**
- Scope: `REQ-008`, `REQ-012`, `REQ-046`, `REQ-048`; `AC-007`,
  `AC-011`, `AC-040`, `AC-042`
- Assurance: repository checks are design evidence only; live Cloudflare and VM
  claims remain `BLOCKED` until the evidence listed below is collected.
- Non-scope: B2, backup/restore implementation, product or deployment-contract
  implementation, and acceptance of any ADR.

This document is the authoring input for Wave 1. It defines the canonical
security boundary before changes to the architecture manifest, production
source, Compose, or deployment configuration. It does not approve the design
and must not be interpreted as evidence that Cloudflare or the origin VM is
configured correctly.

## Security invariants

1. The sole remote user entrance is one named Cloudflare Tunnel public-hostname
   route covered by one deny-by-default Access self-hosted application for the
   complete hostname and every path.
2. No Access Bypass policy, Quick Tunnel, public path exception, direct origin
   route, VPN entrance, local authentication bypass, or client-supplied identity
   header is authoritative.
3. `cloudflared` initiates outbound connections. The origin exposes no inbound
   Internet or LAN port for Caddy, API, SSH, PostgreSQL, Docker API, or a
   management subnet.
4. Tunnel ingress can reach only the local Caddy HTTPS origin. Caddy can reach
   only the Web and API services. It cannot route to PostgreSQL, Docker, SSH,
   another VM, or a management address.
5. FastAPI independently verifies every protected request's Access JWT
   signature, issuer, application audience, validity interval, provider identity
   binding, and current application authorization. A header or successful edge
   request alone is insufficient.
6. Missing policy, identity facts, provider evidence, verification keys, RLS
   context, or a usable bounded verification cache fails closed.
7. A provider identity is keyed by `(provider_id, provider_type, provider_subject)`. Email is
   an allowlist/display fact and never merges identities across providers.
8. Normal Google access lasts exactly eight hours. Recovery access is disabled
   by default, requires MFA on every login, lasts at most thirty minutes, maps
   to the existing Owner without privilege elevation, and cannot appear as a
   normal login choice.
9. Runtime secrets are root-owned file references mounted only into the process
   that needs them. Secret text is absent from Git, images, Compose environment
   values, database dumps, browser responses, logs, traces, and CI artifacts.
10. Application scope and PostgreSQL RLS both enforce isolation. Runtime roles
    do not own protected tables, do not have `BYPASSRLS`, and cannot disable RLS.

## Boundary design

| Interaction | Producer | Consumer | Parent / mapping owner | Contract | Failure rule |
| --- | --- | --- | --- | --- | --- |
| Browser request to edge | Browser | Cloudflare Access application | Cloudflare edge configuration | Complete-hostname HTTPS request | No matching explicit Allow and MFA requirements means deny. |
| Edge to origin | Named Tunnel | Caddy HTTPS | Deployment composition | One public-hostname ingress followed by terminal reject rule | Any route to a non-Caddy service or unprotected path invalidates the deployment. |
| Access token verification | FastAPI adapter | Access verification capability | Backend composition | JWT plus expected issuer/audience and verification-key cache policy | Invalid, expired, unverifiable, or stale evidence returns a non-disclosing denial. |
| Provider identity enrichment | Verified JWT adapter | Provider get-identity adapter | Access domain parent | `AccessIdentityFactsQuery -> VerifiedProviderIdentityFacts` | The query is allowed only after JWT verification; missing, mismatched, or unavailable required facts deny access. |
| Provider identity mapping | Access domain | Internal user/role authority | Application parent | `(provider_id, provider_type, provider_subject) -> internal_user_id, role, identity_version` | Email equality never creates or merges a mapping. Disabled or stale mappings deny access. |
| Request scope to storage | Authorized application flow | PostgreSQL adapter | Owning domain | Transaction-local internal user, role, capability, and correlation context | Missing or malformed context denies protected reads and writes. Pool reuse must not retain context. |
| Consequential identity/role change | Authorized administrator flow | Access identity state and audit | Application parent | Preview, five-minute single-use challenge, non-blank reason, exact version/payload digest | Any actor, action, version, payload, role, expiry, or reuse mismatch requires a new preview. |
| Recovery first use | Verified recovery identity | Security audit and Workflow | Application parent | Provider facts, recovery reason, time, existing Owner mapping | One transaction appends audit and creates a safety-locked shutdown Action Item. |

No Cloudflare wire object, JWT library object, HTTP response, SQL row, session,
or RLS setting crosses into an L0-L2 public contract. Provider and storage
representations remain adapter-private.

## Canonical Cloudflare Access contract

The future machine-readable contract must express these fields without account
IDs, email plaintext, tokens, tunnel credentials, Terraform state, or provider
response fixtures containing personal data.

### Application envelope

- Type is `self_hosted`; hostname is the single configured ThesisTrace hostname.
- Path coverage is the whole hostname. An empty path, wildcard-equivalent whole
  host, or provider-native whole-application representation is required. A list
  of selected protected paths is invalid.
- Default outcome is deny. Only the two policies below may grant interactive
  user access.
- Actions named or equivalent to `bypass`, `service_auth` for a human session,
  `allow everyone`, `any valid identity`, email-domain Allow, or public access
  are forbidden.
- Email Magic Link is not an allowed identity provider.
- Access application audience and issuer are immutable deployment inputs
  delivered to the API by secret file reference.

### Normal Google policy

- Enabled for normal operation.
- Identity provider is the configured Google provider only.
- Include rules contain individually approved complete email identities; domain
  selectors and generic Google users are forbidden.
- MFA is required.
- Access application/session duration is exactly eight hours. Application-owned
  sessions, if later introduced, bind the verified Access token, internal user,
  provider identity, and an expiry no later than the Access JWT expiry.
- At or beyond eight hours the next request cannot be extended by an application
  cookie and must complete Google identity verification and Access MFA again.

### Owner recovery policy

- Disabled by default and absent from the normal login selector.
- Its only allowed principal is the separately registered Cloudflare account
  provider subject mapped to the same existing Owner internal user.
- Other Cloudflare account members, shared principals, Learner, and Admin are
  forbidden.
- Activation is manual in the Cloudflare management plane; there is no timer,
  health check, application endpoint, or automation that enables it.
- MFA is required on every login and session duration is no more than thirty
  minutes. Recovery cannot add a role or capability.
- Activation requires an operator-supplied recovery reason. First successful
  application entry atomically appends a security audit event and creates a
  safety-locked Action Item requiring policy shutdown.
- Repair completion disables the policy, records confirmation, revokes all
  application recovery sessions, and rejects their reuse.
- Loss of both management access and independently stored MFA recovery material
  remains fail closed. It never authorizes a public origin or Bypass rule.

## Provider get-identity seam

JWT verification establishes cryptographic admission first. Provider
get-identity is a separate demand-owned seam used only for identity facts that
the verified token does not safely or stably establish.

`AccessIdentityFactsQuery` contains the already verified token correlation,
expected audience, and bounded deadline. `VerifiedProviderIdentityFacts`
contains only normalized provider ID, provider subject, authentication time,
MFA assurance fact, token/session expiry, and a correlation value required to
match the verified JWT. Raw provider JSON is adapter-private.

- The adapter must use the provider-supported get-identity endpoint and must not
  accept a client-provided copy of its response.
- Returned audience, subject, provider, expiry, and correlation facts must agree
  with the verified JWT and requested application.
- A response cannot create an internal identity. Mapping must already exist or
  be created through the consequential identity-management flow.
- Cache entries, if allowed by the implementation ADR, are keyed by verified
  token identity, never outlive token expiry, and cannot turn an unverifiable
  token into an authenticated request.
- Key rotation refresh is bounded. Refresh failure with no still-valid verified
  key/cache denies access and emits only a redacted operational event.
- JWKS and get-identity requests reject every redirect before following it,
  enforce the canonical HTTPS tenant origin, bound response size/time, and accept
  only their approved JSON media types. Signing keys from another origin are
  never admitted.
- Provider outage may make remote entry unavailable but cannot corrupt or move
  local application/domain data.

## Tunnel, Caddy, and origin contract

The tunnel must be named and reconstructable. Its credentials are runtime
secrets, not versioned configuration. The public-hostname route targets one
local Caddy HTTPS service with certificate verification enabled and a pinned
deployment-owned trust anchor. The final tunnel ingress rule rejects all other
requests.

The origin topology has four directed network zones:

```text
Cloudflare edge <-outbound-> cloudflared -> Caddy HTTPS -> Web/API
                                                        API -> PostgreSQL
                                                  collector -> PostgreSQL
```

- `cloudflared` alone joins tunnel egress and the internal origin network.
- Caddy alone joins the origin network and `edge-app`; Web joins only `edge-app`.
- API joins `edge-app` and `data`; collector, the one-shot migration job and PostgreSQL join only `data`.
- Web, Caddy and cloudflared cannot route to PostgreSQL; workers and PostgreSQL have no tunnel-egress membership.
- No service uses host networking, privileged mode, Docker socket, device
  passthrough, or a published host port.
- Caddy routes only approved Web/API paths. Admin/debug endpoints and arbitrary
  upstream selection are forbidden. Sensitive responses use no-store policy.
- Readiness proves only local dependencies. It does not claim that Access,
  Tunnel, DNS, firewall, or public reachability is valid.

## Process role and secret-scope matrix

| Process | Required capabilities | Allowed secret file references | Explicitly forbidden secrets |
| --- | --- | --- | --- |
| API | Non-owner `NOBYPASSRLS` API role; Access issuer/audience; identity mapping and recovery-policy facts | API DB URL, Access issuer, audience, identity-fact source, exact recovery identity, enabled observation and policy version | Migration/collector DB credentials, Tunnel credential, origin TLS private key, AI/email credentials, Cloudflare management token |
| Collector | Non-owner `NOBYPASSRLS` research DB/queue role; restricted outbound source fetch | Collector DB URL | Migration/API credentials, Access identities, tunnel credential, origin key, AI/email credentials |
| AI worker | AI queue role and selected provider credential | AI DB URL and only its provider credentials | Access, tunnel, origin, email credentials |
| Email worker | Email queue role and delivery credential | Email DB URL and delivery credential | Access, tunnel, origin, AI credentials |
| PostgreSQL | Database initialization/runtime | PostgreSQL password file | Access, tunnel, origin, worker-provider credentials |
| Caddy | Internal TLS termination and Web/API routing | Origin TLS private key/certificate files | Database, Access identity, tunnel, worker credentials |
| `cloudflared` | Named tunnel connection only | Tunnel credential file | Database, Access allowlist, origin private key, application/provider credentials |
| Migration job | One-shot database/schema owner for versioned forward migrations; never serves traffic | Migration DB URL | API/collector credentials, Access, tunnel, origin and worker-provider credentials |

Files are root-owned, mode-restricted, mounted read-only, and absent from shared
`.env` files. Environment variables contain only `_FILE` references and
non-secret selectors. A process stores providers/references for process lifetime
and resolves secret text only for the bounded operation. Logs, exception chains,
health responses, metrics labels, traces, test reports, and CI artifacts must
redact JWTs, cookies, emails, database URLs, provider responses, and tunnel
credentials. Rotation targets only affected processes and produces an immutable
operator/security audit without copying the secret.

## PostgreSQL RLS integration contract

- Migration/table-owner roles are separate from API and worker runtime roles.
- Only the one-shot migration role applies DDL. API and collector startup use a
  read-only exact migration version/name/checksum probe and fail closed on drift.
- Runtime roles are `NOBYPASSRLS`, cannot own protected tables, cannot alter
  policy, and cannot set arbitrary privileged context.
- Every user-scoped table enables and forces RLS. Policy uses the stable internal
  user ID and explicit capability/role facts, not email or provider claims.
- Authorization establishes transaction-local context after JWT and internal
  mapping verification. Missing, stale, malformed, or unrecognized context
  denies protected access.
- Transaction completion/rollback and connection-pool return clear all context.
- Owner, Learner, and Admin scopes are independently tested; guessed IDs and
  export/query variants do not reveal whether an inaccessible record exists.
- Identity/role state, recovery use, session revocation, consequential changes,
  and confirmation metadata append immutable audit rows. Runtime roles cannot
  update or delete audit history.
- A successful consequential action commits domain mutation, non-blank reason,
  single-use challenge metadata, and audit in one transaction. Idempotent replay
  cannot repeat the mutation.

## Repository and CI gates

| Gate | Automated evidence | Blocking failures |
| --- | --- | --- |
| Access contract schema | Parse canonical desired-state and sanitized provider-plan/export fixtures | Partial hostname/path coverage; Bypass; domain/everyone rule; wrong provider; normal duration other than 8h; recovery enabled by default or over 30m; missing MFA/exact identity. |
| Tunnel ingress contract | Provider CLI validation plus repository semantic checker | Quick/unnamed tunnel; non-Caddy target; HTTP/no certificate verification; absent terminal reject; SSH/DB/Docker/private-network route. |
| Origin topology | Rendered Compose inspection and network graph test | Any `ports`, host/privileged network, Docker socket, invalid network membership, Caddy bypass, secret over-sharing. |
| Secret scope | Rendered service-to-secret matrix, secret scan, canary redaction tests | Direct secret environment value, shared secret set, secret in image/source/log/artifact, non-file runtime injection. |
| JWT/get-identity | Unit/contract tests with controlled clock and versioned provider fixtures | Bad signature/issuer/audience/time, forged header, provider mismatch, absent MFA, outage without valid evidence, key-refresh fail-open, same-email merge. |
| Session/recovery | Controlled clock, API contract, audit, and browser tests | Normal use at/after 8h, recovery at/after 30m, disabled-policy acceptance, privilege elevation, stale session reuse, missing shutdown Action Item/audit. |
| PostgreSQL RLS | Ephemeral real PostgreSQL migrations and integration tests | Runtime table ownership/BYPASSRLS, cross-user read/write, missing-context access, pool context leakage, mutable audit. Mocks or SQLite cannot pass this gate. |
| Consequential confirmation | Domain/API tests, controlled clock, real PostgreSQL transaction/idempotency tests | Blank reason; actor/action/version/payload mismatch; over-5-minute/reused challenge; non-atomic mutation/audit; duplicate execution; confirmation added to low-risk writes. |
| Error disclosure | API/log/trace canaries containing tokens, identity, URLs, and provider payload | Any secret/identity/raw exception disclosure or distinguishable inaccessible-record response. |

CI fixtures prove parsers and application behavior against versioned examples.
They do not prove live provider state. A sanitized live export that is absent,
stale, broader than canonical desired state, or unverifiable must produce
`BLOCKED`, never a warning or inferred pass.

## Live-only evidence and BLOCKED seams

The following cannot be accepted from repository automation:

1. **Cloudflare Access (`AC-007`, `AC-011`, `AC-040`) — BLOCKED:** sanitized
   live application/policy/IdP export; exact Google and recovery principals;
   actual MFA; normal 8-hour boundary; recovery disabled state and 30-minute
   every-login MFA; full-host coverage; no Bypass; DNS/audience agreement;
   signing-key and tunnel-credential rotation; provider/JWKS outage behavior;
   manual activation, first-use audit/Action Item, disable/revocation, and lost
   recovery-material guided drill.
2. **Named Tunnel and origin (`AC-011`) — BLOCKED:** live named-tunnel/DNS
   inventory, outbound-only `cloudflared`, verified Caddy HTTPS origin, Tunnel
   outage/recovery, and Internet plus LAN scans showing no reachable origin,
   SSH, PostgreSQL, Docker API, other VM, or management subnet.
3. **Production VM secret custody — BLOCKED:** Ubuntu host evidence for root
   ownership/modes, container mounts, process inspection, targeted rotation,
   restart behavior, and absence of secret text from runtime logs/artifacts.
4. **Recovery operations (`AC-040`) — BLOCKED:** human-controlled Cloudflare
   management operation and independently stored MFA recovery material cannot
   be simulated as proof by CI.

`AC-042` may obtain strong automated evidence for challenge semantics,
transactionality, idempotency, authorization, and audit through real PostgreSQL;
its final user-facing impact-summary and confirmation-dialog acceptance still
requires the scoped product/browser work and is not claimed by this platform
authoring document.

## Wave 1 authoring exit condition

Before implementation, the manifest must materialize the modules, ports, type
ownership, state ownership, dependency edges, execution units/channels, and
validation profiles implied here. Any unresolved provider identity field,
Cloudflare export representation, RLS context authority, recovery revocation
mechanism, secret owner, or live evidence method remains `BLOCKED`. This
document stays **proposed** until explicit non-AI approval and the required
architecture gate; creating it neither accepts an ADR nor authorizes deployment.
