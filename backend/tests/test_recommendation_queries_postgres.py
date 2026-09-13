from dataclasses import replace
from datetime import timedelta

import pytest

from thesis_trace.application.contracts import RecommendationDetailView
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
from test_recommendation_atomic_postgres import context, pytestmark
from test_recommendation_confirm_postgres import published
from test_portfolio_domain import NOW


def test_owner_detail_preserves_frozen_claim_sources_risk_and_decision_history(context):
    transaction, command, store, _, _, inputs = published(context)
    flow = transaction._flow.with_runtime(store, transaction)
    actor = AuthenticatedActor(command.actor_id, Role.OWNER, 1)
    detail = flow.detail(actor, command.record_id, 1, now=NOW)
    assert isinstance(detail, RecommendationDetailView)
    assert detail.view.input_validity == "valid" and detail.view.decision_status is None
    assert detail.sources[0].snapshot_id == inputs.sources[0].snapshot_id
    assert detail.claims[0].citations == (inputs.sources[0].snapshot_id,)
    assert detail.risk and detail.final_multiplier != "0"
    assert detail.portfolio_snapshot_id == inputs.portfolio_snapshot_id
    preview = transaction.preview_decision(command)
    transaction.decide(replace(command, challenge_token=preview.challenge_token))
    later = flow.detail(actor, command.record_id, 1, now=NOW)
    assert later.decisions[0].status == "accepted" and later.decisions[0].checks
    assert later.view.allowed_actions == ()


def test_query_reports_stale_validity_without_appending_expiry(context):
    transaction, command, store, _, _, inputs = published(context)
    flow = transaction._flow.with_runtime(store, transaction)
    expiry = min(
        item.valid_until for item in inputs.bindings if item.valid_until is not None
    )
    view = flow.detail(
        AuthenticatedActor(command.actor_id, Role.OWNER, 1),
        command.record_id,
        1,
        now=expiry,
    )
    assert view.view.input_validity == "invalid" and view.view.allowed_actions == ()
    assert store.decision_history(command.actor_id, command.record_id, 1) == ()


@pytest.mark.parametrize(
    "actor",
    [
        AuthenticatedActor("other", Role.OWNER, 1),
        AuthenticatedActor("other", Role.LEARNER, 1),
        AuthenticatedActor("other", Role.ADMIN, 1),
    ],
)
def test_detail_and_request_status_do_not_expose_another_owners_data(context, actor):
    transaction, command, store, _, _, _ = published(context)
    flow = transaction._flow.with_runtime(store, transaction)
    for operation in (
        lambda: flow.detail(actor, command.record_id, 1, now=NOW),
        lambda: flow.request_status(actor, command.record_id),
    ):
        with pytest.raises(
            (PermissionError, LookupError), match="resource_unavailable"
        ):
            operation()


def test_request_list_and_status_have_exact_published_identity(context):
    transaction, command, store, _, _, inputs = published(context)
    flow = transaction._flow.with_runtime(store, transaction)
    actor = AuthenticatedActor(command.actor_id, Role.OWNER, 1)
    page = flow.requests(actor, inputs.company_id)
    assert page.next_cursor is None and len(page.items) == 1
    assert page.items[0] == flow.request_status(actor, command.record_id)
    assert page.items[0].status == "succeeded" and page.items[0].result_version == 1


def test_http_preview_confirm_roundtrip_uses_real_transaction_and_serializes_history(
    context,
):
    from thesis_trace.api import EvidenceApi, create_fastapi_app
    from test_recommendation_http import send

    transaction, command, store, portfolio, _, _ = published(context)
    flow = transaction._flow.with_runtime(store, transaction)

    async def actor():
        return AuthenticatedActor(command.actor_id, Role.OWNER, 1)

    app = create_fastapi_app(EvidenceApi(flow=None, recommendation_flow=flow), actor)
    root = f"/api/recommendations/{command.record_id}"
    body = {
        "version": 1,
        "expected_sequence": 0,
        "target_status": "accepted",
        "reason": command.reason,
        "defer_until": None,
        "idempotency_key": command.idempotency_key,
    }
    before = portfolio.get(command.actor_id)
    preview = send(app, "POST", root + "/decision-previews", json=body)
    assert preview.status_code == 200, preview.text
    body["challenge_token"] = preview.json()["challenge_token"]
    saved = send(app, "POST", root + "/decisions", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["decision_status"] == "accepted"
    assert send(app, "POST", root + "/decisions", json=body).status_code == 200
    detail = send(app, "GET", root + "/versions/1")
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["decisions"]) == 1
    assert detail.json()["decisions"][0]["confirmation_id"]
    assert detail.json()["decisions"][0]["checks"]
    assert detail.json()["view"]["allowed_actions"] == []
    assert portfolio.get(command.actor_id) == before
