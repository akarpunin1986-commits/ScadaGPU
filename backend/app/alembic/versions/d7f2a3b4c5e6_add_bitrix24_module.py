"""add_bitrix24_module

Revision ID: d7f2a3b4c5e6
Revises: c5e9f2a81b34
Create Date: 2026-02-22 18:00:00.000000

Phase 7: Bitrix24 integration — bitrix24_tasks table + devices.system_code.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7f2a3b4c5e6'
down_revision: Union[str, None] = 'c5e9f2a81b34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add system_code to devices (nullable — no data migration needed)
    op.add_column('devices', sa.Column('system_code', sa.String(50), nullable=True))

    # Create bitrix24_tasks table
    op.create_table(
        'bitrix24_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bitrix_task_id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(30), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=True),
        sa.Column('system_code', sa.String(50), nullable=True),
        sa.Column('task_title', sa.String(500), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('responsible_id', sa.Integer(), nullable=True),
        sa.Column('responsible_name', sa.String(100), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('bitrix_data', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_bitrix24_tasks')),
        sa.ForeignKeyConstraint(
            ['device_id'], ['devices.id'],
            name=op.f('fk_bitrix24_tasks_device_id_devices'),
            ondelete='SET NULL',
        ),
    )
    op.create_index('ix_bitrix24_tasks_source', 'bitrix24_tasks', ['source_type', 'source_id'])
    op.create_index('ix_bitrix24_tasks_status', 'bitrix24_tasks', ['status'])
    op.create_index('ix_bitrix24_tasks_bitrix_id', 'bitrix24_tasks', ['bitrix_task_id'])


def downgrade() -> None:
    op.drop_index('ix_bitrix24_tasks_bitrix_id', table_name='bitrix24_tasks')
    op.drop_index('ix_bitrix24_tasks_status', table_name='bitrix24_tasks')
    op.drop_index('ix_bitrix24_tasks_source', table_name='bitrix24_tasks')
    op.drop_table('bitrix24_tasks')
    op.drop_column('devices', 'system_code')
