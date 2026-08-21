from pathlib import Path

import pytest

from thesis_trace.platform import postgres
from thesis_trace.platform.postgres import PostgresEvidenceStore, PostgresUnavailable
from thesis_trace.platform.runtime import required_secret_provider
from thesis_trace.entrypoints import ai_worker, collector_worker
from thesis_trace.modules.access.jwt_verifier import AccessJwtConfiguration, derive_identity_facts


def test_file_secret_provider_rereads_without_retaining_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_file = tmp_path / "database-url"
    first = "postgresql://user:first-secret@database/trace"
    second = "postgresql://user:rotated-secret@database/trace"
    secret_file.write_text(first, encoding="utf-8")
    monkeypatch.setenv("THESIS_TRACE_DATABASE_URL_FILE", str(secret_file))

    provider = required_secret_provider("THESIS_TRACE_DATABASE_URL")
    store = PostgresEvidenceStore(provider)

    assert provider() == first
    secret_file.write_text(second, encoding="utf-8")
    assert provider() == second
    assert first not in repr(provider)
    assert second not in repr(provider)
    assert first not in repr(store)
    assert second not in repr(store)


def test_database_failure_redacts_resolved_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "postgresql://owner:do-not-leak@database/trace"
    secret_file = tmp_path / "database-url"
    secret_file.write_text(secret, encoding="utf-8")
    monkeypatch.setenv("THESIS_TRACE_DATABASE_URL_FILE", str(secret_file))

    class FailingPsycopg:
        @staticmethod
        def connect(database_url: str) -> None:
            raise RuntimeError(f"could not connect with {database_url}")

    monkeypatch.setattr(postgres, "_psycopg", lambda: FailingPsycopg)
    store = PostgresEvidenceStore(required_secret_provider("THESIS_TRACE_DATABASE_URL"))

    with pytest.raises(PostgresUnavailable, match="postgres_unavailable") as captured:
        store.list_companies()
    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


def test_database_secret_requires_file_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THESIS_TRACE_DATABASE_URL_FILE", raising=False)
    monkeypatch.setenv("THESIS_TRACE_DATABASE_URL", "postgresql://inline-secret")

    with pytest.raises(RuntimeError, match="file reference"):
        required_secret_provider("THESIS_TRACE_DATABASE_URL")


def test_collector_entrypoint_only_invokes_composition_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def factory():
        calls.append("factory")

        def worker() -> int:
            calls.append("worker")
            return 17

        return worker

    monkeypatch.setattr(collector_worker, "compose_application", lambda role: factory() if role == "collector" else None)

    assert collector_worker.main() == 17
    assert calls == ["factory", "worker"]


def test_ai_worker_entrypoint_only_invokes_composition_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def factory():
        calls.append("factory")

        def worker() -> int:
            calls.append("worker")
            return 19

        return worker

    monkeypatch.setattr(
        ai_worker,
        "compose_application",
        lambda role: factory() if role == "ai-worker" else None,
    )

    assert ai_worker.main() == 19
    assert calls == ["factory", "worker"]


def test_owner_identity_secret_is_file_only_rotatable_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity_file = tmp_path / "owner-identities"
    first = "First.Owner@Example.com"
    second = "rotated.owner@example.com"
    identity_file.write_text(first, encoding="utf-8")
    monkeypatch.setenv("THESIS_TRACE_OWNER_IDENTITIES_FILE", str(identity_file))
    monkeypatch.setenv("THESIS_TRACE_OWNER_IDENTITIES", "inline-owner@example.com")

    provider = required_secret_provider("THESIS_TRACE_OWNER_IDENTITIES")
    first_facts = derive_identity_facts(provider())
    identity_file.write_text(second, encoding="utf-8")
    second_facts = derive_identity_facts(provider())
    configuration = AccessJwtConfiguration("https://team.cloudflareaccess.com", "audience", second_facts)

    assert first_facts != second_facts
    assert first.casefold() not in repr(configuration)
    assert second.casefold() not in repr(configuration)
    assert "inline-owner" not in repr(provider)


def test_owner_identity_secret_rejects_direct_environment_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THESIS_TRACE_OWNER_IDENTITIES_FILE", raising=False)
    monkeypatch.setenv("THESIS_TRACE_OWNER_IDENTITIES", "owner@example.com")
    with pytest.raises(RuntimeError, match="file reference"):
        required_secret_provider("THESIS_TRACE_OWNER_IDENTITIES")
