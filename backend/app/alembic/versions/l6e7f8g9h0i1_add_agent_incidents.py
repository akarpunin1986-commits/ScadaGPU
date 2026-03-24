"""add_agent_incidents

Revision ID: l6e7f8g9h0i1
Revises: k5d6e7f8g9h0
Create Date: 2026-03-08 12:00:00.000000

SanekAgent autonomous incident analysis results.
Stores trigger info, collected data, LLM analysis and recommendations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'l6e7f8g9h0i1'
down_revision: Union[str, None] = 'k5d6e7f8g9h0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_incidents',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('device_id', sa.Integer(),
                  sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('site_id', sa.Integer(),
                  sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=True),
        sa.Column('alarm_code', sa.String(50), nullable=False),
        sa.Column('trigger_channel', sa.String(50), nullable=False),
        sa.Column('trigger_payload', JSONB, nullable=True),
        sa.Column('analysis', JSONB, nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('llm_provider', sa.String(20), nullable=True),
        sa.Column('llm_model', sa.String(100), nullable=True),
        sa.Column('llm_tokens_used', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_agent_incidents_device_id', 'agent_incidents', ['device_id'])
    op.create_index('ix_agent_incidents_site_id', 'agent_incidents', ['site_id'])
    op.create_index('ix_agent_incidents_created_at', 'agent_incidents', ['created_at'])
    op.create_index('ix_agent_incidents_status', 'agent_incidents', ['status'])


def downgrade() -> None:
    op.drop_table('agent_incidents')
