"""add_device_type_registry_and_device_metrics

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-03-10 12:00:00.000000

Adds:
- device_type_registry: dynamic device type definitions (metrics, thresholds, statuses)
- device_metrics: universal JSONB metrics storage for arbitrary equipment
- Extends device_type enum with furnace, extruder, custom
- Seeds registry with generator and ats types
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'q2r3s4t5u6v7'
down_revision: Union[str, None] = 'p1q2r3s4t5u6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extend device_type enum
    op.execute("ALTER TYPE devicetype ADD VALUE IF NOT EXISTS 'furnace'")
    op.execute("ALTER TYPE devicetype ADD VALUE IF NOT EXISTS 'extruder'")
    op.execute("ALTER TYPE devicetype ADD VALUE IF NOT EXISTS 'custom'")

    # 2. Create device_type_registry
    op.create_table(
        'device_type_registry',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('type_code', sa.String(50), unique=True, nullable=False),
        sa.Column('display_name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('metrics_schema', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('thresholds', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('statuses', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('nominal_values', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status_field', sa.String(50), nullable=True),
        sa.Column('running_status_code', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_device_type_registry_type_code', 'device_type_registry', ['type_code'])

    # 3. Create device_metrics (JSONB)
    op.create_table(
        'device_metrics',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('device_id', sa.Integer(),
                  sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('device_type', sa.String(50), nullable=False),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('online', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('data', JSONB(), nullable=False, server_default='{}'),
    )
    op.create_index('ix_device_metrics_device_ts', 'device_metrics', ['device_id', 'timestamp'])
    op.create_index('ix_device_metrics_ts', 'device_metrics', ['timestamp'])

    # 4. Seed registry with existing types (use bulk_insert to avoid bind param issues)
    registry_table = sa.table(
        'device_type_registry',
        sa.column('type_code', sa.String),
        sa.column('display_name', sa.String),
        sa.column('description', sa.Text),
        sa.column('metrics_schema', sa.JSON),
        sa.column('thresholds', sa.JSON),
        sa.column('statuses', sa.JSON),
        sa.column('nominal_values', sa.JSON),
        sa.column('status_field', sa.String),
        sa.column('running_status_code', sa.Integer),
    )
    op.bulk_insert(registry_table, [
        {
            "type_code": "generator",
            "display_name": "Генератор газопоршневой",
            "description": "SmartGen HGM9520N, газопоршневой генератор 160 кВт",
            "metrics_schema": {"power_total": {"unit": "кВт", "description": "Активная мощность"}, "engine_speed": {"unit": "об/мин", "description": "Обороты двигателя"}, "coolant_temp": {"unit": "°C", "description": "Температура ОЖ"}, "oil_pressure": {"unit": "бар", "description": "Давление масла"}, "oil_temp": {"unit": "°C", "description": "Температура масла"}, "battery_volt": {"unit": "В", "description": "Напряжение АКБ"}, "gen_uab": {"unit": "В", "description": "Напряжение генератора AB"}, "gen_freq": {"unit": "Гц", "description": "Частота генератора"}, "current_a": {"unit": "А", "description": "Ток фазы A"}, "fuel_consumption": {"unit": "м³/ч", "description": "Расход газа"}, "load_pct": {"unit": "%", "description": "Загрузка"}, "run_hours": {"unit": "ч", "description": "Наработка"}, "energy_kwh": {"unit": "кВт·ч", "description": "Выработка"}},
            "thresholds": {"coolant_temp": {"warn": 90, "critical": 105}, "oil_pressure": {"warn_low": 2.0, "critical_low": 1.5}, "oil_temp": {"warn": 95, "critical": 110}, "battery_volt": {"warn_low": 24, "critical_low": 22}, "gen_freq": {"warn_low": 49, "warn": 51, "critical_low": 48, "critical": 52}, "engine_speed": {"warn_low": 1480, "warn": 1520, "critical_low": 1450, "critical": 1550}},
            "statuses": {"0": "Стоп", "1": "Предпусковой прогрев", "2": "Предпусковой прогрев", "3": "Кранкинг", "4": "Запуск: прогрев", "5": "Запуск: прогрев", "6": "Запуск: прогрев", "7": "Запуск: прогрев", "8": "Набор оборотов", "9": "Работа", "10": "Охлаждение", "11": "Остановка", "12": "Аварийный стоп", "13": "Ошибка", "14": "Ошибка", "15": "Ошибка"},
            "nominal_values": {"power": 160, "power_unit": "кВт"},
            "status_field": "gen_status",
            "running_status_code": 9,
        },
        {
            "type_code": "ats",
            "display_name": "ШПР (АВР)",
            "description": "SmartGen HGM9560, щит переключения резерва",
            "metrics_schema": {"mains_total_p": {"unit": "кВт", "description": "Мощность сети"}, "busbar_p": {"unit": "кВт", "description": "Мощность шины"}, "busbar_uab": {"unit": "В", "description": "Напряжение шины AB"}, "busbar_freq": {"unit": "Гц", "description": "Частота шины"}, "multiset_total_p": {"unit": "кВт", "description": "Суммарная мощность генераторов"}, "mains_uab": {"unit": "В", "description": "Напряжение сети AB"}},
            "thresholds": {"busbar_freq": {"warn_low": 49, "warn": 51, "critical_low": 48, "critical": 52}, "busbar_uab": {"warn_low": 370, "warn": 420, "critical_low": 350, "critical": 440}},
            "statuses": {},
            "nominal_values": {},
            "status_field": "gen_ats_status",
            "running_status_code": None,
        },
    ])


def downgrade() -> None:
    op.drop_index('ix_device_metrics_ts')
    op.drop_index('ix_device_metrics_device_ts')
    op.drop_table('device_metrics')
    op.drop_index('ix_device_type_registry_type_code')
    op.drop_table('device_type_registry')
