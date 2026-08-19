#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import uuid

import psycopg
from psycopg import errors


ROOT = Path(__file__).resolve().parents[1]
DSN = os.environ.get("THESIS_TRACE_TEST_DATABASE_URL", "")
if not DSN:
    raise SystemExit("THESIS_TRACE_TEST_DATABASE_URL is required")

owner_a = uuid.UUID("10000000-0000-0000-0000-000000000001")
owner_b = uuid.UUID("10000000-0000-0000-0000-000000000002")
record_a = uuid.UUID("20000000-0000-0000-0000-000000000001")
record_b = uuid.UUID("20000000-0000-0000-0000-000000000002")

with psycopg.connect(DSN, autocommit=True) as admin:
    admin.execute((ROOT / "infra/postgres/wave1-rls-contract.sql").read_text(encoding="utf-8"))
    admin.execute("TRUNCATE wave1_contract.tenant_records, wave1_contract.security_audit")
    admin.execute(
        "INSERT INTO wave1_contract.tenant_records(record_id,owner_user_id,value) VALUES (%s,%s,'a'),(%s,%s,'b')",
        (record_a, owner_a, record_b, owner_b),
    )

with psycopg.connect(DSN) as connection:
    with connection.transaction():
        connection.execute("SET LOCAL ROLE wave1_api_runtime")
        connection.execute("SELECT set_config('thesis_trace.user_id', %s, true)", (str(owner_a),))
        visible = connection.execute(
            "SELECT record_id FROM wave1_contract.tenant_records ORDER BY record_id"
        ).fetchall()
        assert visible == [(record_a,)], "RLS exposed another user's record"

    with connection.transaction():
        connection.execute("SET LOCAL ROLE wave1_api_runtime")
        visible = connection.execute("SELECT record_id FROM wave1_contract.tenant_records").fetchall()
        assert visible == [], "transaction-local identity leaked through pool/session reuse"

    try:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE wave1_api_runtime")
            connection.execute("SELECT set_config('thesis_trace.user_id', %s, true)", (str(owner_a),))
            connection.execute(
                "INSERT INTO wave1_contract.tenant_records(record_id,owner_user_id,value) VALUES (%s,%s,'forbidden')",
                (uuid.uuid4(), owner_b),
            )
    except errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("RLS allowed a cross-user write")

    with connection.transaction():
        connection.execute("SET LOCAL ROLE wave1_api_runtime")
        connection.execute(
            "INSERT INTO wave1_contract.security_audit(audit_id,actor_user_id,action,reason) VALUES (%s,%s,'identity_change','confirmed')",
            (uuid.uuid4(), owner_a),
        )

    try:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE wave1_api_runtime")
            connection.execute("UPDATE wave1_contract.security_audit SET reason='rewritten'")
    except errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("runtime role mutated append-only audit")

with psycopg.connect(DSN) as admin:
    role = admin.execute(
        "SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname='wave1_api_runtime'"
    ).fetchone()
    assert role == (False, False), "runtime role must be NOLOGIN and NOBYPASSRLS"
    table = admin.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='wave1_contract.tenant_records'::regclass"
    ).fetchone()
    assert table == (True, True), "protected table must enable and force RLS"

print("Wave 1 real PostgreSQL RLS contract passed")
