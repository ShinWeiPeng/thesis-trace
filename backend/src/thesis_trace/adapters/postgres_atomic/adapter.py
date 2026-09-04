from __future__ import annotations

from datetime import datetime
from typing import Any

from thesis_trace.adapters.postgres_access.adapter import PostgresAccessAdapter
from thesis_trace.adapters.postgres_portfolio.adapter import PostgresPortfolioStore
from thesis_trace.adapters.postgres_thesis.adapter import PostgresThesisStore
from thesis_trace.application.contracts import (
    AuthenticatedActor,
    ConfirmCompanyActionCommand,
    ConfirmTradeCommand,
    ConfirmTradeCorrectionCommand,
    PortfolioActorContext,
    PortfolioRecord,
    TradePreview,
    PublishValuationCommand,
    Role,
    ThesisActorContext,
    ThesisRecord,
    TransitionThesisCommand,
)
from thesis_trace.platform.postgres import PostgresEvidenceStore


class PostgresConfirmedThesisTransition:
    """Own the transaction joining confirmation consumption and a Thesis transition."""

    def __init__(self, access: PostgresAccessAdapter, store: PostgresThesisStore, service: Any) -> None:
        self._access = access
        self._store = store
        self._service = service

    def execute(
        self, *, actor: AuthenticatedActor, thesis_id: str, expected_version: int,
        target: Any, reason: str, idempotency_key: str,
        challenge_token: str, now: datetime,
    ) -> ThesisRecord:
        payload = {"thesis_id": thesis_id, "target_status": target.value}

        def mutate(connection, challenge_id: str, replay: bool) -> ThesisRecord:
            service = self._service.with_store(self._store.for_transaction(connection))
            thesis_actor = ThesisActorContext(actor.actor_id, actor.role in {Role.OWNER, Role.LEARNER})
            if replay:
                return service.get(thesis_actor, thesis_id)
            return service.transition(TransitionThesisCommand(
                thesis_actor, thesis_id, expected_version, target, reason,
                idempotency_key, challenge_id,
            ), now=now)

        return self._access.execute_confirmed_mutation(
            token=challenge_token, actor_id=actor.actor_id, actor_role=actor.role,
            action_type="transition_personal_thesis", target_id=thesis_id,
            target_version=expected_version, payload=payload, reason=reason,
            now=now, mutation=mutate,
        )


class PostgresConfirmedPortfolioTrade:
    """Own atomic confirmation for trades, corrections, and company actions."""

    def __init__(self, access: PostgresAccessAdapter, store: PostgresPortfolioStore, service: Any) -> None:
        self._access = access
        self._store = store
        self._service = service

    def _service_for(self, connection) -> Any:
        return self._service.with_store(self._store.for_transaction(connection))

    @staticmethod
    def _actor(actor: AuthenticatedActor) -> PortfolioActorContext:
        return PortfolioActorContext(actor.actor_id, actor.role is Role.OWNER)

    def execute(
        self, *, actor: AuthenticatedActor, preview: TradePreview, reason: str,
        idempotency_key: str, challenge_token: str, now: datetime,
    ) -> PortfolioRecord:
        payload = {"fingerprint": preview.fingerprint, "preview_digest": preview.preview_digest}

        def mutate(connection, challenge_id: str, replay: bool) -> PortfolioRecord:
            service = self._service_for(connection)
            portfolio_actor = self._actor(actor)
            if replay:
                return service.get(portfolio_actor)
            return service.confirm_trade(ConfirmTradeCommand(
                portfolio_actor, preview, challenge_id, reason, idempotency_key,
            ), now=now)

        return self._access.execute_confirmed_mutation(
            token=challenge_token, actor_id=actor.actor_id, actor_role=actor.role,
            action_type="confirm_portfolio_trade", target_id=actor.actor_id,
            target_version=preview.expected_portfolio_version, payload=payload,
            reason=reason, now=now, mutation=mutate,
        )

    def execute_correction(
        self, *, actor: AuthenticatedActor, preview: Any, reason: str,
        idempotency_key: str, challenge_token: str, now: datetime,
    ) -> PortfolioRecord:
        payload = {"original_trade_id": preview.original_trade_id, "preview_digest": preview.preview_digest}

        def mutate(connection, challenge_id: str, replay: bool) -> PortfolioRecord:
            service = self._service_for(connection)
            portfolio_actor = self._actor(actor)
            if replay:
                return service.get(portfolio_actor)
            return service.confirm_correction(ConfirmTradeCorrectionCommand(
                portfolio_actor, preview, challenge_id, reason, idempotency_key,
            ), now=now)

        return self._access.execute_confirmed_mutation(
            token=challenge_token, actor_id=actor.actor_id, actor_role=actor.role,
            action_type="correct_portfolio_trade", target_id=actor.actor_id,
            target_version=preview.expected_portfolio_version, payload=payload,
            reason=reason, now=now, mutation=mutate,
        )

    def execute_company_action(
        self, *, actor: AuthenticatedActor, preview: Any, reason: str,
        idempotency_key: str, challenge_token: str, now: datetime,
    ) -> PortfolioRecord:
        payload = {"preview_digest": preview.preview_digest, "security_id": preview.security_id}

        def mutate(connection, challenge_id: str, replay: bool) -> PortfolioRecord:
            service = self._service_for(connection)
            portfolio_actor = self._actor(actor)
            if replay:
                return service.get(portfolio_actor)
            return service.confirm_company_action(ConfirmCompanyActionCommand(
                portfolio_actor, preview, challenge_id, reason, idempotency_key,
            ), now=now)

        return self._access.execute_confirmed_mutation(
            token=challenge_token, actor_id=actor.actor_id, actor_role=actor.role,
            action_type="confirm_portfolio_company_action", target_id=actor.actor_id,
            target_version=preview.expected_portfolio_version, payload=payload,
            reason=reason, now=now, mutation=mutate,
        )


class PostgresConfirmedValuationPublication:
    """Own atomic confirmation and cross-owner validation for valuation publication."""

    def __init__(
        self, access: PostgresAccessAdapter, store: PostgresThesisStore, service: Any,
        research: PostgresEvidenceStore, portfolio: PostgresPortfolioStore,
    ) -> None:
        self._access = access
        self._store = store
        self._service = service
        self._research = research
        self._portfolio = portfolio

    def execute(
        self, *, actor: AuthenticatedActor, thesis_id: str, expected_thesis_version: int,
        expected_draft_version: int, reason: str, idempotency_key: str,
        challenge_token: str, binding_payload: dict[str, object], now: datetime,
    ) -> ThesisRecord:
        payload = binding_payload

        def mutate(connection, challenge_id: str, replay: bool) -> ThesisRecord:
            research = self._research.for_transaction(connection)
            portfolio = self._portfolio.for_transaction(connection)
            service = self._service.with_store(self._store.for_transaction(connection))
            thesis_actor = ThesisActorContext(actor.actor_id, actor.role is Role.OWNER)
            if replay:
                return service.get(thesis_actor, thesis_id)
            current = service.get(thesis_actor, thesis_id)
            draft = current.valuation_draft
            if (
                current.version != expected_thesis_version or draft is None
                or draft.version != expected_draft_version
                or payload.get("thesis_id") != thesis_id
                or payload.get("draft_version") != expected_draft_version
            ):
                raise ValueError("valuation_draft_conflict")
            current_portfolio = portfolio.get_for_validation(actor.actor_id)
            expected_cost_version = int(payload.get("cost_profile_version", -1))
            if draft.cost_profile_version != expected_cost_version:
                raise ValueError("cost_profile_version_conflict")
            if draft.cost_profile_version != 0 and (
                current_portfolio is None or current_portfolio.cost_profile is None
                or current_portfolio.cost_profile.version != draft.cost_profile_version
            ):
                raise ValueError("cost_profile_version_conflict")
            self._validate_sources(research, draft, payload)
            return service.publish_valuation(PublishValuationCommand(
                thesis_actor, thesis_id, expected_thesis_version, expected_draft_version,
                challenge_id, reason, idempotency_key,
            ), now=now)

        return self._access.execute_confirmed_mutation(
            token=challenge_token, actor_id=actor.actor_id, actor_role=actor.role,
            action_type="publish_thesis_valuation", target_id=thesis_id,
            target_version=expected_thesis_version, payload=payload, reason=reason,
            now=now, mutation=mutate,
        )

    @staticmethod
    def _validate_sources(research: PostgresEvidenceStore, draft, payload: dict[str, object]) -> None:
        draft_refs = {
            (reference.record_id, str(reference.fact_id))
            for reference in (
                ([draft.forecast_source] if draft.forecast_source is not None else [])
                + [sample.source for benchmark in (draft.company_history, draft.peer_group)
                   if benchmark is not None for sample in benchmark.valid_samples]
            )
        }
        bound_sources = payload.get("research_sources")
        if not isinstance(bound_sources, list):
            raise ValueError("valuation_source_invalid")
        if {(str(item.get("record_id")), str(item.get("fact_id"))) for item in bound_sources} != draft_refs:
            raise ValueError("valuation_source_invalid")
        for item in bound_sources:
            evidence = research.get_record_for_validation(str(item["record_id"]))
            snapshot_id = research.get_source_snapshot_id_for_validation(str(item["record_id"]))
            fact = research.get_valuation_fact_for_validation(str(item["record_id"]), str(item["fact_id"]))
            if (
                evidence is None or evidence.version != int(item["version"])
                or evidence.company_id != str(item["company_id"])
                or getattr(evidence.status, "value", evidence.status) != "succeeded"
                or snapshot_id != str(item["source_snapshot_id"]) or fact is None
                or fact.evidence_version != int(item["version"])
                or fact.source_snapshot_id != snapshot_id
                or fact.company_id != str(item["company_id"])
                or fact.policy_version != str(item["fact_policy_version"])
                or (fact.fact_kind == "forecast" and fact.target_date != draft.validity.target_date)
            ):
                raise ValueError("valuation_source_invalid")
