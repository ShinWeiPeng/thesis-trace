#!/usr/bin/env python3
"""Execute the production role bootstrap against the ephemeral CI PostgreSQL."""
from __future__ import annotations
import os
from pathlib import Path
import psycopg

root = Path(__file__).resolve().parents[1]
dsn = os.environ.get("THESIS_TRACE_TEST_DATABASE_URL", "")
if not dsn:
    raise SystemExit("THESIS_TRACE_TEST_DATABASE_URL is required")

with psycopg.connect(dsn, autocommit=True) as admin:
    database = admin.execute("SELECT current_database()").fetchone()[0]
    sql = (root / "infra/postgres/production-roles.sql").read_text(encoding="utf-8")
    admin.execute(sql.replace("ALTER DATABASE thesis_trace ", f'ALTER DATABASE "{database}" '))
    roles = {
        row[0]: row[1:]
        for row in admin.execute(
            "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit "
            "FROM pg_roles WHERE rolname LIKE 'thesis_trace_%'"
        ).fetchall()
    }
    for role in ("thesis_trace_migration", "thesis_trace_api", "thesis_trace_collector"):
        assert roles[role] == (False, False, False, False, False), f"unsafe attributes for {role}"
    owner = admin.execute("SELECT r.rolname FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba WHERE d.datname=current_database()").fetchone()[0]
    assert owner == "thesis_trace_migration", "migration role must own production database"
    for role in ("thesis_trace_api", "thesis_trace_collector"):
        assert role != owner, f"{role} must not own the production database"
        can_create = admin.execute("SELECT has_schema_privilege(%s,'public','CREATE')", (role,)).fetchone()[0]
        assert can_create is False, f"{role} unexpectedly has DDL authority"
print("Production migration/API/collector role separation passed")
