"""Freeze provider context and source lineage; retain explicit legacy absence."""

from alembic import op

revision = "0022_recommendation_context"
down_revision = "0021_recommendation_post_risk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("records", "admissions"):
        op.execute(
            f"ALTER TABLE recommendation.{table} ADD COLUMN analysis_context jsonb CHECK(analysis_context IS NULL OR jsonb_typeof(analysis_context)='array')"
        )
    for table in ("sources", "admission_sources"):
        op.execute(
            f"ALTER TABLE recommendation.{table} ADD COLUMN source_category text CHECK(source_category IN ('A','B','C')), ADD COLUMN lineage text"
        )


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
