"""add self-learning tables (SOP entries, chat feedback, session memory)

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-03-18 14:00:00.000000

Adds:
- sanek_sop_entries — experience-based SOP from solved incidents
- sanek_chat_feedback — operator thumbs up/down per message
- sanek_session_memory — cross-session context summaries
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY


revision = "u6v7w8x9y0z1"
down_revision = "t5u6v7w8x9y0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── SOP Entries ──
    op.create_table(
        "sanek_sop_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("incident_type", sa.String(64), nullable=False),
        sa.Column("device_id", sa.String(32), nullable=True),
        sa.Column("site_code", sa.String(8), nullable=True),
        sa.Column("alarm_code", sa.String(64), nullable=True),
        sa.Column("symptoms", JSONB, nullable=False, server_default="{}"),
        sa.Column("diagnosis", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("resolution_time_minutes", sa.Integer(), nullable=True),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("conversation_id", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("times_referenced", sa.Integer(), server_default="0"),
        sa.Column("last_referenced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(32), server_default="'dialog'"),
    )
    op.create_index("idx_sop_entry_incident", "sanek_sop_entries", ["incident_type"])
    op.create_index("idx_sop_entry_device", "sanek_sop_entries", ["device_id"])
    op.create_index("idx_sop_entry_alarm", "sanek_sop_entries", ["alarm_code"])
    op.create_index("idx_sop_entry_confidence", "sanek_sop_entries", ["confidence"])

    # ── Chat Feedback ──
    op.create_table(
        "sanek_chat_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("message_index", sa.Integer(), nullable=False),
        sa.Column("rating", sa.String(4), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("user_question", sa.Text(), nullable=True),
        sa.Column("sanek_answer_preview", sa.Text(), nullable=True),
        sa.Column("tools_used", JSONB, nullable=True),
        sa.Column("sop_referenced", ARRAY(sa.Integer()), nullable=True),
        sa.Column("processed", sa.Boolean(), server_default="false"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_chat_fb_session", "sanek_chat_feedback", ["session_id"])
    op.create_index("idx_chat_fb_rating", "sanek_chat_feedback", ["rating"])
    op.create_index("idx_chat_fb_processed", "sanek_chat_feedback", ["processed"])

    # ── Session Memory ──
    op.create_table(
        "sanek_session_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("session_id", sa.String(64), nullable=False, unique=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("key_facts", JSONB, nullable=True),
        sa.Column("importance", sa.Float(), server_default="0.5"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_sess_mem_importance", "sanek_session_memory", ["importance"])
    op.create_index("idx_sess_mem_created", "sanek_session_memory", ["created_at"])


def downgrade() -> None:
    op.drop_table("sanek_session_memory")
    op.drop_table("sanek_chat_feedback")
    op.drop_table("sanek_sop_entries")
