"""Add sanek_alarm_reference table with seed data.

Revision ID: p0i1j2k3l4m5
Revises: o9h0i1j2k3l4
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "p0i1j2k3l4m5"
down_revision = "o9h0i1j2k3l4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "sanek_alarm_reference",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("controller", sa.String(50), nullable=False),
        sa.Column("alarm_code", sa.String(50), nullable=False),
        sa.Column("alarm_name_ru", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("typical_causes", JSONB, nullable=False, server_default="[]"),
        sa.Column("immediate_actions", JSONB, nullable=False, server_default="[]"),
        sa.Column("related_alarms", sa.ARRAY(sa.Text), nullable=True),
        sa.Column("possible_cascade", sa.ARRAY(sa.Text), nullable=True),
        sa.Column("manual_reference", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_index("ix_sanek_alarm_ref_controller", "sanek_alarm_reference", ["controller"])
    op.create_index("ix_sanek_alarm_ref_code", "sanek_alarm_reference", ["alarm_code"])
    op.create_index(
        "ix_sanek_alarm_ref_ctrl_code", "sanek_alarm_reference",
        ["controller", "alarm_code"], unique=True,
    )

    # Seed 9 alarm reference records
    op.bulk_insert(table, [
        {
            "controller": "HGM9520N",
            "alarm_code": "SHUTDOWN",
            "alarm_name_ru": "Аварийная остановка",
            "category": "protection",
            "severity": "shutdown",
            "typical_causes": [
                {"cause": "Срабатывание защиты двигателя (давление масла, температура ОЖ)", "probability": 0.45},
                {"cause": "Внешний сигнал аварийного останова", "probability": 0.30},
                {"cause": "Превышение параметров генератора (напряжение, ток, частота)", "probability": 0.25},
            ],
            "immediate_actions": [
                {"step": 1, "action": "Проверить дисплей HGM9520N — определить конкретный код аварии", "verification": "Дисплей показывает код ошибки"},
                {"step": 2, "action": "Проверить давление масла и температуру ОЖ по приборам двигателя", "verification": "Давление >3 bar, температура <95°C"},
                {"step": 3, "action": "НЕ перезапускать до выяснения причины останова", "verification": "Причина установлена и устранена"},
                {"step": 4, "action": "Сбросить аварию кнопкой RESET на контроллере после устранения причины", "verification": "Контроллер перешёл в состояние READY"},
            ],
            "related_alarms": ["LOW_OIL_PRESSURE", "HIGH_COOLANT_TEMP", "OVER_CURRENT"],
            "possible_cascade": ["ENGINE_DAMAGE", "FACILITY_POWER_LOSS"],
            "manual_reference": None,
        },
        {
            "controller": "HGM9520N",
            "alarm_code": "TRIP_STOP",
            "alarm_name_ru": "Защитное отключение генератора",
            "category": "protection",
            "severity": "shutdown",
            "typical_causes": [
                {"cause": "Рассинхронизация с сетью или параллельным генератором", "probability": 0.50},
                {"cause": "Превышение тока нагрузки", "probability": 0.30},
                {"cause": "Потеря возбуждения", "probability": 0.20},
            ],
            "immediate_actions": [
                {"step": 1, "action": "Проверить угол рассинхронизации на дисплее HGM9520N", "verification": "Угол delta < 5 для повторного включения"},
                {"step": 2, "action": "Проверить ток нагрузки — не превышает ли номинал", "verification": "Ток не превышает 80% от номинального"},
                {"step": 3, "action": "Проверить параллельный генератор — его состояние и нагрузку", "verification": "Параллельный ГПУ в норме"},
                {"step": 4, "action": "При подтверждении синхронизации — включить автомат генератора", "verification": "Автомат включён, ток распределяется равномерно"},
            ],
            "related_alarms": ["SYNC_FAIL", "OVER_CURRENT", "LOSS_OF_EXCITATION"],
            "possible_cascade": ["PARALLEL_DESYNC", "FACILITY_POWER_LOSS"],
            "manual_reference": None,
        },
        {
            "controller": "HGM9520N",
            "alarm_code": "OVER_FREQUENCY",
            "alarm_name_ru": "Перечастота",
            "category": "electrical",
            "severity": "shutdown",
            "typical_causes": [
                {"cause": "Внезапный сброс нагрузки (load dump) — потребители отключились", "probability": 0.70},
                {"cause": "Неисправность регулятора оборотов двигателя (governor)", "probability": 0.20},
                {"cause": "Неправильная настройка уставки частоты", "probability": 0.10},
            ],
            "immediate_actions": [
                {"step": 1, "action": "Проверить одновременно: OVER_VOLTAGE и OVER_POWER — если оба есть, это load dump", "verification": "Картина алармов подтверждает load dump"},
                {"step": 2, "action": "Проверить ГРЩ — какие потребители отключились и почему", "verification": "Причина отключения потребителей установлена"},
                {"step": 3, "action": "Проверить настройки регулятора частоты на SECM70 (если применимо)", "verification": "Уставка частоты 50 Гц +/-0.5 Гц"},
            ],
            "related_alarms": ["OVER_VOLTAGE", "OVER_POWER"],
            "possible_cascade": ["LOSS_OF_EXCITATION"],
            "manual_reference": None,
        },
        {
            "controller": "HGM9520N",
            "alarm_code": "OVER_VOLTAGE",
            "alarm_name_ru": "Перенапряжение",
            "category": "electrical",
            "severity": "shutdown",
            "typical_causes": [
                {"cause": "Load dump — внезапный сброс нагрузки", "probability": 0.65},
                {"cause": "Неисправность АВР (возврат с сети без синхронизации)", "probability": 0.20},
                {"cause": "Неисправность регулятора напряжения (AVR)", "probability": 0.15},
            ],
            "immediate_actions": [
                {"step": 1, "action": "Проверить одновременность с OVER_FREQUENCY и OVER_POWER", "verification": "Если все три — load dump"},
                {"step": 2, "action": "Проверить работу HGM9560 — статус АВР и шины", "verification": "HGM9560 в штатном режиме"},
                {"step": 3, "action": "Проверить напряжение сети — нет ли скачка с сетевой стороны", "verification": "Сетевое напряжение в норме 380-400 В"},
            ],
            "related_alarms": ["OVER_FREQUENCY", "OVER_POWER"],
            "possible_cascade": ["LOSS_OF_EXCITATION"],
            "manual_reference": None,
        },
        {
            "controller": "HGM9520N",
            "alarm_code": "LOW_OIL_PRESSURE",
            "alarm_name_ru": "Низкое давление масла",
            "category": "mechanical",
            "severity": "shutdown",
            "typical_causes": [
                {"cause": "Недостаточный уровень масла в картере", "probability": 0.40},
                {"cause": "Износ масляного насоса", "probability": 0.25},
                {"cause": "Засорение масляного фильтра", "probability": 0.20},
                {"cause": "Неисправность датчика давления (ложное срабатывание)", "probability": 0.15},
            ],
            "immediate_actions": [
                {"step": 1, "action": "НЕМЕДЛЕННО остановить ГПУ если не остановлен автоматически", "verification": "ГПУ остановлен"},
                {"step": 2, "action": "Проверить уровень масла щупом — двигатель должен быть остановлен 5 мин", "verification": "Уровень между MIN и MAX"},
                {"step": 3, "action": "Проверить давление масла механическим манометром (исключить ложное срабатывание датчика)", "verification": "Давление >3 bar на холостом ходу"},
                {"step": 4, "action": "НЕ запускать до устранения причины и подтверждения давления масла", "verification": "Причина устранена, давление в норме"},
            ],
            "related_alarms": ["HIGH_OIL_TEMP", "ENGINE_SHUTDOWN"],
            "possible_cascade": ["ENGINE_DAMAGE"],
            "manual_reference": None,
        },
        {
            "controller": "HGM9520N",
            "alarm_code": "HIGH_COOLANT_TEMP",
            "alarm_name_ru": "Высокая температура охлаждающей жидкости",
            "category": "mechanical",
            "severity": "shutdown",
            "typical_causes": [
                {"cause": "Недостаточный уровень охлаждающей жидкости", "probability": 0.35},
                {"cause": "Засорение радиатора или вентилятора охлаждения", "probability": 0.30},
                {"cause": "Длительная работа с перегрузкой (нагрузка >85% длительно)", "probability": 0.25},
                {"cause": "Неисправность термостата", "probability": 0.10},
            ],
            "immediate_actions": [
                {"step": 1, "action": "Снизить нагрузку на ГПУ до 70% — если система управления позволяет", "verification": "Нагрузка снижена, температура перестала расти"},
                {"step": 2, "action": "Проверить уровень ОЖ в расширительном бачке (только на холодном двигателе!)", "verification": "Уровень в норме"},
                {"step": 3, "action": "Проверить работу вентилятора и чистоту радиатора", "verification": "Вентилятор вращается, радиатор чистый"},
                {"step": 4, "action": "Если температура продолжает расти — остановить ГПУ через HGM9520N", "verification": "ГПУ остановлен безопасно"},
            ],
            "related_alarms": ["OVER_POWER", "ENGINE_OVERLOAD"],
            "possible_cascade": ["ENGINE_SHUTDOWN", "ENGINE_DAMAGE"],
            "manual_reference": None,
        },
        {
            "controller": "HGM9520N",
            "alarm_code": "CONN_LOST",
            "alarm_name_ru": "Потеря связи Modbus",
            "category": "communication",
            "severity": "warning",
            "typical_causes": [
                {"cause": "Коллизия на RS-485 шине при активной MSC параллельной работе", "probability": 0.50},
                {"cause": "Физический обрыв кабеля или плохой контакт", "probability": 0.25},
                {"cause": "Неправильные настройки Modbus (адрес, скорость, чётность)", "probability": 0.15},
                {"cause": "Перегрузка USR-TCP232-410S конвертера", "probability": 0.10},
            ],
            "immediate_actions": [
                {"step": 1, "action": "Проверить физическое подключение кабеля RS-485 к USR-TCP232-410S", "verification": "Кабель подключён, клеммы затянуты"},
                {"step": 2, "action": "Проверить состояние MSC-шины параллельной работы — не активна ли во время SCADA-поллинга", "verification": "Коллизии отсутствуют (см. лог поллера)"},
                {"step": 3, "action": "Перезагрузить USR-TCP232-410S конвертер (питание на 10 сек)", "verification": "Связь восстановлена"},
                {"step": 4, "action": "Проверить настройки Modbus в HGM9520N: адрес, 9600/8N1", "verification": "Настройки совпадают с конфигурацией поллера"},
            ],
            "related_alarms": ["MODBUS_TIMEOUT", "MODBUS_ERROR"],
            "possible_cascade": [],
            "manual_reference": None,
        },
        {
            "controller": "HGM9560",
            "alarm_code": "SYNC_FAIL",
            "alarm_name_ru": "Ошибка синхронизации генераторов",
            "category": "control",
            "severity": "shutdown",
            "typical_causes": [
                {"cause": "Разница частот между генераторами превышает допустимую", "probability": 0.45},
                {"cause": "Разница напряжений между генераторами превышает допустимую", "probability": 0.30},
                {"cause": "Разница фаз превышает 10 градусов", "probability": 0.25},
            ],
            "immediate_actions": [
                {"step": 1, "action": "Проверить частоту обоих ГПУ на дисплеях HGM9520N — разница должна быть <0.2 Гц", "verification": "Частоты совпадают"},
                {"step": 2, "action": "Проверить напряжение обоих ГПУ — разница должна быть <5%", "verification": "Напряжения совпадают"},
                {"step": 3, "action": "Дождаться автоматической синхронизации HGM9560 (до 60 сек)", "verification": "HGM9560 показывает SYNCHRONIZED"},
                {"step": 4, "action": "Если автосинхронизация не происходит — переключить в ручной режим и синхронизировать вручную", "verification": "Угол delta < 5 перед включением"},
            ],
            "related_alarms": ["FREQ_MISMATCH", "VOLTAGE_MISMATCH"],
            "possible_cascade": ["TRIP_STOP"],
            "manual_reference": None,
        },
        {
            "controller": "HGM9560",
            "alarm_code": "MIN_SETS_NOT_REACHED",
            "alarm_name_ru": "Недостаточно генераторов в работе",
            "category": "control",
            "severity": "warning",
            "typical_causes": [
                {"cause": "Один из параллельных ГПУ остановлен или недоступен", "probability": 0.70},
                {"cause": "Потеря связи HGM9560 с одним из HGM9520N по MSC-шине", "probability": 0.30},
            ],
            "immediate_actions": [
                {"step": 1, "action": "Проверить статус второго ГПУ на его HGM9520N", "verification": "Определить — остановлен или нет связи"},
                {"step": 2, "action": "Если ГПУ остановлен по аварии — устранить аварию и запустить", "verification": "Оба ГПУ в работе"},
                {"step": 3, "action": "Если проблема в MSC-шине — проверить RS-485 соединение между контроллерами", "verification": "HGM9560 видит оба модуля"},
            ],
            "related_alarms": ["CONN_LOST"],
            "possible_cascade": ["OVERLOAD", "INSUFFICIENT_CAPACITY"],
            "manual_reference": None,
        },
    ])


def downgrade() -> None:
    op.drop_index("ix_sanek_alarm_ref_ctrl_code", table_name="sanek_alarm_reference")
    op.drop_index("ix_sanek_alarm_ref_code", table_name="sanek_alarm_reference")
    op.drop_index("ix_sanek_alarm_ref_controller", table_name="sanek_alarm_reference")
    op.drop_table("sanek_alarm_reference")
