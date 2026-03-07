"""add_ecu_gas_columns

Revision ID: i3b4c5d6e7f8
Revises: h2a3b4c5d6e7
Create Date: 2026-03-04 12:00:00.000000

Add ECU Exon-Gas columns to metrics_data for gas piston diagnostics.
All nullable — instant ADD COLUMN in PostgreSQL, no table rewrite.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'i3b4c5d6e7f8'
down_revision: Union[str, None] = 'h2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('metrics_data', sa.Column('accumulated_fuel', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('throttle_valve_pos', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('fuel_valve_pos', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('fuel_inlet_pressure', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('exhaust_oxygen', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('ignition_timing', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('engine_target_speed', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('air_gas_ratio', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('gas_pressure', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('gas_temp', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('exhaust_back_pressure', sa.Float(), nullable=True))
    op.add_column('metrics_data', sa.Column('throttle_valve_cmd', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('metrics_data', 'throttle_valve_cmd')
    op.drop_column('metrics_data', 'exhaust_back_pressure')
    op.drop_column('metrics_data', 'gas_temp')
    op.drop_column('metrics_data', 'gas_pressure')
    op.drop_column('metrics_data', 'air_gas_ratio')
    op.drop_column('metrics_data', 'engine_target_speed')
    op.drop_column('metrics_data', 'ignition_timing')
    op.drop_column('metrics_data', 'exhaust_oxygen')
    op.drop_column('metrics_data', 'fuel_inlet_pressure')
    op.drop_column('metrics_data', 'fuel_valve_pos')
    op.drop_column('metrics_data', 'throttle_valve_pos')
    op.drop_column('metrics_data', 'accumulated_fuel')
