"""Append-only normalized Portfolio analytical snapshots for Recommendation."""

from alembic import op

revision = "0018_recommendation_risk"
down_revision = "0017_valuation_basis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE portfolio.recommendation_snapshots (
      owner_user_id text NOT NULL, snapshot_id text NOT NULL CHECK(length(snapshot_id)>0),
      portfolio_version integer NOT NULL CHECK(portfolio_version>0), cash numeric NOT NULL,
      cash_as_of timestamptz NOT NULL, created_at timestamptz NOT NULL,
      base_amount numeric NOT NULL, buy_price numeric NOT NULL,
      cost_version integer NOT NULL CHECK(cost_version>0),
      cost_buy_rate numeric NOT NULL, cost_minimum_buy_fee numeric NOT NULL,
      cost_sell_rate numeric NOT NULL, cost_minimum_sell_fee numeric NOT NULL,
      cost_tax_rate numeric NOT NULL, cost_effective_at timestamptz NOT NULL,
      cost_policy_version text NOT NULL,
      target_security_id text NOT NULL, target_official_close numeric NOT NULL,
      target_price_date date NOT NULL, target_price_source text NOT NULL,
      target_official_industry text NOT NULL, target_industry_source text NOT NULL,
      target_classification_effective_at timestamptz NOT NULL, target_themes text[] NOT NULL,
      target_theme_snapshot_version integer NOT NULL, target_theme_source text NOT NULL,
      target_theme_effective_at timestamptz NOT NULL, target_policy_version text NOT NULL,
      nav numeric NOT NULL, feasible boolean NOT NULL, exposure_reasons text[] NOT NULL,
      exposure_policy_version text NOT NULL,
      multiplier numeric NOT NULL CHECK(multiplier IN (0,0.5,1,1.5)),
      sizing_reasons text[] NOT NULL, evaluated numeric[] NOT NULL, sizing_policy_version text NOT NULL,
      holding_count integer NOT NULL CHECK(holding_count>=0),
      exposure_count integer NOT NULL CHECK(exposure_count>=0),
      PRIMARY KEY(owner_user_id,snapshot_id)
    );
    CREATE TABLE portfolio.recommendation_holdings (
      owner_user_id text NOT NULL, snapshot_id text NOT NULL, ordinal integer NOT NULL CHECK(ordinal>=0),
      bucket_id text NOT NULL, security_id text NOT NULL, quantity numeric NOT NULL,
      official_close numeric NOT NULL, official_industry text NOT NULL, themes text[] NOT NULL,
      price_date date NOT NULL, price_source text NOT NULL, industry_source text NOT NULL,
      classification_effective_at timestamptz NOT NULL, theme_snapshot_version integer NOT NULL,
      theme_source text NOT NULL, theme_effective_at timestamptz NOT NULL,
      PRIMARY KEY(owner_user_id,snapshot_id,ordinal),
      UNIQUE(owner_user_id,snapshot_id,bucket_id,security_id),
      FOREIGN KEY(owner_user_id,snapshot_id) REFERENCES portfolio.recommendation_snapshots
    );
    CREATE TABLE portfolio.recommendation_exposures (
      owner_user_id text NOT NULL, snapshot_id text NOT NULL,
      kind text NOT NULL CHECK(kind IN ('security','industry','theme')),
      exposure_key text NOT NULL, ratio numeric NOT NULL,
      PRIMARY KEY(owner_user_id,snapshot_id,kind,exposure_key),
      FOREIGN KEY(owner_user_id,snapshot_id) REFERENCES portfolio.recommendation_snapshots
    );
    """)
    for table in (
        "recommendation_snapshots",
        "recommendation_holdings",
        "recommendation_exposures",
    ):
        op.execute(f"ALTER TABLE portfolio.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE portfolio.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_scope ON portfolio.{table}
          USING(owner_user_id=current_setting('app.user_id',true) AND current_setting('app.role',true)='owner')
          WITH CHECK(owner_user_id=current_setting('app.user_id',true) AND current_setting('app.role',true)='owner')""")
        op.execute(f"""CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON portfolio.{table}
          FOR EACH ROW EXECUTE FUNCTION portfolio.reject_immutable_mutation()""")
    # Deferred completeness checks seal the child sets as well as each immutable row.
    # An extra child inserted after publication is rejected, not a mutation of history.
    op.execute("""
    CREATE FUNCTION portfolio.check_recommendation_snapshot_complete() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE expected_holdings integer; expected_exposures integer;
    BEGIN
      SELECT holding_count,exposure_count INTO STRICT expected_holdings,expected_exposures
        FROM portfolio.recommendation_snapshots
        WHERE owner_user_id=NEW.owner_user_id AND snapshot_id=NEW.snapshot_id;
      IF expected_holdings<>(SELECT count(*) FROM portfolio.recommendation_holdings
            WHERE owner_user_id=NEW.owner_user_id AND snapshot_id=NEW.snapshot_id)
         OR expected_exposures<>(SELECT count(*) FROM portfolio.recommendation_exposures
            WHERE owner_user_id=NEW.owner_user_id AND snapshot_id=NEW.snapshot_id) THEN
        RAISE EXCEPTION 'recommendation_snapshot_incomplete';
      END IF;
      RETURN NULL;
    END $$;
    """)
    for table in (
        "recommendation_snapshots",
        "recommendation_holdings",
        "recommendation_exposures",
    ):
        op.execute(f"""CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON portfolio.{table}
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
          EXECUTE FUNCTION portfolio.check_recommendation_snapshot_complete()""")


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
