"""
Санёк — AI-ассистент СКАДА с полным доступом к системе.

Использует LLM Tool Calling для взаимодействия с API СКАДА:
чтение метрик, управление устройствами, аварии, ТО, история.

Поддерживает OpenAI/Grok (SDK), Claude (httpx), Gemini (httpx).
Опасные команды (пуск/стоп/мощность) требуют подтверждения оператора.
"""
import json
import logging
from datetime import datetime
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger("scada.sanek")

# ---------------------------------------------------------------------------
# Provider display names
# ---------------------------------------------------------------------------
PROVIDER_LABELS = {"openai": "OpenAI", "claude": "Claude", "gemini": "Gemini", "grok": "Grok"}


def _format_llm_error(provider: str, error, status_code: int = 0) -> str:
    """
    Format LLM provider errors into human-readable Russian messages.
    Classifies by error type and provides actionable advice.
    """
    label = PROVIDER_LABELS.get(provider, provider)
    err_str = str(error).lower()

    # Auth errors (invalid API key)
    if status_code in (401, 403) or any(kw in err_str for kw in (
        "401", "403", "unauthorized", "authentication", "invalid api key",
        "incorrect api key", "invalid x-api-key", "permission denied",
    )):
        return (
            f"🔑 Ошибка авторизации: API ключ провайдера {label} недействителен "
            f"или отозван.\n\n"
            f"Откройте «🤖 AI Провайдер» в боковом меню и проверьте ключ."
        )

    # Rate limit
    if status_code == 429 or any(kw in err_str for kw in (
        "429", "rate limit", "rate_limit", "too many requests", "quota",
    )):
        return (
            f"⚡ Лимит запросов: провайдер {label} ограничил частоту обращений.\n\n"
            f"Подождите 30 секунд и повторите попытку."
        )

    # Timeout
    if any(kw in err_str for kw in (
        "timeout", "timed out", "timeouterror",
    )):
        return (
            f"⏱ Превышено время ожидания: провайдер {label} не ответил вовремя.\n\n"
            f"Возможно, сервер перегружен — попробуйте позже или смените провайдер."
        )

    # Connection / network errors
    if any(kw in err_str for kw in (
        "connecterror", "connectionerror", "connection refused",
        "name resolution", "unreachable", "no route", "dns",
        "failed to establish", "cannot connect",
    )):
        return (
            f"🌐 Нет связи с провайдером: не удалось подключиться к {label} API.\n\n"
            f"Проверьте доступ в интернет или попробуйте другой провайдер."
        )

    # Server errors (5xx)
    if status_code >= 500 or any(kw in err_str for kw in (
        "500", "502", "503", "504", "internal server error",
        "bad gateway", "service unavailable",
    )):
        return (
            f"🔧 Сервер провайдера {label} временно недоступен (ошибка {status_code or 'сервера'}).\n\n"
            f"Попробуйте позже или переключитесь на другой провайдер."
        )

    # Model not found
    if any(kw in err_str for kw in ("model not found", "model_not_found", "does not exist")):
        return (
            f"📋 Модель не найдена у провайдера {label}.\n\n"
            f"Откройте «🤖 AI Провайдер» и выберите корректную модель."
        )

    # Fallback — unknown error
    short_err = str(error)[:200]
    return (
        f"❌ Ошибка провайдера {label}: {short_err}\n\n"
        f"Попробуйте повторить или сменить провайдер в настройках."
    )


def _format_http_error(provider: str, status_code: int, error_body: str) -> str:
    """Format HTTP status errors for Claude/Gemini (non-SDK providers)."""
    return _format_llm_error(provider, error_body, status_code=status_code)


# ---------------------------------------------------------------------------
# Internal API base URL (within Docker network)
# ---------------------------------------------------------------------------
_API_BASE = "http://127.0.0.1:8000"

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SANEK_SYSTEM_PROMPT = """Ты — Санёк, AI-ассистент промышленной СКАДА-системы для дизельных и газовых генераторов.

ТВОИ ВОЗМОЖНОСТИ:
- Показать объекты, устройства, их статусы
- Показать текущие метрики: мощность, напряжение, ток, температура, обороты, уровень топлива
- Показать активные аварии и историю аварий
- Показать статус ТО (техобслуживания) и оповещения
- Показать историю метрик за период
- Дать общую сводку по системе
- Управлять генераторами: пуск, стоп, режим авто/ручной
- Устанавливать ограничения мощности P% и Q%
- Парсить документы ТО из Битрикс24

ПРАВИЛА:
1. Отвечай на русском. Будь кратким и точным.
2. Для ОПАСНЫХ действий (пуск, стоп, изменение мощности, смена режима) — ОБЯЗАТЕЛЬНО запроси подтверждение.
   Формат: опиши что собираешься сделать и попроси ответить "Да" для подтверждения.
3. Единицы: мощность в кВт, напряжение в В, ток в А, температура в °C, обороты в об/мин.
4. Если данных нет — так и скажи, не выдумывай.
5. Для сводки — используй get_system_summary, он вернёт всё сразу.
6. Имена устройств показывай как есть из системы.
7. Статусы переводи: online=работает, offline=отключен.
8. При ошибках API — сообщи оператору понятным языком.
9. КОНТЕКСТ СТРАНИЦЫ: если в сообщении есть "[Контекст оператора]" с site_id — ОБЯЗАТЕЛЬНО используй этот site_id при вызове get_devices, get_alarms и других инструментов, привязанных к объекту.
10. Если пользователь спрашивает об объекте по имени, а site_id не в контексте — сначала вызови get_sites, найди нужный ID, затем используй его.

СТРОГИЕ ПРАВИЛА ТОЧНОСТИ ДАННЫХ:
11. ЗАПРЕЩЕНО называть mains_total_p "общей мощностью" или "потреблением объекта". mains_total_p — это ТОЛЬКО мощность ввода сети. Суммарная нагрузка объекта = load_total_p (или mains_total_p + busbar_p).
12. Для ШПР (ATS) при ответе о мощности объекта ВСЕГДА используй поле load_total_p. Если его нет — вычисли: mains_total_p + busbar_p. НИКОГДА не выдавай mains_total_p как общую нагрузку.
13. Кратковременные выбросы или провалы (менее 1 минуты) НЕ считаются реальными событиями. Одиночное значение 0 среди нормальных данных — это сбой опроса Modbus, а НЕ реальное отключение. Сообщай только об устойчивых тенденциях (5+ минут подряд).
14. НЕ делай утверждений вида "мощность упала до 0" или "генератор останавливался", если нет НЕСКОЛЬКИХ ПОСЛЕДОВАТЕЛЬНЫХ точек данных, подтверждающих это. Одиночный ноль среди нормальных значений = артефакт связи Modbus.
15. При анализе трендов и истории: указывай ДИАПАЗОН значений (мин — макс) и СРЕДНЕЕ за период, а не выбирай одну экстремальную точку.
16. На вопрос "какая мощность?" отвечай СУММАРНОЙ нагрузкой объекта (load_total_p для ATS), а затем можешь разбить на составляющие (сеть + генераторы).

АВАРИИ И ДИАГНОСТИКА:
17. При ЛЮБОМ вопросе об ошибках, авариях, проблемах, состоянии — ОБЯЗАТЕЛЬНО вызови get_alarms.
    Результат get_alarms — это ТЕКУЩИЕ ПРОБЛЕМЫ, которые ПРОИСХОДЯТ ПРЯМО СЕЙЧАС.
    Поле "status: ⚠️ АКТИВНА СЕЙЧАС" означает, что проблема НЕ РЕШЕНА и ПРОДОЛЖАЕТСЯ.
    Поле "duration" показывает, СКОЛЬКО ВРЕМЕНИ проблема уже длится.
    CONN_LOST = устройство ПРЯМО СЕЙЧАС не на связи. Это НЕ историческое событие, а ТЕКУЩАЯ авария.
18. НЕ говори "всё работает нормально" или "ошибок нет", пока не вызовешь get_alarms и не убедишься, что список пуст.
    НЕ представляй активные аварии как прошедшие события. Если status="⚠️ АКТИВНА СЕЙЧАС" — говори "СЕЙЧАС есть проблема", а НЕ "была зарегистрирована авария".
19. При ответе об авариях: укажи имя устройства, тип аварии, сколько длится (поле duration), и рекомендации оператору.

СТИЛЬ ОТВЕТОВ:
20. Отвечай РАЗВЁРНУТО и ПОДРОБНО. На каждый вопрос давай максимально полный и информативный ответ.
21. При отчёте о метриках: не просто числа, а контекст. Пример: "Суммарная нагрузка объекта МКЗ — 248.8 кВт (из них 152.5 кВт от сети и 96.3 кВт от генераторов). Генераторы работают параллельно с сетью."
22. При отчёте об авариях: описывай каждую аварию подробно — что произошло, когда, на каком устройстве, как долго длится, каков приоритет, возможные действия оператора.
23. При сводке: дай полную картину — состояние каждого устройства, мощности, аварии, ТО. Не упускай деталей.
24. Используй структурированный формат: заголовки, списки, группировки. Не выдавай сырые коды — переводи в понятный язык (CONN_LOST → "Нет связи", SHUTDOWN → "Аварийный останов" и т.д.).
25. Если устройство offline — объясни последствия: данные не поступают, состояние неизвестно, нужна проверка связи.

КОНТЕКСТ ОБОРУДОВАНИЯ:
- Генераторы HGM9520N — дизельные/газопоршневые установки с контроллером Smartgen
- Панели ШПР HGM9560 — шкафы параллельной работы (АВР/синхронизация)
- Modbus TCP/RTU — промышленный протокол связи
- Метрики обновляются каждые 2-5 секунд через Modbus опрос

ВАЖНО — РАСЧЁТ МОЩНОСТЕЙ ШПР (HGM9560):
- mains_total_p — активная мощность на ВВОДЕ СЕТИ (P сети), кВт. Это то, что потребляется из внешней электросети.
- busbar_p — активная мощность ГЕНЕРАТОРОВ на шине, кВт. Это то, что вырабатывают генераторы.
- СУММАРНАЯ НАГРУЗКА ОБЪЕКТА = mains_total_p + busbar_p (P сети + P генераторов). Это ПОЛНОЕ потребление объекта.
- Если генераторы не работают (busbar_p=0), вся нагрузка = mains_total_p.
- Если сеть отключена (mains_total_p=0), вся нагрузка = busbar_p.
- При параллельной работе суммируются оба источника.
- mains_total_q — реактивная мощность сети, кВар.
- busbar_q — реактивная мощность генераторов, кВар.
- Всегда показывай СУММАРНУЮ нагрузку (mains_total_p + busbar_p) как "общее потребление объекта".

МЕТРИКИ ГЕНЕРАТОРА (HGM9520N):
- total_p — полная активная мощность генератора, кВт
- voltage_ab/bc/ca — линейные напряжения, В
- current_a/b/c — токи по фазам, А
- frequency — частота, Гц
- oil_pressure — давление масла, кПа
- coolant_temp — температура ОЖ, °C
- engine_speed — обороты двигателя, об/мин
- fuel_level — уровень топлива, %
- load_pct — нагрузка генератора, %
- run_hours/run_minutes — наработка, ч"""

# ---------------------------------------------------------------------------
# SCADA tool definitions for LLM function calling
# ---------------------------------------------------------------------------
SCADA_TOOLS = [
    {
        "name": "get_sites",
        "description": "Получить список всех объектов (площадок/станций) СКАДА.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_devices",
        "description": "Получить список устройств на объекте. Если site_id не указан — все устройства.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "integer",
                    "description": "ID объекта (опционально)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_metrics",
        "description": "Получить текущие метрики устройства. Для ШПР (ATS) поле load_total_p = суммарная нагрузка объекта (mains_total_p + busbar_p) в кВт. Для генераторов: total_p, напряжение, ток, температура, обороты, топливо.",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "integer",
                    "description": "ID устройства",
                },
            },
            "required": ["device_id"],
        },
    },
    {
        "name": "get_all_metrics",
        "description": "Получить текущие метрики ВСЕХ устройств сразу. Для ШПР (ATS) включает load_total_p — суммарная нагрузка объекта в кВт.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_alarms",
        "description": (
            "Получить ТЕКУЩИЕ АКТИВНЫЕ аварии (is_active=true). "
            "Сюда входят: CONN_LOST (нет связи с устройством), аппаратные аварии, предупреждения. "
            "ВСЕГДА вызывай этот инструмент при любом вопросе об ошибках, авариях, проблемах или состоянии системы. "
            "НЕ передавай device_id если хочешь увидеть ВСЕ аварии. "
            "Если в контексте есть site_id — передай site_id, а НЕ device_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "integer",
                    "description": "ID конкретного устройства (опционально). НЕ путай с site_id!",
                },
                "site_id": {
                    "type": "integer",
                    "description": "ID объекта — покажет аварии ВСЕХ устройств этого объекта.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_alarm_history",
        "description": (
            "Получить АРХИВ аварий: все события (активные + завершённые) за период. "
            "Активные аварии включаются всегда, даже если возникли раньше указанного периода. "
            "Используй для анализа истории: 'какие аварии были?', 'история ошибок'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "integer",
                    "description": "ID устройства (опционально)",
                },
                "last_hours": {
                    "type": "integer",
                    "description": "За последние N часов. Если не указано — все записи.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Макс. кол-во записей (по умолчанию 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_maintenance_status",
        "description": "Получить статус техобслуживания устройства: моточасы, следующее ТО, оставшиеся часы.",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "integer",
                    "description": "ID устройства",
                },
            },
            "required": ["device_id"],
        },
    },
    {
        "name": "get_maintenance_alerts",
        "description": "Получить оповещения о предстоящем или просроченном ТО.",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "integer",
                    "description": "ID устройства (опционально)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_history",
        "description": (
            "Получить историю метрик устройства за период. "
            "Для ГЕНЕРАТОРОВ: fields=power_total,gen_uab,current_a,coolant_temp,engine_speed. "
            "Для ШПР (ATS): fields=mains_total_p,busbar_p,load_total_p,mains_uab,busbar_uab. "
            "load_total_p = суммарная нагрузка объекта (mains_total_p + busbar_p), вычисляется автоматически. "
            "ВАЖНО: Для ATS НЕ используй power_total — это поле только для генераторов. "
            "Если fields не указан — поля выбираются автоматически по типу устройства."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "integer",
                    "description": "ID устройства",
                },
                "last_hours": {
                    "type": "integer",
                    "description": "За последние N часов (по умолчанию 24)",
                    "default": 24,
                },
                "fields": {
                    "type": "string",
                    "description": (
                        "Поля через запятую. "
                        "Генератор: power_total,gen_uab,current_a,coolant_temp. "
                        "ATS/ШПР: mains_total_p,busbar_p,load_total_p. "
                        "Если не указано — выбирается автоматически."
                    ),
                },
            },
            "required": ["device_id"],
        },
    },
    {
        "name": "get_system_summary",
        "description": "Получить полную сводку по системе: все объекты, устройства, их статусы, метрики, аварии, ТО — всё сразу.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "send_command",
        "description": "⚠ ОПАСНО: Отправить команду управления генератором. Команды: start (пуск), stop (стоп), auto (авто режим), manual (ручной режим). ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ ОПЕРАТОРА.",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "integer",
                    "description": "ID устройства",
                },
                "command": {
                    "type": "string",
                    "description": "Команда: start, stop, auto, manual",
                    "enum": ["start", "stop", "auto", "manual"],
                },
            },
            "required": ["device_id", "command"],
        },
    },
    {
        "name": "set_power_limit",
        "description": "⚠ ОПАСНО: Установить ограничение мощности P% и/или Q%. Значения 0-100%. ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ ОПЕРАТОРА.",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "integer",
                    "description": "ID устройства",
                },
                "p_percent": {
                    "type": "number",
                    "description": "Активная мощность P в % (0-100)",
                },
                "q_percent": {
                    "type": "number",
                    "description": "Реактивная мощность Q в % (0-100)",
                },
            },
            "required": ["device_id"],
        },
    },
]

# Commands that are dangerous and require confirmation
DANGEROUS_TOOLS = {"send_command", "set_power_limit"}

# Command descriptions for confirmation messages
COMMAND_LABELS = {
    "start": "Запуск",
    "stop": "Остановка",
    "auto": "Переключение в авто-режим",
    "manual": "Переключение в ручной режим",
}

# Modbus coil addresses for commands (HGM9520N)
COMMAND_ADDRESSES = {
    "start": (5, 0x0001, 0xFF00),   # FC05, coil 1, ON
    "stop": (5, 0x0002, 0xFF00),    # FC05, coil 2, ON
    "auto": (5, 0x0003, 0xFF00),    # FC05, coil 3, ON
    "manual": (5, 0x0004, 0xFF00),  # FC05, coil 4, ON
}


# ---------------------------------------------------------------------------
# Tool executor functions (call internal SCADA API via httpx)
# ---------------------------------------------------------------------------
async def _api_get(path: str, params: dict = None) -> dict:
    """GET request to internal SCADA API."""
    async with httpx.AsyncClient(base_url=_API_BASE, timeout=10) as client:
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


async def _api_post(path: str, data: dict = None) -> dict:
    """POST request to internal SCADA API."""
    async with httpx.AsyncClient(base_url=_API_BASE, timeout=15) as client:
        resp = await client.post(path, json=data or {})
        resp.raise_for_status()
        return resp.json()


async def execute_tool(name: str, args: dict) -> dict:
    """Execute a SCADA tool and return result."""
    try:
        if name == "get_sites":
            return await _api_get("/api/sites")

        elif name == "get_devices":
            params = {}
            if args.get("site_id"):
                params["site_id"] = args["site_id"]
            return await _api_get("/api/devices", params)

        elif name == "get_metrics":
            device_id = args["device_id"]
            data = await _api_get("/api/metrics", {"device_id": device_id})
            result = data[0] if isinstance(data, list) and data else data
            # Add hint for ATS to prevent LLM from confusing fields
            if isinstance(result, dict) and result.get("device_type") == "ats":
                result["_подсказка"] = (
                    "load_total_p — СУММАРНАЯ нагрузка объекта (сеть+генераторы). "
                    "mains_total_p — только мощность от сети. "
                    "busbar_p — только мощность генераторов на шине."
                )
            return result

        elif name == "get_all_metrics":
            return await _api_get("/api/metrics")

        elif name == "get_alarms":
            params = {}
            if args.get("device_id"):
                params["device_id"] = args["device_id"]
            alarms = await _api_get("/api/history/alarms/active", params)
            # If site_id provided, filter alarms to devices of that site
            site_id = args.get("site_id")
            site_device_ids = None
            if site_id:
                try:
                    devices = await _api_get("/api/devices", {"site_id": site_id})
                    site_device_ids = {d["id"] for d in devices} if isinstance(devices, list) else None
                except Exception:
                    site_device_ids = None
                if site_device_ids is not None and isinstance(alarms, list):
                    alarms = [a for a in alarms if a.get("device_id") in site_device_ids]
            # Enrich with device names, status and duration for LLM
            if isinstance(alarms, list) and alarms:
                try:
                    if site_device_ids is None:
                        devices = await _api_get("/api/devices")
                    dev_names = {d["id"]: d["name"] for d in devices} if isinstance(devices, list) else {}
                except Exception:
                    dev_names = {}
                for a in alarms:
                    a["device_name"] = dev_names.get(a.get("device_id"), f"Устройство #{a.get('device_id')}")
                    a["status"] = "⚠️ АКТИВНА СЕЙЧАС"
                    a["duration"] = _calc_alarm_duration(a.get("occurred_at"))
            return alarms

        elif name == "get_alarm_history":
            params = {"limit": args.get("limit", 50)}
            if args.get("device_id"):
                params["device_id"] = args["device_id"]
            if args.get("last_hours"):
                params["last_hours"] = args["last_hours"]
            alarms = await _api_get("/api/history/alarms", params)
            # Enrich with device names and duration for active alarms
            if isinstance(alarms, list) and alarms:
                try:
                    devices = await _api_get("/api/devices")
                    dev_names = {d["id"]: d["name"] for d in devices} if isinstance(devices, list) else {}
                except Exception:
                    dev_names = {}
                for a in alarms:
                    a["device_name"] = dev_names.get(a.get("device_id"), f"Устройство #{a.get('device_id')}")
                    if a.get("is_active"):
                        a["status"] = "⚠️ АКТИВНА СЕЙЧАС"
                        a["duration"] = _calc_alarm_duration(a.get("occurred_at"))
            return alarms

        elif name == "get_maintenance_status":
            device_id = args["device_id"]
            return await _api_get(f"/api/devices/{device_id}/maintenance")

        elif name == "get_maintenance_alerts":
            params = {}
            if args.get("device_id"):
                params["device_id"] = args["device_id"]
            return await _api_get("/api/alerts", params)

        elif name == "get_history":
            device_id = args["device_id"]
            fields = args.get("fields")
            if not fields:
                # Auto-detect device type to choose correct default fields
                try:
                    devs = await _api_get("/api/metrics", {"device_id": device_id})
                    d = devs[0] if isinstance(devs, list) and devs else {}
                    dt = d.get("device_type", "generator")
                except Exception:
                    dt = "generator"
                fields = "mains_total_p,busbar_p,load_total_p" if dt == "ats" else "power_total"
            params = {
                "last_hours": args.get("last_hours", 24),
                "fields": fields,
                "limit": 100,
            }
            return await _api_get(f"/api/history/metrics/{device_id}", params)

        elif name == "get_system_summary":
            return await _build_system_summary()

        elif name == "send_command":
            return await _execute_command(args["device_id"], args["command"])

        elif name == "set_power_limit":
            return await _execute_power_limit(
                args["device_id"],
                args.get("p_percent"),
                args.get("q_percent"),
            )

        else:
            return {"error": f"Неизвестный инструмент: {name}"}

    except httpx.HTTPStatusError as e:
        logger.error("Tool %s HTTP error: %s", name, e)
        return {"error": f"Ошибка API ({e.response.status_code}): {e.response.text[:200]}"}
    except Exception as e:
        logger.error("Tool %s error: %s", name, e, exc_info=True)
        return {"error": f"Ошибка: {str(e)}"}


def _calc_alarm_duration(occurred_at) -> str:
    """Вычислить человекочитаемую длительность аварии."""
    if not occurred_at:
        return "неизвестно"
    try:
        if isinstance(occurred_at, str):
            ts = datetime.fromisoformat(occurred_at.replace("Z", "").replace("+00:00", ""))
        else:
            ts = occurred_at
        delta = datetime.utcnow() - ts
        days = delta.days
        hours = delta.seconds // 3600
        mins = (delta.seconds % 3600) // 60
        parts = []
        if days > 0:
            parts.append(f"{days} дн.")
        if hours > 0:
            parts.append(f"{hours} ч.")
        if mins > 0 and days == 0:
            parts.append(f"{mins} мин.")
        return " ".join(parts) if parts else "только что"
    except Exception:
        return "неизвестно"


async def _build_system_summary() -> dict:
    """Build comprehensive system summary."""
    summary = {"sites": [], "total_devices": 0, "active_alarms": 0}

    try:
        sites = await _api_get("/api/sites")
        all_metrics = await _api_get("/api/metrics")
        alarms = await _api_get("/api/history/alarms/active")
        alert_summary = await _api_get("/api/alerts/summary")

        metrics_by_device = {}
        if isinstance(all_metrics, list):
            for m in all_metrics:
                did = m.get("device_id")
                if did:
                    metrics_by_device[did] = m

        for site in (sites if isinstance(sites, list) else []):
            devices = await _api_get("/api/devices", {"site_id": site["id"]})
            device_list = []
            for dev in (devices if isinstance(devices, list) else []):
                m = metrics_by_device.get(dev["id"], {})
                dev_type = dev.get("device_type", "")
                # Choose correct fields based on device type
                if dev_type == "ats":
                    power_kw = m.get("load_total_p")
                    voltage_v = m.get("mains_uab")
                else:
                    power_kw = m.get("power_total")
                    voltage_v = m.get("gen_uab")
                dev_info = {
                    "id": dev["id"],
                    "name": dev["name"],
                    "type": dev_type,
                    "online": m.get("online", False),
                    "power_kw": power_kw,
                    "voltage_v": voltage_v,
                    "coolant_temp": m.get("coolant_temp"),
                    "engine_speed": m.get("engine_speed"),
                    "run_hours": m.get("run_hours"),
                    "fuel_level": m.get("fuel_level"),
                    "gen_status": m.get("gen_status"),
                }
                # ATS-specific breakdown
                if dev_type == "ats":
                    dev_info["mains_p_kw"] = m.get("mains_total_p")
                    dev_info["busbar_p_kw"] = m.get("busbar_p")
                device_list.append(dev_info)
                summary["total_devices"] += 1
            summary["sites"].append({
                "id": site["id"],
                "name": site["name"],
                "code": site.get("code", ""),
                "devices": device_list,
            })

        # Build device name lookup for alarm enrichment
        device_names = {}
        for site_data in summary["sites"]:
            for dev in site_data.get("devices", []):
                device_names[dev["id"]] = dev["name"]

        # Active alarm details with status and duration
        if isinstance(alarms, list) and alarms:
            summary["active_alarms"] = len(alarms)
            summary["active_alarm_details"] = [
                {
                    "device_id": a["device_id"],
                    "device_name": device_names.get(a["device_id"], f"Устройство #{a['device_id']}"),
                    "alarm_code": a["alarm_code"],
                    "severity": a["severity"],
                    "message": a["message"],
                    "status": "⚠️ АКТИВНА СЕЙЧАС",
                    "duration": _calc_alarm_duration(a.get("occurred_at")),
                }
                for a in alarms
            ]
        else:
            summary["active_alarms"] = 0
            summary["active_alarm_details"] = []

        summary["maintenance_alerts"] = alert_summary if isinstance(alert_summary, dict) else {}

    except Exception as e:
        logger.error("Error building system summary: %s", e)
        summary["error"] = str(e)

    return summary


async def _execute_command(device_id: int, command: str) -> dict:
    """Execute a Modbus command on a device."""
    if command not in COMMAND_ADDRESSES:
        return {"error": f"Неизвестная команда: {command}"}

    fc, address, value = COMMAND_ADDRESSES[command]
    result = await _api_post("/api/commands", {
        "device_id": device_id,
        "function_code": fc,
        "address": address,
        "value": value,
    })
    return result


async def _execute_power_limit(
    device_id: int,
    p_percent: Optional[float] = None,
    q_percent: Optional[float] = None,
) -> dict:
    """Set power limit on a device."""
    # Read current values first
    current = await _api_get(f"/api/devices/{device_id}/power-limit")

    p_raw = int(p_percent * 10) if p_percent is not None else (current.get("config_p_raw") or 1000)
    q_raw = int(q_percent * 10) if q_percent is not None else (current.get("config_q_raw") or 1000)

    result = await _api_post(f"/api/devices/{device_id}/power-limit", {
        "p_raw": p_raw,
        "q_raw": q_raw,
    })
    return result


# ---------------------------------------------------------------------------
# Format tools for different LLM providers
# ---------------------------------------------------------------------------
def _tools_for_openai() -> list[dict]:
    """Format tools for OpenAI / Grok function calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in SCADA_TOOLS
    ]


def _tools_for_claude() -> list[dict]:
    """Format tools for Claude (Anthropic) tool use."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in SCADA_TOOLS
    ]


def _tools_for_gemini() -> list[dict]:
    """Format tools for Gemini function calling."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
        }
        for t in SCADA_TOOLS
    ]


# ---------------------------------------------------------------------------
# SanekAssistant — main class
# ---------------------------------------------------------------------------
class SanekAssistant:
    """
    AI assistant for SCADA operators.

    Usage:
        assistant = SanekAssistant(provider="openai", api_key="sk-...", model="gpt-4o")
        response = await assistant.chat(messages, pending_action=None)
    """

    def __init__(self, provider: str, api_key: str, model: str = ""):
        self.provider = provider
        self.api_key = api_key
        self.model = model or {
            "openai": "gpt-4o",
            "claude": "claude-sonnet-4-20250514",
            "gemini": "gemini-2.5-flash",
            "grok": "grok-3-mini",
        }.get(provider, "gpt-4o")
        self.timeout = settings.AI_TIMEOUT

    async def chat(
        self,
        messages: list[dict],
        pending_action: Optional[dict] = None,
    ) -> dict:
        """
        Process a chat turn with tool calling.

        Args:
            messages: Conversation history [{role, content}]
            pending_action: If set, user is confirming/declining a previous action.

        Returns:
            {
                "message": str,          # Assistant's text reply
                "actions": [...]          # Executed tool calls
                "pending_action": {...}   # If dangerous command needs confirmation
            }
        """
        # Handle pending action confirmation
        if pending_action:
            last_msg = messages[-1].get("content", "").strip().lower() if messages else ""
            if last_msg in ("да", "yes", "подтверждаю", "ок", "ok", "давай"):
                # Execute the confirmed action
                tool_name = pending_action["tool"]
                tool_args = pending_action["args"]
                logger.info("Executing confirmed action: %s(%s)", tool_name, tool_args)
                result = await execute_tool(tool_name, tool_args)
                return {
                    "message": f"✅ Выполнено: {pending_action.get('description', tool_name)}\n\nРезультат: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}",
                    "actions": [{"tool": tool_name, "args": tool_args, "result": result}],
                    "pending_action": None,
                }
            else:
                return {
                    "message": "❌ Действие отменено.",
                    "actions": [],
                    "pending_action": None,
                }

        # Build messages with system prompt
        full_messages = [{"role": "system", "content": SANEK_SYSTEM_PROMPT}] + messages

        # Call LLM with tools
        if self.provider in ("openai", "grok"):
            return await self._chat_openai(full_messages)
        elif self.provider == "claude":
            return await self._chat_claude(full_messages)
        elif self.provider == "gemini":
            return await self._chat_gemini(full_messages)
        else:
            return {"message": f"Неизвестный провайдер: {self.provider}", "actions": [], "pending_action": None}

    # ------------------------------------------------------------------
    # OpenAI / Grok
    # ------------------------------------------------------------------
    async def _chat_openai(self, messages: list[dict]) -> dict:
        from openai import AsyncOpenAI

        base_url = "https://api.x.ai/v1" if self.provider == "grok" else None
        client = AsyncOpenAI(
            api_key=self.api_key,
            timeout=self.timeout,
            base_url=base_url,
        )

        tools = _tools_for_openai()
        actions = []

        # Allow up to 5 tool call rounds
        for _ in range(5):
            try:
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    temperature=0.3,
                )
            except Exception as e:
                logger.error("OpenAI/Grok error: %s", e)
                return {"message": _format_llm_error(self.provider, e), "actions": actions, "pending_action": None}

            choice = response.choices[0]

            # If tool calls requested
            if choice.message.tool_calls:
                messages.append(choice.message.model_dump())

                for tc in choice.message.tool_calls:
                    tool_name = tc.function.name
                    tool_args = json.loads(tc.function.arguments) if tc.function.arguments else {}

                    logger.info("Tool call: %s(%s)", tool_name, tool_args)

                    # Check if dangerous — return pending action
                    if tool_name in DANGEROUS_TOOLS:
                        pending = self._build_pending_action(tool_name, tool_args)
                        return {
                            "message": pending["description"],
                            "actions": actions,
                            "pending_action": pending,
                        }

                    # Execute safe tool
                    result = await execute_tool(tool_name, tool_args)
                    actions.append({"tool": tool_name, "args": tool_args, "result": result})

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })

                continue  # Next round with tool results

            # No more tool calls — return final text
            text = choice.message.content or ""
            return {"message": text, "actions": actions, "pending_action": None}

        # Max rounds reached
        return {"message": "Достигнут лимит вызовов инструментов.", "actions": actions, "pending_action": None}

    # ------------------------------------------------------------------
    # Claude (Anthropic)
    # ------------------------------------------------------------------
    async def _chat_claude(self, messages: list[dict]) -> dict:
        tools = _tools_for_claude()
        actions = []

        # Separate system prompt from messages
        system_text = ""
        chat_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            else:
                chat_msgs.append(m)

        for _ in range(5):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as http:
                    body = {
                        "model": self.model,
                        "max_tokens": 4096,
                        "system": system_text.strip(),
                        "messages": chat_msgs,
                        "tools": tools,
                        "temperature": 0.3,
                    }
                    resp = await http.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": self.api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json=body,
                    )
            except Exception as e:
                logger.error("Claude error: %s", e)
                return {"message": _format_llm_error("claude", e), "actions": actions, "pending_action": None}

            if resp.status_code != 200:
                try:
                    err = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    err = resp.text[:200]
                return {"message": _format_http_error("claude", resp.status_code, err), "actions": actions, "pending_action": None}

            data = resp.json()
            stop_reason = data.get("stop_reason", "")
            content_blocks = data.get("content", [])

            # Collect text and tool_use blocks
            text_parts = []
            tool_uses = []
            for block in content_blocks:
                if block["type"] == "text":
                    text_parts.append(block["text"])
                elif block["type"] == "tool_use":
                    tool_uses.append(block)

            if tool_uses:
                # Add assistant message with all content blocks
                chat_msgs.append({"role": "assistant", "content": content_blocks})

                tool_results = []
                for tu in tool_uses:
                    tool_name = tu["name"]
                    tool_args = tu.get("input", {})

                    logger.info("Claude tool call: %s(%s)", tool_name, tool_args)

                    # Check if dangerous
                    if tool_name in DANGEROUS_TOOLS:
                        pending = self._build_pending_action(tool_name, tool_args)
                        text = "\n".join(text_parts) if text_parts else ""
                        return {
                            "message": (text + "\n\n" + pending["description"]).strip(),
                            "actions": actions,
                            "pending_action": pending,
                        }

                    result = await execute_tool(tool_name, tool_args)
                    actions.append({"tool": tool_name, "args": tool_args, "result": result})

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })

                chat_msgs.append({"role": "user", "content": tool_results})
                continue

            # No tool calls — return text
            text = "\n".join(text_parts)
            return {"message": text, "actions": actions, "pending_action": None}

        return {"message": "Достигнут лимит вызовов инструментов.", "actions": actions, "pending_action": None}

    # ------------------------------------------------------------------
    # Gemini
    # ------------------------------------------------------------------
    async def _chat_gemini(self, messages: list[dict]) -> dict:
        tools = _tools_for_gemini()
        actions = []

        # Convert messages to Gemini format
        gemini_contents = []
        system_text = ""
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            elif m["role"] == "user":
                gemini_contents.append({"role": "user", "parts": [{"text": m["content"]}]})
            elif m["role"] == "assistant":
                gemini_contents.append({"role": "model", "parts": [{"text": m.get("content", "")}]})

        # Prepend system as first user message if needed
        if system_text and gemini_contents:
            first = gemini_contents[0]
            if first["role"] == "user":
                first["parts"][0]["text"] = system_text.strip() + "\n\n" + first["parts"][0]["text"]

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

        for _ in range(5):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as http:
                    body = {
                        "contents": gemini_contents,
                        "tools": [{"function_declarations": tools}],
                        "generationConfig": {
                            "temperature": 0.3,
                            "maxOutputTokens": 4096,
                        },
                    }
                    resp = await http.post(url, json=body)
            except Exception as e:
                logger.error("Gemini error: %s", e)
                return {"message": _format_llm_error("gemini", e), "actions": actions, "pending_action": None}

            if resp.status_code != 200:
                try:
                    err = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    err = resp.text[:200]
                return {"message": _format_http_error("gemini", resp.status_code, err), "actions": actions, "pending_action": None}

            data = resp.json()
            candidate = data.get("candidates", [{}])[0]
            parts = candidate.get("content", {}).get("parts", [])

            text_parts = []
            function_calls = []
            for part in parts:
                if "text" in part:
                    text_parts.append(part["text"])
                if "functionCall" in part:
                    function_calls.append(part["functionCall"])

            if function_calls:
                # Add model response
                gemini_contents.append({"role": "model", "parts": parts})

                func_responses = []
                for fc in function_calls:
                    tool_name = fc["name"]
                    tool_args = fc.get("args", {})

                    logger.info("Gemini tool call: %s(%s)", tool_name, tool_args)

                    if tool_name in DANGEROUS_TOOLS:
                        pending = self._build_pending_action(tool_name, tool_args)
                        text = "\n".join(text_parts) if text_parts else ""
                        return {
                            "message": (text + "\n\n" + pending["description"]).strip(),
                            "actions": actions,
                            "pending_action": pending,
                        }

                    result = await execute_tool(tool_name, tool_args)
                    actions.append({"tool": tool_name, "args": tool_args, "result": result})

                    func_responses.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": result,
                        }
                    })

                gemini_contents.append({"role": "user", "parts": func_responses})
                continue

            text = "\n".join(text_parts)
            return {"message": text, "actions": actions, "pending_action": None}

        return {"message": "Достигнут лимит вызовов инструментов.", "actions": actions, "pending_action": None}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_pending_action(self, tool_name: str, tool_args: dict) -> dict:
        """Build a pending action that requires operator confirmation."""
        if tool_name == "send_command":
            cmd = tool_args.get("command", "")
            dev_id = tool_args.get("device_id", "?")
            label = COMMAND_LABELS.get(cmd, cmd)
            desc = f"⚠ {label} устройства ID={dev_id}?\n\nОтветьте «Да» для подтверждения или «Нет» для отмены."
        elif tool_name == "set_power_limit":
            dev_id = tool_args.get("device_id", "?")
            p = tool_args.get("p_percent", "—")
            q = tool_args.get("q_percent", "—")
            desc = f"⚠ Установить ограничение мощности для устройства ID={dev_id}: P={p}%, Q={q}%?\n\nОтветьте «Да» для подтверждения или «Нет» для отмены."
        else:
            desc = f"⚠ Выполнить {tool_name}?"

        return {
            "tool": tool_name,
            "args": tool_args,
            "description": desc,
        }
