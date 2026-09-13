"""Narrow Access-owned active-Owner lock without worker account UPDATE grants."""

from alembic import op

revision = "0023_recommendation_owner_lock"
down_revision = "0022_recommendation_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION access.lock_recommendation_owner(requested_user_id text)
    RETURNS TABLE(user_id text, role text, status text, identity_version integer)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
    BEGIN
      IF current_setting('app.user_id',true) IS DISTINCT FROM requested_user_id
         OR current_setting('app.role',true) IS DISTINCT FROM 'owner' THEN
        RETURN;
      END IF;
      RETURN QUERY SELECT u.user_id::text,u.role,u.status,u.identity_version
        FROM access.users u WHERE u.user_id::text=requested_user_id
        AND u.role='owner' AND u.status='active' FOR SHARE OF u;
    END $$;
    REVOKE ALL ON FUNCTION access.lock_recommendation_owner(text) FROM PUBLIC;
    """)


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
