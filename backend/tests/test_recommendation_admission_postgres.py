from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
import os
import uuid

import pytest

from thesis_trace.application.contracts import RecommendationAdmissionCommand
from thesis_trace.modules.portfolio.contracts import (
    PortfolioActorContext,
    SaveInvestableCashCommand,
)
from thesis_trace.modules.portfolio.service import PortfolioService
from test_recommendation_atomic_postgres import context, prepare
from test_portfolio_domain import NOW


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL required",
)


def intent(job, frozen):
    return RecommendationAdmissionCommand(
        job.actor_id,
        1,
        job.thesis_id,
        1,
        frozen.valuation_id,
        1,
        2,
        "company_history",
        "Confirmed benchmark for this analysis",
        str(uuid.uuid4()),
    )


def test_admission_receipt_precedes_recomputing_time_or_current_sources(context):
    transaction, job, store, portfolio, _, frozen = prepare(context)
    command = intent(job, frozen)
    input_id = transaction.admit(command)
    original = store.get_input(job.actor_id, input_id)
    assert (
        original is not None
        and original[0].source_selection_reason == command.source_selection_reason
    )
    assert store.job_status(job.actor_id, input_id) == ("pending", None)
    PortfolioService(portfolio).save_investable_cash(
        SaveInvestableCashCommand(
            PortfolioActorContext(job.actor_id, True),
            2,
            Decimal(10000),
            NOW,
            "Changed after admission",
            str(uuid.uuid4()),
        ),
        now=NOW,
    )
    transaction._clock = lambda: (_ for _ in ()).throw(
        AssertionError("Receipt replay must not rebuild inputs")
    )
    assert transaction.admit(command) == input_id
    assert store.get_input(job.actor_id, input_id) == original
    with pytest.raises(ValueError, match="idempotency_conflict"):
        transaction.admit(
            replace(command, source_selection_reason="Different financial intent")
        )


def test_identical_concurrent_admissions_share_one_immutable_job(context):
    transaction, job, store, _, _, frozen = prepare(context)
    command = intent(job, frozen)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(transaction.admit, (command, command)))
    assert results[0] == results[1]
    assert store.job_status(job.actor_id, results[0]) == ("pending", None)


@pytest.mark.parametrize(
    "change",
    [
        {"expected_thesis_version": True},
        {"expected_portfolio_version": "2"},
        {"expected_valuation_version": 0},
        {"source_selection_reason": " "},
        {"benchmark_source": "auto"},
        {"idempotency_key": " "},
    ],
)
def test_malformed_or_unconfirmed_intent_is_rejected_before_admission(context, change):
    transaction, job, _, _, _, frozen = prepare(context)
    with pytest.raises(ValueError, match="invalid_admission_intent"):
        transaction.admit(replace(intent(job, frozen), **change))


def test_changed_account_identity_version_cannot_replay_an_admission(context):
    transaction, job, _, _, _, frozen = prepare(context)
    command = intent(job, frozen)
    transaction.admit(command)
    with pytest.raises(PermissionError, match="resource_unavailable"):
        transaction.admit(replace(command, identity_version=2))
