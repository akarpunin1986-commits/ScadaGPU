"""add_sanek_memory

Revision ID: p1q2r3s4t5u6
Revises: u5v6w7x8y9z0
Create Date: 2026-03-09 16:00:00.000000

Persistent memory for Sanek AI assistant.
Stores user instructions, facts, preferences.
user_id nullable for now — per-user when auth is added.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'p1q2r3s4t5u6'
down_revision: Union[str, None] = 'u5v6w7x8y9z0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sanek_memory',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(100), nullable=True),
        sa.Column('category', sa.String(30), nullable=False, server_default='instruction'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source', sa.String(50), nullable=True),
        sa.Column('session_id', sa.String(50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_sanek_memory_user_id', 'sanek_memory', ['user_id'])
    op.create_index('ix_sanek_memory_category', 'sanek_memory', ['category'])
    op.create_index('ix_sanek_memory_active', 'sanek_memory', ['is_active'])


def downgrade() -> None:
    op.drop_index('ix_sanek_memory_active')
    op.drop_index('ix_sanek_memory_category')
    op.drop_index('ix_sanek_memory_user_id')
    op.drop_table('sanek_memory')
