from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import os
import uuid

import pytest

from thesis_trace.adapters.postgres_access.adapter import PostgresAccessAdapter
from thesis_trace.modules.access.confirmation_challenge.service import ConfirmationService
from thesis_trace.modules.access.orchestration import AccountActionService
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role, SecurityContext
from thesis_trace.modules.access.identity_registry.contracts import ProviderIdentity, VerifiedPrincipal
from thesis_trace.modules.access.session_management.service import SessionService
from thesis_trace.modules.access.recovery_policy import RecoveryPolicyConfiguration
from thesis_trace.platform.postgres import PostgresUnavailable, bootstrap_schema


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="set THESIS_TRACE_TEST_DATABASE_URL for PostgreSQL integration evidence",
)


@pytest.fixture()
def access_store():
    import psycopg

    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    bootstrap_schema(lambda: url)
    with psycopg.connect(url) as connection:
        connection.execute("TRUNCATE access.workflow_outbox,access.security_audit_events,access.confirmation_challenges,access.sessions,access.identities,access.users CASCADE")
    return PostgresAccessAdapter(lambda: url)


def test_tenth_account_succeeds_and_eleventh_is_rejected_transaction_safely(access_store) -> None:
    def create(index: int):
        return access_store.create_account(
            role=Role.LEARNER,
            provider_identity=ProviderIdentity("google", "google", f"subject-{index}"),
            email_fact=f"learner-{index}@example.test",
        )

    with ThreadPoolExecutor(max_workers=10) as pool:
        assert len(list(pool.map(create, range(10)))) == 10
    with pytest.raises(PostgresUnavailable):
        create(11)
    assert len(access_store.list_account_summaries()) == 10


def test_confirmation_consumption_mutation_and_audit_are_one_transaction(access_store) -> None:
    owner = access_store.create_account(
        role=Role.OWNER, provider_identity=ProviderIdentity("cf", "cloudflare", "owner"), email_fact="owner@example.test"
    )
    learner = access_store.create_account(
        role=Role.LEARNER, provider_identity=ProviderIdentity("google", "google", "learner"), email_fact="learner@example.test"
    )
    challenge_service = ConfirmationService(access_store, token_factory=lambda: "one-use-token")
    challenge_service.preview(owner.user_id, "change_role", learner.user_id, 1, {"role": "admin"}, "Change Learner to Admin")
    challenge_id = access_store.execute_confirmed_account_action(
        token="one-use-token", actor_id=owner.user_id, action_type="change_role", target_version=1,
        payload={"role": "admin"}, reason="approved for operations", now=datetime.now(timezone.utc),
    )
    assert challenge_id
    assert access_store.get_account(learner.user_id).role is Role.ADMIN
    with pytest.raises(PermissionError):
        access_store.execute_confirmed_account_action(
            token="one-use-token", actor_id=owner.user_id, action_type="change_role", target_version=1,
            payload={"role": "admin"}, reason="replay", now=datetime.now(timezone.utc),
        )


def test_recovery_bootstrap_session_audit_and_outbox_are_atomic(access_store) -> None:
    import psycopg

    identity = ProviderIdentity("cf-account", "cloudflare", "recovery-owner")
    owner = access_store.create_account(role=Role.OWNER, provider_identity=identity, email_fact="masked@example.test")
    now = datetime.now(timezone.utc)
    principal = VerifiedPrincipal(identity, True, now + timedelta(hours=1))
    policy = RecoveryPolicyConfiguration(identity, "policy-v1", True)
    service = SessionService(access_store, recovery_policy=policy, clock=lambda: now, token_factory=lambda: "recovery-token")
    _token, session, _profile = service.bootstrap(
        owner, principal, recovery=True, recovery_reason="primary identity unavailable",
    )
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT count(*) FROM access.sessions WHERE session_id=%s AND recovery", (session.session_id,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM access.security_audit_events WHERE subject_id=%s", (session.session_id,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM access.workflow_outbox WHERE event_type='workflow.safety_item.requested'").fetchone()[0] == 1

    failing = PostgresAccessAdapter(lambda: url, recovery_fault_hook=lambda: (_ for _ in ()).throw(RuntimeError("fault")))
    failing_service = SessionService(failing, recovery_policy=policy, clock=lambda: now, token_factory=lambda: "rollback-token")
    with pytest.raises(PostgresUnavailable):
        failing_service.bootstrap(owner, principal, recovery=True, recovery_reason="safe reason")
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT count(*) FROM access.sessions WHERE token_digest=%s", (hashlib.sha256(b"rollback-token").hexdigest(),)).fetchone()[0] == 0


def test_confirmed_identity_add_replace_disable_are_atomic_and_audited(access_store) -> None:
    owner = access_store.create_account(role=Role.OWNER, provider_identity=ProviderIdentity("cf", "cloudflare", "owner"), email_fact="owner@example.test")
    learner = access_store.create_account(role=Role.LEARNER, provider_identity=ProviderIdentity("google", "google", "old"), email_fact="learner@example.test")
    tokens = iter(("add", "replace", "disable"))
    service = AccountActionService(access_store, ConfirmationService(access_store, token_factory=lambda: next(tokens)))
    added = {"provider_id": "idp-2", "provider_type": "google", "provider_subject": "added", "email_fact": "masked@example.test"}
    service.preview(owner_as_actor := AuthenticatedActor(owner.user_id, Role.OWNER, 1), action_type="add_identity", target_id=learner.user_id, target_version=1, payload=added)
    service.confirm(owner_as_actor, token="add", action_type="add_identity", target_version=1, payload=added, reason="approved add")
    assert access_store.find_mapping(ProviderIdentity("idp-2", "google", "added")).enabled
    replacement = {"old_provider_id": "idp-2", "old_provider_type": "google", "old_provider_subject": "added", "provider_id": "idp-3", "provider_type": "google", "provider_subject": "replacement", "email_fact": "masked@example.test"}
    service.preview(owner_as_actor, action_type="replace_identity", target_id=learner.user_id, target_version=2, payload=replacement)
    service.confirm(owner_as_actor, token="replace", action_type="replace_identity", target_version=2, payload=replacement, reason="approved replace")
    assert access_store.find_mapping(ProviderIdentity("idp-2", "google", "added")).enabled is False
    disable = {"provider_id": "idp-3", "provider_type": "google", "provider_subject": "replacement"}
    service.preview(owner_as_actor, action_type="disable_identity", target_id=learner.user_id, target_version=3, payload=disable)
    service.confirm(owner_as_actor, token="disable", action_type="disable_identity", target_version=3, payload=disable, reason="approved disable")
    assert access_store.find_mapping(ProviderIdentity("idp-3", "google", "replacement")).enabled is False


def test_set_local_context_does_not_survive_commit_or_rollback(access_store) -> None:
    import psycopg

    owner_id = str(uuid.uuid4())
    with access_store.transaction(SecurityContext(owner_id, Role.OWNER, "request-commit")) as connection:
        assert connection.execute("SELECT current_setting('app.request_id',true)").fetchone()[0] == "request-commit"
    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT current_setting('app.request_id',true)").fetchone()[0] in (None, "")
    with pytest.raises(RuntimeError):
        with access_store.transaction(SecurityContext(owner_id, Role.OWNER, "request-rollback")):
            raise RuntimeError("inject rollback")
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT current_setting('app.request_id',true)").fetchone()[0] in (None, "")


def test_rls_missing_context_denies_for_real_nobypassrls_role_and_local_context_resets(access_store) -> None:
    import psycopg

    url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    role_name = "thesis_trace_rls_integration"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role_name}') THEN CREATE ROLE {role_name} NOLOGIN NOBYPASSRLS; END IF; END $$"
        )
        connection.execute(f"GRANT USAGE ON SCHEMA research TO {role_name}")
        connection.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON research.companies,research.evidence_intakes TO {role_name}")
        connection.execute("INSERT INTO research.companies(company_id,ticker,name,version) VALUES('rls-company','RLS','RLS',1) ON CONFLICT DO NOTHING")
        assert connection.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname=%s", (role_name,)).fetchone()[0] is False
        connection.execute(f"SET ROLE {role_name}")
        with connection.transaction():
            assert connection.execute("SELECT count(*) FROM research.companies").fetchone()[0] == 0
        with connection.transaction():
            connection.execute("SELECT set_config('app.role','owner',true)")
            assert connection.execute("SELECT count(*) FROM research.companies").fetchone()[0] >= 1
        with connection.transaction():
            assert connection.execute("SELECT current_setting('app.role',true)").fetchone()[0] in (None, "")
        with pytest.raises(RuntimeError):
            with connection.transaction():
                connection.execute("SELECT set_config('app.role','owner',true)")
                raise RuntimeError("rollback")
        with connection.transaction():
            assert connection.execute("SELECT current_setting('app.role',true)").fetchone()[0] in (None, "")
        connection.execute("RESET ROLE")
