"""Admit source-bound Recommendation tasks without changing anomaly history."""

from alembic import op


revision = "0016_recommendation_workflow"
down_revision = "0015_normalized_thesis_portfolio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "action_items_item_type_check", "action_items", schema="workflow", type_="check"
    )
    op.create_check_constraint(
        "action_items_item_type_check",
        "action_items",
        "item_type IN ('anomaly_review','recommendation_decision')",
        schema="workflow",
    )
    op.execute("""CREATE UNIQUE INDEX workflow_recommendation_source_version
        ON workflow.action_items(assignee_user_id,source_domain,source_record_id,source_version)
        WHERE item_type='recommendation_decision'""")


def downgrade() -> None:
    raise RuntimeError("forward_only_migration")
