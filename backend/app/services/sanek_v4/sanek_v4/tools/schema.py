"""
САНЁК v4 — Schema introspection tool.

get_db_schema — dynamically reads PostgreSQL schema, always up-to-date.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from models.base import async_session
from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek_v4.tools.schema")

# Table descriptions — business context that SQL schema can't provide
TABLE_DESCRIPTIONS = {
    "sites": "Площадки (МКЗ site_id=3, ЯКЗ site_id=5)",
    "devices": "Устройства Modbus: генераторы (HGM9520N) и панели ШПР (HGM9560)",
    "metrics_data": "Метрики реального времени — 1 строка = 1 устройство × 1 опрос (~2 сек). 70+ колонок: мощность, напряжение, ток, температура, давление, расход топлива, моточасы",
    "alarm_events": "Аварии с lifecycle: occurred_at → cleared_at, is_active",
    "scada_events": "Журнал событий: старт/стоп, переключения режимов, статусы АВР",
    "gas_prices": "Цены газа (руб/м³) по периодам для каждой площадки",
    "grid_prices": "Тарифы электросети (руб/кВт·ч) по полугодиям: 1П 2026=6.42, 2П 2026=7.062",
    "planned_costs": "Плановые затраты помесячно: масло, запчасти, ТО, зарплата, налоги ФОТ, капремонт, страхование, лизинг",
    "maintenance_intervals": "Уровни ТО: ТО-1 (250ч), ТО-2 (500ч), ТО-3 (1000ч)",
    "maintenance_tasks": "Чек-листы для каждого уровня ТО",
    "maintenance_logs": "Записи о проведённых ТО с моточасами и датой",
    "maintenance_alerts": "Предупреждения: ТО приближается / просрочено",
    "ai_knowledge_chunks": "База знаний: фрагменты мануалов SmartGen HGM9520N, HGM9560",
    "sanek_alarm_reference": "Справочник алармов: код → причины, действия, связанные алармы",
    "equipment_units": "Логические группы оборудования (ГПУ = генератор + двигатель + ...)",
    "bitrix24_tasks": "Локальный трекинг задач из Битрикс24",
    "ai_chat_messages": "История чата Санька: session_id, role, content",
    "learning_insights": "ML-инсайты: корреляции, прекурсоры, диапазоны нормы",
    "sanek_audit_log": "Аудит tool calls Санька: tool_name, input, output, время",
    "sanek_command_log": "Лог Modbus команд: pending → confirmed → executed",
}

# Which columns are most important for analysis (metrics_data has 70+ cols)
METRICS_KEY_COLUMNS = {
    "power_total": "Активная мощность генератора (кВт)",
    "reactive_total": "Реактивная мощность (кВАр)",
    "gen_freq": "Частота генератора (Гц)",
    "gen_uab": "Напряжение генератора AB (В)",
    "current_a": "Ток фазы A (А)",
    "coolant_temp": "Температура ОЖ (°C)",
    "oil_pressure": "Давление масла (кПа)",
    "oil_temp": "Температура масла (°C)",
    "engine_speed": "Обороты двигателя (об/мин)",
    "fuel_consumption": "Расход топлива (л/ч, дизель-эквивалент)",
    "load_pct": "Загрузка генератора (%)",
    "energy_kwh": "Счётчик выработки (кВт·ч, накопительный)",
    "run_hours": "Моточасы (ч, накопительный)",
    "battery_volt": "Напряжение АКБ (В)",
    "mains_total_p": "Потребление из сети через ШПР (кВт) — КЛЮЧЕВОЙ для экономики",
    "mains_uab": "Напряжение сети AB (В)",
    "mains_freq": "Частота сети (Гц)",
    "busbar_p": "Мощность на шине (кВт)",
    "multiset_total_p": "Суммарная мощность всех генераторов (кВт)",
    "gen_status": "Статус: 0=стоп, 1=прогрев, 6=работа, 8=аварийный стоп, 10=авария",
    "gas_pressure": "Давление газа на входе (кПа)",
    "air_gas_ratio": "Соотношение воздух/газ",
}


@registry.tool(
    name="get_db_schema",
    description=(
        "Получить актуальную структуру базы данных ScadaGPU. "
        "Возвращает таблицы, колонки, типы данных и описания. "
        "Вызывай когда нужно: написать SQL запрос через query_db, "
        "понять какие данные доступны, узнать точные имена колонок. "
        "Без параметров — список всех таблиц с описаниями. "
        "С table_name — детальная структура конкретной таблицы."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": (
                    "Имя таблицы для детального описания. Опционально. "
                    "Примеры: 'metrics_data', 'alarm_events', 'planned_costs'. "
                    "Без параметра — обзор всех таблиц."
                ),
            },
        },
    },
)
async def get_db_schema(table_name: str | None = None) -> dict:
    """Dynamically read PostgreSQL schema."""

    async with async_session() as db:
        if table_name:
            # Detailed schema for specific table
            result = await db.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :tn
                ORDER BY ordinal_position
            """), {"tn": table_name})
            rows = result.fetchall()

            if not rows:
                return {"error": f"Table '{table_name}' not found"}

            columns = []
            for col_name, data_type, nullable, default in rows:
                col_info = {
                    "name": col_name,
                    "type": data_type,
                }
                if nullable == "NO":
                    col_info["required"] = True
                if default:
                    col_info["default"] = str(default)[:50]
                # Add business description for metrics_data
                if table_name == "metrics_data" and col_name in METRICS_KEY_COLUMNS:
                    col_info["description"] = METRICS_KEY_COLUMNS[col_name]
                columns.append(col_info)

            # Get row count estimate
            count_result = await db.execute(text(f"""
                SELECT reltuples::bigint AS estimate
                FROM pg_class WHERE relname = :tn
            """), {"tn": table_name})
            row_estimate = count_result.scalar() or 0

            # Get indexes
            idx_result = await db.execute(text("""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = :tn AND schemaname = 'public'
            """), {"tn": table_name})
            indexes = [{"name": r[0], "definition": r[1][:100]} for r in idx_result.fetchall()]

            return {
                "table": table_name,
                "description": TABLE_DESCRIPTIONS.get(table_name, ""),
                "columns": columns,
                "column_count": len(columns),
                "row_estimate": row_estimate,
                "indexes": indexes,
            }

        else:
            # Overview: all tables with descriptions and row counts
            result = await db.execute(text("""
                SELECT c.relname AS table_name,
                       c.reltuples::bigint AS row_estimate,
                       pg_size_pretty(pg_total_relation_size(c.oid)) AS size
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                ORDER BY c.reltuples DESC
            """))
            rows = result.fetchall()

            tables = []
            for tname, row_est, size in rows:
                tables.append({
                    "table": tname,
                    "description": TABLE_DESCRIPTIONS.get(tname, ""),
                    "rows": row_est,
                    "size": size,
                })

            return {
                "tables": tables,
                "total_tables": len(tables),
                "hint": "Вызови get_db_schema(table_name='...') для детальной структуры конкретной таблицы.",
            }
