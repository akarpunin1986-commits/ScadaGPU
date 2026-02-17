"""
Phase 3 — Maintenance Scheduler.

Background task that runs every MAINTENANCE_CHECK_INTERVAL seconds:
1. Reads engine hours for all generator devices from Redis
2. Loads default maintenance template intervals from DB
3. For each device: finds next TO, calculates remaining hours
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

THRESHOLD_WARNING = 50
THRESHOLD_CRITICAL = 20


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
            template = await self._load_default_template(session)
            if not template:
                logger.debug("No default maintenance template — skipping check")
                return

            intervals = sorted(template.intervals, key=lambda i: i.hours)
            if not intervals:
                return

            devices = await self._load_generator_devices(session)
            if not devices:
                return

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
            return

        hours_at_last_to = await self._get_last_to_hours(session, device.id)
        hours_since_to = current_hours - hours_at_last_to

        next_interval: MaintenanceInterval | None = None
        for iv in intervals:
            if hours_since_to < iv.hours:
                next_interval = iv
                break
        if next_interval is None:
            next_interval = intervals[-1]

        hours_remaining = next_interval.hours - hours_since_to

        if hours_remaining <= 0:
            severity = AlertSeverity.overdue
        elif hours_remaining <= THRESHOLD_CRITICAL:
            severity = AlertSeverity.critical
        elif hours_remaining <= THRESHOLD_WARNING:
            severity = AlertSeverity.warning
        else:
            await self._resolve_alerts(session, device.id)
            return

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
                await self._publish_alert(existing, "updated")
        else:
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
            await session.flush()
            logger.info(
                "Alert created: device=%d %s %s remaining=%.0fh",
                device.id, interval.name, severity.value, hours_remaining,
            )
            await self._publish_alert(alert, "created")

    async def _resolve_alerts(
        self, session: AsyncSession, device_id: int
    ) -> None:
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
        payload = {
            "type": "maintenance_alert",
            "action": action,
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
