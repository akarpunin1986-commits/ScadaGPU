"""add scada_rules — automation rules for SCADA

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-03-22 18:00:00.000000

Adds:
- scada_rules — automated trigger→action rules
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "y2z3a4b5c6d7"
down_revision = "x1y2z3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scada_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True, server_default="user"),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("equipment_code", sa.String(100), nullable=True),
        sa.Column("trigger_type", sa.String(30), nullable=False),
        sa.Column("trigger_config", JSONB(), nullable=True),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("action_config", JSONB(), nullable=True),
        sa.Column("executor_bitrix_id", sa.Integer(), nullable=True),
        sa.Column("executor_name", sa.String(255), nullable=True),
        sa.Column("watchers", JSONB(), nullable=True),
        sa.Column("sanek_control", sa.Boolean(), server_default="true"),
        sa.Column("sanek_control_config", JSONB(), nullable=True),
        sa.Column("times_triggered", sa.Integer(), server_default="0"),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_rules_active", "scada_rules", ["is_active"])
    op.create_index("ix_rules_trigger", "scada_rules", ["trigger_type"])
    op.create_index("ix_rules_site", "scada_rules", ["site_id"])


def downgrade() -> None:
    op.drop_table("scada_rules")
