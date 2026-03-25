"""
САНЁК v4 — Task Manager tools.

get_scada_tasks — query ScadaTask with filters
create_scada_task — create task via TaskEngine
get_scada_task_details — full task details with relations
upload_maintenance_card — parse maintenance card from file
get_executor_stats — executor performance statistics
escalate_task — manual escalation
get_maintenance_status — equipment maintenance status
record_maintenance — record completed maintenance
update_equipment_hours — manual hours update
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select

from config import settings
from models.base import async_session
from models.task_manager import (
    EscalationLog,
    MaintenanceCard,
    ScadaTask,
    TaskCommunication,
    TaskQualityCheck,
)
from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek_v4.tools.task_tools")


# ═══════════════════════════════════════════════════════════════
# TOOL: get_scada_tasks
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_scada_tasks",
    description=(
        "Получить задачи SCADA Task Manager с фильтрами. "
        "Используй для: просмотра открытых задач, просроченных, "
        "по оборудованию, по типу (maintenance/incident). "
        "Возвращает список задач с основными полями."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["created", "in_progress", "completed", "escalated", "all"],
                "description": "Фильтр по статусу. 'all' = все статусы.",
            },
            "task_type": {
                "type": "string",
                "enum": ["maintenance", "incident", "manual"],
                "description": "Тип задачи: ТО, инцидент или ручная.",
            },
            "equipment_code": {
                "type": "string",
                "description": "Код оборудования, например 'mkz_dgu1'.",
            },
            "overdue_only": {
                "type": "boolean",
                "description": "Только просроченные задачи.",
            },
            "limit": {
                "type": "integer",
                "description": "Макс. количество задач (1-50). По умолчанию 10.",
            },
        },
    },
)
async def get_scada_tasks(
    status: str = "all",
    task_type: str | None = None,
    equipment_code: str | None = None,
    overdue_only: bool = False,
    limit: int = 10,
) -> dict:
    """Query ScadaTask with filters."""
    limit = max(1, min(50, limit))

    async with async_session() as session:
        stmt = select(ScadaTask).order_by(ScadaTask.created_at.desc())

        if status and status != "all":
            stmt = stmt.where(ScadaTask.status == status)

        if task_type:
            stmt = stmt.where(ScadaTask.task_type == task_type)

        if equipment_code:
            stmt = stmt.where(ScadaTask.equipment_code == equipment_code)

        if overdue_only:
            now = datetime.utcnow()
            stmt = stmt.where(
                ScadaTask.deadline < now,
                ScadaTask.status.notin_(["completed", "closed"]),
            )

        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

        tasks = []
        now = datetime.utcnow()
        for t in rows:
            is_overdue = (
                t.deadline < now and t.status not in ("completed", "closed")
                if t.deadline
                else False
            )
            tasks.append({
                "id": t.id,
                "title": t.title,
                "type": t.task_type,
                "status": t.status,
                "priority": t.priority,
                "equipment": t.equipment_code,
                "responsible": t.responsible_name,
                "deadline": t.deadline.isoformat()[:10] if t.deadline else None,
                "overdue": is_overdue,
                "quality_status": t.quality_status,
                "created_at": t.created_at.isoformat()[:10] if t.created_at else None,
            })

        return {
            "tasks": tasks,
            "total": len(tasks),
            "filters": {
                "status": status,
                "task_type": task_type,
                "equipment_code": equipment_code,
                "overdue_only": overdue_only,
            },
        }


# ═══════════════════════════════════════════════════════════════
# TOOL: create_scada_task
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="create_scada_task",
    description=(
        "Создать задачу в SCADA Task Manager. Задача автоматически "
        "синхронизируется в Bitrix24. Используй для: создания задач ТО, "
        "ручных задач, инцидентов. ВАЖНО: перед созданием проверь "
        "get_scada_tasks чтобы избежать дублей."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Заголовок задачи.",
            },
            "equipment_code": {
                "type": "string",
                "description": "Код оборудования: 'mkz_dgu1', 'yakz_dgu1' и т.д.",
            },
            "description": {
                "type": "string",
                "description": "Описание задачи: причина, рекомендации.",
            },
            "priority": {
                "type": "integer",
                "enum": [0, 1, 2],
                "description": "Приоритет: 0=низкий, 1=нормальный, 2=высокий.",
            },
            "deadline_days": {
                "type": "integer",
                "description": "Дедлайн через N дней. По умолчанию 7.",
            },
        },
        "required": ["title"],
    },
)
async def create_scada_task(
    title: str,
    equipment_code: str | None = None,
    description: str | None = None,
    priority: int = 1,
    deadline_days: int = 7,
) -> dict:
    """Create a task via TaskEngine."""
    # Lazy import to avoid circular dependency
    from services.task_manager.task_engine import TaskEngine
    import redis.asyncio as aioredis

    try:
        redis = aioredis.from_url(settings.REDIS_URL)
        engine = TaskEngine(redis)

        # Resolve site_id from equipment_code
        site_id = None
        if equipment_code:
            if equipment_code.startswith("mkz"):
                site_id = 3
            elif equipment_code.startswith("yakz") or equipment_code.startswith("ykz"):
                site_id = 5

        deadline = datetime.utcnow() + timedelta(days=deadline_days)

        task = await engine.create_task(
            task_type="manual",
            trigger_source="sanek_tool",
            title=title,
            priority=priority,
            equipment_code=equipment_code,
            site_id=site_id,
            description=description,
            deadline=deadline,
            creator="sanek",
        )

        await redis.aclose()

        if task is None:
            return {
                "status": "skipped",
                "message": "Задача не создана — возможный дубль.",
            }

        return {
            "status": "created",
            "task_id": task.id,
            "title": task.title,
            "bitrix_task_id": task.bitrix_task_id,
            "deadline": task.deadline.isoformat()[:10] if task.deadline else None,
            "responsible": task.responsible_name,
        }

    except Exception as e:
        logger.exception("create_scada_task failed: %s", e)
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════
# TOOL: get_scada_task_details
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_scada_task_details",
    description=(
        "Получить полную информацию о задаче SCADA по ID. "
        "Включает: коммуникации, эскалации, проверки качества."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "ID задачи в SCADA Task Manager.",
            },
        },
        "required": ["task_id"],
    },
)
async def get_scada_task_details(task_id: int) -> dict:
    """Full task details with communications, escalations, quality."""
    async with async_session() as session:
        task = await session.get(ScadaTask, task_id)
        if not task:
            return {"error": f"Задача #{task_id} не найдена."}

        # Communications
        comms_stmt = (
            select(TaskCommunication)
            .where(TaskCommunication.task_id == task_id)
            .order_by(TaskCommunication.created_at.desc())
            .limit(20)
        )
        comms = (await session.execute(comms_stmt)).scalars().all()

        # Escalations
        esc_stmt = (
            select(EscalationLog)
            .where(EscalationLog.task_id == task_id)
            .order_by(EscalationLog.created_at.desc())
        )
        escalations = (await session.execute(esc_stmt)).scalars().all()

        # Quality checks
        quality_stmt = (
            select(TaskQualityCheck)
            .where(TaskQualityCheck.task_id == task_id)
            .order_by(TaskQualityCheck.checked_at.desc())
        )
        quality_checks = (await session.execute(quality_stmt)).scalars().all()

        return {
            "task": {
                "id": task.id,
                "title": task.title,
                "type": task.task_type,
                "status": task.status,
                "priority": task.priority,
                "equipment": task.equipment_code,
                "responsible": task.responsible_name,
                "responsible_user_id": task.responsible_user_id,
                "creator": task.creator,
                "bitrix_task_id": task.bitrix_task_id,
                "deadline": task.deadline.isoformat() if task.deadline else None,
                "escalation_level": task.escalation_level,
                "quality_status": task.quality_status,
                "quality_score": task.quality_score,
                "description": task.description,
                "tags": task.tags,
                "alarm_name": task.alarm_name,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            },
            "communications": [
                {
                    "id": c.id,
                    "channel": c.channel,
                    "direction": c.direction,
                    "sender": c.sender,
                    "recipient": c.recipient_name,
                    "message_type": c.message_type,
                    "message": c.message_text[:200],
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in comms
            ],
            "escalations": [
                {
                    "level": e.level,
                    "level_name": e.level_name,
                    "target": e.target_name,
                    "reason": e.reason,
                    "resolved": e.resolved,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in escalations
            ],
            "quality_checks": [
                {
                    "type": q.check_type,
                    "passed": q.passed,
                    "details": q.details,
                    "checked_at": q.checked_at.isoformat() if q.checked_at else None,
                }
                for q in quality_checks
            ],
        }


# ═══════════════════════════════════════════════════════════════
# TOOL: upload_maintenance_card
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="upload_maintenance_card",
    description=(
        "Загрузить и распарсить карточку ТО из файла (Word/PDF). "
        "Файл должен быть доступен по пути на сервере. "
        "Возвращает preview с количеством интервалов, работ, запчастей."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Путь к файлу на сервере (.docx или .pdf).",
            },
            "equipment_hint": {
                "type": "string",
                "description": "Подсказка: для какого оборудования карточка.",
            },
        },
        "required": ["file_path"],
    },
)
async def upload_maintenance_card(
    file_path: str,
    equipment_hint: str | None = None,
) -> dict:
    """Parse a maintenance card file and return preview."""
    import os
    if not os.path.exists(file_path):
        return {"error": f"Файл не найден: {file_path}"}

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".pdf", ".docx", ".doc"):
        return {"error": f"Неподдерживаемый формат: {ext}. Нужен .pdf или .docx"}

    try:
        from services.maintenance import card_parser
        result = await card_parser.parse_card(file_path, method="auto")
        parsed = result.get("parsed")

        return {
            "status": "parsed",
            "method": result.get("method"),
            "confidence": result.get("confidence"),
            "equipment_hint": equipment_hint,
            "intervals_count": len(parsed.intervals) if parsed else 0,
            "intervals": [
                {"name": iv.name, "code": iv.code, "type": iv.interval_type, "hours": iv.interval_value}
                for iv in (parsed.intervals if parsed else [])
            ],
        }
    except Exception as e:
        logger.exception("upload_maintenance_card failed: %s", e)
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════
# TOOL: get_executor_stats
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_executor_stats",
    description=(
        "Получить статистику исполнителя: количество задач, "
        "процент просроченных, среднее время выполнения."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "integer",
                "description": "Bitrix24 user ID исполнителя.",
            },
        },
        "required": ["user_id"],
    },
)
async def get_executor_stats(user_id: int) -> dict:
    """Get executor performance statistics."""
    async with async_session() as session:
        # Total tasks
        total_stmt = select(func.count(ScadaTask.id)).where(
            ScadaTask.responsible_user_id == user_id
        )
        total = (await session.execute(total_stmt)).scalar() or 0

        if total == 0:
            return {
                "user_id": user_id,
                "total_tasks": 0,
                "message": "Нет задач для этого исполнителя.",
            }

        # Completed tasks
        completed_stmt = select(func.count(ScadaTask.id)).where(
            ScadaTask.responsible_user_id == user_id,
            ScadaTask.status == "completed",
        )
        completed = (await session.execute(completed_stmt)).scalar() or 0

        # Overdue tasks (not completed and past deadline)
        now = datetime.utcnow()
        overdue_stmt = select(func.count(ScadaTask.id)).where(
            ScadaTask.responsible_user_id == user_id,
            ScadaTask.deadline < now,
            ScadaTask.status.notin_(["completed", "closed"]),
        )
        overdue = (await session.execute(overdue_stmt)).scalar() or 0

        # Average completion time (hours) for completed tasks
        avg_time_stmt = select(
            func.avg(
                func.extract("epoch", ScadaTask.completed_at - ScadaTask.created_at) / 3600
            )
        ).where(
            ScadaTask.responsible_user_id == user_id,
            ScadaTask.status == "completed",
            ScadaTask.completed_at.isnot(None),
        )
        avg_hours = (await session.execute(avg_time_stmt)).scalar()

        # Average quality score
        avg_quality_stmt = select(func.avg(ScadaTask.quality_score)).where(
            ScadaTask.responsible_user_id == user_id,
            ScadaTask.quality_score.isnot(None),
        )
        avg_quality = (await session.execute(avg_quality_stmt)).scalar()

        overdue_rate = overdue / total if total > 0 else 0

        return {
            "user_id": user_id,
            "total_tasks": total,
            "completed": completed,
            "overdue": overdue,
            "overdue_rate": round(overdue_rate, 2),
            "avg_completion_hours": round(avg_hours, 1) if avg_hours else None,
            "avg_quality_score": round(avg_quality, 2) if avg_quality else None,
            "completion_rate": round(completed / total, 2) if total > 0 else 0,
        }


# ═══════════════════════════════════════════════════════════════
# TOOL: escalate_task
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="escalate_task",
    description=(
        "Ручная эскалация задачи SCADA. Используй когда: "
        "задача застряла, исполнитель не отвечает, срочная ситуация. "
        "Создаёт запись в escalation_log и уведомляет руководителя."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "ID задачи для эскалации.",
            },
            "reason": {
                "type": "string",
                "description": "Причина эскалации.",
            },
        },
        "required": ["task_id", "reason"],
    },
)
async def escalate_task(task_id: int, reason: str) -> dict:
    """Manual task escalation."""
    async with async_session() as session:
        task = await session.get(ScadaTask, task_id)
        if not task:
            return {"error": f"Задача #{task_id} не найдена."}

        if task.status in ("completed", "closed"):
            return {
                "error": f"Задача #{task_id} уже {task.status}, эскалация невозможна.",
            }

        # Increment escalation level
        new_level = task.escalation_level + 1
        level_names = {1: "soft_reminder", 2: "hard", 3: "manager", 4: "founder"}
        level_name = level_names.get(new_level, f"level_{new_level}")

        # Create escalation log entry
        escalation = EscalationLog(
            task_id=task_id,
            level=new_level,
            level_name=level_name,
            target_user_id=task.responsible_user_id,
            target_name=task.responsible_name,
            reason=reason,
            channel="sanek_tool",
            message_text=f"Ручная эскалация: {reason}",
        )
        session.add(escalation)

        task.escalation_level = new_level
        task.last_escalation_at = datetime.utcnow()
        task.status = "escalated"

        await session.commit()

        logger.info(
            "task %d escalated to level %d (%s) by sanek tool: %s",
            task_id,
            new_level,
            level_name,
            reason,
        )

        return {
            "status": "escalated",
            "task_id": task_id,
            "new_level": new_level,
            "level_name": level_name,
            "reason": reason,
            "responsible": task.responsible_name,
        }


# ═══════════════════════════════════════════════════════════════
# TOOL: create_scada_rule
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="create_scada_rule",
    description=(
        "Создать автоматическое правило СКАДА. "
        "Триггеры: alarm (аларм/ошибка), metric_threshold (порог параметра), "
        "schedule (расписание), hours_threshold (моточасы). "
        "Действия: create_task (задача), notify (уведомление), create_task_and_notify (оба)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Название правила"},
            "trigger_type": {
                "type": "string",
                "enum": ["alarm", "metric_threshold", "schedule", "hours_threshold"],
                "description": "Тип триггера.",
            },
            "trigger_config": {
                "type": "object",
                "description": (
                    "Конфигурация триггера. "
                    "alarm: {severity_min, alarm_codes, any}. "
                    "metric_threshold: {metric, operator, value, device_id}. "
                    "schedule: {interval_hours, interval_days}. "
                    "hours_threshold: {interval_hours, maintenance_type}"
                ),
            },
            "action_type": {
                "type": "string",
                "enum": ["create_task", "notify", "create_task_and_notify"],
                "description": "Тип действия.",
            },
            "action_config": {
                "type": "object",
                "description": "Конфиг действия. create_task: {priority, deadline_days}. notify: {message_template}",
            },
            "equipment_code": {
                "type": "string",
                "description": "Код оборудования: mkz_dgu1, yakz_dgu1",
            },
            "executor_name": {
                "type": "string",
                "description": "Имя исполнителя",
            },
            "sanek_control": {
                "type": "boolean",
                "description": "Санёк контролирует исполнение",
                "default": True,
            },
        },
        "required": ["name", "trigger_type", "action_type"],
    },
)
async def create_scada_rule(
    name: str,
    trigger_type: str,
    action_type: str,
    trigger_config: dict | None = None,
    action_config: dict | None = None,
    equipment_code: str | None = None,
    executor_name: str | None = None,
    sanek_control: bool = True,
) -> dict:
    """Create an automation rule via Sanek tool."""
    from models.scada_rule import ScadaRule

    try:
        async with async_session() as session:
            rule = ScadaRule(
                name=name,
                trigger_type=trigger_type,
                trigger_config=trigger_config or {},
                action_type=action_type,
                action_config=action_config or {},
                equipment_code=equipment_code,
                executor_name=executor_name,
                sanek_control=sanek_control,
                created_by="sanek",
            )
            session.add(rule)
            await session.commit()
            await session.refresh(rule)
            return {
                "status": "created",
                "rule_id": rule.id,
                "name": rule.name,
                "trigger_type": rule.trigger_type,
                "action_type": rule.action_type,
            }
    except Exception as e:
        logger.exception("create_scada_rule failed: %s", e)
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════
# TOOL: get_maintenance_status
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_maintenance_status",
    description=(
        "Получить статус ТО оборудования: наработка, ближайшее ТО, "
        "предстоящие ТО. Без параметров — общий дашборд по всему "
        "оборудованию. С equipment_code — детальный статус одного."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "equipment_code": {
                "type": "string",
                "description": "Код оборудования (mkz_dgu1, yakz_dgu1...). Без кода — все.",
            },
            "equipment_id": {
                "type": "integer",
                "description": "ID оборудования (альтернатива equipment_code).",
            },
        },
    },
)
async def get_maintenance_status(
    equipment_code: str | None = None,
    equipment_id: int | None = None,
) -> dict:
    """Get equipment maintenance status."""
    from services.maintenance import lifecycle as maint_lifecycle
    from models.equipment_unit import EquipmentUnit

    try:
        async with async_session() as session:
            if equipment_code:
                eq = (await session.execute(
                    select(EquipmentUnit).where(EquipmentUnit.code == equipment_code)
                )).scalar_one_or_none()
                if not eq:
                    return {"error": f"Оборудование '{equipment_code}' не найдено."}
                equipment_id = eq.id

            if equipment_id:
                status = await maint_lifecycle.get_equipment_status(equipment_id, session)
                return status.model_dump()
            else:
                statuses = await maint_lifecycle.get_all_equipment_status(session)
                overdue = [s for s in statuses if s.status == "overdue"]
                warning = [s for s in statuses if s.status == "warning"]
                return {
                    "total": len(statuses),
                    "overdue": len(overdue),
                    "warning": len(warning),
                    "equipment": [
                        {
                            "name": s.equipment_name,
                            "type": s.equipment_type,
                            "status": s.status,
                            "operating_hours": s.operating_hours,
                            "next_maintenance": (
                                {
                                    "name": s.next_maintenance.interval_name,
                                    "code": s.next_maintenance.interval_code,
                                    "remaining_hours": s.next_maintenance.remaining_hours,
                                    "remaining_days": s.next_maintenance.remaining_days,
                                }
                                if s.next_maintenance else None
                            ),
                        }
                        for s in statuses
                    ],
                }
    except Exception as e:
        logger.exception("get_maintenance_status failed: %s", e)
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════
# TOOL: record_maintenance
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="record_maintenance",
    description=(
        "Записать выполненное ТО для оборудования. "
        "Нужен код оборудования и код интервала (TO-1, ETO, KR...). "
        "Автоматически каскадирует вложенные интервалы."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "equipment_code": {
                "type": "string",
                "description": "Код оборудования: mkz_dgu1, yakz_dgu1 и т.д.",
            },
            "interval_code": {
                "type": "string",
                "description": "Код интервала ТО: ETO, TO-1, TO-2, KR.",
            },
            "performed_by": {
                "type": "string",
                "description": "Кто выполнил ТО. По умолчанию 'sanek'.",
            },
            "notes": {
                "type": "string",
                "description": "Примечания к выполненному ТО.",
            },
        },
        "required": ["equipment_code", "interval_code"],
    },
)
async def record_maintenance_tool(
    equipment_code: str,
    interval_code: str,
    performed_by: str = "sanek",
    notes: str | None = None,
) -> dict:
    """Record completed maintenance via Sanek tool."""
    from services.maintenance import lifecycle as maint_lifecycle
    from models.equipment_unit import EquipmentUnit

    try:
        async with async_session() as session:
            eq = (await session.execute(
                select(EquipmentUnit).where(EquipmentUnit.code == equipment_code)
            )).scalar_one_or_none()
            if not eq:
                return {"error": f"Оборудование '{equipment_code}' не найдено."}

            log_entry = await maint_lifecycle.record_maintenance(
                equipment_id=eq.id,
                interval_code=interval_code,
                performed_by=performed_by,
                performed_date=datetime.utcnow(),
                session=session,
                notes=notes,
            )

            return {
                "status": "recorded",
                "log_id": log_entry.id,
                "equipment": equipment_code,
                "interval_code": interval_code,
                "operating_hours": log_entry.operating_hours,
                "performed_by": performed_by,
            }

    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("record_maintenance failed: %s", e)
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════
# TOOL: update_equipment_hours
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="update_equipment_hours",
    description=(
        "Ручной ввод моточасов (наработки) для оборудования с "
        "hours_source='manual'. Обновляет current_value в equipment_units."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "equipment_code": {
                "type": "string",
                "description": "Код оборудования: mkz_dgu1, yakz_dgu1 и т.д.",
            },
            "hours": {
                "type": "integer",
                "description": "Новое значение счётчика (моточасы).",
            },
        },
        "required": ["equipment_code", "hours"],
    },
)
async def update_equipment_hours(equipment_code: str, hours: int) -> dict:
    """Manual hours update for equipment."""
    from models.equipment_unit import EquipmentUnit

    try:
        async with async_session() as session:
            eq = (await session.execute(
                select(EquipmentUnit).where(EquipmentUnit.code == equipment_code)
            )).scalar_one_or_none()
            if not eq:
                return {"error": f"Оборудование '{equipment_code}' не найдено."}

            if eq.hours_source != "manual":
                return {
                    "error": (
                        f"Оборудование '{equipment_code}' использует "
                        f"hours_source='{eq.hours_source}'. "
                        "Ручной ввод только для 'manual'."
                    ),
                }

            old_value = eq.current_value
            eq.current_value = hours
            eq.current_value_updated_at = datetime.utcnow()
            await session.commit()

            return {
                "status": "updated",
                "equipment": equipment_code,
                "old_value": old_value,
                "new_value": hours,
                "operating_hours": hours - eq.epoch_value,
            }

    except Exception as e:
        logger.exception("update_equipment_hours failed: %s", e)
        return {"status": "error", "message": str(e)}
