"""Add feedback tables and columns.

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

revision = "u5v6w7x8y9z0"
down_revision = "t4u5v6w7x8y9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- sanek_feedback ---
    op.create_table(
        "sanek_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("agent_incidents.id"), nullable=False),
        sa.Column("assessment", sa.String(20), nullable=False),
        sa.Column("actual_root_cause", sa.Text(), nullable=True),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("incident_id", name="unique_feedback_per_incident"),
    )
    op.create_index("idx_sanek_feedback_incident", "sanek_feedback", ["incident_id"])
    op.create_index("idx_sanek_feedback_assessment", "sanek_feedback", ["assessment"])
    op.create_index("idx_sanek_feedback_created", "sanek_feedback", ["created_at"])

    # --- sanek_pattern_stats ---
    op.create_table(
        "sanek_pattern_stats",
        sa.Column("pattern_id", sa.String(50), primary_key=True),
        sa.Column("correct_count", sa.Integer(), server_default="0"),
        sa.Column("total_count", sa.Integer(), server_default="0"),
        sa.Column("last_confirmed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_incorrect", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- agent_incidents: new columns ---
    op.add_column(
        "agent_incidents",
        sa.Column("feedback_status", sa.String(20), server_default="pending"),
    )
    op.add_column(
        "agent_incidents",
        sa.Column("correlation_pattern_id", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_incidents", "correlation_pattern_id")
    op.drop_column("agent_incidents", "feedback_status")
    op.drop_table("sanek_pattern_stats")
    op.drop_table("sanek_feedback")
