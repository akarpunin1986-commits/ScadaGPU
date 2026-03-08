"""add sop_actions column to agent_incidents

Revision ID: o9h0i1j2k3l4
Revises: n8g9h0i1j2k3
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "o9h0i1j2k3l4"
down_revision = "n8g9h0i1j2k3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_incidents", sa.Column("sop_actions", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_incidents", "sop_actions")
