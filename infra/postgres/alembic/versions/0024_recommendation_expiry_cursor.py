"""Indexed unfinalized projection and worker-only durable expiry cursor."""

from alembic import op

revision = "0024_recommendation_expiry"
down_revision = "0023_recommendation_owner_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE recommendation.expiry_candidates (
      owner_user_id text NOT NULL, recommendation_id text NOT NULL, version integer NOT NULL,
      PRIMARY KEY(owner_user_id,recommendation_id,version),
      FOREIGN KEY(owner_user_id,recommendation_id,version)
        REFERENCES recommendation.records(owner_user_id,recommendation_id,version)
    );
    CREATE TABLE recommendation.expiry_cursor (
      singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
      owner_user_id text NOT NULL DEFAULT '', recommendation_id text NOT NULL DEFAULT '',
      version integer NOT NULL DEFAULT 0 CHECK(version>=0)
    );
    INSERT INTO recommendation.expiry_cursor(singleton) VALUES(true);
    INSERT INTO recommendation.expiry_candidates
      SELECT r.owner_user_id,r.recommendation_id,r.version FROM recommendation.records r
      WHERE r.direction IN ('buy','hold') AND NOT EXISTS (
        SELECT 1 FROM recommendation.decisions d WHERE d.owner_user_id=r.owner_user_id
        AND d.recommendation_id=r.recommendation_id AND d.version=r.version
        AND d.status IN ('accepted','rejected','expired'));
    CREATE FUNCTION recommendation.add_expiry_candidate() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
      IF NEW.direction IN ('buy','hold') THEN
        INSERT INTO recommendation.expiry_candidates(owner_user_id,recommendation_id,version)
          VALUES(NEW.owner_user_id,NEW.recommendation_id,NEW.version);
      END IF;
      RETURN NULL;
    END $$;
    CREATE FUNCTION recommendation.resolve_expiry_candidate() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
      IF NEW.status IN ('accepted','rejected','expired') THEN
        DELETE FROM recommendation.expiry_candidates WHERE owner_user_id=NEW.owner_user_id
          AND recommendation_id=NEW.recommendation_id AND version=NEW.version;
      END IF;
      RETURN NULL;
    END $$;
    CREATE TRIGGER record_expiry_candidate AFTER INSERT ON recommendation.records
      FOR EACH ROW EXECUTE FUNCTION recommendation.add_expiry_candidate();
    CREATE TRIGGER decision_expiry_candidate AFTER INSERT ON recommendation.decisions
      FOR EACH ROW EXECUTE FUNCTION recommendation.resolve_expiry_candidate();
    CREATE FUNCTION recommendation.next_expiry_candidate()
    RETURNS TABLE(owner_id text,record_id text,record_version integer,decision_sequence integer)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    DECLARE cursor_row recommendation.expiry_cursor%ROWTYPE;
      candidate recommendation.expiry_candidates%ROWTYPE;
    BEGIN
      SELECT * INTO STRICT cursor_row FROM recommendation.expiry_cursor WHERE singleton FOR UPDATE;
      SELECT * INTO candidate FROM recommendation.expiry_candidates c
        WHERE (c.owner_user_id,c.recommendation_id,c.version)>
          (cursor_row.owner_user_id,cursor_row.recommendation_id,cursor_row.version)
        ORDER BY c.owner_user_id,c.recommendation_id,c.version LIMIT 1;
      IF NOT FOUND THEN
        SELECT * INTO candidate FROM recommendation.expiry_candidates c
          ORDER BY c.owner_user_id,c.recommendation_id,c.version LIMIT 1;
      END IF;
      IF NOT FOUND THEN RETURN; END IF;
      UPDATE recommendation.expiry_cursor SET owner_user_id=candidate.owner_user_id,
        recommendation_id=candidate.recommendation_id,version=candidate.version WHERE singleton;
      RETURN QUERY SELECT candidate.owner_user_id,candidate.recommendation_id,candidate.version,
        COALESCE((SELECT d.sequence FROM recommendation.decisions d
          WHERE d.owner_user_id=candidate.owner_user_id AND d.recommendation_id=candidate.recommendation_id
          AND d.version=candidate.version ORDER BY d.sequence DESC LIMIT 1),0);
    END $$;
    REVOKE ALL ON recommendation.expiry_candidates,recommendation.expiry_cursor FROM PUBLIC;
    REVOKE ALL ON FUNCTION recommendation.add_expiry_candidate(),recommendation.resolve_expiry_candidate(),
      recommendation.next_expiry_candidate() FROM PUBLIC;
    """)


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
