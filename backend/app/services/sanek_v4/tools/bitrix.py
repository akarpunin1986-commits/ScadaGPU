"""
САНЁК v4 — Bitrix24 tools.

get_bitrix_tasks — list tasks from Bitrix24 project
create_bitrix_task — create task with auto-responsible and checklist
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from config import settings
from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek_v4.tools.bitrix")

# ── Bitrix24 Configuration ──

BITRIX_CONFIG = {
    "group_id": 46,
    "admin_user_id": 102,  # Карпунин А.
    "rate_limit": 2,       # req/sec
}

# Status codes mapping
STATUS_MAP = {
    2: "pending", 3: "in_progress", 4: "supposedly_completed",
    5: "completed", 6: "deferred", 7: "declined",
}

# Responsible mapping by site (fallback to admin)
RESPONSIBLE_USER_IDS = {
    "mkz": 104,   # Михайлов Алексей
    "yakz": 38,   # Ратников Сергей
}

RESPONSIBLE_NAMES = {
    "mkz": "Михайлов",
    "yakz": "Ратников",
}


async def _bitrix_call(method: str, params: dict | None = None) -> dict:
    """Call Bitrix24 REST API via app access_token (b24_app_call)."""
    from services.bitrix_bot import b24_app_call
    import redis.asyncio as aioredis

    redis = aioredis.from_url(settings.REDIS_URL)
    try:
        data = await b24_app_call(method, params or {}, redis=redis)
    except Exception:
        data = await b24_app_call(method, params or {}, redis=redis)
    finally:
        await redis.aclose()

    if "error" in data:
        raise RuntimeError(f"Bitrix24 API: {data['error']} — {data.get('error_description', '')}")
    return data


# ═══════════════════════════════════════════════════════════════
# TOOL: get_bitrix_tasks
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_bitrix_tasks",
    description=(
        "Получить задачи из Битрикс24 проекта 'Диспетчеризация' (GROUP_ID=46). "
        "Используй для: проверки существующих задач перед созданием новой (защита от дублей), "
        "просмотра просроченных задач, анализа загрузки ответственных. "
        "ВАЖНО: ВСЕГДА вызывай этот tool ПЕРЕД create_bitrix_task чтобы не создавать дубли."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "enum": ["active", "overdue", "completed", "all"],
                "description": "Статус задач. 'active' = незакрытые. 'overdue' = просроченные.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Фильтр по тегам. Примеры: "
                    "['ТО', 'mkz_dgu1'] — задачи ТО для МКЗ, "
                    "['АВАРМ', 'yakz_dgu1'] — аварийные задачи ЯКЗ."
                ),
            },
            "responsible": {
                "type": "string",
                "description": "Фильтр по ответственному: 'Михайлов' или 'Ратников'.",
            },
            "limit": {
                "type": "integer",
                "description": "Макс. количество задач (1-50). По умолчанию 20.",
            },
        },
    },
)
async def get_bitrix_tasks(
    filter: str = "active",
    tags: list[str] | None = None,
    responsible: str | None = None,
    limit: int = 20,
) -> dict:
    """Fetch tasks from Bitrix24."""
    limit = max(1, min(50, limit))

    # Build filter
    task_filter = {"GROUP_ID": BITRIX_CONFIG["group_id"]}

    if filter == "active":
        task_filter["!STATUS"] = 5
    elif filter == "completed":
        task_filter["STATUS"] = 5
    elif filter == "overdue":
        task_filter["!STATUS"] = 5
        task_filter["<DEADLINE"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    if tags:
        task_filter["TAG"] = tags

    if responsible:
        # Find user_id by name
        resp_lower = responsible.lower()
        for site, name in RESPONSIBLE_NAMES.items():
            if resp_lower in name.lower():
                uid = RESPONSIBLE_USER_IDS.get(site)
                if uid:
                    task_filter["RESPONSIBLE_ID"] = uid
                break

    try:
        data = await _bitrix_call("tasks.task.list", {
            "filter": task_filter,
            "select": ["ID", "TITLE", "STATUS", "RESPONSIBLE_ID", "DEADLINE",
                        "CREATED_DATE", "TAGS", "PRIORITY", "DESCRIPTION"],
            "order": {"DEADLINE": "asc"},
            "start": 0,
        })
    except Exception as e:
        return {"error": f"Bitrix24 API error: {str(e)}"}

    tasks_raw = data.get("result", {}).get("tasks", [])
    now = datetime.utcnow()

    tasks = []
    for t in tasks_raw[:limit]:
        status_code = int(t.get("status", 0))
        deadline_str = t.get("deadline", "")
        is_overdue = False
        if deadline_str and status_code != 5:
            try:
                dl = datetime.fromisoformat(deadline_str.replace("+00:00", ""))
                is_overdue = dl < now
            except Exception:
                pass

        tasks.append({
            "id": int(t.get("id", 0)),
            "title": t.get("title", ""),
            "status": STATUS_MAP.get(status_code, f"status_{status_code}"),
            "responsible_id": t.get("responsibleId"),
            "deadline": deadline_str[:10] if deadline_str else None,
            "overdue": is_overdue,
            "priority": "high" if t.get("priority") == "2" else "normal",
            "tags": t.get("tags", []),
            "created": (t.get("createdDate") or "")[:10],
        })

    return {
        "tasks": tasks,
        "total": len(tasks),
        "filter_applied": {"status": filter, "tags": tags, "responsible": responsible},
    }


# ═══════════════════════════════════════════════════════════════
# TOOL: create_bitrix_task
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="create_bitrix_task",
    description=(
        "Создать задачу в Битрикс24 проекте 'Диспетчеризация' (GROUP_ID=46). "
        "⚠️ ПЕРЕД ВЫЗОВОМ: ОБЯЗАТЕЛЬНО вызови get_bitrix_tasks с соответствующими тегами "
        "чтобы проверить нет ли уже открытой похожей задачи. Создание дубля — ошибка. "
        "Ответственный назначается автоматически по сайту: МКЗ→Михайлов, ЯКЗ→Ратников."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": (
                    "Заголовок задачи. Форматы: "
                    "'ТО-1 (250ч) — МКЗ ГПУ (Кама_Энерго)' для ТО, "
                    "'⚠️ АВАРМ: Low Oil Pressure — ЯКЗ ГПУ' для аварий."
                ),
            },
            "description": {
                "type": "string",
                "description": "Описание: текущие показания, причина создания, рекомендации.",
            },
            "responsible_site": {
                "type": "string",
                "enum": ["mkz", "yakz"],
                "description": "Сайт → авто-назначение ответственного.",
            },
            "priority": {
                "type": "string",
                "enum": ["normal", "high"],
                "description": "'high' для аварий, 'normal' для ТО.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Теги задачи. Примеры: "
                    "['ТО', 'to_1', 'МКЗ', 'mkz_dgu1'], "
                    "['АВАРМ', 'МКЗ', 'mkz_dgu1', 'low_oil_pressure']."
                ),
            },
            "deadline_days": {
                "type": "integer",
                "description": "Дедлайн через N дней. По умолчанию 7 для ТО, 1 для аварий.",
            },
            "checklist": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Чек-лист задачи. Каждый элемент — пункт проверки.",
            },
        },
        "required": ["title", "responsible_site", "tags"],
    },
)
async def create_bitrix_task(
    title: str,
    responsible_site: str,
    tags: list[str],
    description: str = "",
    priority: str = "normal",
    deadline_days: int = 7,
    checklist: list[str] | None = None,
) -> dict:
    """Create a task in Bitrix24 with auto-responsible and optional checklist."""
    # Resolve responsible
    user_id = RESPONSIBLE_USER_IDS.get(responsible_site, BITRIX_CONFIG["admin_user_id"])
    responsible_name = RESPONSIBLE_NAMES.get(responsible_site, "Карпунин")

    deadline = (datetime.utcnow() + timedelta(days=deadline_days)).strftime("%Y-%m-%dT23:59:59")

    try:
        # Create task
        data = await _bitrix_call("tasks.task.add", {
            "fields": {
                "TITLE": title,
                "DESCRIPTION": description or title,
                "RESPONSIBLE_ID": user_id,
                "GROUP_ID": BITRIX_CONFIG["group_id"],
                "PRIORITY": "2" if priority == "high" else "1",
                "DEADLINE": deadline,
                "TAGS": tags,
            },
        })

        task_id = data.get("result", {}).get("task", {}).get("id")
        if not task_id:
            return {"status": "error", "message": "Task created but no ID returned", "raw": data}

        # Add checklist items (with rate limiting)
        checklist_count = 0
        if checklist:
            for item in checklist:
                await asyncio.sleep(0.5)  # Bitrix rate limit: 2 req/sec
                try:
                    await _bitrix_call("task.checklistitem.add", {
                        "TASKID": task_id,
                        "FIELDS": {"TITLE": item},
                    })
                    checklist_count += 1
                except Exception as e:
                    logger.warning("Checklist item failed: %s", e)

        task_url = f"https://bricks-trade.bitrix24.ru/workgroups/group/46/tasks/task/view/{task_id}/"

        return {
            "status": "created",
            "task_id": int(task_id),
            "title": title,
            "responsible": responsible_name,
            "deadline": deadline[:10],
            "url": task_url,
            "checklist_items": checklist_count,
            "tags": tags,
        }

    except Exception as e:
        return {"status": "error", "message": f"Bitrix24 API error: {str(e)}", "code": "TASK_CREATE_FAILED"}
