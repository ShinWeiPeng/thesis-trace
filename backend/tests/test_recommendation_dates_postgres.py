import os
from dataclasses import replace
from decimal import Decimal

import pytest

from thesis_trace.adapters.postgres_thesis.adapter import PostgresThesisStore
from thesis_trace.modules.access.contracts import Role, SecurityContext
from thesis_trace.modules.thesis.contracts import PublishValuationCommand
from thesis_trace.modules.thesis.service import ThesisService
from thesis_trace.platform.postgres import bootstrap_schema
from test_thesis_domain import ACTOR, NOW, create
from test_valuation_domain import command
from test_recommendation_final_size import calculate


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="isolated PostgreSQL required",
)


def test_saved_basis_survives_reload_and_final_size_recomputation():
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    context = SecurityContext(ACTOR.actor_id, Role.OWNER, "wave7-dates")
    store = PostgresThesisStore(lambda: url, security_context_provider=lambda: context)
    store.delete_all_for_test()
    service = ThesisService(store, id_factory=lambda: "thesis-1")
    record = create(service)
    request = command(record.version)
    request = replace(
        request,
        forecast=Decimal("108"),
        company_history_samples=tuple(
            replace(sample, multiple=Decimal(1))
            for sample in request.company_history_samples
        ),
    )
    saved = service.save_valuation_draft(request, now=NOW)
    service.publish_valuation(
        PublishValuationCommand(
            ACTOR,
            saved.thesis_id,
            saved.version,
            1,
            "confirmed",
            "Publish",
            "publish-1",
        ),
        now=NOW,
    )
    fresh = ThesisService(
        PostgresThesisStore(lambda: url, security_context_provider=lambda: context)
    )
    loaded = fresh.get(ACTOR, "thesis-1")
    snapshot = loaded.valuation_snapshots[0]
    assert snapshot.draft.basis_date == request.basis_date
    assert snapshot.draft.horizon_months == 12
    assert calculate(snapshot).annualized_return == Decimal(
        "0.044961538461538461538461538"
    )
