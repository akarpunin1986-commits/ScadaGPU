"""add auth module (users, codes, activity, dept mapping, user_id FKs)

Revision ID: v1w2x3y4z5a6
Revises: u6v7w8x9y0z1
Create Date: 2026-03-20 12:00:00.000000

Adds:
- scada_users — users with Bitrix24 binding, RBAC, hierarchy
- auth_codes — one-time login codes (Phase 1)
- user_activity_log — action journal
- department_role_mapping — dept → default role
- ALTER TABLE: user_id + source columns on existing tables
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "v1w2x3y4z5a6"
down_revision = "u6v7w8x9y0z1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── scada_users ──
    op.create_table(
        "scada_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bitrix_id", sa.Integer(), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.String(255), nullable=True),
        sa.Column("is_department_head", sa.Boolean(), server_default="false"),
        sa.Column("manager_bitrix_id", sa.Integer(), nullable=True),
        sa.Column("hierarchy_level", sa.Integer(), server_default="5"),
        sa.Column("user_weight", sa.Float(), server_default="0.3"),
        sa.Column("bitrix_access_token", sa.Text(), nullable=True),
        sa.Column("bitrix_refresh_token", sa.Text(), nullable=True),
        sa.Column("bitrix_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_scada_users_bitrix_id", "scada_users", ["bitrix_id"], unique=True)
    op.create_index("ix_scada_users_email", "scada_users", ["email"], unique=True)

    # ── auth_codes ──
    op.create_table(
        "auth_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("scada_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("is_used", sa.Boolean(), server_default="false"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_auth_codes_user", "auth_codes", ["user_id", "is_used", "expires_at"])

    # ── user_activity_log ──
    op.create_table(
        "user_activity_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("scada_users.id"), nullable=True),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("target_device_id", sa.Integer(), sa.ForeignKey("devices.id"), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("source", sa.String(20), server_default="scada"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_activity_user", "user_activity_log", ["user_id", "created_at"])
    op.create_index("ix_activity_action", "user_activity_log", ["action", "created_at"])

    # ── department_role_mapping ──
    op.create_table(
        "department_role_mapping",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("department_id", sa.Integer(), unique=True, nullable=False),
        sa.Column("department_name", sa.String(255), nullable=True),
        sa.Column("default_role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── ALTER existing tables: add user_id + source ──

    # ai_chat_messages
    op.add_column("ai_chat_messages", sa.Column("user_id", sa.Integer(), sa.ForeignKey("scada_users.id"), nullable=True))
    op.add_column("ai_chat_messages", sa.Column("source", sa.String(20), server_default="scada"))
    op.create_index("ix_chat_messages_user", "ai_chat_messages", ["user_id"])

    # sanek_session_memory
    op.add_column("sanek_session_memory", sa.Column("user_id", sa.Integer(), sa.ForeignKey("scada_users.id"), nullable=True))
    op.create_index("ix_session_memory_user", "sanek_session_memory", ["user_id"])

    # scada_events
    op.add_column("scada_events", sa.Column("user_id", sa.Integer(), sa.ForeignKey("scada_users.id"), nullable=True))

    # sanek_feedback
    op.add_column("sanek_feedback", sa.Column("user_id", sa.Integer(), sa.ForeignKey("scada_users.id"), nullable=True))

    # sanek_chat_feedback
    op.add_column("sanek_chat_feedback", sa.Column("user_id", sa.Integer(), sa.ForeignKey("scada_users.id"), nullable=True))


def downgrade() -> None:
    # Remove added columns
    op.drop_column("sanek_chat_feedback", "user_id")
    op.drop_column("sanek_feedback", "user_id")
    op.drop_column("scada_events", "user_id")
    op.drop_index("ix_session_memory_user", "sanek_session_memory")
    op.drop_column("sanek_session_memory", "user_id")
    op.drop_index("ix_chat_messages_user", "ai_chat_messages")
    op.drop_column("ai_chat_messages", "source")
    op.drop_column("ai_chat_messages", "user_id")

    # Drop tables
    op.drop_table("department_role_mapping")
    op.drop_table("user_activity_log")
    op.drop_table("auth_codes")
    op.drop_table("scada_users")
