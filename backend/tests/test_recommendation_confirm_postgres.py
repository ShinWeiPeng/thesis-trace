from dataclasses import replace
from datetime import timedelta
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import uuid

import psycopg
import pytest

from thesis_trace.application.contracts import RecommendationDecisionCommand
from thesis_trace.adapters.postgres_access.adapter import PostgresAccessAdapter
from thesis_trace.platform.database import PostgresUnavailable
from thesis_trace.modules.portfolio.contracts import (
    PortfolioActorContext,
    SaveInvestableCashCommand,
)
from thesis_trace.modules.portfolio.service import PortfolioService
from test_recommendation_atomic_postgres import context, prepare, pytestmark
from test_portfolio_domain import NOW


def published(context):
    transaction, publication, store, portfolio, workflow, inputs = prepare(context)
    transaction.publish(publication)
    command = RecommendationDecisionCommand(
        publication.actor_id,
        1,
        publication.input_id,
        1,
        0,
        "accepted",
        "Reviewed exact sources and risk",
        None,
        str(uuid.uuid4()),
    )
    return transaction, command, store, portfolio, workflow, inputs


def consumed(context):
    with psycopg.connect(context[0]) as connection:
        return connection.execute(
            "SELECT count(*) FROM access.confirmation_challenges WHERE actor_user_id=%s AND consumed_at IS NOT NULL",
            (context[1].user_id,),
        ).fetchone()[0]


def test_confirm_commits_challenge_decision_workflow_once_and_exact_replay(context):
    transaction, command, store, portfolio, workflow, _ = published(context)
    before = portfolio.get(command.actor_id)
    preview = transaction.preview_decision(command)
    assert (
        preview.view.decision_sequence == 0 and preview.view.input_validity == "valid"
    )
    assert preview.expires_at == NOW + timedelta(minutes=5)
    assert store.decision_history(command.actor_id, command.record_id, 1) == ()
    confirmed = replace(command, challenge_token=preview.challenge_token)
    view = transaction.decide(confirmed)
    assert (view.decision_status, view.decision_sequence, view.allowed_actions) == (
        "accepted",
        1,
        (),
    )
    assert consumed(context) == 1
    item = workflow.get_by_source(
        command.actor_id, "recommendation", command.record_id, 1
    )
    assert item.status.value == "completed"
    assert portfolio.get(command.actor_id) == before
    replay = transaction.decide(confirmed)
    assert (
        replay.decision_status == "accepted"
        and replay.input_validity == "not_revalidated"
    )
    assert replay.allowed_actions == () and consumed(context) == 1
    assert len(store.decision_history(command.actor_id, command.record_id, 1)) == 1
    saved = store.decision_history(command.actor_id, command.record_id, 1)[0]
    assert saved.input_checks and saved.confirmation_id
    with pytest.raises(ValueError, match="idempotency_conflict"):
        transaction.decide(replace(confirmed, reason="Changed after confirmation"))


def test_changed_input_expires_without_consuming_the_acceptance_challenge(context):
    transaction, command, store, portfolio, workflow, _ = published(context)
    preview = transaction.preview_decision(command)
    current = portfolio.get(command.actor_id)
    PortfolioService(portfolio).save_investable_cash(
        SaveInvestableCashCommand(
            PortfolioActorContext(command.actor_id, True),
            current.version,
            current.cash - 1,
            NOW,
            "Cash changed after preview",
            str(uuid.uuid4()),
        ),
        now=NOW,
    )
    view = transaction.decide(replace(command, challenge_token=preview.challenge_token))
    assert view.decision_status == "expired" and view.input_validity == "invalid"
    assert consumed(context) == 0
    saved = store.decision_history(command.actor_id, command.record_id, 1)[0]
    assert saved.input_checks and saved.confirmation_id is None
    assert (
        workflow.get_by_source(
            command.actor_id, "recommendation", command.record_id, 1
        ).status.value
        == "completed"
    )
    assert len(store.decision_history(command.actor_id, command.record_id, 1)) == 1


def test_challenge_timeout_does_not_expire_valid_recommendation(context):
    transaction, command, store, _, _, _ = published(context)
    preview = transaction.preview_decision(command)
    transaction._clock = lambda: NOW + timedelta(minutes=5)
    with pytest.raises(PermissionError, match="challenge_invalid"):
        transaction.decide(replace(command, challenge_token=preview.challenge_token))
    assert consumed(context) == 0
    assert store.decision_history(command.actor_id, command.record_id, 1) == ()
    fresh = transaction.preview_decision(command)
    assert (
        fresh.challenge_token != preview.challenge_token
        and fresh.view.input_validity == "valid"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"reason": "Different reason"},
        {"target_status": "rejected"},
        {"challenge_token": "forged"},
    ],
)
def test_tampered_confirm_rolls_back_without_any_decision(context, change):
    transaction, command, store, _, _, _ = published(context)
    preview = transaction.preview_decision(command)
    confirmed = replace(command, challenge_token=preview.challenge_token)
    with pytest.raises(PermissionError, match="challenge_invalid"):
        transaction.decide(replace(confirmed, **change))
    assert (
        consumed(context) == 0
        and store.decision_history(command.actor_id, command.record_id, 1) == ()
    )


def test_deferral_needs_no_challenge_and_can_be_followed_by_rejection(context):
    transaction, command, store, _, workflow, _ = published(context)
    deferred = replace(
        command, target_status="deferred", defer_until=NOW + timedelta(days=1)
    )
    view = transaction.decide(deferred)
    assert view.decision_status == "deferred" and view.decision_sequence == 1
    assert (
        workflow.get_by_source(
            command.actor_id, "recommendation", command.record_id, 1
        ).status.value
        == "deferred"
    )
    reject = replace(
        command,
        expected_sequence=1,
        target_status="rejected",
        idempotency_key=str(uuid.uuid4()),
    )
    preview = transaction.preview_decision(reject)
    transaction.decide(replace(reject, challenge_token=preview.challenge_token))
    assert [
        d.status for d in store.decision_history(command.actor_id, command.record_id, 1)
    ] == ["deferred", "rejected"]


def test_concurrent_accept_reject_has_one_winning_decision_and_challenge(context):
    transaction, command, store, _, _, _ = published(context)
    reject = replace(
        command, target_status="rejected", idempotency_key=str(uuid.uuid4())
    )
    accepted = replace(
        command, challenge_token=transaction.preview_decision(command).challenge_token
    )
    rejected = replace(
        reject, challenge_token=transaction.preview_decision(reject).challenge_token
    )

    def execute(value):
        try:
            return transaction.decide(value).decision_status
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(execute, [accepted, rejected]))
    assert outcomes.count("version_conflict") == 1
    assert len(store.decision_history(command.actor_id, command.record_id, 1)) == 1
    assert consumed(context) == 1


def test_workflow_sql_failure_rolls_back_challenge_decision_receipt_and_allows_retry(
    context,
):
    transaction, command, store, _, workflow, _ = published(context)
    confirmed = replace(
        command, challenge_token=transaction.preview_decision(command).challenge_token
    )

    class FailingAccess(PostgresAccessAdapter):
        @contextmanager
        def recommendation_transaction(self, actor_id):
            with super().recommendation_transaction(actor_id) as binding:
                connection = binding[0]
                connection.exec_driver_sql(
                    "CREATE FUNCTION pg_temp.reject_decision_workflow() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test workflow failure'; END $$"
                )
                connection.exec_driver_sql(
                    "CREATE TRIGGER reject_decision_workflow BEFORE UPDATE ON workflow.action_items FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_decision_workflow()"
                )
                yield binding

    original = transaction._access
    transaction._access = FailingAccess(lambda: context[0])
    with pytest.raises(PostgresUnavailable):
        transaction.decide(confirmed)
    assert (
        consumed(context) == 0
        and store.decision_history(command.actor_id, command.record_id, 1) == ()
    )
    assert (
        workflow.get_by_source(
            command.actor_id, "recommendation", command.record_id, 1
        ).status.value
        == "pending"
    )
    transaction._access = original
    assert transaction.decide(confirmed).decision_status == "accepted"


def test_input_expiry_during_commit_replaces_provisional_acceptance_without_consuming_token(
    context,
):
    transaction, command, store, _, workflow, inputs = published(context)
    confirmed = replace(
        command, challenge_token=transaction.preview_decision(command).challenge_token
    )
    expiry = min(
        bound.valid_until for bound in inputs.bindings if bound.valid_until is not None
    )
    ticks = iter([NOW, NOW, expiry])
    transaction._clock = lambda: next(ticks, expiry)
    result = transaction.decide(confirmed)
    assert result.decision_status == "expired" and result.input_validity == "invalid"
    assert consumed(context) == 0
    assert [
        d.status for d in store.decision_history(command.actor_id, command.record_id, 1)
    ] == ["expired"]
    assert (
        workflow.get_by_source(
            command.actor_id, "recommendation", command.record_id, 1
        ).status.value
        == "completed"
    )


def test_challenge_expiry_during_commit_rolls_back_all_participants(context):
    transaction, command, store, _, workflow, _ = published(context)
    confirmed = replace(
        command, challenge_token=transaction.preview_decision(command).challenge_token
    )
    ticks = iter([NOW, NOW, NOW + timedelta(minutes=5)])
    transaction._clock = lambda: next(ticks, NOW + timedelta(minutes=5))
    with pytest.raises(PermissionError, match="challenge_invalid"):
        transaction.decide(confirmed)
    assert (
        consumed(context) == 0
        and store.decision_history(command.actor_id, command.record_id, 1) == ()
    )
    assert (
        workflow.get_by_source(
            command.actor_id, "recommendation", command.record_id, 1
        ).status.value
        == "pending"
    )
