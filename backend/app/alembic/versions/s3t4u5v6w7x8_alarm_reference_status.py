"""Add status and source columns to sanek_alarm_reference.

Revision ID: s3t4u5v6w7x8
Revises: r2k3l4m5n6o7
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "s3t4u5v6w7x8"
down_revision = "r2k3l4m5n6o7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sanek_alarm_reference",
        sa.Column("status", sa.String(20), server_default="confirmed", nullable=False),
    )
    op.add_column(
        "sanek_alarm_reference",
        sa.Column("source", sa.String(50), server_default="manual_seed", nullable=False),
    )
    op.add_column(
        "sanek_alarm_reference",
        sa.Column("extracted_from", sa.String(200), nullable=True),
    )
    op.execute("UPDATE sanek_alarm_reference SET status='confirmed', source='manual_seed'")


def downgrade() -> None:
    op.drop_column("sanek_alarm_reference", "extracted_from")
    op.drop_column("sanek_alarm_reference", "source")
    op.drop_column("sanek_alarm_reference", "status")
