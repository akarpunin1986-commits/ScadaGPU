"""add_ai_provider_configs

Revision ID: e8a1b2c3d4f5
Revises: d7f2a3b4c5e6
Create Date: 2026-02-23 12:00:00.000000

Phase 5.1: Persistent multi-provider AI config — ai_provider_configs table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8a1b2c3d4f5'
down_revision: Union[str, None] = 'd7f2a3b4c5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_provider_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False),
        sa.Column('api_key', sa.Text(), server_default='', nullable=False),
        sa.Column('model', sa.String(100), server_default='', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_configured', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_provider_configs')),
        sa.UniqueConstraint('provider', name=op.f('uq_ai_provider_configs_provider')),
    )


def downgrade() -> None:
    op.drop_table('ai_provider_configs')
