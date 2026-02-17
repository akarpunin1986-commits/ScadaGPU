# Phase 3 Task 3 — Scheduler проверки моточасов + алерты

## Цель
Создать фоновый scheduler, который каждые N секунд:
1. Читает моточасы всех генераторов из Redis
2. Сравнивает с интервалами ТО из дефолтного шаблона
3. При приближении/просрочке ТО — создаёт/обновляет алерт в БД
4. Пушит алерт в WebSocket через Redis pub/sub (канал `maintenance:alerts`)
5. Фронтенд получает уведомления в реальном времени

## Архитектура

```
                  ┌─────────────┐
                  │ Redis       │
                  │ device:*    │◄── Poller (run_hours)
                  │ :metrics    │
                  └──────┬──────┘
                         │ read
                  ┌──────▼──────┐
                  │  Maintenance │
                  │  Scheduler   │──► PostgreSQL (maintenance_alerts)
                  │  (30s loop)  │
                  └──────┬──────┘
                         │ publish
                  ┌──────▼──────┐
                  │ Redis PubSub│
                  │ maintenance │
                  │ :alerts     │
                  └──────┬──────┘
                         │ bridge
                  ┌──────▼──────┐
                  │  WebSocket  │──► Frontend
                  │  /ws/metrics│
                  └─────────────┘
```

---

## Файлы для создания/изменения

| # | Файл | Действие |
|---|------|----------|
| 1 | `backend/app/models/maintenance_alert.py` | **Создать** — модель MaintenanceAlert |
| 2 | `backend/app/models/__init__.py` | **Обновить** — добавить MaintenanceAlert |
| 3 | `backend/app/services/maintenance_scheduler.py` | **Создать** — фоновый scheduler |
| 4 | `backend/app/core/websocket.py` | **Обновить** — добавить подписку на `maintenance:alerts` |
| 5 | `backend/app/config.py` | **Обновить** — добавить `MAINTENANCE_CHECK_INTERVAL` |
| 6 | `backend/app/main.py` | **Обновить** — запустить scheduler в lifespan |
| 7 | `backend/app/api/maintenance.py` | **Обновить** — добавить GET /api/alerts |
| 8 | Alembic миграция | **Сгенерировать** — таблица maintenance_alerts |

---

## 1. Модель `MaintenanceAlert`

**Создать файл** `backend/app/models/maintenance_alert.py`:

```python
"""Maintenance alert model — persistent storage for ТО warnings."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class AlertSeverity(str, enum.Enum):
    info = "info"           # ТО далеко (>50ч), но для информации
    warning = "warning"     # ТО скоро (≤50ч)
    critical = "critical"   # ТО очень скоро (≤20ч)
    overdue = "overdue"     # ТО просрочено (≤0ч)


class AlertStatus(str, enum.Enum):
    active = "active"
    acknowledged = "acknowledged"   # Оператор видел, но ТО не сделано
    resolved = "resolved"           # ТО выполнено


class MaintenanceAlert(Base):
    __tablename__ = "maintenance_alerts"

    # Уникальность: один активный алерт на устройство + интервал
    __table_args__ = (
        UniqueConstraint("device_id", "interval_id", "status",
                         name="uq_maintenance_alerts_device_interval_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    interval_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_intervals.id", ondelete="CASCADE")
    )

    severity: Mapped[AlertSeverity]                       # warning / critical / overdue
    status: Mapped[AlertStatus] = mapped_column(default=AlertStatus.active)

    # Snapshot данных на момент создания/обновления
    engine_hours: Mapped[float] = mapped_column()         # Текущие моточасы
    hours_remaining: Mapped[float] = mapped_column()      # Осталось часов до ТО
    interval_name: Mapped[str] = mapped_column(String(50)) # "ТО-1" (снапшот)
    interval_hours: Mapped[int] = mapped_column()          # 250 (снапшот)
    device_name: Mapped[str] = mapped_column(String(100))  # "Генератор 1" (снапшот)
    site_code: Mapped[str] = mapped_column(String(50), default="")

    message: Mapped[str] = mapped_column(String(500))     # Человекочитаемое сообщение
    acknowledged_by: Mapped[str | None] = mapped_column(String(100), default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    device = relationship("Device")
    interval = relationship("MaintenanceInterval")

    def __repr__(self) -> str:
        return f"<MaintenanceAlert {self.severity.value} device={self.device_id} {self.interval_name}>"
```

---

## 2. Обновить `models/__init__.py`

Добавить:
```python
from models.maintenance_alert import MaintenanceAlert, AlertSeverity, AlertStatus
```

И в `__all__` добавить:
```python
    "MaintenanceAlert",
    "AlertSeverity",
    "AlertStatus",
```

---

## 3. Scheduler `backend/app/services/maintenance_scheduler.py`

**Создать файл:**

```python
"""
Phase 3 — Maintenance Scheduler.

Background task that runs every MAINTENANCE_CHECK_INTERVAL seconds:
1. Reads engine hours for all generator devices from Redis
2. Loads default maintenance template intervals from DB
3. For each device: finds next ТО, calculates remaining hours
4. Creates/updates MaintenanceAlert records in DB
5. Publishes alerts to Redis pub/sub channel 'maintenance:alerts'
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from config import settings
from models.device import Device
from models.site import Site
from models.maintenance import (
    MaintenanceTemplate,
    MaintenanceInterval,
    MaintenanceLog,
)
from models.maintenance_alert import (
    MaintenanceAlert,
    AlertSeverity,
    AlertStatus,
)

logger = logging.getLogger("scada.maintenance_scheduler")

# Thresholds (matching frontend logic)
THRESHOLD_WARNING = 50    # hours — severity: warning
THRESHOLD_CRITICAL = 20   # hours — severity: critical
# <= 0 hours — severity: overdue


class MaintenanceScheduler:
    """Background task: checks engine hours and creates/updates maintenance alerts."""

    def __init__(
        self,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.redis = redis
        self.session_factory = session_factory
        self._running = False

    async def start(self) -> None:
        self._running = True
        interval = settings.MAINTENANCE_CHECK_INTERVAL
        logger.info(
            "MaintenanceScheduler started (check every %ds, "
            "thresholds: warning=%dh, critical=%dh)",
            interval, THRESHOLD_WARNING, THRESHOLD_CRITICAL,
        )

        while self._running:
            try:
                await self._check_cycle()
            except Exception as exc:
                logger.error("MaintenanceScheduler cycle error: %s", exc, exc_info=True)
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        self._running = False
        logger.info("MaintenanceScheduler stopped")

    # ------------------------------------------------------------------
    # Main check cycle
    # ------------------------------------------------------------------

    async def _check_cycle(self) -> None:
        async with self.session_factory() as session:
            # 1. Load default template with intervals
            template = await self._load_default_template(session)
            if not template:
                logger.debug("No default maintenance template — skipping check")
                return

            intervals = sorted(template.intervals, key=lambda i: i.hours)
            if not intervals:
                return

            # 2. Load all active generator devices
            devices = await self._load_generator_devices(session)
            if not devices:
                return

            # 3. For each device: read hours from Redis, calculate, alert
            for device in devices:
                await self._check_device(session, device, intervals)

            await session.commit()

    async def _load_default_template(
        self, session: AsyncSession
    ) -> MaintenanceTemplate | None:
        stmt = (
            select(MaintenanceTemplate)
            .where(MaintenanceTemplate.is_default == True)  # noqa: E712
            .options(selectinload(MaintenanceTemplate.intervals))
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _load_generator_devices(
        self, session: AsyncSession
    ) -> list[Device]:
        stmt = (
            select(Device)
            .where(
                and_(
                    Device.is_active == True,  # noqa: E712
                    Device.device_type == "generator",
                )
            )
            .options(selectinload(Device.site))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _get_engine_hours(self, device_id: int) -> float | None:
        """Read current engine hours from Redis."""
        raw = await self.redis.get(f"device:{device_id}:metrics")
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data.get("run_hours")
        except (json.JSONDecodeError, TypeError):
            return None

    async def _get_last_to_hours(
        self, session: AsyncSession, device_id: int
    ) -> float:
        """Get engine hours at last maintenance, or 0 if never serviced."""
        stmt = (
            select(MaintenanceLog.engine_hours)
            .where(MaintenanceLog.device_id == device_id)
            .order_by(MaintenanceLog.performed_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return row if row is not None else 0.0

    # ------------------------------------------------------------------
    # Per-device check
    # ------------------------------------------------------------------

    async def _check_device(
        self,
        session: AsyncSession,
        device: Device,
        intervals: list[MaintenanceInterval],
    ) -> None:
        current_hours = await self._get_engine_hours(device.id)
        if current_hours is None:
            return  # Device offline — skip

        hours_at_last_to = await self._get_last_to_hours(session, device.id)
        hours_since_to = current_hours - hours_at_last_to

        # Find next interval
        next_interval: MaintenanceInterval | None = None
        for iv in intervals:
            if hours_since_to < iv.hours:
                next_interval = iv
                break
        if next_interval is None:
            next_interval = intervals[-1]  # All overdue — use last

        hours_remaining = next_interval.hours - hours_since_to

        # Determine severity
        if hours_remaining <= 0:
            severity = AlertSeverity.overdue
        elif hours_remaining <= THRESHOLD_CRITICAL:
            severity = AlertSeverity.critical
        elif hours_remaining <= THRESHOLD_WARNING:
            severity = AlertSeverity.warning
        else:
            # No alert needed — resolve any existing active alerts for this device
            await self._resolve_alerts(session, device.id)
            return

        # Build message
        site_code = device.site.code if device.site else ""
        if severity == AlertSeverity.overdue:
            message = (
                f"{device.name}: {next_interval.name} просрочено на "
                f"{abs(hours_remaining):.0f}ч (моточасы: {current_hours:.0f})"
            )
        else:
            message = (
                f"{device.name}: до {next_interval.name} осталось "
                f"{hours_remaining:.0f}ч (моточасы: {current_hours:.0f})"
            )

        # Create or update alert
        await self._upsert_alert(
            session,
            device=device,
            interval=next_interval,
            severity=severity,
            engine_hours=current_hours,
            hours_remaining=hours_remaining,
            site_code=site_code,
            message=message,
        )

    async def _upsert_alert(
        self,
        session: AsyncSession,
        *,
        device: Device,
        interval: MaintenanceInterval,
        severity: AlertSeverity,
        engine_hours: float,
        hours_remaining: float,
        site_code: str,
        message: str,
    ) -> None:
        """Create new alert or update existing active one."""
        # Look for existing active alert for this device + interval
        stmt = select(MaintenanceAlert).where(
            and_(
                MaintenanceAlert.device_id == device.id,
                MaintenanceAlert.interval_id == interval.id,
                MaintenanceAlert.status == AlertStatus.active,
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update if severity changed or hours updated significantly
            changed = (
                existing.severity != severity
                or abs(existing.engine_hours - engine_hours) >= 1.0
            )
            if changed:
                existing.severity = severity
                existing.engine_hours = engine_hours
                existing.hours_remaining = hours_remaining
                existing.message = message
                logger.info(
                    "Alert updated: device=%d %s %s remaining=%.0fh",
                    device.id, interval.name, severity.value, hours_remaining,
                )
                # Publish update
                await self._publish_alert(existing, "updated")
        else:
            # Create new alert
            alert = MaintenanceAlert(
                device_id=device.id,
                interval_id=interval.id,
                severity=severity,
                engine_hours=engine_hours,
                hours_remaining=hours_remaining,
                interval_name=interval.name,
                interval_hours=interval.hours,
                device_name=device.name,
                site_code=site_code,
                message=message,
            )
            session.add(alert)
            await session.flush()  # Get id assigned
            logger.info(
                "Alert created: device=%d %s %s remaining=%.0fh",
                device.id, interval.name, severity.value, hours_remaining,
            )
            await self._publish_alert(alert, "created")

    async def _resolve_alerts(
        self, session: AsyncSession, device_id: int
    ) -> None:
        """Resolve all active alerts for a device (ТО far away, no alert needed)."""
        stmt = select(MaintenanceAlert).where(
            and_(
                MaintenanceAlert.device_id == device_id,
                MaintenanceAlert.status == AlertStatus.active,
            )
        )
        result = await session.execute(stmt)
        alerts = result.scalars().all()
        for alert in alerts:
            alert.status = AlertStatus.resolved
            logger.info(
                "Alert resolved: device=%d %s",
                device_id, alert.interval_name,
            )
            await self._publish_alert(alert, "resolved")

    async def _publish_alert(
        self, alert: MaintenanceAlert, action: str
    ) -> None:
        """Publish alert to Redis pub/sub for WebSocket delivery."""
        payload = {
            "type": "maintenance_alert",
            "action": action,  # "created" | "updated" | "resolved"
            "alert": {
                "id": alert.id,
                "device_id": alert.device_id,
                "device_name": alert.device_name,
                "site_code": alert.site_code,
                "interval_id": alert.interval_id,
                "interval_name": alert.interval_name,
                "interval_hours": alert.interval_hours,
                "severity": alert.severity.value,
                "status": alert.status.value,
                "engine_hours": alert.engine_hours,
                "hours_remaining": alert.hours_remaining,
                "message": alert.message,
                "created_at": alert.created_at.isoformat() if alert.created_at else None,
            },
        }
        await self.redis.publish(
            "maintenance:alerts",
            json.dumps(payload, default=str),
        )
```

---

## 4. Обновить `backend/app/core/websocket.py`

Добавить второй bridge для канала `maintenance:alerts`.

**Изменения:**

После существующей функции `redis_to_ws_bridge` добавить:

```python
async def maintenance_alerts_bridge(redis: Redis) -> None:
    """Subscribe to Redis PubSub 'maintenance:alerts' and broadcast to all WS clients."""
    logger.info("Maintenance alerts bridge started, subscribing to maintenance:alerts")
    pubsub = redis.pubsub()
    await pubsub.subscribe("maintenance:alerts")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                payload = message["data"]
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                await manager.broadcast(payload)
    except Exception as exc:
        logger.error("Maintenance alerts bridge error: %s", exc)
    finally:
        await pubsub.unsubscribe("maintenance:alerts")
        await pubsub.close()
```

**Также обновить импорт в `__init__`:** функция должна быть импортируемой.

---

## 5. Обновить `backend/app/config.py`

Добавить настройку интервала проверки:

```python
    # Maintenance scheduler
    MAINTENANCE_CHECK_INTERVAL: int = 30  # seconds between checks
```

Добавить **после** строки `DEMO_MODE: bool = False`.

---

## 6. Обновить `backend/app/main.py`

### Добавить импорт:
```python
from services.maintenance_scheduler import MaintenanceScheduler
from core.websocket import maintenance_alerts_bridge
```

Обратить внимание: `maintenance_alerts_bridge` импортируется из `core.websocket` — нужно добавить его в строку импорта, которая уже есть:

```python
# Было:
from core.websocket import router as ws_router, redis_to_ws_bridge

# Стало:
from core.websocket import router as ws_router, redis_to_ws_bridge, maintenance_alerts_bridge
```

### В lifespan, после `ws_bridge_task = ...`:

```python
    # Maintenance scheduler
    scheduler = MaintenanceScheduler(redis, async_session)
    app.state.maintenance_scheduler = scheduler
    scheduler_task = asyncio.create_task(scheduler.start())

    # Maintenance alerts → WebSocket bridge
    alerts_bridge_task = asyncio.create_task(maintenance_alerts_bridge(redis))
```

### В shutdown-секции (после `ws_bridge_task.cancel()`):

```python
    await scheduler.stop()
    scheduler_task.cancel()
    alerts_bridge_task.cancel()

    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass

    try:
        await alerts_bridge_task
    except asyncio.CancelledError:
        pass
```

---

## 7. Обновить `backend/app/api/maintenance.py`

Добавить 3 эндпоинта для алертов.

### Добавить импорты (в начало файла):

```python
from models.maintenance_alert import MaintenanceAlert, AlertSeverity, AlertStatus
```

### Добавить Pydantic-схемы:

```python
# ---- Alert schemas ----

class AlertOut(BaseModel):
    id: int
    device_id: int
    device_name: str
    site_code: str
    interval_id: int
    interval_name: str
    interval_hours: int
    severity: str       # "warning" | "critical" | "overdue"
    status: str         # "active" | "acknowledged" | "resolved"
    engine_hours: float
    hours_remaining: float
    message: str
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class AlertAcknowledge(BaseModel):
    acknowledged_by: str  # Имя оператора
```

### Добавить эндпоинты:

```python
# ===========================================================================
#  16. GET /api/alerts — список активных алертов ТО
# ===========================================================================

@router.get("/api/alerts", response_model=list[AlertOut])
async def list_alerts(
    status: str | None = Query(None, description="Filter: active|acknowledged|resolved"),
    device_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(MaintenanceAlert).order_by(
        MaintenanceAlert.severity.desc(),
        MaintenanceAlert.created_at.desc(),
    )
    if status:
        stmt = stmt.where(MaintenanceAlert.status == status)
    else:
        # Default: show active + acknowledged (not resolved)
        stmt = stmt.where(MaintenanceAlert.status != AlertStatus.resolved)
    if device_id:
        stmt = stmt.where(MaintenanceAlert.device_id == device_id)

    result = await session.execute(stmt)
    return result.scalars().all()


# ===========================================================================
#  17. PATCH /api/alerts/{id}/acknowledge — оператор подтвердил алерт
# ===========================================================================

@router.patch("/api/alerts/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: int,
    data: AlertAcknowledge,
    session: AsyncSession = Depends(get_session),
):
    alert = await session.get(MaintenanceAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    if alert.status != AlertStatus.active:
        raise HTTPException(400, "Alert is not active")

    alert.status = AlertStatus.acknowledged
    alert.acknowledged_by = data.acknowledged_by
    alert.acknowledged_at = datetime.utcnow()
    await session.commit()
    await session.refresh(alert)
    return alert


# ===========================================================================
#  18. GET /api/alerts/summary — сводка по алертам для дашборда
# ===========================================================================

@router.get("/api/alerts/summary")
async def alerts_summary(session: AsyncSession = Depends(get_session)):
    """Returns count of alerts by severity for active + acknowledged."""
    stmt = select(MaintenanceAlert).where(
        MaintenanceAlert.status != AlertStatus.resolved
    )
    result = await session.execute(stmt)
    alerts = result.scalars().all()

    summary = {"warning": 0, "critical": 0, "overdue": 0, "total": 0}
    for a in alerts:
        summary[a.severity.value] = summary.get(a.severity.value, 0) + 1
        summary["total"] += 1
    return summary
```

---

## 8. Alembic миграция

### Команда:
```bash
docker exec -it scada-backend bash -c \
  "cd /app && alembic revision --autogenerate -m 'add_maintenance_alerts'"
```

### Ожидаемая таблица:

**`maintenance_alerts`**:
- id (PK)
- device_id (FK → devices, CASCADE)
- interval_id (FK → maintenance_intervals, CASCADE)
- severity (enum: info, warning, critical, overdue)
- status (enum: active, acknowledged, resolved)
- engine_hours (float)
- hours_remaining (float)
- interval_name (varchar 50)
- interval_hours (int)
- device_name (varchar 100)
- site_code (varchar 50)
- message (varchar 500)
- acknowledged_by (varchar 100, nullable)
- acknowledged_at (timestamp, nullable)
- created_at (timestamp, server_default now())
- updated_at (timestamp, server_default now(), onupdate now())
- UNIQUE(device_id, interval_id, status)

### Применить:
```bash
docker exec -it scada-backend bash -c "cd /app && alembic upgrade head"
```

---

## WebSocket формат сообщений

Фронтенд получает через `/ws/metrics` **два типа** сообщений:

### 1. Метрики (уже есть):
```json
{"device_id": 1, "site_code": "MKZ", "device_type": "generator", "run_hours": 1237, ...}
```

### 2. Алерты ТО (новое):
```json
{
  "type": "maintenance_alert",
  "action": "created",
  "alert": {
    "id": 5,
    "device_id": 1,
    "device_name": "Генератор 1",
    "site_code": "MKZ",
    "interval_name": "ТО-1",
    "interval_hours": 250,
    "severity": "warning",
    "status": "active",
    "engine_hours": 1237,
    "hours_remaining": 13,
    "message": "Генератор 1: до ТО-1 осталось 13ч (моточасы: 1237)"
  }
}
```

Фронтенд отличает по наличию поля `type`: если есть `type === "maintenance_alert"` — это алерт, иначе — метрика.

---

## Логика severity (совпадает с фронтендом)

| Осталось часов | Severity | Цвет на фронте |
|---|---|---|
| > 50 | *нет алерта* | зелёный (ok) |
| 20 < remaining ≤ 50 | `warning` | жёлтый |
| 0 < remaining ≤ 20 | `critical` | оранжевый |
| ≤ 0 | `overdue` | красный, пульсирует |

---

## Тестирование

### 1. Проверить что scheduler стартует:
```bash
docker compose logs -f backend 2>&1 | grep -i maintenance
```
Ожидание: `MaintenanceScheduler started (check every 30s, thresholds: warning=50h, critical=20h)`

### 2. Список алертов (до первого цикла — пусто):
```bash
curl -s http://localhost:8010/api/alerts | python -m json.tool
```

### 3. Подождать 30с, затем проверить снова:
```bash
curl -s http://localhost:8010/api/alerts | python -m json.tool
```
Ожидание: алерты появились (demo poller генерирует 1237+ моточасов, последнее ТО было на 1237 → hours_since_to ~= 0 → статус ok).

Чтобы увидеть алерт, нужно чтобы `hours_since_to` превысил порог. В demo poller `run_hours = 1237 + tick // 1800`. Если после последнего ТО (1237ч) наберётся 200+ часов → `warning` для ТО-1(250ч).

**Быстрый способ проверки** — создать seed-данные: записать ТО с маленькими hours, и scheduler обнаружит приближение. Или подождать пока demo поднимет моточасы.

### 4. Сводка:
```bash
curl -s http://localhost:8010/api/alerts/summary | python -m json.tool
```

### 5. Acknowledge:
```bash
curl -s -X PATCH http://localhost:8010/api/alerts/1/acknowledge \
  -H "Content-Type: application/json" \
  -d '{"acknowledged_by": "Иванов И.И."}' | python -m json.tool
```

### 6. WebSocket — проверить что приходят алерты:
Открыть `ws://localhost:8010/ws/metrics` в браузере DevTools и ждать сообщений с `type: "maintenance_alert"`.

---

## Чеклист готовности

- [ ] `backend/app/models/maintenance_alert.py` — модель MaintenanceAlert с enum Severity/Status
- [ ] `backend/app/models/__init__.py` — обновлён
- [ ] Alembic миграция создана и применена
- [ ] `backend/app/services/maintenance_scheduler.py` — scheduler с циклом 30с
- [ ] `backend/app/core/websocket.py` — добавлен `maintenance_alerts_bridge`
- [ ] `backend/app/config.py` — добавлен `MAINTENANCE_CHECK_INTERVAL = 30`
- [ ] `backend/app/main.py` — scheduler и alerts bridge запущены в lifespan
- [ ] `backend/app/api/maintenance.py` — 3 новых эндпоинта (GET alerts, PATCH acknowledge, GET summary)
- [ ] Backend стартует без ошибок
- [ ] Scheduler пишет в лог
- [ ] `GET /api/alerts` возвращает результат
- [ ] `GET /api/alerts/summary` возвращает counts
- [ ] WebSocket получает `maintenance_alert` сообщения
