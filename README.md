# ThesisTrace

ThesisTrace is a private, evidence-led investment research workspace for Taiwan-listed securities. SPEC-0001 is the canonical product contract; Wave 0 establishes the governed architecture and a runnable repository/platform skeleton.

## Repository layout

- `architecture/`: schema 2.2.0 manifest, decisions, algorithm records, and generated views.
- `backend/`: FastAPI application plus isolated collector and AI-worker roles.
- `frontend/`: responsive React/TypeScript application.
- `infra/`: non-secret deployment configuration and examples.
- `scripts/`: offline repository validation helpers.
- `specs/`: canonical specifications.

## Local Compose skeleton

`compose.yaml` defines `api`, `collector`, `ai-worker`, `web`, PostgreSQL, migration, and the Caddy/Cloudflare ingress path. It deliberately publishes no host ports. Runtime credentials are external Compose secrets and must never be committed. Only `ai-worker` joins the dedicated `ai-egress` network; API and collector cannot call the model provider.

1. Create the external secrets through the deployment environment:

   - `thesis_trace_postgres_password`
   - `thesis_trace_api_database_url`
   - `thesis_trace_collector_database_url`
   - `thesis_trace_migration_database_url`
   - `thesis_trace_ai_worker_database_url`
   - `thesis_trace_api_database_password`
   - `thesis_trace_collector_database_password`
   - `thesis_trace_migration_database_password`
   - `thesis_trace_ai_worker_database_password`
   - `thesis_trace_openai_api_key`
   - `thesis_trace_access_issuer`
   - `thesis_trace_access_audience`
   - `thesis_trace_owner_identities`
   - `thesis_trace_recovery_identity` containing the exact approved
     `provider_id:provider_type:provider_subject` triple

   Configure `THESIS_TRACE_OPENAI_MODEL` and `THESIS_TRACE_OPENAI_CRITIC_MODEL`
   to the exact approved model identifiers. API binds those values plus the image
   build ID, prompt versions, schemas, and policy version into every durable
   assessment job; the AI worker rejects a model-version mismatch.

2. Build the backend and frontend images. The API, collector, and AI worker refuse to become
   healthy until their required identity and PostgreSQL adapters are usable; no
   fixed Wave 0 Owner identity is enabled by Compose.
3. Validate configuration without starting services:

   ```bash
   ./scripts/validate-repository.sh
   docker compose config --quiet
   ```

The Compose project does not contain production credentials, publish the database, or provide a bypass around Cloudflare Access. The anomaly worker currently records `soft` or `would_be_hard` shadow results only; formal Hard notification stays disabled pending the 100-case qualification, 30 continuous production shadow days, and explicit Owner activation. On the standalone production VM, combine `compose.yaml` with `infra/compose.production.yaml` and set `THESIS_TRACE_SECRETS_DIR` to the approved root-owned secret directory; do not enable Swarm or use a shared secret `.env`. Before Compose can start, run `scripts/validate_production_secret_files.py` as root against that directory and its separate lifecycle inventory; it never reads or prints secret values.

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
