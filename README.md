# ThesisTrace

ThesisTrace is a private, evidence-led investment research workspace for Taiwan-listed securities. SPEC-0001 is the canonical product contract; Wave 0 establishes the governed architecture and a runnable repository/platform skeleton.

## Repository layout

- `architecture/`: schema 2.2.0 manifest, decisions, algorithm records, and generated views.
- `backend/`: FastAPI application plus collector and later isolated worker roles.
- `frontend/`: responsive React/TypeScript application.
- `infra/`: non-secret deployment configuration and examples.
- `scripts/`: offline repository validation helpers.
- `specs/`: canonical specifications.

## Local Compose skeleton

`compose.yaml` defines `api`, `collector`, `web`, and `postgres`. It deliberately publishes no host ports: a future Caddy/Cloudflare Tunnel deployment is the only supported remote ingress. Runtime credentials are external Compose secrets and must never be committed.

1. Create the external secrets through the deployment environment:

   - `thesis_trace_postgres_password`
   - `thesis_trace_database_url`
   - `thesis_trace_access_issuer`
   - `thesis_trace_access_audience`
   - `thesis_trace_owner_identities`
   - `thesis_trace_recovery_identity` containing the exact approved
     `provider_id:provider_type:provider_subject` triple

2. Build the backend and frontend images. The API and collector refuse to become
   healthy until their required identity and PostgreSQL adapters are usable; no
   fixed Wave 0 Owner identity is enabled by Compose.
3. Validate configuration without starting services:

   ```bash
   ./scripts/validate-repository.sh
   docker compose config --quiet
   ```

The Compose project uses placeholder image/build contracts during Wave 0. It does not contain production credentials, publish the database, or provide a bypass around Cloudflare Access. On the standalone production VM, combine `compose.yaml` with `infra/compose.production.yaml` and set `THESIS_TRACE_SECRETS_DIR` to the approved root-owned secret directory; do not enable Swarm or use a shared secret `.env`. Before Compose can start, run `scripts/validate_production_secret_files.py` as root against that directory and its separate lifecycle inventory; it never reads or prints secret values.

## Governance checks

Run the development gate whenever product source or runtime wiring changes:

```bash
python tools/architecture/architecture_cli.py gate \
  --phase development \
  --manifest architecture/manifest.yaml \
  --adoption architecture/adoption.yaml \
  --baseline architecture/baseline.yaml \
  --format text
```

CI starts an isolated PostgreSQL service and runs backend tests (including tagged
integration tests), verifies the OpenAPI-generated frontend client is current,
runs the schema 2.2.0 development architecture gate, and tests/builds the frontend.
The CI database credential is ephemeral test data; deployment credentials remain
external Compose secrets and are required at configuration/startup time.

Regenerate and verify the frontend API client with:

```bash
./scripts/check-generated-client.sh
```
