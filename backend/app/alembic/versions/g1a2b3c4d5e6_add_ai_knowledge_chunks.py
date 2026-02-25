"""add_ai_knowledge_chunks

Revision ID: g1a2b3c4d5e6
Revises: f9b2c3d4e5f6
Create Date: 2026-02-25 12:00:00.000000

Knowledge base for SmartGen manuals — chunked text storage.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g1a2b3c4d5e6'
down_revision: Union[str, None] = 'f9b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_knowledge_chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source_filename', sa.String(500), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_knowledge_chunks')),
    )
    op.create_index('ix_ai_knowledge_category', 'ai_knowledge_chunks', ['category'])
    op.create_index('ix_ai_knowledge_source', 'ai_knowledge_chunks', ['source_filename'])


def downgrade() -> None:
    op.drop_index('ix_ai_knowledge_source', table_name='ai_knowledge_chunks')
    op.drop_index('ix_ai_knowledge_category', table_name='ai_knowledge_chunks')
    op.drop_table('ai_knowledge_chunks')
