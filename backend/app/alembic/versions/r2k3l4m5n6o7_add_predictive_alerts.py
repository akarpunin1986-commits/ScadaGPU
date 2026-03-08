"""Add predictive alerts table.

Revision ID: r2k3l4m5n6o7
Revises: q1j2k3l4m5n6
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "r2k3l4m5n6o7"
down_revision = "q1j2k3l4m5n6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sanek_predictive_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id"), nullable=True),
        sa.Column("metric_name", sa.String(50), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("predicted_value", sa.Float(), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("time_to_breach_min", sa.Float(), nullable=False),
        sa.Column("trend_slope", sa.Float(), nullable=False),
        sa.Column("r_squared", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_sanek_pred_device", "sanek_predictive_alerts", ["device_id"])
    op.create_index("ix_sanek_pred_status", "sanek_predictive_alerts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_sanek_pred_status", table_name="sanek_predictive_alerts")
    op.drop_index("ix_sanek_pred_device", table_name="sanek_predictive_alerts")
    op.drop_table("sanek_predictive_alerts")
