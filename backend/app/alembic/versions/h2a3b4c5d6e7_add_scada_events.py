"""add_scada_events

Revision ID: h2a3b4c5d6e7
Revises: g1a2b3c4d5e6
Create Date: 2026-02-27 18:00:00.000000

Event journal for SCADA: tracks gen_status, mode, ATS, mains, operator commands, system events.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


revision: str = 'h2a3b4c5d6e7'
down_revision: Union[str, None] = 'g1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scada_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('device_id', sa.Integer(),
                  sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.String(20), nullable=False),
        sa.Column('event_code', sa.String(40), nullable=False),
        sa.Column('message', sa.String(300), nullable=False),
        sa.Column('old_value', sa.String(60), nullable=True),
        sa.Column('new_value', sa.String(60), nullable=True),
        sa.Column('details', JSON, nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_scada_events_device_created', 'scada_events', ['device_id', 'created_at'])
    op.create_index('ix_scada_events_category', 'scada_events', ['category'])
    op.create_index('ix_scada_events_created', 'scada_events', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_scada_events_created', table_name='scada_events')
    op.drop_index('ix_scada_events_category', table_name='scada_events')
    op.drop_index('ix_scada_events_device_created', table_name='scada_events')
    op.drop_table('scada_events')
