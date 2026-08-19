from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import uuid

from thesis_trace.api import EvidenceApi, OwnerSessionResponse, create_fastapi_app
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.platform.postgres import PostgresEvidenceStore, bootstrap_schema


database_url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
provider = lambda: database_url
bootstrap_schema(provider)
store = PostgresEvidenceStore(provider)
store.delete_all_for_test()


async def fixture_owner() -> AuthenticatedActor:
    return AuthenticatedActor("acceptance-owner", Role.OWNER, 1)


app = create_fastapi_app(
    EvidenceApi(flow=EvidenceIntakeFlow(store=store, id_generator=lambda: str(uuid.uuid4()))),
    fixture_owner,
)


@app.get("/api/session", response_model=OwnerSessionResponse)
async def fixture_session() -> OwnerSessionResponse:
    return OwnerSessionResponse(
        kind="owner",
        user_id="acceptance-owner",
        capabilities=["research:read", "research:write"],
        session_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        is_recovery_session=False,
        display_name="Acceptance Owner",
    )


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/acceptance/evidence/{evidence_id}")
async def acceptance_evidence(evidence_id: str) -> dict[str, object]:
    return {
        "audit_events": store.count_audit_events(evidence_id),
        "collection_jobs": store.count_collection_jobs(evidence_id),
        "provenance": store.get_source_provenance(evidence_id),
    }
