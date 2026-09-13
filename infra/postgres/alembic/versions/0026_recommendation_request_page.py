"""Stable Owner/company request pagination without hydrating frozen inputs."""

from alembic import op

revision = "0026_recommendation_page"
down_revision = "0025_recommendation_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX recommendation_request_page ON recommendation.admissions(owner_user_id,company_id,admitted_at DESC,input_id DESC)"
    )


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
