from dataclasses import replace
from datetime import timedelta

import psycopg

from test_recommendation_atomic_postgres import context, pytestmark
from test_recommendation_confirm_postgres import published, consumed
from test_portfolio_domain import NOW


def test_valid_scan_does_not_create_history_or_extend_validity(context):
    transaction, command, store, _, _, _ = published(context)
    assert (
        transaction.reconcile_expiry(
            command.actor_id, command.record_id, 1, 0
        ).decision_status
        is None
    )
    assert store.decision_history(command.actor_id, command.record_id, 1) == ()
    assert consumed(context) == 0


def test_background_expiry_closes_deferred_task_once_without_challenge(context):
    transaction, command, store, _, workflow, inputs = published(context)
    transaction.decide(
        replace(command, target_status="deferred", defer_until=NOW + timedelta(days=1))
    )
    expiry = min(
        item.valid_until for item in inputs.bindings if item.valid_until is not None
    )
    transaction._clock = lambda: expiry
    result = transaction.reconcile_expiry(command.actor_id, command.record_id, 1, 1)
    assert result.decision_status == "expired" and result.decision_sequence == 2
    replay = transaction.reconcile_expiry(command.actor_id, command.record_id, 1, 1)
    assert replay.decision_status == "expired"
    assert [
        d.status for d in store.decision_history(command.actor_id, command.record_id, 1)
    ] == ["deferred", "expired"]
    assert (
        workflow.get_by_source(
            command.actor_id, "recommendation", command.record_id, 1
        ).status.value
        == "completed"
    )
    assert consumed(context) == 0
    with psycopg.connect(context[0]) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM recommendation.expiry_candidates WHERE owner_user_id=%s AND recommendation_id=%s",
                (command.actor_id, command.record_id),
            ).fetchone()[0]
            == 0
        )


def test_accepted_history_is_never_expired(context):
    transaction, command, store, _, _, inputs = published(context)
    preview = transaction.preview_decision(command)
    transaction.decide(replace(command, challenge_token=preview.challenge_token))
    expiry = min(
        item.valid_until for item in inputs.bindings if item.valid_until is not None
    )
    transaction._clock = lambda: expiry
    result = transaction.reconcile_expiry(command.actor_id, command.record_id, 1, 1)
    assert result.decision_status == "accepted"
    assert [
        d.status for d in store.decision_history(command.actor_id, command.record_id, 1)
    ] == ["accepted"]


def test_selector_visits_every_candidate_once_per_cycle_and_survives_store_restart(
    context,
):
    _, command, store, _, _, _ = published(context)
    with psycopg.connect(context[0]) as connection:
        count = connection.execute(
            "SELECT count(*) FROM recommendation.expiry_candidates"
        ).fetchone()[0]
    seen = [store.next_expiry_candidate() for _ in range(count)]
    assert len(set(seen)) == count
    assert (command.actor_id, command.record_id, 1, 0) in seen
    restarted = type(store)(
        lambda: context[0], security_context_provider=lambda: context[1]
    )
    assert restarted.next_expiry_candidate() == seen[0]
