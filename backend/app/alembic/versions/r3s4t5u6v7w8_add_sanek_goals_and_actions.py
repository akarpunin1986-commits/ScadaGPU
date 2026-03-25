"""add sanek goals and actions

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-03-10 14:00:00.000000

Adds:
- sanek_goals: operator/AI goals with target configs and safety limits
- sanek_actions: proposed control actions requiring operator confirmation
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


revision: str = 'r3s4t5u6v7w8'
down_revision: Union[str, None] = 'q2r3s4t5u6v7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. sanek_goals — long-running objectives
    op.create_table(
        'sanek_goals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('site_id', sa.Integer(),
                  sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('goal_type', sa.String(50), nullable=False),
        sa.Column('target_config', JSON(), nullable=False, server_default='{}'),
        sa.Column('safety_limits', JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('created_by', sa.String(50), nullable=False, server_default='operator'),
        sa.Column('last_check_at', sa.DateTime(), nullable=True),
        sa.Column('last_action_at', sa.DateTime(), nullable=True),
        sa.Column('actions_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_sanek_goals_site_status', 'sanek_goals', ['site_id', 'status'])

    # 2. sanek_actions — proposed control commands
    op.create_table(
        'sanek_actions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('device_id', sa.Integer(),
                  sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('site_id', sa.Integer(),
                  sa.ForeignKey('sites.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action_type', sa.String(50), nullable=False),
        sa.Column('params', JSON(), nullable=False, server_default='{}'),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='proposed'),
        sa.Column('proposed_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('result', JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('goal_id', sa.Integer(),
                  sa.ForeignKey('sanek_goals.id', ondelete='SET NULL'), nullable=True),
        sa.Column('chat_session_id', sa.String(100), nullable=True),
    )
    op.create_index('ix_sanek_actions_device_status', 'sanek_actions', ['device_id', 'status'])
    op.create_index('ix_sanek_actions_proposed_at', 'sanek_actions', ['proposed_at'])


def downgrade() -> None:
    op.drop_index('ix_sanek_actions_proposed_at')
    op.drop_index('ix_sanek_actions_device_status')
    op.drop_table('sanek_actions')
    op.drop_index('ix_sanek_goals_site_status')
    op.drop_table('sanek_goals')
