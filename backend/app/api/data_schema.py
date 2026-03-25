"""
Схема всех доступных данных в ScadaGPU.
data_api.py использует эту схему для построения SQL-запросов.
Санёк использует эту схему чтобы знать что можно запросить.

Версия: 1.0  |  Март 2026
"""

from __future__ import annotations

DATA_SCHEMA: dict[str, dict] = {

    # ══════════════════════════════════════
    # УСТРОЙСТВА И ОБЪЕКТЫ
    # ══════════════════════════════════════
    "sites": {
        "description": "Объекты (МКЗ, ЯКЗ)",
        "table": "sites",
        "fields": {
            "id":        {"col": "id",        "type": "int",  "label": "ID объекта"},
            "name":      {"col": "name",      "type": "str",  "label": "Название"},
            "code":      {"col": "code",      "type": "str",  "label": "Код"},
            "network":   {"col": "network",   "type": "str",  "label": "Сеть"},
            "is_active": {"col": "is_active", "type": "bool", "label": "Активен"},
        },
        "filters": ["id", "name", "is_active"],
        "pk": "id",
        "order_default": "id",
    },

    "devices": {
        "description": "Устройства (генераторы, ШПР, контроллеры)",
        "table": "devices",
        "fields": {
            "id":               {"col": "id",               "type": "int",  "label": "ID устройства"},
            "name":             {"col": "name",             "type": "str",  "label": "Название"},
            "site_id":          {"col": "site_id",          "type": "int",  "label": "ID объекта"},
            "device_type":      {"col": "device_type",      "type": "str",  "label": "Тип (generator/spr/controller)"},
            "is_active":        {"col": "is_active",        "type": "bool", "label": "Активен"},
            "ip_address":       {"col": "ip_address",       "type": "str",  "label": "IP-адрес"},
        },
        "filters": ["id", "site_id", "device_type", "is_active"],
        "pk": "id",
        "order_default": "id",
    },

    # ══════════════════════════════════════
    # МЕТРИКИ (ЖИВЫЕ — Redis)
    # ══════════════════════════════════════
    "metrics": {
        "description": "Текущие (live) метрики устройств из Redis",
        "source": "redis",
        "fields": {
            "power_total":   {"label": "Выработка кВт"},
            "gen_freq":      {"label": "Частота генератора Гц"},
            "coolant_temp":  {"label": "Температура ОЖ °C"},
            "oil_pressure":  {"label": "Давление масла bar"},
            "oil_temp":      {"label": "Температура масла °C"},
            "gen_status":    {"label": "Статус генератора (0=стоп, 9=работа)"},
            "run_hours":     {"label": "Моточасы"},
            "battery_volt":  {"label": "Напряжение батареи В"},
            "mains_total_p": {"label": "Потребление из сети кВт"},
        },
        "filters": ["device_id", "site_id"],
    },

    # ══════════════════════════════════════
    # МЕТРИКИ ИСТОРИЯ (PostgreSQL — metrics_data)
    # ══════════════════════════════════════
    "metrics_history": {
        "description": "История метрик за период с агрегацией по времени",
        "table": "metrics_data",
        "relations": {
            "device_id": {
                "entity": "devices",
                "foreign_key": "id",
                "include_fields": ["name", "site_id"],
                "rename": {"name": "device_name"},
            },
        },
        "fields": {
            "timestamp":     {"col": "timestamp",     "type": "datetime", "label": "Время записи"},
            "device_id":     {"col": "device_id",     "type": "int",      "label": "ID устройства"},
            "power_total":   {"col": "power_total",   "type": "float",    "label": "Выработка кВт"},
            "reactive_total":{"col": "reactive_total", "type": "float",   "label": "Реактивная мощность кВАР"},
            "coolant_temp":  {"col": "coolant_temp",  "type": "float",    "label": "Температура ОЖ °C"},
            "oil_pressure":  {"col": "oil_pressure",  "type": "float",    "label": "Давление масла bar"},
            "oil_temp":      {"col": "oil_temp",      "type": "float",    "label": "Температура масла °C"},
            "engine_speed":  {"col": "engine_speed",  "type": "float",    "label": "Обороты двигателя"},
            "gen_freq":      {"col": "gen_freq",      "type": "float",    "label": "Частота генератора Гц"},
            "battery_volt":  {"col": "battery_volt",  "type": "float",    "label": "Напряжение батареи В"},
            "fuel_consumption": {"col": "fuel_consumption", "type": "float", "label": "Расход топлива л/ч"},
            "load_pct":      {"col": "load_pct",      "type": "float",    "label": "Нагрузка %"},
            "run_hours":     {"col": "run_hours",     "type": "float",    "label": "Моточасы"},
            "gen_status":    {"col": "gen_status",    "type": "int",      "label": "Статус генератора"},
            "energy_kwh":    {"col": "energy_kwh",    "type": "float",    "label": "Энергия кВт·ч (накопит)"},
            "mains_total_p": {"col": "mains_total_p", "type": "float",    "label": "Потребление из сети кВт"},
            "current_a":     {"col": "current_a",     "type": "float",    "label": "Ток фаза A"},
            "current_b":     {"col": "current_b",     "type": "float",    "label": "Ток фаза B"},
            "current_c":     {"col": "current_c",     "type": "float",    "label": "Ток фаза C"},
            "gen_uab":       {"col": "gen_uab",       "type": "float",    "label": "Напряжение AB В"},
            "gen_ubc":       {"col": "gen_ubc",       "type": "float",    "label": "Напряжение BC В"},
            "gen_uca":       {"col": "gen_uca",       "type": "float",    "label": "Напряжение CA В"},
        },
        "filters": ["device_id"],
        "period": True,
        "aggregations": ["avg", "min", "max", "sum", "last"],
        "group_by": ["5min", "10min", "30min", "hour", "day", "week"],
        "ts_col": "timestamp",
        "pk": "id",
        "order_default": "timestamp",
    },

    # ══════════════════════════════════════
    # АВАРИИ
    # ══════════════════════════════════════
    "alarms": {
        "description": "Аварии (активные и исторические)",
        "table": "alarm_events",
        "fields": {
            "id":          {"col": "id",          "type": "int",      "label": "ID аварии"},
            "device_id":   {"col": "device_id",   "type": "int",      "label": "ID устройства"},
            "alarm_code":  {"col": "alarm_code",   "type": "str",     "label": "Код аварии"},
            "severity":    {"col": "severity",     "type": "str",     "label": "Серьёзность (critical/high/medium/low)"},
            "message":     {"col": "message",      "type": "str",     "label": "Описание"},
            "occurred_at": {"col": "occurred_at",  "type": "datetime", "label": "Время начала"},
            "cleared_at":  {"col": "cleared_at",   "type": "datetime", "label": "Время окончания"},
            "is_active":   {"col": "is_active",    "type": "bool",    "label": "Активна сейчас"},
        },
        "filters": ["device_id", "alarm_code", "severity", "is_active"],
        "period": True,
        "ts_col": "occurred_at",
        "pk": "id",
        "order_default": "occurred_at",
        "aggregations": ["count"],
        "group_by": ["hour", "day", "week"],
        "relations": {
            "device_id": {
                "entity": "devices",
                "foreign_key": "id",
                "include_fields": ["name", "site_id"],
                "rename": {"name": "device_name"},
            },
        },
    },

    # ══════════════════════════════════════
    # СОБЫТИЯ
    # ══════════════════════════════════════
    "events": {
        "description": "Журнал событий (запуски, остановки, переключения режимов)",
        "table": "scada_events",
        "fields": {
            "id":         {"col": "id",         "type": "int",      "label": "ID события"},
            "device_id":  {"col": "device_id",  "type": "int",      "label": "ID устройства"},
            "category":   {"col": "category",   "type": "str",      "label": "Категория (GEN_STATUS/MODE_CHANGE/ATS_STATUS/MAINS/OPERATOR/SYSTEM)"},
            "event_code": {"col": "event_code", "type": "str",      "label": "Код события"},
            "message":    {"col": "message",    "type": "str",      "label": "Описание"},
            "old_value":  {"col": "old_value",  "type": "str",      "label": "Значение до"},
            "new_value":  {"col": "new_value",  "type": "str",      "label": "Значение после"},
            "created_at": {"col": "created_at", "type": "datetime", "label": "Время"},
        },
        "filters": ["device_id", "category", "event_code"],
        "period": True,
        "ts_col": "created_at",
        "pk": "id",
        "order_default": "created_at",
        "aggregations": ["count"],
        "group_by": ["hour", "day", "week"],
        "relations": {
            "device_id": {
                "entity": "devices",
                "foreign_key": "id",
                "include_fields": ["name"],
                "rename": {"name": "device_name"},
            },
        },
    },

    # ══════════════════════════════════════
    # ИНЦИДЕНТЫ АГЕНТА
    # ══════════════════════════════════════
    "incidents": {
        "description": "История инцидентов зафиксированных AI-агентом",
        "table": "agent_incidents",
        "fields": {
            "id":              {"col": "id",              "type": "int",      "label": "ID"},
            "device_id":       {"col": "device_id",       "type": "int",      "label": "ID устройства"},
            "site_id":         {"col": "site_id",         "type": "int",      "label": "ID объекта"},
            "alarm_code":      {"col": "alarm_code",      "type": "str",      "label": "Код аварии"},
            "cause":           {"col": "cause",           "type": "str",      "label": "Причина"},
            "recommendation":  {"col": "recommendation",  "type": "str",      "label": "Рекомендация"},
            "status":          {"col": "status",          "type": "str",      "label": "Статус (pending/analyzing/completed/failed)"},
            "created_at":      {"col": "created_at",      "type": "datetime", "label": "Время"},
        },
        "filters": ["device_id", "site_id", "alarm_code", "status"],
        "period": True,
        "ts_col": "created_at",
        "pk": "id",
        "order_default": "created_at",
        "relations": {
            "device_id": {
                "entity": "devices",
                "foreign_key": "id",
                "include_fields": ["name"],
                "rename": {"name": "device_name"},
            },
            "site_id": {
                "entity": "sites",
                "foreign_key": "id",
                "include_fields": ["name"],
                "rename": {"name": "site_name"},
            },
        },
    },

    # ══════════════════════════════════════
    # ПАМЯТЬ САНЬКА
    # ══════════════════════════════════════
    "memory": {
        "description": "Сохранённые факты и инструкции оператора",
        "table": "sanek_memory",
        "fields": {
            "id":         {"col": "id",         "type": "int",      "label": "ID"},
            "category":   {"col": "category",   "type": "str",      "label": "Категория (instruction/fact/preference/context)"},
            "content":    {"col": "content",     "type": "str",      "label": "Содержание"},
            "is_active":  {"col": "is_active",   "type": "bool",    "label": "Активна"},
            "created_at": {"col": "created_at",  "type": "datetime", "label": "Дата сохранения"},
        },
        "filters": ["category", "is_active"],
        "pk": "id",
        "order_default": "created_at",
    },

    # ══════════════════════════════════════
    # ТЕХОБСЛУЖИВАНИЕ (агрегированное через SQL)
    # ══════════════════════════════════════
    "maintenance_logs": {
        "description": "Журнал выполненных ТО",
        "table": "maintenance_logs",
        "fields": {
            "id":              {"col": "id",              "type": "int",      "label": "ID"},
            "device_id":       {"col": "device_id",       "type": "int",      "label": "ID устройства"},
            "performed_at":    {"col": "performed_at",    "type": "datetime", "label": "Дата проведения"},
            "engine_hours":    {"col": "engine_hours",    "type": "float",    "label": "Моточасы на момент ТО"},
            "completed_count": {"col": "completed_count", "type": "int",      "label": "Выполнено задач"},
            "total_count":     {"col": "total_count",     "type": "int",      "label": "Всего задач"},
            "notes":           {"col": "notes",           "type": "str",      "label": "Примечания"},
            "performed_by":    {"col": "performed_by",    "type": "str",      "label": "Исполнитель"},
        },
        "filters": ["device_id"],
        "period": True,
        "ts_col": "performed_at",
        "pk": "id",
        "order_default": "performed_at",
        "relations": {
            "device_id": {
                "entity": "devices",
                "foreign_key": "id",
                "include_fields": ["name"],
                "rename": {"name": "device_name"},
            },
        },
    },

    # ══════════════════════════════════════
    # ЦЕНЫ НА ГАЗ
    # ══════════════════════════════════════
    "gas_prices": {
        "description": "Цены на газ по объектам",
        "table": "gas_prices",
        "fields": {
            "id":             {"col": "id",             "type": "int",   "label": "ID"},
            "site_id":        {"col": "site_id",        "type": "int",   "label": "ID объекта"},
            "effective_from": {"col": "effective_from",  "type": "date",  "label": "Действует с"},
            "price_per_m3":   {"col": "price_per_m3",   "type": "float", "label": "Цена руб/м³"},
            "note":           {"col": "note",           "type": "str",   "label": "Примечание"},
        },
        "filters": ["site_id"],
        "pk": "id",
        "order_default": "effective_from",
    },
}


# ══════════════════════════════════════
# Периоды которые понимает прокладка
# ══════════════════════════════════════
PERIOD_MAP = {
    "now":        "текущий момент (→ entity=metrics)",
    "today":      "сегодня 00:00 — сейчас",
    "yesterday":  "вчера 00:00 — 23:59",
    "last_1h":    "последний час",
    "last_6h":    "последние 6 часов",
    "last_24h":   "последние 24 часа",
    "last_7d":    "последние 7 дней",
    "last_30d":   "последние 30 дней",
    "this_week":  "текущая неделя (пн — сейчас)",
    "this_month": "текущий месяц (1-е — сейчас)",
    "all_time":   "весь период в БД",
    # Конкретные даты:
    # "2026-03-10"            → один день
    # "2026-03-01:2026-03-10" → диапазон
}


# group_by → bucket_seconds mapping
GROUP_BY_SECONDS = {
    "5min":  300,
    "10min": 600,
    "30min": 1800,
    "hour":  3600,
    "day":   86400,
    "week":  604800,
}

# Aggregation SQL functions
AGG_SQL = {
    "avg":   "AVG",
    "min":   "MIN",
    "max":   "MAX",
    "sum":   "SUM",
    "count": "COUNT",
    "last":  "MAX",   # approximation for "last" — use MAX(timestamp) based
}


def get_schema_summary() -> dict:
    """Краткая схема для LLM — без внутренних деталей реализации."""
    result = {}
    for name, schema in DATA_SCHEMA.items():
        entry = {
            "description": schema["description"],
            "fields": {
                k: v.get("label", k)
                for k, v in schema.get("fields", {}).items()
            },
            "filters": schema.get("filters", []),
        }
        if schema.get("period"):
            entry["supports_period"] = True
        if schema.get("aggregations"):
            entry["aggregations"] = schema["aggregations"]
        if schema.get("group_by"):
            entry["group_by"] = schema["group_by"]
        result[name] = entry
    return {
        "entities": result,
        "periods": list(PERIOD_MAP.keys()),
    }
