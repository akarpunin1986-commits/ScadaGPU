"""Bitrix24 module REST API — status, equipment, tasks, sync, config.

Prefix: /api/bitrix24 (separate from existing /api/bitrix proxy).
Only loaded when BITRIX24_ENABLED=true.
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import get_session
from models.bitrix24_task import Bitrix24Task
from models.device import Device

router = APIRouter(prefix="/api/bitrix24", tags=["bitrix24-module"])
logger = logging.getLogger("scada.bitrix24.api")


def _get_module(request: Request):
    """Get Bitrix24Module from app state."""
    module = getattr(request.app.state, "bitrix24_module", None)
    if not module:
        raise HTTPException(503, "Bitrix24 module is not enabled")
    return module


# ─── Status ───────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(request: Request):
    """Module status, connection health, counters."""
    module = getattr(request.app.state, "bitrix24_module", None)
    if not module:
        return {
            "enabled": False,
            "connected": False,
            "equipment_count": 0,
            "last_sync": None,
        }
    return {
        "enabled": True,
        "connected": module.client.is_connected,
        "webhook_url": settings.BITRIX24_WEBHOOK_URL or "",
        "equipment_count": module.equipment_sync.cached_count,
        "last_sync": module.equipment_sync.last_sync_time,
        "group_id": settings.BITRIX24_GROUP_ID,
    }


# ─── Equipment ────────────────────────────────────────────────────────

@router.get("/equipment")
async def list_equipment(request: Request):
    """Cached equipment list with roles."""
    module = _get_module(request)
    equipment = await module.equipment_sync.get_all_equipment()
    return {"items": equipment, "total": len(equipment)}


@router.post("/equipment/sync")
async def force_sync(request: Request):
    """Force equipment sync from Bitrix24."""
    module = _get_module(request)
    await module.equipment_sync._sync()
    return {
        "success": True,
        "message": "Equipment sync completed",
        "cached": module.equipment_sync.cached_count,
    }


# ─── Tasks ────────────────────────────────────────────────────────────

@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    source_type: str | None = None,
    device_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List tracked Bitrix24 tasks with optional filters."""
    stmt = (
        select(Bitrix24Task)
        .order_by(Bitrix24Task.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Bitrix24Task.status == status)
    if source_type:
        stmt = stmt.where(Bitrix24Task.source_type == source_type)
    if device_id:
        stmt = stmt.where(Bitrix24Task.device_id == device_id)

    result = await session.execute(stmt)
    tasks = result.scalars().all()

    return {
        "tasks": [
            {
                "id": t.id,
                "bitrix_task_id": t.bitrix_task_id,
                "source_type": t.source_type,
                "device_id": t.device_id,
                "system_code": t.system_code,
                "task_title": t.task_title,
                "status": t.status,
                "responsible_id": t.responsible_id,
                "responsible_name": t.responsible_name,
                "priority": t.priority,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in tasks
        ],
        "total": len(tasks),
    }


# ─── Test Task ────────────────────────────────────────────────────────

@router.post("/tasks/test")
async def create_test_task(request: Request):
    """Create a test task in Bitrix24 and save to local DB."""
    module = _get_module(request)

    try:
        title = f"SCADA Тест — {datetime.utcnow().strftime('%d.%m.%Y %H:%M')}"
        result = await module.client.create_task({
            "TITLE": title,
            "DESCRIPTION": "Тестовая задача от SCADA для проверки интеграции. Можно закрыть.",
            "GROUP_ID": settings.BITRIX24_GROUP_ID,
            "RESPONSIBLE_ID": settings.BITRIX24_FALLBACK_RESPONSIBLE_ID,
            "PRIORITY": 0,
        })

        task_id = None
        task = result.get("task", {})
        if isinstance(task, dict):
            task_id = task.get("id")
        else:
            task_id = task

        if not task_id:
            return {"success": False, "error": "No task_id in response"}

        # Сохранить в локальную БД — задача появится в «Активных задачах»
        await module.task_creator._save_record(
            bitrix_task_id=int(task_id),
            source_type="maintenance",
            source_id=0,
            device_id=None,
            system_code=None,
            task_title=title,
            responsible_id=settings.BITRIX24_FALLBACK_RESPONSIBLE_ID,
            responsible_name=None,
            priority=0,
        )

        return {"success": True, "task_id": int(task_id)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ─── Stats ────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Statistics: open/closed tasks, by type, etc."""
    # Total counts by status
    stmt_open = select(func.count()).select_from(Bitrix24Task).where(
        Bitrix24Task.status == "open"
    )
    stmt_closed = select(func.count()).select_from(Bitrix24Task).where(
        Bitrix24Task.status == "closed"
    )
    stmt_maint = select(func.count()).select_from(Bitrix24Task).where(
        Bitrix24Task.source_type == "maintenance"
    )
    stmt_alarm = select(func.count()).select_from(Bitrix24Task).where(
        Bitrix24Task.source_type == "alarm"
    )

    open_count = (await session.execute(stmt_open)).scalar() or 0
    closed_count = (await session.execute(stmt_closed)).scalar() or 0
    maint_count = (await session.execute(stmt_maint)).scalar() or 0
    alarm_count = (await session.execute(stmt_alarm)).scalar() or 0

    return {
        "total": open_count + closed_count,
        "open": open_count,
        "closed": closed_count,
        "by_type": {
            "maintenance": maint_count,
            "alarm": alarm_count,
        },
    }


# ─── Device Mapping ──────────────────────────────────────────────────

@router.get("/device-mapping")
async def get_device_mapping(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """List all devices with their system_code + available equipment."""
    module = _get_module(request)

    stmt = select(Device).order_by(Device.id)
    result = await session.execute(stmt)
    devices = result.scalars().all()

    equipment = await module.equipment_sync.get_all_equipment()

    return {
        "devices": [
            {
                "id": d.id,
                "name": d.name,
                "device_type": d.device_type,
                "system_code": d.system_code,
            }
            for d in devices
        ],
        "equipment": [
            {"system_code": eq["system_code"], "name": eq["name"]}
            for eq in equipment
        ],
    }


class DeviceMappingUpdate(BaseModel):
    device_id: int
    system_code: str | None = None


@router.put("/device-mapping")
async def update_device_mapping(
    body: DeviceMappingUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Set system_code for a device (link to Bitrix24 equipment)."""
    stmt = (
        update(Device)
        .where(Device.id == body.device_id)
        .values(system_code=body.system_code or None)
    )
    result = await session.execute(stmt)
    await session.commit()

    if result.rowcount == 0:
        raise HTTPException(404, f"Device {body.device_id} not found")

    return {"success": True, "device_id": body.device_id, "system_code": body.system_code}


# ─── Runtime Config ──────────────────────────────────────────────────

REDIS_CONFIG_KEY = "bitrix24:runtime_config"


@router.get("/config")
async def get_config(request: Request):
    """Get current runtime config (from Redis or defaults from .env)."""
    module = _get_module(request)
    raw = await module.redis.get(REDIS_CONFIG_KEY)
    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        cfg = json.loads(raw)
    else:
        cfg = {}

    return {
        "group_id": cfg.get("group_id", settings.BITRIX24_GROUP_ID),
        "deadline_days": cfg.get("deadline_days", 3),
        "priority": cfg.get("priority", 1),
        "auto_create": cfg.get("auto_create", True),
        "add_checklist": cfg.get("add_checklist", True),
        "auditor_id": cfg.get("auditor_id", None),
        "task_title_template": cfg.get(
            "task_title_template",
            "{TO_NAME} — {SITE_NAME} — {GEN_NAME}",
        ),
    }


class RuntimeConfigUpdate(BaseModel):
    group_id: int | None = None
    deadline_days: int | None = None
    priority: int | None = None
    auto_create: bool | None = None
    add_checklist: bool | None = None
    auditor_id: int | None = None
    task_title_template: str | None = None


@router.put("/config")
async def update_config(body: RuntimeConfigUpdate, request: Request):
    """Update runtime config (stored in Redis, survives restarts)."""
    module = _get_module(request)

    raw = await module.redis.get(REDIS_CONFIG_KEY)
    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        cfg = json.loads(raw)
    else:
        cfg = {}

    update_data = body.model_dump(exclude_none=True)
    cfg.update(update_data)
    await module.redis.set(REDIS_CONFIG_KEY, json.dumps(cfg))

    return {"success": True, "config": cfg}
