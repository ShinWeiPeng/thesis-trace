from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import uuid

from thesis_trace.api import EvidenceApi, OwnerSessionResponse, create_fastapi_app
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.application.flows.anomaly_assessment import AnomalyAssessmentFlow
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from thesis_trace.modules.research import ResearchAnomalyFacade
from thesis_trace.modules.research.anomaly_assessment.service import AnomalyAssessmentService
from thesis_trace.platform.postgres import PostgresEvidenceStore, bootstrap_schema


database_url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
provider = lambda: database_url
bootstrap_schema(provider)
store = PostgresEvidenceStore(provider)
store.delete_all_for_test()


async def fixture_owner() -> AuthenticatedActor:
    return AuthenticatedActor("acceptance-owner", Role.OWNER, 1)


app = create_fastapi_app(
    EvidenceApi(
        flow=EvidenceIntakeFlow(store=store, id_generator=lambda: str(uuid.uuid4())),
        anomaly_flow=AnomalyAssessmentFlow(
            research=ResearchAnomalyFacade(
                AnomalyAssessmentService(
                    store=store, clock=lambda: datetime.now(timezone.utc).isoformat()
                )
            )
        ),
    ),
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


@app.get("/acceptance/anomaly/{assessment_id}")
async def acceptance_anomaly(assessment_id: str) -> dict[str, int]:
    return {
        "audit_events": store.count_audit_events(assessment_id),
        "analysis_jobs": store.count_anomaly_jobs(assessment_id),
    }
