# Infrastructure configuration

This directory contains non-secret, versionable deployment examples only. Actual credentials belong in root-owned host files or external Compose secrets and are mounted solely into the process that needs them.

Wave 1 adds repository-verifiable platform contracts without configuring any
live Cloudflare account or host firewall:

- `cloudflare/access-contract.yaml` is the canonical deny-by-default Access
  contract; it contains references rather than hostnames, emails, or secrets.
- `cloudflare/tunnel-config.yaml` permits one named tunnel route to the local
  Caddy HTTPS origin and terminates with a 404 rule.
- `caddy/Caddyfile` routes only Web and API traffic.
- `secrets/manifest.yaml` is the exact process-to-secret allowlist.
- `postgres/wave1-rls-contract.sql` is an isolated CI contract and is not a
  production migration authority.
- `cloudflare/live-evidence.yaml` keeps real Access, Tunnel, MFA, rotation,
  outage, and VM network evidence explicitly `BLOCKED`.

Run `python3 scripts/validate_wave1_platform.py` for the local semantic gate.
Passing it does not prove the live Cloudflare or VM state.

## Standalone production Compose

The production VM remains a standalone Docker Engine and does not enable Swarm.
`infra/compose.production.yaml` replaces the base file's external platform-secret
references with process-scoped files below `THESIS_TRACE_SECRETS_DIR`. The directory
must be outside the repository, root-owned, and unreadable to ordinary users. Run
Compose through the approved root operation path so it can read each source file and
mount only the declared secret into `/run/secrets` for its consumer.

Validate the merged model before starting a service:

```bash
sudo python3 scripts/validate_production_secret_files.py \
  --root "$THESIS_TRACE_SECRETS_DIR" \
  --inventory /etc/thesis-trace/secret-inventory.json \
  --ordinary-user "$(id -un)"

sudo --preserve-env=THESIS_TRACE_SECRETS_DIR docker compose \
  -f compose.yaml \
  -f infra/compose.production.yaml \
  config --quiet
```

The secret preflight never reads secret values. It reads only file metadata plus
the separate root-only lifecycle inventory, which must contain timestamps and
audit references but no credential values. It fails when the directory or a
file is missing, symlinked, empty, owned by the wrong UID/GID, has a mode other
than the runtime-specific policy, or contains an undeclared leftover file. The
canonical runtime identities are PostgreSQL `70:70`, backend/cloudflared
`65532:65532`, and root for the origin Caddy process.

Do not replace this with a shared `.env`, direct secret environment values, or
`docker swarm init`.
