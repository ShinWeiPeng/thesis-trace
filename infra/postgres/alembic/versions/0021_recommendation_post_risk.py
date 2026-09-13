"""Retain selected post-transaction exposure without rewriting old snapshots."""

from alembic import op

revision = "0021_recommendation_post_risk"
down_revision = "0020_recommendation_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE portfolio.recommendation_snapshots
      ADD COLUMN post_nav numeric,
      ADD COLUMN post_feasible boolean,
      ADD COLUMN post_exposure_reasons text[],
      ADD COLUMN post_exposure_policy_version text,
      ADD COLUMN purchase_outflow numeric,
      ADD COLUMN acquired_quantity numeric,
      ADD CONSTRAINT projected_result_complete CHECK(
        (post_nav IS NULL AND post_feasible IS NULL AND post_exposure_reasons IS NULL
          AND post_exposure_policy_version IS NULL AND purchase_outflow IS NULL AND acquired_quantity IS NULL)
        OR (post_nav IS NOT NULL AND post_feasible IS NOT NULL AND post_exposure_reasons IS NOT NULL
          AND post_exposure_policy_version IS NOT NULL AND purchase_outflow IS NOT NULL AND acquired_quantity IS NOT NULL));
    ALTER TABLE portfolio.recommendation_exposures DROP CONSTRAINT recommendation_exposures_kind_check;
    ALTER TABLE portfolio.recommendation_exposures ADD CONSTRAINT recommendation_exposures_kind_check
      CHECK(kind IN ('security','industry','theme','post_security','post_industry','post_theme'));
    """)


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
