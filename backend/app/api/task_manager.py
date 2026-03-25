"""ScadaGPU — Task Manager API router (/api/task-manager)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from middleware.auth import get_current_user, require_role
from models.base import async_session, get_session
from models.scada_user import ScadaUser
from models.scada_rule import ScadaRule
from models.task_manager import (
    EscalationLog,
    MaintenanceCard,
    ScadaTask,
    TaskCommunication,
    TaskQualityCheck,
)

logger = logging.getLogger("scada.task_manager")

router = APIRouter(prefix="/api/task-manager", tags=["task-manager"])


# ---------------------------------------------------------------------------
#  Pydantic schemas
# ---------------------------------------------------------------------------

class CardOut(BaseModel):
    id: int
    equipment_code: str
    equipment_name: str
    maintenance_type: str
    maintenance_name: str | None = None
    interval_hours: int | None = None
    interval_days: int | None = None
    checklist_items: dict | list | None = None
    is_active: bool
    last_completed_at: datetime | None = None
    source_file: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class TaskCreateBody(BaseModel):
    title: str
    equipment_code: str | None = None
    description: str | None = None
    priority: int = 1
    deadline_days: int = 7
    task_type: str = "manual"


class TaskOut(BaseModel):
    id: int
    title: str
    task_type: str
    status: str
    priority: int
    equipment_code: str | None = None
    responsible_name: str | None = None
    deadline: datetime | None = None
    quality_status: str | None = None
    quality_score: float | None = None
    created_at: datetime
    completed_at: datetime | None = None
    model_config = {"from_attributes": True}


class TaskStatusUpdate(BaseModel):
    status: str

class CloseTaskBody(BaseModel):
    interval_code: str | None = None
    notes: str | None = None
    performed_by: str | None = None


class CommunicationOut(BaseModel):
    id: int
    channel: str
    direction: str
    sender: str
    recipient_name: str | None = None
    message_type: str
    message_text: str
    created_at: datetime
    model_config = {"from_attributes": True}


class QualityCheckOut(BaseModel):
    id: int
    check_type: str
    passed: bool
    details: dict | None = None
    checked_at: datetime
    checked_by: str | None = None
    model_config = {"from_attributes": True}


class StatsOverview(BaseModel):
    total: int
    open: int
    overdue: int
    completed_this_week: int


class EscalationOut(BaseModel):
    id: int
    task_id: int
    level: int
    level_name: str | None = None
    target_name: str | None = None
    reason: str | None = None
    resolved: bool
    created_at: datetime
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
#  Cards endpoints
# ---------------------------------------------------------------------------

@router.post("/cards/upload")
async def upload_card(
    file: UploadFile = File(...),
    user: ScadaUser = Depends(get_current_user),
):
    """Upload and parse a maintenance card file (Word/PDF)."""
    from services.task_manager.maintenance_parser import parse_maintenance_file

    if not file.filename:
        raise HTTPException(400, "No filename provided")

    allowed_ext = (".docx", ".pdf", ".doc")
    if not any(file.filename.lower().endswith(ext) for ext in allowed_ext):
        raise HTTPException(400, f"Unsupported file type. Allowed: {', '.join(allowed_ext)}")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 10 MB)")

    try:
        cards = await parse_maintenance_file(file.filename, content)
    except Exception as e:
        logger.exception("Card upload parse error")
        raise HTTPException(500, f"Parse error: {str(e)}")

    return {"status": "ok", "cards_created": len(cards), "cards": [c.id for c in cards]}


@router.get("/cards", response_model=list[CardOut])
async def list_cards(
    session: AsyncSession = Depends(get_session),
):
    """List all active maintenance cards."""
    stmt = (
        select(MaintenanceCard)
        .where(MaintenanceCard.is_active.is_(True))
        .order_by(MaintenanceCard.equipment_code, MaintenanceCard.maintenance_type)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return rows


@router.get("/cards/{card_id}", response_model=CardOut)
async def get_card(
    card_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get maintenance card by ID."""
    card = await session.get(MaintenanceCard, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    return card


@router.delete("/cards/{card_id}")
async def deactivate_card(
    card_id: int,
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(require_role("admin")),
):
    """Deactivate a maintenance card (admin only)."""
    card = await session.get(MaintenanceCard, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    card.is_active = False
    await session.commit()
    return {"status": "deactivated", "card_id": card_id}


# ---------------------------------------------------------------------------
#  Tasks endpoints
# ---------------------------------------------------------------------------

@router.post("/tasks", response_model=TaskOut)
async def create_task(
    body: TaskCreateBody,
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(get_current_user),
):
    """Create a task manually."""
    site_id = None
    if body.equipment_code:
        if body.equipment_code.startswith("mkz"):
            site_id = 3
        elif body.equipment_code.startswith("yakz") or body.equipment_code.startswith("ykz"):
            site_id = 5

    deadline = datetime.utcnow() + timedelta(days=body.deadline_days)

    task = ScadaTask(
        task_type=body.task_type,
        trigger_source="manual_api",
        title=body.title,
        description=body.description,
        equipment_code=body.equipment_code,
        site_id=site_id,
        priority=body.priority,
        deadline=deadline,
        status="created",
        responsible_user_id=user.bitrix_id,
        responsible_name=user.name,
        creator=user.name,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    status: str | None = Query(None),
    task_type: str | None = Query(None, alias="type"),
    equipment: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List tasks with optional filters."""
    stmt = select(ScadaTask).order_by(ScadaTask.created_at.desc())

    if status:
        stmt = stmt.where(ScadaTask.status == status)
    if task_type:
        stmt = stmt.where(ScadaTask.task_type == task_type)
    if equipment:
        stmt = stmt.where(ScadaTask.equipment_code == equipment)

    stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return rows


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get task details."""
    task = await session.get(ScadaTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.patch("/tasks/{task_id}/status")
async def update_task_status(
    task_id: int,
    body: TaskStatusUpdate,
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(get_current_user),
):
    """Update task status."""
    valid_statuses = {"created", "in_progress", "completed", "escalated", "closed"}
    if body.status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Valid: {', '.join(valid_statuses)}")

    task = await session.get(ScadaTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    task.status = body.status
    if body.status == "completed":
        task.completed_at = datetime.utcnow()
    elif body.status == "closed":
        task.closed_at = datetime.utcnow()

    await session.commit()

    logger.info("task %d status → %s (by %s)", task_id, body.status, user.name)
    return {"status": "updated", "task_id": task_id, "new_status": body.status}


# ---------------------------------------------------------------------------
#  Close task (complete + record maintenance + quality check)
# ---------------------------------------------------------------------------

@router.post("/tasks/{task_id}/close")
async def close_task(
    task_id: int,
    body: CloseTaskBody,
    session: AsyncSession = Depends(get_session),
):
    """Close a task: set completed, optionally record maintenance and run quality check."""
    task = await session.get(ScadaTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status in ("completed", "closed"):
        raise HTTPException(400, f"Task already {task.status}")

    now = datetime.utcnow()
    performer = body.performed_by or task.responsible_name or "unknown"

    # Record maintenance if interval_code provided and task is maintenance type
    maintenance_log_id = None
    if body.interval_code and task.equipment_code:
        try:
            from services.maintenance.lifecycle import record_maintenance
            from models.equipment_unit import EquipmentUnit
            from sqlalchemy import select as sa_select

            # Find equipment by code
            eq = (await session.execute(
                sa_select(EquipmentUnit).where(EquipmentUnit.name == task.equipment_code).limit(1)
            )).scalar_one_or_none()

            if eq:
                log_entry = await record_maintenance(
                    equipment_id=eq.id,
                    interval_code=body.interval_code,
                    performed_by=performer,
                    performed_date=now,
                    session=session,
                    notes=body.notes,
                    scada_task_id=task_id,
                )
                maintenance_log_id = log_entry.id
                logger.info("Maintenance recorded for task %d: log_id=%d", task_id, log_entry.id)
        except Exception as e:
            logger.warning("Failed to record maintenance for task %d: %s", task_id, e)

    # Run quality check if enabled
    quality_status = None
    if settings.QUALITY_VISION_ENABLED:
        try:
            from services.task_manager.quality_control import run_quality_check
            qc = await run_quality_check(task_id, session=session)
            if qc:
                quality_status = qc.get("status", "passed")
                task.quality_status = quality_status
                task.quality_score = qc.get("score")
        except Exception as e:
            logger.warning("Quality check failed for task %d: %s", task_id, e)

    # Complete task
    task.status = "completed"
    task.completed_at = now
    await session.commit()

    logger.info("Task %d closed by %s (maintenance_log=%s, quality=%s)",
                task_id, performer, maintenance_log_id, quality_status)

    return {
        "status": "closed",
        "task_id": task_id,
        "maintenance_log_id": maintenance_log_id,
        "quality_status": quality_status,
    }


# ---------------------------------------------------------------------------
#  Quality & Communications
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}/quality", response_model=list[QualityCheckOut])
async def get_task_quality(
    task_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get quality checks for a task."""
    stmt = (
        select(TaskQualityCheck)
        .where(TaskQualityCheck.task_id == task_id)
        .order_by(TaskQualityCheck.checked_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return rows


@router.get("/tasks/{task_id}/communications", response_model=list[CommunicationOut])
async def get_task_communications(
    task_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get communication log for a task."""
    stmt = (
        select(TaskCommunication)
        .where(TaskCommunication.task_id == task_id)
        .order_by(TaskCommunication.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return rows


# ---------------------------------------------------------------------------
#  Stats & Escalations
# ---------------------------------------------------------------------------

@router.get("/stats/overview", response_model=StatsOverview)
async def stats_overview(
    session: AsyncSession = Depends(get_session),
):
    """Overview statistics: total, open, overdue, completed this week."""
    total = (await session.execute(
        select(func.count(ScadaTask.id))
    )).scalar() or 0

    open_count = (await session.execute(
        select(func.count(ScadaTask.id)).where(
            ScadaTask.status.notin_(["completed", "closed"])
        )
    )).scalar() or 0

    now = datetime.utcnow()
    overdue = (await session.execute(
        select(func.count(ScadaTask.id)).where(
            ScadaTask.deadline < now,
            ScadaTask.status.notin_(["completed", "closed"]),
        )
    )).scalar() or 0

    week_ago = now - timedelta(days=7)
    completed_week = (await session.execute(
        select(func.count(ScadaTask.id)).where(
            ScadaTask.status == "completed",
            ScadaTask.completed_at >= week_ago,
        )
    )).scalar() or 0

    return StatsOverview(
        total=total,
        open=open_count,
        overdue=overdue,
        completed_this_week=completed_week,
    )


@router.get("/escalations", response_model=list[EscalationOut])
async def list_escalations(
    session: AsyncSession = Depends(get_session),
):
    """List active (unresolved) escalations."""
    stmt = (
        select(EscalationLog)
        .where(EscalationLog.resolved.is_(False))
        .order_by(EscalationLog.created_at.desc())
        .limit(50)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return rows


# ---------------------------------------------------------------------------
#  Employees (for dropdowns)
# ---------------------------------------------------------------------------

@router.get("/employees")
async def list_employees(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """List ALL employees from Б24 company cache (Redis) for dropdowns. Public endpoint."""
    import json as _json

    result = []

    # Primary source: Redis company:employees (all 46+ employees from B24)
    try:
        redis = request.app.state.redis
        raw = await redis.get("company:employees")
        if raw:
            data = _json.loads(raw)
            if isinstance(data, list):
                # List of employee dicts: [{bitrix_id, name, position, ...}]
                for emp in data:
                    if emp.get("active", True):
                        result.append({
                            "bitrix_id": emp.get("bitrix_id") or emp.get("id"),
                            "name": emp.get("name", ""),
                            "position": emp.get("position", ""),
                            "department": "",
                        })
            elif isinstance(data, dict):
                by_name = data.get("by_name", data)
                for name, emp in by_name.items():
                    result.append({
                        "bitrix_id": emp.get("id") or emp.get("bitrix_id"),
                        "name": name,
                        "position": emp.get("position", ""),
                        "department": emp.get("department", ""),
                    })
    except Exception:
        pass

    # Fallback: scada_users table (only logged-in users)
    if not result:
        stmt = select(ScadaUser).where(ScadaUser.is_active.is_(True)).order_by(ScadaUser.name)
        rows = (await session.execute(stmt)).scalars().all()
        result = [
            {
                "bitrix_id": u.bitrix_id,
                "name": u.name,
                "position": u.position or "",
                "department": u.department or "",
            }
            for u in rows
        ]

    # Sort by name
    result.sort(key=lambda x: x.get("name", ""))
    return result


@router.get("/equipment")
async def list_equipment(
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(get_current_user),
):
    """List equipment with responsible persons from equipment_responsible table."""
    import json as _json
    from models.equipment_responsible import EquipmentResponsible

    # Equipment map from config
    eq_map_raw = settings.EQUIPMENT_DEVICE_MAP
    try:
        eq_map = _json.loads(eq_map_raw) if isinstance(eq_map_raw, str) else eq_map_raw
    except Exception:
        eq_map = {"mkz_dgu1": [1, 2, 3], "yakz_dgu1": [4, 5, 6]}

    # Load responsible from DB
    stmt = select(EquipmentResponsible)
    rows = (await session.execute(stmt)).scalars().all()
    resp_map = {r.equipment_code: {"bitrix_id": r.responsible_bitrix_id, "name": r.responsible_name} for r in rows}

    # Build equipment list
    equipment = []
    site_map = {"mkz": {"id": 3, "name": "МКЗ"}, "yakz": {"id": 5, "name": "ЯКЗ"}}
    eq_names = {
        "gpu": "ГПУ «Кама Энерго»", "dgu1": "ГПУ «Кама Энерго»",
        "extruder": "Экструдер", "furnace": "Печь", "mixer": "Миксер",
    }

    for code, device_ids in eq_map.items():
        site_prefix = code.split("_")[0]
        site_info = site_map.get(site_prefix, {"id": None, "name": site_prefix.upper()})
        eq_type = "gpu" if "dgu" in code else code.split("_")[-1]

        equipment.append({
            "code": code,
            "name": eq_names.get(eq_type, eq_type),
            "type": eq_type,
            "site_code": site_prefix,
            "site_name": site_info["name"],
            "site_id": site_info["id"],
            "device_ids": device_ids,
            "responsible": resp_map.get(code),
        })

    return equipment


@router.put("/equipment/{equipment_code}/responsible")
async def set_equipment_responsible(
    equipment_code: str,
    body: dict,
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(get_current_user),
):
    """Assign responsible person to equipment."""
    from models.equipment_responsible import EquipmentResponsible

    bitrix_id = body.get("bitrix_id") or body.get("responsible_bitrix_id")
    name = body.get("name") or body.get("responsible_name", "")
    if not bitrix_id or not name:
        raise HTTPException(400, "bitrix_id and name required")

    # Upsert
    stmt = select(EquipmentResponsible).where(EquipmentResponsible.equipment_code == equipment_code)
    existing = (await session.execute(stmt)).scalar_one_or_none()

    site_prefix = equipment_code.split("_")[0]
    eq_names = {"mkz_dgu1": "МКЗ ГПУ", "yakz_dgu1": "ЯКЗ ГПУ"}

    if existing:
        existing.responsible_bitrix_id = int(bitrix_id)
        existing.responsible_name = name
    else:
        session.add(EquipmentResponsible(
            equipment_code=equipment_code,
            equipment_name=eq_names.get(equipment_code, equipment_code),
            site_code=site_prefix,
            responsible_bitrix_id=int(bitrix_id),
            responsible_name=name,
        ))

    await session.commit()
    return {"status": "ok", "equipment_code": equipment_code, "responsible": name}


# ---------------------------------------------------------------------------
#  Rules CRUD
# ---------------------------------------------------------------------------

@router.post("/rules")
async def create_rule(body: dict, session: AsyncSession = Depends(get_session), user: ScadaUser = Depends(get_current_user)):
    """Create a new automation rule."""
    rule = ScadaRule(
        name=body.get("name", "Новое правило"),
        description=body.get("description"),
        created_by=f"user:{user.id}",
        site_id=body.get("site_id"),
        equipment_code=body.get("equipment_code"),
        trigger_type=body["trigger_type"],
        trigger_config=body.get("trigger_config", {}),
        action_type=body["action_type"],
        action_config=body.get("action_config", {}),
        executor_bitrix_id=body.get("executor_bitrix_id"),
        executor_name=body.get("executor_name"),
        watchers=body.get("watchers"),
        sanek_control=body.get("sanek_control", True),
        sanek_control_config=body.get("sanek_control_config"),
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return {"id": rule.id, "name": rule.name, "status": "created"}


@router.get("/rules")
async def list_rules(session: AsyncSession = Depends(get_session), user: ScadaUser = Depends(get_current_user)):
    """List all automation rules."""
    rows = (await session.execute(select(ScadaRule).order_by(ScadaRule.created_at.desc()))).scalars().all()
    return [{"id": r.id, "name": r.name, "trigger_type": r.trigger_type, "action_type": r.action_type,
             "equipment_code": r.equipment_code, "executor_name": r.executor_name,
             "is_active": r.is_active, "sanek_control": r.sanek_control,
             "times_triggered": r.times_triggered, "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: int, session: AsyncSession = Depends(get_session), user: ScadaUser = Depends(get_current_user)):
    """Get automation rule by ID."""
    rule = await session.get(ScadaRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return {k: getattr(rule, k) for k in ['id', 'name', 'description', 'trigger_type', 'trigger_config',
            'action_type', 'action_config', 'equipment_code', 'executor_bitrix_id', 'executor_name',
            'watchers', 'sanek_control', 'sanek_control_config', 'is_active', 'times_triggered',
            'last_triggered_at', 'created_at']}


@router.patch("/rules/{rule_id}")
async def update_rule(rule_id: int, body: dict, session: AsyncSession = Depends(get_session), user: ScadaUser = Depends(get_current_user)):
    """Update an automation rule."""
    rule = await session.get(ScadaRule, rule_id)
    if not rule:
        raise HTTPException(404)
    for field in ['name', 'description', 'trigger_type', 'trigger_config', 'action_type', 'action_config',
                  'equipment_code', 'executor_bitrix_id', 'executor_name', 'watchers', 'sanek_control',
                  'sanek_control_config', 'is_active']:
        if field in body:
            setattr(rule, field, body[field])
    await session.commit()
    return {"status": "updated"}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, session: AsyncSession = Depends(get_session), user: ScadaUser = Depends(require_role("admin"))):
    """Deactivate an automation rule (admin only)."""
    rule = await session.get(ScadaRule, rule_id)
    if not rule:
        raise HTTPException(404)
    rule.is_active = False
    await session.commit()
    return {"status": "deactivated"}
