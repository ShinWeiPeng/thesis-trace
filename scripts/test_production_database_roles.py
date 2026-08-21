#!/usr/bin/env python3
"""Execute the production role bootstrap against the ephemeral CI PostgreSQL."""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import uuid


def render_role_bootstrap(sql_text: str, database: str) -> str:
    """Bind every production database reference to the ephemeral CI database."""
    placeholder = "DATABASE thesis_trace"
    expected_references = 2
    if sql_text.count(placeholder) != expected_references:
        raise ValueError("production role bootstrap database references changed")
    escaped_database = database.replace('"', '""')
    identifier = f'"{escaped_database}"'
    return sql_text.replace(placeholder, f"DATABASE {identifier}")


def main() -> None:
    import psycopg

    root = Path(__file__).resolve().parents[1]
    dsn = os.environ.get("THESIS_TRACE_TEST_DATABASE_URL", "")
    if not dsn:
        raise SystemExit("THESIS_TRACE_TEST_DATABASE_URL is required")

    with psycopg.connect(dsn, autocommit=True) as admin:
        database = admin.execute("SELECT current_database()").fetchone()[0]
        bootstrap_sql = (root / "infra/postgres/production-roles.sql").read_text(encoding="utf-8")
        admin.execute(render_role_bootstrap(bootstrap_sql, database))
        roles = {
            row[0]: row[1:]
            for row in admin.execute(
                "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit "
                "FROM pg_roles WHERE rolname LIKE 'thesis_trace_%'"
            ).fetchall()
        }
        for role in (
            "thesis_trace_migration", "thesis_trace_api", "thesis_trace_collector",
            "thesis_trace_ai_worker",
        ):
            assert roles[role] == (False, False, False, False, False), f"unsafe attributes for {role}"
        owner = admin.execute(
            "SELECT r.rolname FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba "
            "WHERE d.datname=current_database()"
        ).fetchone()[0]
        assert owner == "thesis_trace_migration", "migration role must own production database"
        for role in ("thesis_trace_api", "thesis_trace_collector", "thesis_trace_ai_worker"):
            assert role != owner, f"{role} must not own the production database"
            can_create = admin.execute(
                "SELECT has_schema_privilege(%s,'public','CREATE')", (role,)
            ).fetchone()[0]
            assert can_create is False, f"{role} unexpectedly has DDL authority"
        migration_module = runpy.run_path(str(root / "infra/postgres/run-production-migrations.py"))
        migration_module["apply_runtime_grants"](admin)
        assert admin.execute(
            "SELECT has_table_privilege('thesis_trace_api','research.evidence_stage_versions','SELECT,INSERT')"
        ).fetchone()[0]
        assert not admin.execute(
            "SELECT has_table_privilege('thesis_trace_api','research.evidence_stage_versions','UPDATE,DELETE')"
        ).fetchone()[0]
        assert not admin.execute(
            "SELECT has_table_privilege('thesis_trace_collector','research.evidence_stage_versions','SELECT,INSERT,UPDATE,DELETE')"
        ).fetchone()[0]
        assert admin.execute(
            "SELECT has_table_privilege('thesis_trace_collector','research.canonical_sources','SELECT,INSERT')"
        ).fetchone()[0]
        assert not admin.execute(
            "SELECT has_table_privilege('thesis_trace_collector','research.canonical_sources','UPDATE,DELETE')"
        ).fetchone()[0]
        assert admin.execute(
            "SELECT has_table_privilege('thesis_trace_ai_worker','research.anomaly_analysis_jobs','SELECT,UPDATE')"
        ).fetchone()[0]
        assert admin.execute(
            "SELECT has_table_privilege('thesis_trace_ai_worker','research.anomaly_assessments','SELECT,UPDATE')"
        ).fetchone()[0]
        assert not admin.execute(
            "SELECT has_table_privilege('thesis_trace_ai_worker','research.anomaly_assessments','INSERT,DELETE')"
        ).fetchone()[0]
        source_id = uuid.uuid4()
        admin.execute("BEGIN")
        try:
            admin.execute("SET LOCAL ROLE thesis_trace_collector")
            admin.execute("SELECT count(*) FROM research.canonical_sources")
            admin.execute(
                """INSERT INTO research.canonical_sources(
                source_id,normalization_policy_version,canonical_url)
                VALUES (%s,'url-normalization-v1',%s)""",
                (source_id, f"https://runtime-role-{source_id}.example/"),
            )
        finally:
            admin.execute("ROLLBACK")
    print("Production migration/API/collector/AI-worker role separation passed")


if __name__ == "__main__":
    main()
