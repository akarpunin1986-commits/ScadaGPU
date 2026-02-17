# Phase 3 Task 2 — CRUD API для регламентов ТО + выполнение + статус

## Цель
Создать файл `backend/app/api/maintenance.py` с полным REST API для системы техобслуживания. Подключить роутер в `main.py`. Засеять стандартный регламент при первом запуске.

---

## Обзор эндпоинтов

| # | Метод | URL | Назначение |
|---|-------|-----|------------|
| 1 | GET | `/api/templates` | Список регламентов |
| 2 | GET | `/api/templates/{id}` | Регламент с интервалами и задачами |
| 3 | POST | `/api/templates` | Создать регламент |
| 4 | PATCH | `/api/templates/{id}` | Обновить регламент |
| 5 | DELETE | `/api/templates/{id}` | Удалить регламент |
| 6 | POST | `/api/templates/{id}/intervals` | Добавить интервал в регламент |
| 7 | PATCH | `/api/intervals/{id}` | Обновить интервал |
| 8 | DELETE | `/api/intervals/{id}` | Удалить интервал |
| 9 | POST | `/api/intervals/{id}/tasks` | Добавить задачу в интервал |
| 10 | PATCH | `/api/tasks/{id}` | Обновить задачу |
| 11 | DELETE | `/api/tasks/{id}` | Удалить задачу |
| 12 | GET | `/api/devices/{id}/maintenance` | Статус ТО устройства |
| 13 | GET | `/api/devices/{id}/maintenance/history` | История ТО устройства |
| 14 | POST | `/api/devices/{id}/maintenance` | Записать выполненное ТО |
| 15 | POST | `/api/seed-templates` | Засеять стандартный регламент |

---

## Файл: `backend/app/api/maintenance.py`

### Импорты и роутер

```python
"""Phase 3 — Maintenance API: templates CRUD, maintenance execution, status."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import (
    Device,
    MaintenanceTemplate,
    MaintenanceInterval,
    MaintenanceTask,
    MaintenanceLog,
    MaintenanceLogItem,
    get_session,
)

router = APIRouter(tags=["maintenance"])
```

---

### Pydantic-схемы

```python
# ---- Task schemas ----

class TaskCreate(BaseModel):
    text: str
    is_critical: bool = False
    sort_order: int = 0

class TaskUpdate(BaseModel):
    text: str | None = None
    is_critical: bool | None = None
    sort_order: int | None = None

class TaskOut(BaseModel):
    id: int
    text: str
    is_critical: bool
    sort_order: int
    model_config = {"from_attributes": True}


# ---- Interval schemas ----

class IntervalCreate(BaseModel):
    name: str           # "ТО-1"
    code: str           # "to1"
    hours: int          # 250
    sort_order: int = 0
    tasks: list[TaskCreate] = []

class IntervalUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    hours: int | None = None
    sort_order: int | None = None

class IntervalOut(BaseModel):
    id: int
    name: str
    code: str
    hours: int
    sort_order: int
    tasks: list[TaskOut] = []
    model_config = {"from_attributes": True}


# ---- Template schemas ----

class TemplateCreate(BaseModel):
    name: str
    description: str | None = None
    is_default: bool = False
    intervals: list[IntervalCreate] = []

class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_default: bool | None = None

class TemplateListOut(BaseModel):
    id: int
    name: str
    description: str | None
    is_default: bool
    interval_count: int = 0
    model_config = {"from_attributes": True}

class TemplateOut(BaseModel):
    id: int
    name: str
    description: str | None
    is_default: bool
    intervals: list[IntervalOut] = []
    model_config = {"from_attributes": True}


# ---- Maintenance execution schemas ----

class MaintenanceItemIn(BaseModel):
    task_id: int | None = None
    task_text: str
    is_completed: bool
    is_critical: bool = False

class MaintenancePerform(BaseModel):
    interval_id: int
    engine_hours: float
    notes: str | None = None
    performed_by: str | None = None
    items: list[MaintenanceItemIn] = []

class MaintenanceLogItemOut(BaseModel):
    id: int
    task_text: str
    is_completed: bool
    is_critical: bool
    model_config = {"from_attributes": True}

class MaintenanceLogOut(BaseModel):
    id: int
    device_id: int
    interval_id: int | None
    interval_name: str | None = None
    performed_at: datetime
    engine_hours: float
    completed_count: int
    total_count: int
    notes: str | None
    performed_by: str | None
    items: list[MaintenanceLogItemOut] = []
    model_config = {"from_attributes": True}


# ---- Maintenance status schema ----

class MaintenanceStatusOut(BaseModel):
    device_id: int
    current_engine_hours: float | None    # Текущие моточасы из Redis (null если offline)
    last_to_date: str | None              # ISO дата последнего ТО
    last_to_type: str | None              # "ТО-1" и т.д.
    hours_at_last_to: float | None        # Моточасы при последнем ТО
    hours_since_to: float | None          # Сколько прошло с последнего ТО
    next_to_name: str | None              # "ТО-2"
    next_to_hours: int | None             # Интервал (500)
    hours_remaining: float | None         # Осталось до следующего ТО
    progress_percent: float | None        # 0-100 прогресс до следующего ТО
    status: str                           # "ok" | "warning" | "overdue" | "unknown"
```

---

### Эндпоинты — Templates CRUD

```python
# ===========================================================================
#  1. GET /api/templates — список регламентов
# ===========================================================================

@router.get("/api/templates", response_model=list[TemplateListOut])
async def list_templates(session: AsyncSession = Depends(get_session)):
    stmt = (
        select(MaintenanceTemplate)
        .options(selectinload(MaintenanceTemplate.intervals))
        .order_by(MaintenanceTemplate.id)
    )
    result = await session.execute(stmt)
    templates = result.scalars().all()
    out = []
    for t in templates:
        out.append(TemplateListOut(
            id=t.id,
            name=t.name,
            description=t.description,
            is_default=t.is_default,
            interval_count=len(t.intervals),
        ))
    return out


# ===========================================================================
#  2. GET /api/templates/{id} — регламент с интервалами и задачами
# ===========================================================================

@router.get("/api/templates/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(MaintenanceTemplate)
        .where(MaintenanceTemplate.id == template_id)
        .options(
            selectinload(MaintenanceTemplate.intervals)
            .selectinload(MaintenanceInterval.tasks)
        )
    )
    result = await session.execute(stmt)
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(404, "Template not found")
    return template


# ===========================================================================
#  3. POST /api/templates — создать регламент (с интервалами и задачами)
# ===========================================================================

@router.post("/api/templates", response_model=TemplateOut, status_code=201)
async def create_template(
    data: TemplateCreate,
    session: AsyncSession = Depends(get_session),
):
    template = MaintenanceTemplate(
        name=data.name,
        description=data.description,
        is_default=data.is_default,
    )
    for iv in data.intervals:
        interval = MaintenanceInterval(
            name=iv.name,
            code=iv.code,
            hours=iv.hours,
            sort_order=iv.sort_order,
        )
        for tk in iv.tasks:
            task = MaintenanceTask(
                text=tk.text,
                is_critical=tk.is_critical,
                sort_order=tk.sort_order,
            )
            interval.tasks.append(task)
        template.intervals.append(interval)

    session.add(template)
    await session.commit()

    # Reload with relationships
    stmt = (
        select(MaintenanceTemplate)
        .where(MaintenanceTemplate.id == template.id)
        .options(
            selectinload(MaintenanceTemplate.intervals)
            .selectinload(MaintenanceInterval.tasks)
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one()


# ===========================================================================
#  4. PATCH /api/templates/{id} — обновить регламент (только мета-поля)
# ===========================================================================

@router.patch("/api/templates/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    session: AsyncSession = Depends(get_session),
):
    template = await session.get(MaintenanceTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    await session.commit()

    stmt = (
        select(MaintenanceTemplate)
        .where(MaintenanceTemplate.id == template_id)
        .options(
            selectinload(MaintenanceTemplate.intervals)
            .selectinload(MaintenanceInterval.tasks)
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one()


# ===========================================================================
#  5. DELETE /api/templates/{id} — удалить регламент
# ===========================================================================

@router.delete("/api/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
):
    template = await session.get(MaintenanceTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    await session.delete(template)
    await session.commit()
```

---

### Эндпоинты — Intervals CRUD

```python
# ===========================================================================
#  6. POST /api/templates/{id}/intervals — добавить интервал
# ===========================================================================

@router.post(
    "/api/templates/{template_id}/intervals",
    response_model=IntervalOut,
    status_code=201,
)
async def create_interval(
    template_id: int,
    data: IntervalCreate,
    session: AsyncSession = Depends(get_session),
):
    template = await session.get(MaintenanceTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")

    interval = MaintenanceInterval(
        template_id=template_id,
        name=data.name,
        code=data.code,
        hours=data.hours,
        sort_order=data.sort_order,
    )
    for tk in data.tasks:
        task = MaintenanceTask(
            text=tk.text,
            is_critical=tk.is_critical,
            sort_order=tk.sort_order,
        )
        interval.tasks.append(task)

    session.add(interval)
    await session.commit()

    stmt = (
        select(MaintenanceInterval)
        .where(MaintenanceInterval.id == interval.id)
        .options(selectinload(MaintenanceInterval.tasks))
    )
    result = await session.execute(stmt)
    return result.scalar_one()


# ===========================================================================
#  7. PATCH /api/intervals/{id} — обновить интервал
# ===========================================================================

@router.patch("/api/intervals/{interval_id}", response_model=IntervalOut)
async def update_interval(
    interval_id: int,
    data: IntervalUpdate,
    session: AsyncSession = Depends(get_session),
):
    interval = await session.get(MaintenanceInterval, interval_id)
    if not interval:
        raise HTTPException(404, "Interval not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(interval, field, value)
    await session.commit()

    stmt = (
        select(MaintenanceInterval)
        .where(MaintenanceInterval.id == interval_id)
        .options(selectinload(MaintenanceInterval.tasks))
    )
    result = await session.execute(stmt)
    return result.scalar_one()


# ===========================================================================
#  8. DELETE /api/intervals/{id} — удалить интервал
# ===========================================================================

@router.delete("/api/intervals/{interval_id}", status_code=204)
async def delete_interval(
    interval_id: int,
    session: AsyncSession = Depends(get_session),
):
    interval = await session.get(MaintenanceInterval, interval_id)
    if not interval:
        raise HTTPException(404, "Interval not found")
    await session.delete(interval)
    await session.commit()
```

---

### Эндпоинты — Tasks CRUD

```python
# ===========================================================================
#  9. POST /api/intervals/{id}/tasks — добавить задачу
# ===========================================================================

@router.post(
    "/api/intervals/{interval_id}/tasks",
    response_model=TaskOut,
    status_code=201,
)
async def create_task(
    interval_id: int,
    data: TaskCreate,
    session: AsyncSession = Depends(get_session),
):
    interval = await session.get(MaintenanceInterval, interval_id)
    if not interval:
        raise HTTPException(404, "Interval not found")

    task = MaintenanceTask(
        interval_id=interval_id,
        text=data.text,
        is_critical=data.is_critical,
        sort_order=data.sort_order,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


# ===========================================================================
#  10. PATCH /api/tasks/{id} — обновить задачу
# ===========================================================================

@router.patch("/api/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    data: TaskUpdate,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(MaintenanceTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task


# ===========================================================================
#  11. DELETE /api/tasks/{id} — удалить задачу
# ===========================================================================

@router.delete("/api/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(MaintenanceTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    await session.delete(task)
    await session.commit()
```

---

### Эндпоинты — Maintenance Status & Execution

```python
# ===========================================================================
#  12. GET /api/devices/{id}/maintenance — текущий статус ТО устройства
# ===========================================================================

@router.get(
    "/api/devices/{device_id}/maintenance",
    response_model=MaintenanceStatusOut,
)
async def get_maintenance_status(
    device_id: int,
    template_id: int | None = Query(None, description="Template ID (uses default if omitted)"),
    request: Request = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Вычисляет текущий статус ТО для устройства:
    - Берёт текущие моточасы из Redis
    - Находит последний MaintenanceLog для device
    - Определяет следующий интервал ТО
    - Возвращает прогресс и статус
    """
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")

    # 1. Текущие моточасы из Redis
    current_hours: float | None = None
    redis = request.app.state.redis
    raw = await redis.get(f"device:{device_id}:metrics")
    if raw:
        try:
            metrics = json.loads(raw)
            current_hours = metrics.get("run_hours")
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. Последний лог ТО
    stmt = (
        select(MaintenanceLog)
        .where(MaintenanceLog.device_id == device_id)
        .order_by(MaintenanceLog.performed_at.desc())
        .limit(1)
        .options(selectinload(MaintenanceLog.interval))
    )
    result = await session.execute(stmt)
    last_log = result.scalar_one_or_none()

    last_to_date: str | None = None
    last_to_type: str | None = None
    hours_at_last_to: float | None = None

    if last_log:
        last_to_date = last_log.performed_at.isoformat()
        last_to_type = last_log.interval.name if last_log.interval else None
        hours_at_last_to = last_log.engine_hours

    # 3. Загрузить интервалы из шаблона
    if template_id:
        tmpl_stmt = (
            select(MaintenanceTemplate)
            .where(MaintenanceTemplate.id == template_id)
            .options(selectinload(MaintenanceTemplate.intervals))
        )
    else:
        tmpl_stmt = (
            select(MaintenanceTemplate)
            .where(MaintenanceTemplate.is_default == True)
            .options(selectinload(MaintenanceTemplate.intervals))
        )
    tmpl_result = await session.execute(tmpl_stmt)
    template = tmpl_result.scalar_one_or_none()

    if not template or not template.intervals:
        return MaintenanceStatusOut(
            device_id=device_id,
            current_engine_hours=current_hours,
            last_to_date=last_to_date,
            last_to_type=last_to_type,
            hours_at_last_to=hours_at_last_to,
            hours_since_to=None,
            next_to_name=None,
            next_to_hours=None,
            hours_remaining=None,
            progress_percent=None,
            status="unknown",
        )

    intervals = sorted(template.intervals, key=lambda i: i.hours)
    hours_since_to = (
        (current_hours - (hours_at_last_to or 0))
        if current_hours is not None
        else None
    )

    # 4. Найти следующий интервал ТО
    next_interval = None
    if hours_since_to is not None:
        for iv in intervals:
            if hours_since_to < iv.hours:
                next_interval = iv
                break
        if next_interval is None:
            next_interval = intervals[-1]  # Все просрочены — показываем последний

    hours_remaining: float | None = None
    progress: float | None = None
    status = "unknown"

    if next_interval and hours_since_to is not None:
        hours_remaining = next_interval.hours - hours_since_to
        progress = min(100.0, (hours_since_to / next_interval.hours) * 100)
        if hours_remaining <= 0:
            status = "overdue"
        elif hours_remaining <= 20:
            status = "warning"
        else:
            status = "ok"

    return MaintenanceStatusOut(
        device_id=device_id,
        current_engine_hours=current_hours,
        last_to_date=last_to_date,
        last_to_type=last_to_type,
        hours_at_last_to=hours_at_last_to,
        hours_since_to=hours_since_to,
        next_to_name=next_interval.name if next_interval else None,
        next_to_hours=next_interval.hours if next_interval else None,
        hours_remaining=hours_remaining,
        progress_percent=progress,
        status=status,
    )


# ===========================================================================
#  13. GET /api/devices/{id}/maintenance/history — история ТО
# ===========================================================================

@router.get(
    "/api/devices/{device_id}/maintenance/history",
    response_model=list[MaintenanceLogOut],
)
async def get_maintenance_history(
    device_id: int,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")

    stmt = (
        select(MaintenanceLog)
        .where(MaintenanceLog.device_id == device_id)
        .order_by(MaintenanceLog.performed_at.desc())
        .limit(limit)
        .options(
            selectinload(MaintenanceLog.items),
            selectinload(MaintenanceLog.interval),
        )
    )
    result = await session.execute(stmt)
    logs = result.scalars().all()

    out = []
    for log in logs:
        out.append(MaintenanceLogOut(
            id=log.id,
            device_id=log.device_id,
            interval_id=log.interval_id,
            interval_name=log.interval.name if log.interval else None,
            performed_at=log.performed_at,
            engine_hours=log.engine_hours,
            completed_count=log.completed_count,
            total_count=log.total_count,
            notes=log.notes,
            performed_by=log.performed_by,
            items=[MaintenanceLogItemOut.model_validate(item) for item in log.items],
        ))
    return out


# ===========================================================================
#  14. POST /api/devices/{id}/maintenance — записать выполненное ТО
# ===========================================================================

@router.post(
    "/api/devices/{device_id}/maintenance",
    response_model=MaintenanceLogOut,
    status_code=201,
)
async def perform_maintenance(
    device_id: int,
    data: MaintenancePerform,
    session: AsyncSession = Depends(get_session),
):
    """
    Записывает факт проведения ТО:
    - Проверяет device и interval
    - Создаёт MaintenanceLog + MaintenanceLogItem для каждой задачи
    - Снапшотит текст и критичность задач
    """
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")

    interval = await session.get(MaintenanceInterval, data.interval_id)
    if not interval:
        raise HTTPException(404, "Interval not found")

    log = MaintenanceLog(
        device_id=device_id,
        interval_id=data.interval_id,
        engine_hours=data.engine_hours,
        completed_count=sum(1 for it in data.items if it.is_completed),
        total_count=len(data.items),
        notes=data.notes,
        performed_by=data.performed_by,
    )

    for it in data.items:
        log_item = MaintenanceLogItem(
            task_id=it.task_id,
            task_text=it.task_text,
            is_completed=it.is_completed,
            is_critical=it.is_critical,
        )
        log.items.append(log_item)

    session.add(log)
    await session.commit()

    # Reload with relationships
    stmt = (
        select(MaintenanceLog)
        .where(MaintenanceLog.id == log.id)
        .options(
            selectinload(MaintenanceLog.items),
            selectinload(MaintenanceLog.interval),
        )
    )
    result = await session.execute(stmt)
    saved_log = result.scalar_one()

    return MaintenanceLogOut(
        id=saved_log.id,
        device_id=saved_log.device_id,
        interval_id=saved_log.interval_id,
        interval_name=saved_log.interval.name if saved_log.interval else None,
        performed_at=saved_log.performed_at,
        engine_hours=saved_log.engine_hours,
        completed_count=saved_log.completed_count,
        total_count=saved_log.total_count,
        notes=saved_log.notes,
        performed_by=saved_log.performed_by,
        items=[MaintenanceLogItemOut.model_validate(item) for item in saved_log.items],
    )
```

---

### Эндпоинт — Seed стандартного регламента

```python
# ===========================================================================
#  15. POST /api/seed-templates — засеять стандартный регламент
# ===========================================================================

DEFAULT_TEMPLATE = {
    "name": "Стандартный регламент",
    "description": "Стандартный регламент ТО для газопоршневых установок",
    "is_default": True,
    "intervals": [
        {
            "code": "to1",
            "name": "ТО-1",
            "hours": 250,
            "sort_order": 0,
            "tasks": [
                {"text": "Замена моторного масла", "is_critical": True, "sort_order": 0},
                {"text": "Замена масляного фильтра", "is_critical": True, "sort_order": 1},
                {"text": "Проверка уровня охлаждающей жидкости", "is_critical": False, "sort_order": 2},
                {"text": "Проверка натяжения ремней", "is_critical": False, "sort_order": 3},
                {"text": "Проверка состояния аккумулятора", "is_critical": False, "sort_order": 4},
                {"text": "Визуальный осмотр на утечки", "is_critical": False, "sort_order": 5},
                {"text": "Проверка давления масла", "is_critical": True, "sort_order": 6},
                {"text": "Проверка температуры двигателя", "is_critical": False, "sort_order": 7},
                {"text": "Очистка воздушного фильтра", "is_critical": False, "sort_order": 8},
                {"text": "Проверка крепежных соединений", "is_critical": False, "sort_order": 9},
            ],
        },
        {
            "code": "to2",
            "name": "ТО-2",
            "hours": 500,
            "sort_order": 1,
            "tasks": [
                {"text": "Все работы ТО-1", "is_critical": True, "sort_order": 0},
                {"text": "Замена воздушного фильтра", "is_critical": True, "sort_order": 1},
                {"text": "Замена топливного фильтра", "is_critical": True, "sort_order": 2},
                {"text": "Проверка топливной системы", "is_critical": True, "sort_order": 3},
                {"text": "Проверка системы зажигания", "is_critical": False, "sort_order": 4},
                {"text": "Проверка свечей зажигания", "is_critical": False, "sort_order": 5},
                {"text": "Регулировка зазора клапанов (проверка)", "is_critical": False, "sort_order": 6},
                {"text": "Проверка компрессии цилиндров", "is_critical": False, "sort_order": 7},
                {"text": "Проверка давления в системе охлаждения", "is_critical": False, "sort_order": 8},
                {"text": "Промывка системы охлаждения", "is_critical": False, "sort_order": 9},
                {"text": "Проверка электрических соединений", "is_critical": False, "sort_order": 10},
                {"text": "Проверка генератора зарядки АКБ", "is_critical": False, "sort_order": 11},
                {"text": "Проверка системы отвода выхлопных газов", "is_critical": False, "sort_order": 12},
                {"text": "Замена уплотнительных прокладок (при необходимости)", "is_critical": False, "sort_order": 13},
                {"text": "Тестирование аварийной остановки", "is_critical": True, "sort_order": 14},
                {"text": "Проверка датчиков температуры и давления", "is_critical": False, "sort_order": 15},
                {"text": "Обновление журнала обслуживания", "is_critical": False, "sort_order": 16},
                {"text": "Функциональное тестирование", "is_critical": True, "sort_order": 17},
            ],
        },
        {
            "code": "to3",
            "name": "ТО-3",
            "hours": 1000,
            "sort_order": 2,
            "tasks": [
                {"text": "Все работы ТО-2", "is_critical": True, "sort_order": 0},
                {"text": "Полная замена охлаждающей жидкости", "is_critical": True, "sort_order": 1},
                {"text": "Регулировка зазора клапанов", "is_critical": True, "sort_order": 2},
                {"text": "Проверка компрессии всех цилиндров", "is_critical": True, "sort_order": 3},
                {"text": "Проверка турбокомпрессора", "is_critical": True, "sort_order": 4},
                {"text": "Замена ремня ГРМ (при необходимости)", "is_critical": False, "sort_order": 5},
                {"text": "Проверка масляного насоса", "is_critical": False, "sort_order": 6},
                {"text": "Диагностика контроллера Smartgen", "is_critical": False, "sort_order": 7},
                {"text": "Калибровка датчиков", "is_critical": False, "sort_order": 8},
                {"text": "Проверка системы автоматического запуска", "is_critical": True, "sort_order": 9},
                {"text": "Замена антифриза", "is_critical": False, "sort_order": 10},
                {"text": "Проверка радиатора на засорение", "is_critical": False, "sort_order": 11},
                {"text": "Проверка водяного насоса", "is_critical": False, "sort_order": 12},
                {"text": "Промывка масляной системы", "is_critical": False, "sort_order": 13},
                {"text": "Проверка виброизоляции", "is_critical": False, "sort_order": 14},
            ],
        },
        {
            "code": "to4",
            "name": "ТО-4",
            "hours": 2000,
            "sort_order": 3,
            "tasks": [
                {"text": "Все работы ТО-3", "is_critical": True, "sort_order": 0},
                {"text": "Замена ремня ГРМ", "is_critical": True, "sort_order": 1},
                {"text": "Замена водяного насоса", "is_critical": True, "sort_order": 2},
                {"text": "Замена всех ремней привода", "is_critical": True, "sort_order": 3},
                {"text": "Полная диагностика двигателя", "is_critical": True, "sort_order": 4},
                {"text": "Капитальный осмотр турбокомпрессора", "is_critical": True, "sort_order": 5},
                {"text": "Замена форсунок (при необходимости)", "is_critical": False, "sort_order": 6},
                {"text": "Проверка блока цилиндров", "is_critical": False, "sort_order": 7},
                {"text": "Замена сальников коленвала", "is_critical": False, "sort_order": 8},
                {"text": "Проверка маховика и стартера", "is_critical": False, "sort_order": 9},
                {"text": "Полная ревизия электропроводки", "is_critical": False, "sort_order": 10},
                {"text": "Обновление ПО контроллера (при наличии)", "is_critical": False, "sort_order": 11},
                {"text": "Составление дефектной ведомости", "is_critical": True, "sort_order": 12},
            ],
        },
    ],
}


@router.post("/api/seed-templates", response_model=TemplateOut, status_code=201)
async def seed_default_template(session: AsyncSession = Depends(get_session)):
    """Создаёт стандартный регламент ТО, если дефолтного ещё нет."""
    # Проверяем, есть ли уже дефолтный
    stmt = select(MaintenanceTemplate).where(MaintenanceTemplate.is_default == True)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Default template already exists")

    # Создаём из константы
    data = TemplateCreate(**DEFAULT_TEMPLATE)
    template = MaintenanceTemplate(
        name=data.name,
        description=data.description,
        is_default=data.is_default,
    )
    for iv in data.intervals:
        interval = MaintenanceInterval(
            name=iv.name,
            code=iv.code,
            hours=iv.hours,
            sort_order=iv.sort_order,
        )
        for tk in iv.tasks:
            task = MaintenanceTask(
                text=tk.text,
                is_critical=tk.is_critical,
                sort_order=tk.sort_order,
            )
            interval.tasks.append(task)
        template.intervals.append(interval)

    session.add(template)
    await session.commit()

    stmt = (
        select(MaintenanceTemplate)
        .where(MaintenanceTemplate.id == template.id)
        .options(
            selectinload(MaintenanceTemplate.intervals)
            .selectinload(MaintenanceInterval.tasks)
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one()
```

---

## Файл: `backend/app/main.py`

### Изменения

Добавить **2 строки**:

```diff
 from api.sites import router as sites_router
 from api.devices import router as devices_router
 from api.metrics import router as metrics_router
+from api.maintenance import router as maintenance_router
 from core.websocket import router as ws_router, redis_to_ws_bridge
```

```diff
 app.include_router(sites_router)
 app.include_router(devices_router)
 app.include_router(metrics_router)
+app.include_router(maintenance_router)
 app.include_router(ws_router)
```

---

## Тестирование

После реализации выполнить **последовательно** (PowerShell или curl):

### 1. Seed стандартного регламента
```bash
curl -s -X POST http://localhost:8010/api/seed-templates | python -m json.tool
```
Ожидание: 201, регламент с 4 интервалами и ~55 задачами суммарно.

### 2. Список регламентов
```bash
curl -s http://localhost:8010/api/templates | python -m json.tool
```
Ожидание: массив из 1 элемента, `interval_count: 4`.

### 3. Получить регламент с деталями
```bash
curl -s http://localhost:8010/api/templates/1 | python -m json.tool
```
Ожидание: `intervals` с вложенными `tasks`.

### 4. Статус ТО устройства (до первого ТО)
```bash
curl -s http://localhost:8010/api/devices/1/maintenance | python -m json.tool
```
Ожидание: `hours_at_last_to: null`, `status: "ok"` или `"warning"` или `"overdue"` в зависимости от моточасов.

### 5. Записать выполненное ТО
```bash
curl -s -X POST http://localhost:8010/api/devices/1/maintenance \
  -H "Content-Type: application/json" \
  -d '{
    "interval_id": 1,
    "engine_hours": 245.5,
    "performed_by": "Иванов И.И.",
    "notes": "Плановое ТО-1",
    "items": [
      {"task_text": "Замена моторного масла", "is_completed": true, "is_critical": true, "task_id": 1},
      {"task_text": "Замена масляного фильтра", "is_completed": true, "is_critical": true, "task_id": 2},
      {"task_text": "Проверка уровня ОЖ", "is_completed": true, "is_critical": false}
    ]
  }' | python -m json.tool
```
Ожидание: 201, `completed_count: 3`, `total_count: 3`.

### 6. История ТО
```bash
curl -s http://localhost:8010/api/devices/1/maintenance/history | python -m json.tool
```
Ожидание: массив с 1 записью, внутри `items`.

### 7. Статус ТО после ТО
```bash
curl -s http://localhost:8010/api/devices/1/maintenance | python -m json.tool
```
Ожидание: `hours_at_last_to: 245.5`, `hours_since_to` обновлён, `next_to_name: "ТО-2"`.

### 8. Повторный seed — должен вернуть 409
```bash
curl -s -X POST http://localhost:8010/api/seed-templates
```
Ожидание: 409 Conflict.

### 9. CRUD интервалов
```bash
# Добавить интервал
curl -s -X POST http://localhost:8010/api/templates/1/intervals \
  -H "Content-Type: application/json" \
  -d '{"name": "ТО-5", "code": "to5", "hours": 4000, "sort_order": 4}' | python -m json.tool

# Обновить интервал
curl -s -X PATCH http://localhost:8010/api/intervals/5 \
  -H "Content-Type: application/json" \
  -d '{"hours": 5000}' | python -m json.tool

# Удалить интервал
curl -s -X DELETE http://localhost:8010/api/intervals/5 -w "%{http_code}"
```

### 10. CRUD задач
```bash
# Добавить задачу
curl -s -X POST http://localhost:8010/api/intervals/1/tasks \
  -H "Content-Type: application/json" \
  -d '{"text": "Проверка нового узла", "is_critical": true, "sort_order": 99}' | python -m json.tool

# Обновить задачу
curl -s -X PATCH http://localhost:8010/api/tasks/1 \
  -H "Content-Type: application/json" \
  -d '{"text": "Замена моторного масла (синтетика 5W-40)"}' | python -m json.tool

# Удалить задачу
curl -s -X DELETE http://localhost:8010/api/tasks/99 -w "%{http_code}"
```

---

## Чеклист готовности

- [ ] Файл `backend/app/api/maintenance.py` создан (15 эндпоинтов)
- [ ] `backend/app/main.py` — импорт + include_router
- [ ] Backend стартует без ошибок
- [ ] `POST /api/seed-templates` → 201 (создаёт стандартный регламент)
- [ ] `GET /api/templates` → список с interval_count
- [ ] `GET /api/templates/1` → полное дерево intervals → tasks
- [ ] `POST/PATCH/DELETE` на templates, intervals, tasks работают
- [ ] `GET /api/devices/{id}/maintenance` → статус с прогрессом
- [ ] `POST /api/devices/{id}/maintenance` → запись ТО с items
- [ ] `GET /api/devices/{id}/maintenance/history` → история с items
- [ ] Swagger `/docs` показывает все 15 эндпоинтов
