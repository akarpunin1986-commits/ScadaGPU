"""add_ai_chat_messages

Revision ID: f9b2c3d4e5f6
Revises: e8a1b2c3d4f5
Create Date: 2026-02-23 14:00:00.000000

Phase 5.2: AI chat history table for Sanek assistant.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9b2c3d4e5f6'
down_revision: Union[str, None] = 'e8a1b2c3d4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_chat_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.String(50), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), server_default='', nullable=False),
        sa.Column('tool_calls', sa.Text(), nullable=True),
        sa.Column('tool_name', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_chat_messages')),
    )
    op.create_index('ix_ai_chat_session', 'ai_chat_messages', ['session_id'])
    op.create_index('ix_ai_chat_created', 'ai_chat_messages', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_ai_chat_created', table_name='ai_chat_messages')
    op.drop_index('ix_ai_chat_session', table_name='ai_chat_messages')
    op.drop_table('ai_chat_messages')
