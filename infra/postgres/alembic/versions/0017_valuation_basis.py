"""Preserve analytical basis without reconstructing immutable legacy history."""

from alembic import op
import sqlalchemy as sa


revision = "0017_valuation_basis"
down_revision = "0016_recommendation_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("valuation_drafts", "valuation_snapshots"):
        op.add_column(
            name, sa.Column("basis_date", sa.Date(), nullable=True), schema="thesis"
        )
        op.add_column(
            name,
            sa.Column("horizon_months", sa.Integer(), nullable=True),
            schema="thesis",
        )
        op.create_check_constraint(
            f"{name}_basis_pair",
            name,
            "(basis_date IS NULL AND horizon_months IS NULL) OR "
            "(basis_date IS NOT NULL AND horizon_months IS NOT NULL AND horizon_months IN (6,12,24) AND target_date > basis_date)",
            schema="thesis",
        )


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
