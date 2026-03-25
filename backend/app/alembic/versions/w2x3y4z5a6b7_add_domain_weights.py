"""add domain weights to SOP and feedback tables

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-03-20 20:30:00.000000

Adds domain, weight, hierarchy_weight, domain_relevance, author_position,
is_verified to sanek_sop_entries and sanek_feedback for weighted learning.
"""

from alembic import op
import sqlalchemy as sa


revision = "w2x3y4z5a6b7"
down_revision = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sanek_sop_entries ──
    op.add_column("sanek_sop_entries", sa.Column("domain", sa.String(50), nullable=True))
    op.add_column("sanek_sop_entries", sa.Column("weight", sa.Float(), server_default="0.5"))
    op.add_column("sanek_sop_entries", sa.Column("hierarchy_weight", sa.Float(), nullable=True))
    op.add_column("sanek_sop_entries", sa.Column("domain_relevance", sa.Float(), nullable=True))
    op.add_column("sanek_sop_entries", sa.Column("author_position", sa.String(255), nullable=True))
    op.add_column("sanek_sop_entries", sa.Column("is_verified", sa.Boolean(), server_default="false"))
    op.create_index("ix_sop_domain_weight", "sanek_sop_entries", ["domain", sa.text("weight DESC")])

    # ── sanek_feedback ──
    op.add_column("sanek_feedback", sa.Column("domain", sa.String(50), nullable=True))
    op.add_column("sanek_feedback", sa.Column("user_weight", sa.Float(), nullable=True))
    op.add_column("sanek_feedback", sa.Column("hierarchy_weight", sa.Float(), nullable=True))
    op.add_column("sanek_feedback", sa.Column("domain_relevance", sa.Float(), nullable=True))
    op.add_column("sanek_feedback", sa.Column("user_position", sa.String(255), nullable=True))

    # ── sanek_chat_feedback ──
    op.add_column("sanek_chat_feedback", sa.Column("domain", sa.String(50), nullable=True))
    op.add_column("sanek_chat_feedback", sa.Column("user_weight", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("sanek_chat_feedback", "user_weight")
    op.drop_column("sanek_chat_feedback", "domain")

    op.drop_column("sanek_feedback", "user_position")
    op.drop_column("sanek_feedback", "domain_relevance")
    op.drop_column("sanek_feedback", "hierarchy_weight")
    op.drop_column("sanek_feedback", "user_weight")
    op.drop_column("sanek_feedback", "domain")

    op.drop_index("ix_sop_domain_weight", "sanek_sop_entries")
    op.drop_column("sanek_sop_entries", "is_verified")
    op.drop_column("sanek_sop_entries", "author_position")
    op.drop_column("sanek_sop_entries", "domain_relevance")
    op.drop_column("sanek_sop_entries", "hierarchy_weight")
    op.drop_column("sanek_sop_entries", "weight")
    op.drop_column("sanek_sop_entries", "domain")
