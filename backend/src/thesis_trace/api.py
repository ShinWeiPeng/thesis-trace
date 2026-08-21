from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from starlette.requests import Request
from starlette.responses import Response

from thesis_trace.application.contracts import CreateCompanyCommand, ListCompaniesQuery, SubmitEvidenceRequest
from thesis_trace.application.flows.evidence_intake import EvidenceIntakeFlow
from thesis_trace.application.flows.evidence_stage import (
    ConfirmEvidenceStageRequest,
    EvidenceStageFlow,
    EvidenceStageResult,
    QueryEvidenceStageRequest,
)
from thesis_trace.modules.access.contracts import AuthenticatedActor
from thesis_trace.modules.access.contracts import Role
from thesis_trace.modules.access.identity_registry.contracts import ProviderIdentity
from thesis_trace.modules.access.orchestration import AccountActionService
from thesis_trace.modules.access.session_management.service import SessionService, _CAPABILITIES
from thesis_trace.modules.research.evidence_intake.contracts import EvidenceStatus


class CompanyCreateBody(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=200)


class CompanyResponse(BaseModel):
    company_id: str
    ticker: str
    name: str
    version: int


class EvidenceSubmissionBody(BaseModel):
    company_id: str
    company_version: int = Field(ge=1)
    url: HttpUrl
    idempotency_key: str = Field(min_length=1, max_length=200)


class EvidenceResponse(BaseModel):
    evidence_id: str
    version: int
    status: EvidenceStatus
    source_snapshot_id: str | None = None


class DimensionFactsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_confirmation: Literal["unverified", "official"]
    product_established: bool
    commercialization_established: bool
    identifiable_revenue: bool
    identifiable_profit_or_cash_flow: bool
    consecutive_financial_quarters: int = Field(ge=0, le=100)


class EvidenceStageConfirmationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_snapshot_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    facts: DimensionFactsBody
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class GateResultResponse(BaseModel):
    gate: str
    passed: bool
    code: str


class EvidenceStageResponse(BaseModel):
    evidence_id: str
    version: int
    source_snapshot_id: str
    actor_id: str
    confirmed_at: str
    reason: str
    facts: DimensionFactsBody
    stage: str
    gate_trace: list[GateResultResponse]
    policy_version: str


class OwnerSessionResponse(BaseModel):
    kind: Literal["owner"]
    user_id: str
    capabilities: list[str]
    session_expires_at: datetime
    is_recovery_session: bool
    display_name: str
    recovery_task_url: str | None = None


class LearnerSessionResponse(BaseModel):
    kind: Literal["learner"]
    user_id: str
    capabilities: list[str]
    session_expires_at: datetime
    is_recovery_session: bool
    display_name: str


class AdminSessionResponse(BaseModel):
    kind: Literal["admin"]
    user_id: str
    capabilities: list[str]
    session_expires_at: datetime
    is_recovery_session: bool
    display_name: str


SessionResponse = Annotated[
    Union[OwnerSessionResponse, LearnerSessionResponse, AdminSessionResponse],
    Field(discriminator="kind"),
]


class AccountCreateBody(BaseModel):
    role: Role
    provider_id: str = Field(min_length=1)
    provider_type: str = Field(min_length=1)
    provider_subject: str = Field(min_length=1)
    email_fact: str = Field(min_length=3)
    challenge_token: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class AccountResponse(BaseModel):
    user_id: str
    role: Role
    status: Literal["active", "disabled"]
    masked_identity: str
    version: int


class ConfirmationChallengeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    target_version: int = Field(ge=1)
    payload: dict[str, Any]


class ImpactSummaryResponse(BaseModel):
    subject: str
    action_label: str
    before: dict[str, str]
    after: dict[str, str]
    consequences: list[str]
    confirmation_verb: str


class ConfirmationChallengeResponse(BaseModel):
    challenge_token: str
    expires_at: datetime
    target_version: int
    impact_summary: ImpactSummaryResponse


class ConfirmedActionBody(BaseModel):
    challenge_token: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    target_version: int = Field(ge=1)
    payload: dict[str, Any]
    reason: str = Field(min_length=1)


class ConfirmedActionResponse(BaseModel):
    challenge_id: str
    accepted: bool


class ProblemResponse(BaseModel):
    code: str


class AccessProblem(Exception):
    def __init__(self, code: str = "resource_unavailable") -> None:
        self.code = code


class AccessApiPort(Protocol):
    def session_profile(self, actor: AuthenticatedActor, token: str) -> dict[str, Any]: ...
    def logout(self, actor: AuthenticatedActor, token: str) -> None: ...
    def list_accounts(self, actor: AuthenticatedActor) -> list[dict[str, Any]]: ...
    def get_account(self, actor: AuthenticatedActor, user_id: str) -> dict[str, Any]: ...
    def create_account(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]: ...
    def preview_confirmation(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]: ...
    def confirm_action(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]: ...


class AccessApi:
    """HTTP-facing orchestration; it exposes no persistence handles or raw tokens."""

    def __init__(self, repository: Any, sessions: SessionService, account_actions: AccountActionService) -> None:
        self._repository = repository
        self._sessions = sessions
        self._account_actions = account_actions

    @staticmethod
    def profile_for(account: Any, session: Any) -> dict[str, Any]:
        result = {"kind": account.role.value, "user_id": account.user_id,
                  "capabilities": sorted(_CAPABILITIES[account.role]), "session_expires_at": session.expires_at,
                  "is_recovery_session": session.recovery, "display_name": f"{account.role.value.title()} • {account.user_id[-4:]}"}
        return result

    def session_profile(self, actor: AuthenticatedActor, token: str) -> dict[str, Any]:
        account = self._repository.get_account(actor.actor_id)
        if account is None:
            raise LookupError("resource_unavailable")
        session = self._sessions.validate(token, account)
        return self.profile_for(account, session)

    def logout(self, actor: AuthenticatedActor, token: str) -> None:
        account = self._repository.get_account(actor.actor_id)
        if account is None:
            raise LookupError("resource_unavailable")
        self._sessions.revoke(token, account)

    def list_accounts(self, actor: AuthenticatedActor) -> list[dict[str, Any]]:
        return self._account_actions.list_accounts(actor)

    def get_account(self, actor: AuthenticatedActor, user_id: str) -> dict[str, Any]:
        return self._account_actions.get_account(actor, user_id)

    def create_account(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        payload = {key: body[key] for key in ("role", "provider_id", "provider_type", "provider_subject", "email_fact")}
        _confirmed, account = self._account_actions.confirm(
            actor, token=body["challenge_token"], action_type="create_account", target_version=1,
            payload=payload, reason=body["reason"],
        )
        if account is None:
            raise LookupError("resource_unavailable")
        return {"user_id": account.user_id, "role": account.role, "status": account.status,
                "masked_identity": body["provider_type"], "version": account.version}

    def preview_confirmation(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        preview = self._account_actions.preview(actor, action_type=body["action_type"], target_id=body["target_id"],
                                                target_version=body["target_version"], payload=body["payload"])
        return {"challenge_token": preview.challenge_token, "expires_at": preview.expires_at,
                "target_version": preview.target_version, "impact_summary": preview.impact_summary}

    def confirm_action(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        confirmed, _result = self._account_actions.confirm(
            actor, token=body["challenge_token"], action_type=body["action_type"],
            target_version=body["target_version"], payload=body["payload"], reason=body["reason"],
        )
        return {"challenge_id": confirmed.challenge_id, "accepted": confirmed.accepted}


class EvidenceApi:
    """Framework-independent HTTP boundary contract used by the FastAPI adapter."""

    def __init__(self, *, flow: EvidenceIntakeFlow, stage_flow: EvidenceStageFlow | None = None) -> None:
        self._flow = flow
        self._stage_flow = stage_flow

    def create_company(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        try:
            company = self._flow.create_company(CreateCompanyCommand(
                actor=actor, ticker=str(body.get("ticker", "")), name=str(body.get("name", ""))
            ))
        except PermissionError:
            return {"error": "forbidden"}
        return {"company_id": company.company_id, "ticker": company.ticker, "name": company.name, "version": company.version}

    def list_companies(self, actor: AuthenticatedActor) -> list[dict[str, Any]]:
        return [
            {"company_id": item.company_id, "ticker": item.ticker, "name": item.name, "version": item.version}
            for item in self._flow.list_companies(ListCompaniesQuery(actor=actor))
        ]

    def submit_evidence(self, actor: AuthenticatedActor, body: dict[str, Any]) -> dict[str, Any]:
        result = self._flow.submit(
            SubmitEvidenceRequest(
                actor=actor,
                company_id=str(body.get("company_id", "")),
                company_version=int(body.get("company_version", 0)),
                url=str(body.get("url", "")),
                idempotency_key=str(body.get("idempotency_key", "")),
            )
        )
        if result.accepted is None:
            return {"error": result.rejection_code}
        return {
            "evidence_id": result.evidence_id,
            "version": result.version,
            "status": "received",
        }

    def get_evidence(self, actor: AuthenticatedActor, evidence_id: str) -> dict[str, Any]:
        snapshot = self._flow.get_status(actor, evidence_id)
        response = {
            "evidence_id": snapshot.evidence_id,
            "version": snapshot.version,
            "status": snapshot.status.value,
        }
        if snapshot.source_snapshot_id is not None:
            response["source_snapshot_id"] = snapshot.source_snapshot_id
        return response

    @staticmethod
    def _stage_response(record: EvidenceStageResult) -> dict[str, Any]:
        return {
            "evidence_id": record.evidence_id,
            "version": record.version,
            "source_snapshot_id": record.source_snapshot_id,
            "actor_id": record.actor_id,
            "confirmed_at": record.confirmed_at,
            "reason": record.reason,
            "facts": {
                "source_confirmation": record.facts.source_confirmation,
                "product_established": record.facts.product_established,
                "commercialization_established": record.facts.commercialization_established,
                "identifiable_revenue": record.facts.identifiable_revenue,
                "identifiable_profit_or_cash_flow": record.facts.identifiable_profit_or_cash_flow,
                "consecutive_financial_quarters": record.facts.consecutive_financial_quarters,
            },
            "stage": record.stage,
            "gate_trace": [
                {"gate": item.gate, "passed": item.passed, "code": item.code}
                for item in record.gate_trace
            ],
            "policy_version": record.policy_version,
        }

    def confirm_evidence_stage(self, actor: AuthenticatedActor, evidence_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._stage_flow is None:
            raise LookupError("resource_unavailable")
        facts = body["facts"]
        record = self._stage_flow.confirm(actor, ConfirmEvidenceStageRequest(
            evidence_id=evidence_id,
            source_snapshot_id=body["source_snapshot_id"],
            expected_version=body["expected_version"],
            source_confirmation=facts["source_confirmation"],
            product_established=facts["product_established"],
            commercialization_established=facts["commercialization_established"],
            identifiable_revenue=facts["identifiable_revenue"],
            identifiable_profit_or_cash_flow=facts["identifiable_profit_or_cash_flow"],
            consecutive_financial_quarters=facts["consecutive_financial_quarters"],
            reason=body["reason"],
            idempotency_key=body["idempotency_key"],
        ))
        return self._stage_response(record)

    def get_evidence_stage(self, actor: AuthenticatedActor, evidence_id: str) -> dict[str, Any]:
        if self._stage_flow is None:
            raise LookupError("resource_unavailable")
        return self._stage_response(
            self._stage_flow.get_stage(actor, QueryEvidenceStageRequest(evidence_id))
        )


def create_fastapi_app(api: EvidenceApi, actor_provider: Any, access_api: AccessApiPort | None = None) -> Any:
    """Create the delivery adapter; import FastAPI only in installed runtimes."""
    from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response

    app = FastAPI(title="ThesisTrace", version="0.1.0")

    @app.post("/api/companies", status_code=201, response_model=CompanyResponse)
    async def create_company(body: CompanyCreateBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
        try:
            response = api.create_company(actor, body.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if "error" in response:
            raise HTTPException(status_code=403, detail=response["error"])
        return response

    @app.get("/api/companies", response_model=list[CompanyResponse])
    async def list_companies(actor: AuthenticatedActor = Depends(actor_provider)) -> list[dict[str, Any]]:
        try:
            return api.list_companies(actor)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="forbidden") from error

    @app.post("/api/evidence", status_code=202, response_model=EvidenceResponse, response_model_exclude_none=True)
    async def submit(body: EvidenceSubmissionBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
        response = api.submit_evidence(actor, {**body.model_dump(), "url": str(body.url)})
        if "error" in response:
            code = 403 if response["error"] == "forbidden" else 422
            raise HTTPException(status_code=code, detail=response["error"])
        return response

    @app.get("/api/evidence/{evidence_id}", response_model=EvidenceResponse, response_model_exclude_none=True)
    async def status(evidence_id: str, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
        try:
            return api.get_evidence(actor, evidence_id)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="forbidden") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="not_found") from error

    @app.post(
        "/api/evidence/{evidence_id}/stage-confirmations",
        status_code=201,
        response_model=EvidenceStageResponse,
    )
    async def confirm_evidence_stage(
        evidence_id: str,
        body: EvidenceStageConfirmationBody,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.confirm_evidence_stage(actor, evidence_id, body.model_dump())
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="forbidden") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error
        except ValueError as error:
            status_code = 409 if str(error) == "version_conflict" else 422
            raise HTTPException(status_code=status_code, detail=str(error)) from error

    @app.get("/api/evidence/{evidence_id}/stage", response_model=EvidenceStageResponse)
    async def get_evidence_stage(
        evidence_id: str,
        actor: AuthenticatedActor = Depends(actor_provider),
    ) -> dict[str, Any]:
        try:
            return api.get_evidence_stage(actor, evidence_id)
        except (PermissionError, LookupError) as error:
            raise HTTPException(status_code=404, detail="resource_unavailable") from error

    if access_api is not None:
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
        from fastapi.encoders import jsonable_encoder

        @app.exception_handler(AccessProblem)
        async def access_problem_handler(_request: Request, error: AccessProblem) -> JSONResponse:
            return JSONResponse(status_code=404, content={"code": error.code})

        @app.exception_handler(RequestValidationError)
        async def access_validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
            access_prefixes = ("/api/session", "/api/admin/accounts", "/api/confirmation-challenges", "/api/confirmed-actions")
            if request.url.path.startswith(access_prefixes):
                return JSONResponse(status_code=422, content={"code": "invalid_request"})
            return JSONResponse(status_code=422, content={"detail": jsonable_encoder(error.errors())})

        def unavailable(_error: Exception) -> AccessProblem:
            return AccessProblem()

        @app.get("/api/session", response_model=SessionResponse, responses={404: {"model": ProblemResponse}})
        async def get_session(request: Request, actor: AuthenticatedActor = Depends(actor_provider), thesis_trace_session: str = Cookie(default="")) -> dict[str, Any]:
            try:
                bootstrapped = getattr(request.state, "access_session_profile", None)
                if bootstrapped is not None:
                    return bootstrapped
                return access_api.session_profile(actor, thesis_trace_session)
            except (PermissionError, LookupError, ValueError) as error:
                raise unavailable(error) from error

        @app.delete("/api/session", status_code=204, responses={404: {"model": ProblemResponse}})
        async def delete_session(response: Response, actor: AuthenticatedActor = Depends(actor_provider), thesis_trace_session: str = Cookie(default="")) -> None:
            try:
                access_api.logout(actor, thesis_trace_session)
                response.delete_cookie("thesis_trace_session", secure=True, httponly=True, samesite="strict")
            except (PermissionError, LookupError) as error:
                raise unavailable(error) from error

        @app.get("/api/admin/accounts", response_model=list[AccountResponse], responses={404: {"model": ProblemResponse}})
        async def list_accounts(actor: AuthenticatedActor = Depends(actor_provider)) -> list[dict[str, Any]]:
            try:
                return access_api.list_accounts(actor)
            except (PermissionError, LookupError) as error:
                raise unavailable(error) from error

        @app.get("/api/admin/accounts/{user_id}", response_model=AccountResponse, responses={404: {"model": ProblemResponse}})
        async def account_detail(user_id: str, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
            try:
                return access_api.get_account(actor, user_id)
            except (PermissionError, LookupError) as error:
                raise unavailable(error) from error

        @app.post("/api/admin/accounts", status_code=201, response_model=AccountResponse, responses={404: {"model": ProblemResponse}})
        async def create_account(body: AccountCreateBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
            try:
                return access_api.create_account(actor, body.model_dump())
            except (PermissionError, LookupError) as error:
                raise unavailable(error) from error

        @app.post("/api/confirmation-challenges", status_code=201, response_model=ConfirmationChallengeResponse, responses={404: {"model": ProblemResponse}})
        async def preview_confirmation(body: ConfirmationChallengeBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
            try:
                return access_api.preview_confirmation(actor, body.model_dump())
            except (PermissionError, LookupError, ValueError) as error:
                raise unavailable(error) from error

        @app.post("/api/confirmed-actions", response_model=ConfirmedActionResponse, responses={404: {"model": ProblemResponse}})
        async def confirm_action(body: ConfirmedActionBody, actor: AuthenticatedActor = Depends(actor_provider)) -> dict[str, Any]:
            try:
                return access_api.confirm_action(actor, body.model_dump())
            except (PermissionError, LookupError, ValueError) as error:
                raise unavailable(error) from error

    return app
