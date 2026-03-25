"""Add clarification columns to agent_incidents.

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

revision = "t4u5v6w7x8y9"
down_revision = "s3t4u5v6w7x8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_incidents",
        sa.Column("clarification_question", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_incidents",
        sa.Column("clarification_answer", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_incidents",
        sa.Column("clarification_asked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_incidents",
        sa.Column("clarification_answered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_incidents",
        sa.Column("preliminary_diagnosis", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_incidents",
        sa.Column("preliminary_confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_incidents", "preliminary_confidence")
    op.drop_column("agent_incidents", "preliminary_diagnosis")
    op.drop_column("agent_incidents", "clarification_answered_at")
    op.drop_column("agent_incidents", "clarification_asked_at")
    op.drop_column("agent_incidents", "clarification_answer")
    op.drop_column("agent_incidents", "clarification_question")
