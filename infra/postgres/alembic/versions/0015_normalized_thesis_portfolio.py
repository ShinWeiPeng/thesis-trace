"""Normalize Thesis drafts and Portfolio current state.

Owner schemas: thesis, portfolio. Forward-only production migration.

The migration role owns these schemas but intentionally has no BYPASSRLS.  A
bounded owner-only backfill window temporarily relaxes FORCE RLS and immutable
triggers on the legacy rows that must be read or rewritten.  The transaction
restores every retained protection before commit.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_normalized_thesis_portfolio"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing production tables use FORCE RLS, which also applies to their
    # owner, and immutable-history tables reject UPDATE.  Alembic runs this
    # transaction as the schema-owning migration role; runtime roles cannot
    # perform these ALTER TABLE operations.
    for schema, table_name in (
        ("thesis", "theses"),
        ("thesis", "valuation_drafts"),
        ("thesis", "valuation_snapshots"),
        ("thesis", "audit_events"),
        ("thesis", "reflection_draft_revisions"),
        ("portfolio", "portfolios"),
        ("portfolio", "record_versions"),
        ("portfolio", "official_security_snapshots"),
        ("portfolio", "audit_events"),
    ):
        op.execute(f"ALTER TABLE {schema}.{table_name} NO FORCE ROW LEVEL SECURITY")
    for schema, table_name in (
        ("thesis", "valuation_drafts"),
        ("thesis", "valuation_snapshots"),
        ("thesis", "audit_events"),
        ("thesis", "reflection_draft_revisions"),
        ("portfolio", "audit_events"),
    ):
        op.execute(
            f"ALTER TABLE {schema}.{table_name} DISABLE TRIGGER "
            f"{schema}_{table_name}_append_only"
        )

    op.add_column("theses", sa.Column("valuation_draft_version", sa.Integer()), schema="thesis")
    op.execute("""UPDATE thesis.theses SET valuation_draft_version=
      NULLIF(valuation_draft->>'version','')::integer WHERE valuation_draft IS NOT NULL""")
    for table_name in ("valuation_drafts", "valuation_snapshots"):
        op.add_column(table_name, sa.Column("method", sa.Text()), schema="thesis")
        op.add_column(table_name, sa.Column("benchmark_source", sa.Text()), schema="thesis")
        op.add_column(table_name, sa.Column("benchmark_variant", sa.Text()), schema="thesis")
        op.add_column(table_name, sa.Column("target_date", sa.Date()), schema="thesis")
        op.add_column(table_name, sa.Column("expires_at", sa.DateTime(timezone=True)), schema="thesis")
        op.add_column(table_name, sa.Column("cost_profile_version", sa.Integer()), schema="thesis")
        op.add_column(table_name, sa.Column("policy_version", sa.Text()), schema="thesis")
    op.add_column("valuation_snapshots", sa.Column("reason", sa.Text()), schema="thesis")
    op.execute("""UPDATE thesis.valuation_drafts SET
      method=payload->>'method',benchmark_source=payload->>'benchmark_source',
      benchmark_variant=payload->>'benchmark_variant',target_date=(payload->'validity'->>'target_date')::date,
      expires_at=(payload->'validity'->>'expires_at')::timestamptz,
      cost_profile_version=(payload->>'cost_profile_version')::integer,policy_version=payload->>'policy_version'""")
    op.execute("""UPDATE thesis.valuation_snapshots SET
      method=payload->'draft'->>'method',benchmark_source=payload->'draft'->>'benchmark_source',
      benchmark_variant=payload->'draft'->>'benchmark_variant',
      target_date=(payload->'draft'->'validity'->>'target_date')::date,
      expires_at=(payload->'draft'->'validity'->>'expires_at')::timestamptz,
      cost_profile_version=(payload->'draft'->>'cost_profile_version')::integer,
      policy_version=payload->>'policy_version',reason=payload->>'reason'""")
    for table_name in ("valuation_drafts", "valuation_snapshots"):
        for column in (
            "method", "benchmark_source", "benchmark_variant", "target_date", "expires_at",
            "cost_profile_version", "policy_version",
        ):
            op.alter_column(table_name, column, nullable=False, schema="thesis")
    op.alter_column("valuation_snapshots", "reason", nullable=False, schema="thesis")
    op.create_check_constraint(
        "thesis_valuation_draft_cost_profile_nonnegative", "valuation_drafts",
        "cost_profile_version >= 0", schema="thesis",
    )
    op.create_check_constraint(
        "thesis_valuation_snapshot_cost_profile_nonnegative", "valuation_snapshots",
        "cost_profile_version >= 0", schema="thesis",
    )
    op.create_foreign_key(
        "thesis_snapshot_draft_fk", "valuation_snapshots", "valuation_drafts",
        ["thesis_id", "draft_version"], ["thesis_id", "draft_version"],
        source_schema="thesis", referent_schema="thesis",
    )
    op.alter_column("theses", "valuation_draft", nullable=True, schema="thesis")
    op.alter_column(
        "theses", "valuation_snapshots", nullable=True, server_default=None, schema="thesis",
    )
    op.execute("UPDATE thesis.theses SET valuation_draft=NULL,valuation_snapshots=NULL")

    for table_name in ("audit_events",):
        op.add_column(table_name, sa.Column("before_version", sa.Integer()), schema="thesis")
        op.add_column(table_name, sa.Column("after_version", sa.Integer()), schema="thesis")
        op.add_column(table_name, sa.Column("correlation_id", sa.Text()), schema="thesis")
        op.add_column(table_name, sa.Column("causation_id", sa.Text()), schema="thesis")
        op.add_column(table_name, sa.Column("policy_version", sa.Text()), schema="thesis")
        op.add_column(table_name, sa.Column("build_version", sa.Text()), schema="thesis")
    op.execute("""UPDATE thesis.audit_events SET before_version=GREATEST(thesis_version-1,0),
      after_version=thesis_version,correlation_id=event_id::text,causation_id=event_id::text,
      policy_version='thesis-lifecycle-legacy',build_version='legacy'""")

    op.add_column("reflection_draft_revisions", sa.Column("original_assumption", sa.Text()), schema="thesis")
    op.add_column("reflection_draft_revisions", sa.Column("judgment_errors", sa.Text()), schema="thesis")
    op.add_column("reflection_draft_revisions", sa.Column("missing_evidence", sa.Text()), schema="thesis")
    op.add_column("reflection_draft_revisions", sa.Column("improvement", sa.Text()), schema="thesis")
    op.execute("""
    UPDATE thesis.reflection_draft_revisions current SET
      original_assumption=COALESCE((SELECT text_value FROM thesis.reflection_draft_revisions prior WHERE prior.thesis_id=current.thesis_id AND prior.cycle=current.cycle AND prior.revision<=current.revision AND prior.field='original_assumption' ORDER BY prior.revision DESC LIMIT 1),''),
      judgment_errors=COALESCE((SELECT text_value FROM thesis.reflection_draft_revisions prior WHERE prior.thesis_id=current.thesis_id AND prior.cycle=current.cycle AND prior.revision<=current.revision AND prior.field='judgment_errors' ORDER BY prior.revision DESC LIMIT 1),''),
      missing_evidence=COALESCE((SELECT text_value FROM thesis.reflection_draft_revisions prior WHERE prior.thesis_id=current.thesis_id AND prior.cycle=current.cycle AND prior.revision<=current.revision AND prior.field='missing_evidence' ORDER BY prior.revision DESC LIMIT 1),''),
      improvement=COALESCE((SELECT text_value FROM thesis.reflection_draft_revisions prior WHERE prior.thesis_id=current.thesis_id AND prior.cycle=current.cycle AND prior.revision<=current.revision AND prior.field='improvement' ORDER BY prior.revision DESC LIMIT 1),'')
    """)
    for column in ("original_assumption", "judgment_errors", "missing_evidence", "improvement"):
        op.alter_column("reflection_draft_revisions", column, nullable=False, schema="thesis")
    op.alter_column("reflection_draft_revisions", "field", nullable=True, schema="thesis")
    op.alter_column("reflection_draft_revisions", "text_value", nullable=True, schema="thesis")

    op.add_column("official_security_snapshots", sa.Column("official_close", sa.Numeric()), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("price_date", sa.Date()), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("price_source", sa.Text()), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("official_industry", sa.Text()), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("industry_source", sa.Text()), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("classification_effective_at", sa.DateTime(timezone=True)), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("themes", postgresql.ARRAY(sa.Text())), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("theme_snapshot_version", sa.Integer()), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("theme_source", sa.Text()), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("theme_effective_at", sa.DateTime(timezone=True)), schema="portfolio")
    op.add_column("official_security_snapshots", sa.Column("policy_version", sa.Text()), schema="portfolio")
    op.execute("""
    UPDATE portfolio.official_security_snapshots SET
      official_close=(payload->>'official_close')::numeric,
      price_date=(payload->>'price_date')::date,
      price_source=payload->>'price_source',
      official_industry=payload->>'official_industry',
      industry_source=payload->>'industry_source',
      classification_effective_at=(payload->>'classification_effective_at')::timestamptz,
      themes=ARRAY(SELECT jsonb_array_elements_text(payload->'themes')),
      theme_snapshot_version=(payload->>'theme_snapshot_version')::integer,
      theme_source=payload->>'theme_source',
      theme_effective_at=(payload->>'theme_effective_at')::timestamptz,
      policy_version=payload->>'policy_version'
    """)
    for column in (
        "official_close", "price_date", "price_source", "official_industry", "industry_source",
        "classification_effective_at", "themes", "theme_snapshot_version", "theme_source",
        "theme_effective_at", "policy_version",
    ):
        op.alter_column("official_security_snapshots", column, nullable=False, schema="portfolio")
    op.alter_column("official_security_snapshots", "payload", nullable=True, schema="portfolio")

    op.create_table(
        "current_state",
        sa.Column("owner_user_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("cash", sa.Numeric(), nullable=False),
        sa.Column("cash_as_of", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="portfolio_current_state_version_positive"),
        sa.CheckConstraint("cash >= 0", name="portfolio_current_state_cash_nonnegative"),
        schema="portfolio",
    )
    op.create_table(
        "cost_profiles",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("buy_rate", sa.Numeric(), nullable=False),
        sa.Column("minimum_buy_fee", sa.Numeric(), nullable=False),
        sa.Column("sell_rate", sa.Numeric(), nullable=False),
        sa.Column("minimum_sell_fee", sa.Numeric(), nullable=False),
        sa.Column("tax_rate", sa.Numeric(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.CheckConstraint("version >= 1", name="portfolio_cost_profile_version_positive"),
        sa.CheckConstraint(
            "buy_rate >= 0 AND minimum_buy_fee >= 0 AND sell_rate >= 0 "
            "AND minimum_sell_fee >= 0 AND tax_rate >= 0",
            name="portfolio_cost_profile_nonnegative",
        ),
        sa.PrimaryKeyConstraint("owner_user_id", "version"),
        schema="portfolio",
    )
    op.create_table(
        "investable_cash_versions",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("portfolio_version", sa.Integer(), nullable=False),
        sa.Column("cash", sa.Numeric(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("portfolio_version >= 1", name="portfolio_cash_version_positive"),
        sa.CheckConstraint("cash >= 0", name="portfolio_cash_nonnegative"),
        sa.PrimaryKeyConstraint("owner_user_id", "portfolio_version"),
        schema="portfolio",
    )
    op.create_table(
        "holdings",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("bucket_id", sa.Text(), nullable=False),
        sa.Column("security_id", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("official_close", sa.Numeric(), nullable=False),
        sa.Column("official_industry", sa.Text(), nullable=False),
        sa.Column("themes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("price_source", sa.Text(), nullable=False),
        sa.Column("industry_source", sa.Text(), nullable=False),
        sa.Column("classification_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("theme_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("theme_source", sa.Text(), nullable=False),
        sa.Column("theme_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="portfolio_holding_quantity_nonnegative"),
        sa.CheckConstraint("official_close >= 0", name="portfolio_holding_close_nonnegative"),
        sa.PrimaryKeyConstraint("owner_user_id", "bucket_id", "security_id"),
        schema="portfolio",
    )
    op.create_table(
        "trades",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("trade_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_row_id", sa.Text(), nullable=False),
        sa.Column("broker_reference", sa.Text()),
        sa.Column("security_id", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("fees", sa.Numeric(), nullable=False),
        sa.Column("tax", sa.Numeric(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.CheckConstraint("version >= 1", name="portfolio_trade_version_positive"),
        sa.CheckConstraint("side IN ('buy','sell')", name="portfolio_trade_side_valid"),
        sa.CheckConstraint("quantity > 0", name="portfolio_trade_quantity_positive"),
        sa.CheckConstraint(
            "price >= 0 AND fees >= 0 AND tax >= 0",
            name="portfolio_trade_amounts_nonnegative",
        ),
        sa.PrimaryKeyConstraint("owner_user_id", "trade_id", "version"),
        sa.UniqueConstraint("owner_user_id", "fingerprint"),
        schema="portfolio",
    )
    op.create_table(
        "trade_allocations",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("trade_id", sa.Text(), nullable=False),
        sa.Column("trade_version", sa.Integer(), nullable=False),
        sa.Column("bucket_id", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="portfolio_trade_allocation_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["owner_user_id", "trade_id", "trade_version"],
            ["portfolio.trades.owner_user_id", "portfolio.trades.trade_id", "portfolio.trades.version"],
        ),
        sa.PrimaryKeyConstraint("owner_user_id", "trade_id", "trade_version", "bucket_id"),
        schema="portfolio",
    )
    op.create_table(
        "trade_corrections",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("correction_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("original_trade_id", sa.Text(), nullable=False),
        sa.Column("original_trade_version", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.CheckConstraint("version >= 1", name="portfolio_correction_version_positive"),
        sa.CheckConstraint(
            "original_trade_version >= 1",
            name="portfolio_correction_original_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id", "original_trade_id", "original_trade_version"],
            ["portfolio.trades.owner_user_id", "portfolio.trades.trade_id", "portfolio.trades.version"],
            name="portfolio_correction_original_trade_fk",
        ),
        sa.PrimaryKeyConstraint("owner_user_id", "correction_id", "version"),
        schema="portfolio",
    )
    op.create_table(
        "correction_allocations",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("correction_id", sa.Text(), nullable=False),
        sa.Column("correction_version", sa.Integer(), nullable=False),
        sa.Column("bucket_id", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="portfolio_correction_allocation_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["owner_user_id", "correction_id", "correction_version"],
            ["portfolio.trade_corrections.owner_user_id", "portfolio.trade_corrections.correction_id", "portfolio.trade_corrections.version"],
        ),
        sa.PrimaryKeyConstraint("owner_user_id", "correction_id", "correction_version", "bucket_id"),
        schema="portfolio",
    )
    op.create_table(
        "company_actions",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Text(), nullable=False),
        sa.Column("action_kind", sa.Text(), nullable=False),
        sa.Column("pre_action_shares", sa.Integer(), nullable=False),
        sa.Column("confirmed_post_action_shares", sa.Integer(), nullable=False),
        sa.Column("cash_in_lieu", sa.Numeric(), nullable=False),
        sa.Column("remainder_order", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("allocation_policy_version", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.CheckConstraint("version >= 1", name="portfolio_company_action_version_positive"),
        sa.CheckConstraint(
            "pre_action_shares >= 0 AND confirmed_post_action_shares >= 0 AND cash_in_lieu >= 0",
            name="portfolio_company_action_nonnegative",
        ),
        sa.PrimaryKeyConstraint("owner_user_id", "action_id", "version"),
        schema="portfolio",
    )
    op.create_table(
        "company_action_allocations",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("action_version", sa.Integer(), nullable=False),
        sa.Column("bucket_id", sa.Text(), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("cash", sa.Numeric(), nullable=False),
        sa.CheckConstraint(
            "shares >= 0 AND cash >= 0",
            name="portfolio_company_action_allocation_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id", "action_id", "action_version"],
            ["portfolio.company_actions.owner_user_id", "portfolio.company_actions.action_id", "portfolio.company_actions.version"],
        ),
        sa.PrimaryKeyConstraint("owner_user_id", "action_id", "action_version", "bucket_id"),
        schema="portfolio",
    )
    op.create_table(
        "version_history",
        sa.Column("owner_user_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="portfolio_history_version_positive"),
        sa.PrimaryKeyConstraint("owner_user_id", "version"),
        schema="portfolio",
    )

    op.add_column("audit_events", sa.Column("before_version", sa.Integer()), schema="portfolio")
    op.add_column("audit_events", sa.Column("after_version", sa.Integer()), schema="portfolio")
    op.add_column("audit_events", sa.Column("correlation_id", sa.Text()), schema="portfolio")
    op.add_column("audit_events", sa.Column("causation_id", sa.Text()), schema="portfolio")
    op.add_column("audit_events", sa.Column("policy_version", sa.Text()), schema="portfolio")
    op.add_column("audit_events", sa.Column("build_version", sa.Text()), schema="portfolio")
    op.execute("""UPDATE portfolio.audit_events SET before_version=GREATEST(portfolio_version-1,0),
      after_version=portfolio_version,correlation_id=event_id::text,causation_id=event_id::text,
      policy_version='portfolio-legacy',build_version='legacy'""")
    for schema, table_name, columns in (
        ("thesis", "audit_events", ("before_version", "after_version", "correlation_id", "causation_id", "policy_version", "build_version")),
        ("portfolio", "audit_events", ("before_version", "after_version", "correlation_id", "causation_id", "policy_version", "build_version")),
    ):
        for column in columns:
            op.alter_column(table_name, column, nullable=False, schema=schema)

    op.execute("""
    INSERT INTO portfolio.current_state(owner_user_id,version,cash,cash_as_of,updated_at)
    SELECT owner_user_id,version,(payload->>'cash')::numeric,NULLIF(payload->>'cash_as_of','')::timestamptz,updated_at
    FROM portfolio.portfolios ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.cost_profiles(owner_user_id,version,buy_rate,minimum_buy_fee,sell_rate,minimum_sell_fee,tax_rate,effective_at,policy_version)
    SELECT owner_user_id,(payload->'cost_profile'->>'version')::integer,(payload->'cost_profile'->>'buy_rate')::numeric,
      (payload->'cost_profile'->>'minimum_buy_fee')::numeric,(payload->'cost_profile'->>'sell_rate')::numeric,
      (payload->'cost_profile'->>'minimum_sell_fee')::numeric,(payload->'cost_profile'->>'tax_rate')::numeric,
      (payload->'cost_profile'->>'effective_at')::timestamptz,payload->'cost_profile'->>'policy_version'
    FROM portfolio.record_versions WHERE payload->'cost_profile' IS NOT NULL ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.investable_cash_versions(owner_user_id,portfolio_version,cash,as_of,recorded_at)
    SELECT owner_user_id,version,(payload->>'cash')::numeric,
      NULLIF(payload->>'cash_as_of','')::timestamptz,recorded_at
    FROM portfolio.record_versions ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.holdings(owner_user_id,bucket_id,security_id,quantity,official_close,official_industry,themes,price_date,price_source,industry_source,classification_effective_at,theme_snapshot_version,theme_source,theme_effective_at)
    SELECT p.owner_user_id,h->>'bucket_id',h->>'security_id',(h->>'quantity')::numeric,(h->>'official_close')::numeric,
      h->>'official_industry',ARRAY(SELECT jsonb_array_elements_text(h->'themes')),(h->>'price_date')::date,
      h->>'price_source',h->>'industry_source',(h->>'classification_effective_at')::timestamptz,
      (h->>'theme_snapshot_version')::integer,h->>'theme_source',(h->>'theme_effective_at')::timestamptz
    FROM portfolio.portfolios p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'holdings') h ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.trades(owner_user_id,trade_id,version,fingerprint,source_kind,source_row_id,broker_reference,security_id,side,quantity,price,fees,tax,executed_at,confirmed_at,reason,policy_version)
    SELECT p.owner_user_id,t->>'trade_id',(t->>'version')::integer,t->>'fingerprint',t->'trade'->>'source_kind',t->'trade'->>'source_row_id',
      t->'trade'->>'broker_reference',t->'trade'->>'security_id',t->'trade'->>'side',(t->'trade'->>'quantity')::integer,
      (t->'trade'->>'price')::numeric,(t->'trade'->>'fees')::numeric,(t->'trade'->>'tax')::numeric,
      (t->'trade'->>'executed_at')::timestamptz,(t->>'confirmed_at')::timestamptz,t->>'reason',t->>'policy_version'
    FROM portfolio.portfolios p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'trades') t ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.trade_allocations(owner_user_id,trade_id,trade_version,bucket_id,quantity)
    SELECT p.owner_user_id,t->>'trade_id',(t->>'version')::integer,a->>'bucket_id',(a->>'quantity')::integer
    FROM portfolio.portfolios p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'trades') t
      CROSS JOIN LATERAL jsonb_array_elements(t->'allocations') a ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.trade_corrections(owner_user_id,correction_id,version,original_trade_id,original_trade_version,confirmed_at,reason,policy_version)
    SELECT p.owner_user_id,c->>'correction_id',(c->>'version')::integer,c->>'original_trade_id',
      (SELECT MAX((original->>'version')::integer)
       FROM jsonb_array_elements(p.payload->'trades') original
       WHERE original->>'trade_id'=c->>'original_trade_id'),
      (c->>'confirmed_at')::timestamptz,c->>'reason',c->>'policy_version'
    FROM portfolio.portfolios p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'corrections') c
    ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.correction_allocations(owner_user_id,correction_id,correction_version,bucket_id,quantity)
    SELECT p.owner_user_id,c->>'correction_id',(c->>'version')::integer,a->>'bucket_id',(a->>'quantity')::integer
    FROM portfolio.portfolios p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'corrections') c
      CROSS JOIN LATERAL jsonb_array_elements(c->'reversed_allocations') a ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.company_actions(owner_user_id,action_id,version,security_id,action_kind,
      pre_action_shares,confirmed_post_action_shares,cash_in_lieu,remainder_order,
      allocation_policy_version,confirmed_at,reason,policy_version)
    SELECT p.owner_user_id,a->>'action_id',(a->>'version')::integer,a->>'security_id',a->>'action_kind',
      (a->>'pre_action_shares')::integer,(a->>'confirmed_post_action_shares')::integer,
      (a->>'cash_in_lieu')::numeric,ARRAY(SELECT jsonb_array_elements_text(a->'allocation'->'remainder_order')),
      a->'allocation'->>'policy_version',(a->>'confirmed_at')::timestamptz,a->>'reason',a->>'policy_version'
    FROM portfolio.portfolios p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'company_actions') a
    ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.company_action_allocations(owner_user_id,action_id,action_version,bucket_id,shares,cash)
    SELECT p.owner_user_id,a->>'action_id',(a->>'version')::integer,keys.bucket_id,
      COALESCE((a->'allocation'->'shares'->>keys.bucket_id)::integer,0),
      COALESCE((a->'allocation'->'cash'->>keys.bucket_id)::numeric,0)
    FROM portfolio.portfolios p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'company_actions') a
      CROSS JOIN LATERAL (
        SELECT jsonb_object_keys(COALESCE(a->'allocation'->'shares','{}'::jsonb)) AS bucket_id
        UNION SELECT jsonb_object_keys(COALESCE(a->'allocation'->'cash','{}'::jsonb))
      ) keys ON CONFLICT DO NOTHING
    """)
    op.execute("""
    INSERT INTO portfolio.version_history(owner_user_id,version,action,recorded_at)
    SELECT owner_user_id,version,'legacy_snapshot_migrated',recorded_at FROM portfolio.record_versions ON CONFLICT DO NOTHING
    """)

    # The normalized tables are now the sole Portfolio authority.  Removing
    # the writable aggregate JSON prevents old and new representations from
    # diverging after deployment.
    op.drop_table("record_versions", schema="portfolio")
    op.drop_table("portfolios", schema="portfolio")

    op.execute("""
    DO $$ DECLARE table_name text; BEGIN
      FOREACH table_name IN ARRAY ARRAY['current_state','cost_profiles','investable_cash_versions','holdings','trades','trade_allocations','trade_corrections','correction_allocations','company_actions','company_action_allocations','version_history'] LOOP
        EXECUTE format('ALTER TABLE portfolio.%I ENABLE ROW LEVEL SECURITY',table_name);
        EXECUTE format('ALTER TABLE portfolio.%I FORCE ROW LEVEL SECURITY',table_name);
        EXECUTE format('CREATE POLICY %I ON portfolio.%I USING (owner_user_id=current_setting(''app.user_id'',true)) WITH CHECK (owner_user_id=current_setting(''app.user_id'',true))','portfolio_'||table_name||'_scope',table_name);
      END LOOP;
    END $$
    """)

    for schema, table_name in (
        ("thesis", "valuation_drafts"),
        ("thesis", "valuation_snapshots"),
        ("thesis", "audit_events"),
        ("thesis", "reflection_draft_revisions"),
        ("portfolio", "audit_events"),
    ):
        op.execute(
            f"ALTER TABLE {schema}.{table_name} ENABLE TRIGGER "
            f"{schema}_{table_name}_append_only"
        )
    for schema, table_name in (
        ("thesis", "theses"),
        ("thesis", "valuation_drafts"),
        ("thesis", "valuation_snapshots"),
        ("thesis", "audit_events"),
        ("thesis", "reflection_draft_revisions"),
        ("portfolio", "official_security_snapshots"),
        ("portfolio", "audit_events"),
    ):
        op.execute(f"ALTER TABLE {schema}.{table_name} FORCE ROW LEVEL SECURITY")
    op.execute("""
    DO $$ DECLARE table_name text; BEGIN
      FOREACH table_name IN ARRAY ARRAY['cost_profiles','investable_cash_versions','trades','trade_allocations','trade_corrections','correction_allocations','company_actions','company_action_allocations','version_history'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON portfolio.%I FOR EACH ROW EXECUTE FUNCTION portfolio.reject_immutable_mutation()','portfolio_'||table_name||'_append_only',table_name);
      END LOOP;
    END $$
    """)


def downgrade() -> None:
    raise RuntimeError("production downgrade is disabled")
