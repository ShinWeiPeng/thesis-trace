"""Preserve decision-time source checks and exact Access audit correlation."""

from alembic import op

revision = "0025_recommendation_trace"
down_revision = "0024_recommendation_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE recommendation.decisions
      ADD COLUMN input_checks jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK(jsonb_typeof(input_checks)='array' AND octet_length(input_checks::text)<=262144),
      ADD COLUMN confirmation_id text;
    """)


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
