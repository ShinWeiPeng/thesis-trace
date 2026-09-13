"""Normalized immutable Recommendation records and sequenced Owner decisions."""

from alembic import op

revision = "0019_recommendation_records"
down_revision = "0018_recommendation_risk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA recommendation")
    op.execute("""
    CREATE TABLE recommendation.records (
      owner_user_id text NOT NULL, recommendation_id text NOT NULL, version integer NOT NULL CHECK(version>0),
      thesis_id text NOT NULL, cycle integer NOT NULL CHECK(cycle>0), company_id text NOT NULL,
      valuation_id text NOT NULL, portfolio_snapshot_id text,
      source_selection_reason text NOT NULL CHECK(length(trim(source_selection_reason))>0),
      benchmark_source text NOT NULL CHECK(benchmark_source IN ('company_history','peer_group','abstain')),
      input_gate_reasons text[] NOT NULL, admitted_at timestamptz NOT NULL,
      candidate_direction text NOT NULL CHECK(candidate_direction IN ('buy','hold','abstain')),
      raw_dca_ceiling numeric NOT NULL CHECK(raw_dca_ceiling IN (0,0.5,1,1.5)),
      candidate_schema_version text NOT NULL, candidate_digest text NOT NULL,
      direction text NOT NULL CHECK(direction IN ('buy','hold','abstain')),
      final_multiplier numeric NOT NULL CHECK(final_multiplier IN (0,0.5,1,1.5)),
      reasons text[] NOT NULL, annualized_return numeric, minimum_return numeric,
      published_at timestamptz NOT NULL, policy_version text NOT NULL,
      calculation_trace jsonb NOT NULL CHECK(jsonb_typeof(calculation_trace)='array'),
      provenance jsonb NOT NULL CHECK(jsonb_typeof(provenance)='array'), critic_evidence text NOT NULL,
      binding_count integer NOT NULL CHECK(binding_count>0),
      source_count integer NOT NULL CHECK(source_count BETWEEN 1 AND 32),
      claim_count integer NOT NULL CHECK(claim_count BETWEEN 1 AND 32),
      PRIMARY KEY(owner_user_id,recommendation_id,version),
      CHECK(published_at>=admitted_at),
      CHECK(final_multiplier<=raw_dca_ceiling),
      CHECK(direction='buy' OR final_multiplier=0),
      CHECK(direction<>'buy' OR (final_multiplier>0 AND annualized_return IS NOT NULL
        AND minimum_return IS NOT NULL AND annualized_return>=minimum_return AND cardinality(reasons)=0))
    );
    CREATE INDEX records_company_history ON recommendation.records(owner_user_id,company_id,published_at,recommendation_id,version);
    CREATE TABLE recommendation.input_bindings (
      owner_user_id text NOT NULL, recommendation_id text NOT NULL, version integer NOT NULL,
      ordinal integer NOT NULL CHECK(ordinal>=0), owner_domain text NOT NULL, record_id text NOT NULL,
      input_version integer NOT NULL CHECK(input_version>0), digest text NOT NULL, valid_until timestamptz,
      PRIMARY KEY(owner_user_id,recommendation_id,version,ordinal),
      UNIQUE(owner_user_id,recommendation_id,version,owner_domain,record_id),
      FOREIGN KEY(owner_user_id,recommendation_id,version) REFERENCES recommendation.records
    );
    CREATE TABLE recommendation.sources (
      owner_user_id text NOT NULL, recommendation_id text NOT NULL, version integer NOT NULL,
      ordinal integer NOT NULL CHECK(ordinal>=0), snapshot_id text NOT NULL, publisher text NOT NULL,
      excerpt text NOT NULL CHECK(length(excerpt) BETWEEN 1 AND 2048), canonical_url text NOT NULL,
      published_at timestamptz, observed_at timestamptz, retrieved_at timestamptz NOT NULL,
      PRIMARY KEY(owner_user_id,recommendation_id,version,ordinal),
      UNIQUE(owner_user_id,recommendation_id,version,snapshot_id),
      FOREIGN KEY(owner_user_id,recommendation_id,version) REFERENCES recommendation.records
    );
    CREATE TABLE recommendation.claims (
      owner_user_id text NOT NULL, recommendation_id text NOT NULL, version integer NOT NULL,
      ordinal integer NOT NULL CHECK(ordinal>=0), claim_text text NOT NULL CHECK(length(claim_text) BETWEEN 1 AND 2048),
      supporting_snapshot_ids text[] NOT NULL,
      PRIMARY KEY(owner_user_id,recommendation_id,version,ordinal),
      FOREIGN KEY(owner_user_id,recommendation_id,version) REFERENCES recommendation.records
    );
    CREATE TABLE recommendation.decisions (
      owner_user_id text NOT NULL, recommendation_id text NOT NULL, version integer NOT NULL,
      sequence integer NOT NULL CHECK(sequence>0), status text NOT NULL CHECK(status IN ('accepted','rejected','deferred','expired')),
      reason text NOT NULL CHECK(length(trim(reason))>0), recorded_at timestamptz NOT NULL,
      defer_until timestamptz, policy_version text NOT NULL,
      PRIMARY KEY(owner_user_id,recommendation_id,version,sequence),
      FOREIGN KEY(owner_user_id,recommendation_id,version) REFERENCES recommendation.records,
      CHECK((status='deferred' AND defer_until IS NOT NULL AND defer_until>recorded_at) OR (status<>'deferred' AND defer_until IS NULL))
    );
    CREATE TABLE recommendation.receipts (
      owner_user_id text NOT NULL, idempotency_key text NOT NULL, command_digest text NOT NULL,
      recommendation_id text NOT NULL, version integer NOT NULL, decision_sequence integer NOT NULL,
      PRIMARY KEY(owner_user_id,idempotency_key),
      FOREIGN KEY(owner_user_id,recommendation_id,version,decision_sequence) REFERENCES recommendation.decisions
    );
    CREATE TABLE recommendation.audit_events (
      event_id text PRIMARY KEY, owner_user_id text NOT NULL, recommendation_id text NOT NULL, version integer NOT NULL,
      action text NOT NULL, reason text NOT NULL, occurred_at timestamptz NOT NULL,
      before_sequence integer NOT NULL, after_sequence integer NOT NULL,
      correlation_id text NOT NULL, causation_id text NOT NULL, policy_version text NOT NULL, build_version text NOT NULL,
      FOREIGN KEY(owner_user_id,recommendation_id,version) REFERENCES recommendation.records
    );
    CREATE FUNCTION recommendation.reject_immutable_mutation() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable_recommendation_history'; END $$;
    """)
    for table in (
        "records",
        "input_bindings",
        "sources",
        "claims",
        "decisions",
        "receipts",
        "audit_events",
    ):
        op.execute(f"ALTER TABLE recommendation.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE recommendation.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_scope ON recommendation.{table}
          USING(owner_user_id=current_setting('app.user_id',true) AND current_setting('app.role',true)='owner')
          WITH CHECK(owner_user_id=current_setting('app.user_id',true) AND current_setting('app.role',true)='owner')""")
        op.execute(f"""CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON recommendation.{table}
          FOR EACH ROW EXECUTE FUNCTION recommendation.reject_immutable_mutation()""")
    op.execute("""
    CREATE FUNCTION recommendation.check_record_complete() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE bindings integer; sources integer; claims integer;
    BEGIN
      SELECT binding_count,source_count,claim_count INTO STRICT bindings,sources,claims
        FROM recommendation.records WHERE owner_user_id=NEW.owner_user_id
          AND recommendation_id=NEW.recommendation_id AND version=NEW.version;
      IF bindings<>(SELECT count(*) FROM recommendation.input_bindings WHERE owner_user_id=NEW.owner_user_id
            AND recommendation_id=NEW.recommendation_id AND version=NEW.version)
        OR sources<>(SELECT count(*) FROM recommendation.sources WHERE owner_user_id=NEW.owner_user_id
            AND recommendation_id=NEW.recommendation_id AND version=NEW.version)
        OR claims<>(SELECT count(*) FROM recommendation.claims WHERE owner_user_id=NEW.owner_user_id
            AND recommendation_id=NEW.recommendation_id AND version=NEW.version) THEN
        RAISE EXCEPTION 'recommendation_record_incomplete';
      END IF;
      RETURN NULL;
    END $$;
    CREATE FUNCTION recommendation.check_decision_sequence() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE previous_sequence integer; previous_status text; previous_time timestamptz; record_direction text;
    BEGIN
      SELECT direction,published_at INTO STRICT record_direction,previous_time FROM recommendation.records
        WHERE owner_user_id=NEW.owner_user_id AND recommendation_id=NEW.recommendation_id AND version=NEW.version FOR UPDATE;
      IF record_direction NOT IN ('buy','hold') THEN RAISE EXCEPTION 'nonactionable_recommendation'; END IF;
      SELECT sequence,status,recorded_at INTO previous_sequence,previous_status,previous_time FROM recommendation.decisions
        WHERE owner_user_id=NEW.owner_user_id AND recommendation_id=NEW.recommendation_id AND version=NEW.version
        ORDER BY sequence DESC LIMIT 1;
      IF NEW.sequence<>coalesce(previous_sequence,0)+1 THEN RAISE EXCEPTION 'decision_sequence_conflict'; END IF;
      IF previous_status IN ('accepted','rejected','expired') THEN RAISE EXCEPTION 'terminal_decision_immutable'; END IF;
      IF previous_time IS NOT NULL AND NEW.recorded_at<previous_time THEN RAISE EXCEPTION 'decision_time_conflict'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER decision_sequence BEFORE INSERT ON recommendation.decisions
      FOR EACH ROW EXECUTE FUNCTION recommendation.check_decision_sequence();
    """)
    for table in ("records", "input_bindings", "sources", "claims"):
        op.execute(f"""CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON recommendation.{table}
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION recommendation.check_record_complete()""")


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
