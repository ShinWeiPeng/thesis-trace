"""Bounded typed Recommendation queue with immutable admissions and fenced leases."""

from alembic import op

revision = "0020_recommendation_jobs"
down_revision = "0019_recommendation_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE recommendation.records ADD CONSTRAINT finite_returns CHECK(
      (annualized_return IS NULL OR annualized_return NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)) AND
      (minimum_return IS NULL OR minimum_return NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)));
    CREATE OR REPLACE FUNCTION recommendation.check_decision_sequence() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE previous_sequence integer; previous_status text; previous_time timestamptz;
      published_time timestamptz; record_direction text;
    BEGIN
      SELECT direction,published_at INTO STRICT record_direction,published_time FROM recommendation.records
        WHERE owner_user_id=NEW.owner_user_id AND recommendation_id=NEW.recommendation_id AND version=NEW.version FOR UPDATE;
      IF record_direction NOT IN ('buy','hold') THEN RAISE EXCEPTION 'nonactionable_recommendation'; END IF;
      SELECT sequence,status,recorded_at INTO previous_sequence,previous_status,previous_time FROM recommendation.decisions
        WHERE owner_user_id=NEW.owner_user_id AND recommendation_id=NEW.recommendation_id AND version=NEW.version
        ORDER BY sequence DESC LIMIT 1;
      IF NEW.sequence<>coalesce(previous_sequence,0)+1 THEN RAISE EXCEPTION 'decision_sequence_conflict'; END IF;
      IF previous_status IN ('accepted','rejected','expired') THEN RAISE EXCEPTION 'terminal_decision_immutable'; END IF;
      IF NEW.recorded_at<coalesce(previous_time,published_time) THEN RAISE EXCEPTION 'decision_time_conflict'; END IF;
      RETURN NEW;
    END $$;
    CREATE TABLE recommendation.admissions (
      owner_user_id text NOT NULL, input_id text NOT NULL, thesis_id text NOT NULL, cycle integer NOT NULL CHECK(cycle>0),
      company_id text NOT NULL, valuation_id text NOT NULL, portfolio_snapshot_id text,
      source_selection_reason text NOT NULL, benchmark_source text NOT NULL CHECK(benchmark_source IN ('company_history','peer_group','abstain')),
      gate_reasons text[] NOT NULL, admitted_at timestamptz NOT NULL, input_digest text NOT NULL,
      versions jsonb NOT NULL CHECK(jsonb_typeof(versions)='array'),
      idempotency_key text NOT NULL, command_digest text NOT NULL,
      binding_count integer NOT NULL CHECK(binding_count>0), source_count integer NOT NULL CHECK(source_count BETWEEN 1 AND 32),
      PRIMARY KEY(owner_user_id,input_id), UNIQUE(owner_user_id,idempotency_key),
      UNIQUE(owner_user_id,input_id,thesis_id,cycle)
    );
    CREATE TABLE recommendation.admission_bindings (
      owner_user_id text NOT NULL, input_id text NOT NULL, ordinal integer NOT NULL CHECK(ordinal>=0),
      owner_domain text NOT NULL, record_id text NOT NULL, version integer NOT NULL CHECK(version>0),
      digest text NOT NULL, valid_until timestamptz,
      PRIMARY KEY(owner_user_id,input_id,ordinal), UNIQUE(owner_user_id,input_id,owner_domain,record_id),
      FOREIGN KEY(owner_user_id,input_id) REFERENCES recommendation.admissions
    );
    CREATE TABLE recommendation.admission_sources (
      owner_user_id text NOT NULL, input_id text NOT NULL, ordinal integer NOT NULL CHECK(ordinal>=0),
      snapshot_id text NOT NULL, publisher text NOT NULL, excerpt text NOT NULL CHECK(length(excerpt) BETWEEN 1 AND 2048),
      canonical_url text NOT NULL, published_at timestamptz, observed_at timestamptz, retrieved_at timestamptz NOT NULL,
      PRIMARY KEY(owner_user_id,input_id,ordinal), UNIQUE(owner_user_id,input_id,snapshot_id),
      FOREIGN KEY(owner_user_id,input_id) REFERENCES recommendation.admissions
    );
    CREATE TABLE recommendation.jobs (
      job_id text PRIMARY KEY, owner_user_id text NOT NULL, input_id text NOT NULL, thesis_id text NOT NULL, cycle integer NOT NULL,
      kind text NOT NULL DEFAULT 'recommendation-analysis-v1' CHECK(kind='recommendation-analysis-v1'),
      state text NOT NULL CHECK(state IN ('pending','processing','retrying','succeeded','failed','dead_letter')),
      attempt integer NOT NULL CHECK(attempt BETWEEN 0 AND 3), lease_token text, lease_expires_at timestamptz,
      available_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, error_code text,
      UNIQUE(owner_user_id,input_id),
      FOREIGN KEY(owner_user_id,input_id,thesis_id,cycle) REFERENCES recommendation.admissions(owner_user_id,input_id,thesis_id,cycle),
      CHECK((state='processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND attempt>0)
        OR (state<>'processing' AND lease_token IS NULL AND lease_expires_at IS NULL))
    );
    CREATE INDEX jobs_available ON recommendation.jobs(available_at,job_id) WHERE state IN ('pending','retrying','processing');
    CREATE UNIQUE INDEX jobs_processing_stream ON recommendation.jobs(owner_user_id,thesis_id,cycle) WHERE state='processing';
    CREATE TABLE recommendation.admission_events (
      event_id text PRIMARY KEY, owner_user_id text NOT NULL, input_id text NOT NULL, job_id text NOT NULL,
      action text NOT NULL, occurred_at timestamptz NOT NULL, attempt integer NOT NULL, error_code text,
      FOREIGN KEY(owner_user_id,input_id) REFERENCES recommendation.admissions
    );
    CREATE TABLE recommendation.queue_capacity (
      singleton boolean PRIMARY KEY CHECK(singleton), live_count integer NOT NULL CHECK(live_count BETWEEN 0 AND 1000)
    );
    INSERT INTO recommendation.queue_capacity VALUES(true,0);
    ALTER TABLE recommendation.queue_capacity ENABLE ROW LEVEL SECURITY;
    ALTER TABLE recommendation.queue_capacity FORCE ROW LEVEL SECURITY;
    CREATE POLICY capacity_owner ON recommendation.queue_capacity USING(true) WITH CHECK(true);
    REVOKE ALL ON recommendation.queue_capacity FROM PUBLIC;
    CREATE FUNCTION recommendation.enforce_queue_capacity() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE delta integer;
    BEGIN
      delta := CASE WHEN NEW.state IN ('pending','processing','retrying') THEN 1 ELSE 0 END;
      IF TG_OP='UPDATE' THEN delta := delta-CASE WHEN OLD.state IN ('pending','processing','retrying') THEN 1 ELSE 0 END; END IF;
      IF delta=1 THEN
        UPDATE recommendation.queue_capacity SET live_count=live_count+1 WHERE singleton AND live_count<1000;
        IF NOT FOUND THEN RAISE EXCEPTION 'recommendation_queue_full'; END IF;
      ELSIF delta=-1 THEN
        UPDATE recommendation.queue_capacity SET live_count=live_count-1 WHERE singleton;
      END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION recommendation.enforce_queue_capacity() FROM PUBLIC;
    CREATE TRIGGER jobs_capacity BEFORE INSERT OR UPDATE ON recommendation.jobs
      FOR EACH ROW EXECUTE FUNCTION recommendation.enforce_queue_capacity();
    CREATE FUNCTION recommendation.guard_job_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable_job_history'; END IF;
      IF ROW(OLD.job_id,OLD.owner_user_id,OLD.input_id,OLD.thesis_id,OLD.cycle,OLD.kind)
        IS DISTINCT FROM ROW(NEW.job_id,NEW.owner_user_id,NEW.input_id,NEW.thesis_id,NEW.cycle,NEW.kind)
        OR NEW.attempt<OLD.attempt OR (OLD.state IN ('succeeded','failed','dead_letter') AND NEW IS DISTINCT FROM OLD) THEN
        RAISE EXCEPTION 'immutable_job_history';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER jobs_history BEFORE UPDATE OR DELETE ON recommendation.jobs
      FOR EACH ROW EXECUTE FUNCTION recommendation.guard_job_history();
    CREATE FUNCTION recommendation.record_job_event() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='INSERT' OR ROW(NEW.state,NEW.attempt) IS DISTINCT FROM ROW(OLD.state,OLD.attempt) THEN
        INSERT INTO recommendation.admission_events(event_id,owner_user_id,input_id,job_id,action,occurred_at,attempt,error_code)
          VALUES(gen_random_uuid()::text,NEW.owner_user_id,NEW.input_id,NEW.job_id,NEW.state,clock_timestamp(),NEW.attempt,NEW.error_code);
      END IF;
      RETURN NULL;
    END $$;
    CREATE TRIGGER jobs_events AFTER INSERT OR UPDATE ON recommendation.jobs
      FOR EACH ROW EXECUTE FUNCTION recommendation.record_job_event();
    """)
    for table in (
        "admissions",
        "admission_bindings",
        "admission_sources",
        "admission_events",
        "jobs",
    ):
        op.execute(f"ALTER TABLE recommendation.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE recommendation.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_scope ON recommendation.{table}
          USING(current_user='thesis_trace_ai_worker' OR (owner_user_id=current_setting('app.user_id',true) AND current_setting('app.role',true)='owner'))
          WITH CHECK(current_user='thesis_trace_ai_worker' OR (owner_user_id=current_setting('app.user_id',true) AND current_setting('app.role',true)='owner'))""")
        if table != "jobs":
            op.execute(f"""CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON recommendation.{table}
              FOR EACH ROW EXECUTE FUNCTION recommendation.reject_immutable_mutation()""")
    op.execute("""
    CREATE FUNCTION recommendation.check_admission_complete() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE bindings integer; sources integer;
    BEGIN
      SELECT binding_count,source_count INTO STRICT bindings,sources FROM recommendation.admissions
        WHERE owner_user_id=NEW.owner_user_id AND input_id=NEW.input_id;
      IF bindings<>(SELECT count(*) FROM recommendation.admission_bindings WHERE owner_user_id=NEW.owner_user_id AND input_id=NEW.input_id)
        OR sources<>(SELECT count(*) FROM recommendation.admission_sources WHERE owner_user_id=NEW.owner_user_id AND input_id=NEW.input_id)
        OR 1<>(SELECT count(*) FROM recommendation.jobs WHERE owner_user_id=NEW.owner_user_id AND input_id=NEW.input_id) THEN
        RAISE EXCEPTION 'recommendation_admission_incomplete';
      END IF;
      RETURN NULL;
    END $$;
    """)
    for table in ("admissions", "admission_bindings", "admission_sources"):
        op.execute(f"""CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON recommendation.{table}
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION recommendation.check_admission_complete()""")


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
