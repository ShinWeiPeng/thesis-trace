from __future__ import annotations

import json
import os
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit
import uuid

import psycopg
from psycopg import sql
import pytest

from thesis_trace.platform.postgres import MIGRATIONS, bootstrap_schema


pytestmark = pytest.mark.skipif(
    not os.environ.get("THESIS_TRACE_TEST_DATABASE_URL"),
    reason="set THESIS_TRACE_TEST_DATABASE_URL for PostgreSQL migration evidence",
)


def test_populated_legacy_schema_migrates_as_nobypassrls_owner() -> None:
    configured_url = os.environ["THESIS_TRACE_TEST_DATABASE_URL"]
    parsed = urlsplit(configured_url)
    admin_url = urlunsplit(parsed._replace(path="/postgres"))
    suffix = uuid.uuid4().hex
    role_name = f"thesis_trace_migration_{suffix}"
    database_name = f"thesis_trace_normalized_{suffix}"
    password = f"migration-{suffix}"
    host = parsed.hostname or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    migration_url = urlunsplit(parsed._replace(
        netloc=f"{role_name}:{password}@{host}{port}", path=f"/{database_name}",
    ))

    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL(
            "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOBYPASSRLS NOINHERIT"
        ).format(sql.Identifier(role_name), sql.Literal(password)))
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
            sql.Identifier(database_name), sql.Identifier(role_name),
        ))
    try:
        _create_populated_legacy_schema(migration_url)
        bootstrap_schema(lambda: migration_url)
        with psycopg.connect(migration_url) as connection:
            connection.execute("SELECT set_config('app.user_id','migration-owner',true)")
            assert connection.execute(
                "SELECT valuation_draft_version,valuation_draft,valuation_snapshots "
                "FROM thesis.theses WHERE thesis_id='legacy-thesis'"
            ).fetchone() == (1, None, None)
            assert connection.execute(
                "SELECT original_trade_version FROM portfolio.trade_corrections "
                "WHERE correction_id='correction-1'"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT to_regclass('portfolio.portfolios'),to_regclass('portfolio.record_versions')"
            ).fetchone() == (None, None)
            protected = connection.execute(
                "SELECT c.relname,c.relforcerowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='thesis' AND c.relname IN "
                "('theses','valuation_drafts','valuation_snapshots','audit_events',"
                "'reflection_draft_revisions')"
            ).fetchall()
            assert len(protected) == 5
            assert all(row[1] for row in protected)
            triggers = connection.execute(
                "SELECT tgname,tgenabled FROM pg_trigger WHERE tgname IN "
                "('thesis_valuation_drafts_append_only','thesis_valuation_snapshots_append_only',"
                "'thesis_audit_events_append_only','thesis_reflection_draft_revisions_append_only',"
                "'portfolio_audit_events_append_only')"
            ).fetchall()
            assert len(triggers) == 5
            assert all(row[1] == "O" for row in triggers)
        with psycopg.connect(admin_url) as admin:
            assert admin.execute(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
                "FROM pg_roles WHERE rolname=%s", (role_name,),
            ).fetchone() == (False, False, False, False)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database_name),
            ))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name)))


def _create_populated_legacy_schema(database_url: str) -> None:
    timestamp = "2026-08-29T00:00:00+00:00"
    valuation = {
        "version": 1, "method": "pe", "benchmark_source": "company_history",
        "benchmark_variant": "p75",
        "validity": {"target_date": "2027-08-29", "expires_at": "2026-09-29T00:00:00+00:00"},
        "cost_profile_version": 1, "policy_version": "valuation-policy-v1",
    }
    portfolio = {
        "cash": "900", "cash_as_of": timestamp,
        "cost_profile": {
            "version": 1, "buy_rate": "0", "minimum_buy_fee": "0",
            "sell_rate": "0", "minimum_sell_fee": "0", "tax_rate": "0",
            "effective_at": timestamp, "policy_version": "cost-profile-v1",
        },
        "holdings": [],
        "trades": [{
            "trade_id": "trade-1", "version": 1, "fingerprint": "legacy-fingerprint",
            "trade": {
                "source_kind": "manual", "source_row_id": "row-1",
                "broker_reference": None, "security_id": "2330", "side": "buy",
                "quantity": 1, "price": "100", "fees": "0", "tax": "0",
                "executed_at": timestamp,
            },
            "allocations": [{"bucket_id": "independent", "quantity": 1}],
            "confirmed_at": timestamp, "reason": "legacy trade",
            "policy_version": "trade-policy-v1",
        }],
        "corrections": [{
            "correction_id": "correction-1", "version": 2,
            "original_trade_id": "trade-1",
            "reversed_allocations": [{"bucket_id": "independent", "quantity": 1}],
            "confirmed_at": timestamp, "reason": "legacy correction",
            "policy_version": "trade-policy-v1",
        }],
        "company_actions": [],
    }
    with psycopg.connect(database_url) as connection:
        connection.execute("CREATE SCHEMA research")
        connection.execute(
            "CREATE TABLE research.schema_migrations ("
            "version integer PRIMARY KEY,name text NOT NULL,checksum text NOT NULL,"
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for version, name, migration_sql in MIGRATIONS:
            connection.execute(migration_sql)
            connection.execute(
                "INSERT INTO research.schema_migrations(version,name,checksum) VALUES (%s,%s,%s)",
                (version, name, sha256(migration_sql.encode("utf-8")).hexdigest()),
            )
        connection.execute("SELECT set_config('app.user_id','migration-owner',true)")
        connection.execute("SELECT set_config('app.role','owner',true)")
        connection.execute(
            "INSERT INTO thesis.theses(thesis_id,version,owner_user_id,company_id,company_version,"
            "status,cycle,title,narrative,reflection_pending,policy_version,created_at,updated_at,"
            "valuation_draft,valuation_snapshots) VALUES "
            "('legacy-thesis',1,'migration-owner','2330',1,'invalidated',1,'Legacy','Legacy thesis',"
            "true,'thesis-policy-v1',%s,%s,%s::jsonb,%s::jsonb)",
            (timestamp, timestamp, json.dumps(valuation), json.dumps([])),
        )
        connection.execute(
            "INSERT INTO thesis.valuation_drafts(thesis_id,draft_version,owner_user_id,payload,saved_at) "
            "VALUES ('legacy-thesis',1,'migration-owner',%s::jsonb,%s)",
            (json.dumps(valuation), timestamp),
        )
        connection.execute(
            "INSERT INTO thesis.valuation_snapshots(valuation_id,version,thesis_id,owner_user_id,"
            "draft_version,payload,published_at) VALUES "
            "('valuation-1',1,'legacy-thesis','migration-owner',1,%s::jsonb,%s)",
            (json.dumps({"draft": valuation, "policy_version": "valuation-policy-v1", "reason": "legacy"}), timestamp),
        )
        connection.execute(
            "INSERT INTO thesis.audit_events(event_id,thesis_id,thesis_version,owner_user_id,action,reason,occurred_at) "
            "VALUES (%s,'legacy-thesis',1,'migration-owner','created','legacy',%s)",
            (uuid.uuid4(), timestamp),
        )
        connection.execute(
            "INSERT INTO thesis.reflection_draft_revisions(thesis_id,owner_user_id,cycle,revision,field,text_value,saved_at) "
            "VALUES ('legacy-thesis','migration-owner',1,1,'original_assumption','legacy assumption',%s)",
            (timestamp,),
        )
        connection.execute(
            "INSERT INTO portfolio.portfolios(owner_user_id,version,payload,updated_at) "
            "VALUES ('migration-owner',2,%s::jsonb,%s)", (json.dumps(portfolio), timestamp),
        )
        connection.execute(
            "INSERT INTO portfolio.record_versions(owner_user_id,version,payload,recorded_at) "
            "VALUES ('migration-owner',2,%s::jsonb,%s)", (json.dumps(portfolio), timestamp),
        )
        connection.execute(
            "INSERT INTO portfolio.audit_events(event_id,owner_user_id,portfolio_version,action,reason,occurred_at) "
            "VALUES (%s,'migration-owner',2,'legacy','legacy',%s)", (uuid.uuid4(), timestamp),
        )
        official = {
            "official_close": "100", "price_date": "2026-08-29", "price_source": "TWSE",
            "official_industry": "Semiconductor", "industry_source": "TWSE",
            "classification_effective_at": timestamp, "themes": ["AI"],
            "theme_snapshot_version": 1, "theme_source": "Owner",
            "theme_effective_at": timestamp, "policy_version": "security-v1",
        }
        connection.execute(
            "INSERT INTO portfolio.official_security_snapshots(owner_user_id,security_id,payload) "
            "VALUES ('migration-owner','2330',%s::jsonb)", (json.dumps(official),),
        )
