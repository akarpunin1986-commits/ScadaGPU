"""add_metrics_data_and_alarm_events

Revision ID: c5e9f2a81b34
Revises: a3f8c1d29e47
Create Date: 2026-02-19 12:00:00.000000

Phase 6: persistent storage for metrics + alarm events.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5e9f2a81b34'
down_revision: Union[str, None] = 'a3f8c1d29e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- metrics_data ---
    op.create_table(
        'metrics_data',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('device_type', sa.String(20), nullable=False),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('online', sa.Boolean(), default=True, nullable=False),
        # Voltage
        sa.Column('gen_uab', sa.Float(), nullable=True),
        sa.Column('gen_ubc', sa.Float(), nullable=True),
        sa.Column('gen_uca', sa.Float(), nullable=True),
        sa.Column('gen_freq', sa.Float(), nullable=True),
        sa.Column('mains_uab', sa.Float(), nullable=True),
        sa.Column('mains_ubc', sa.Float(), nullable=True),
        sa.Column('mains_uca', sa.Float(), nullable=True),
        sa.Column('mains_freq', sa.Float(), nullable=True),
        # Current
        sa.Column('current_a', sa.Float(), nullable=True),
        sa.Column('current_b', sa.Float(), nullable=True),
        sa.Column('current_c', sa.Float(), nullable=True),
        # Power
        sa.Column('power_total', sa.Float(), nullable=True),
        sa.Column('power_a', sa.Float(), nullable=True),
        sa.Column('power_b', sa.Float(), nullable=True),
        sa.Column('power_c', sa.Float(), nullable=True),
        sa.Column('reactive_total', sa.Float(), nullable=True),
        # Engine
        sa.Column('engine_speed', sa.Float(), nullable=True),
        sa.Column('coolant_temp', sa.Float(), nullable=True),
        sa.Column('oil_pressure', sa.Float(), nullable=True),
        sa.Column('oil_temp', sa.Float(), nullable=True),
        sa.Column('battery_volt', sa.Float(), nullable=True),
        sa.Column('fuel_level', sa.Float(), nullable=True),
        sa.Column('load_pct', sa.Float(), nullable=True),
        sa.Column('fuel_pressure', sa.Float(), nullable=True),
        sa.Column('turbo_pressure', sa.Float(), nullable=True),
        sa.Column('fuel_consumption', sa.Float(), nullable=True),
        # Accumulated
        sa.Column('run_hours', sa.Float(), nullable=True),
        sa.Column('energy_kwh', sa.Float(), nullable=True),
        sa.Column('gen_status', sa.Integer(), nullable=True),
    )
    op.create_index('ix_metrics_data_device_ts', 'metrics_data', ['device_id', 'timestamp'])
    op.create_index('ix_metrics_data_ts', 'metrics_data', ['timestamp'])

    # --- alarm_events ---
    op.create_table(
        'alarm_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('alarm_code', sa.String(20), nullable=False),
        sa.Column('severity', sa.String(10), nullable=False),
        sa.Column('message', sa.String(200), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('cleared_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
    )
    op.create_index('ix_alarm_events_device_occurred', 'alarm_events', ['device_id', 'occurred_at'])
    op.create_index('ix_alarm_events_active', 'alarm_events', ['is_active'])


def downgrade() -> None:
    op.drop_index('ix_alarm_events_active', 'alarm_events')
    op.drop_index('ix_alarm_events_device_occurred', 'alarm_events')
    op.drop_table('alarm_events')
    op.drop_index('ix_metrics_data_ts', 'metrics_data')
    op.drop_index('ix_metrics_data_device_ts', 'metrics_data')
    op.drop_table('metrics_data')
