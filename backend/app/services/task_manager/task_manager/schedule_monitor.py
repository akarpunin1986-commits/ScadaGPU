"""Background monitor — calendar-based maintenance scheduling."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_

from config import settings
from models.base import async_session
from models.task_manager import MaintenanceCard

logger = logging.getLogger("scada.task_manager")


class ScheduleMonitor:
    """Creates maintenance tasks when a MaintenanceCard's day-based
    interval has elapsed since the last completion."""

    def __init__(self, redis, task_engine):
        self._redis = redis
        self._task_engine = task_engine
        self._running = False

    # ───────────────────────────────────────────────────────
    # lifecycle
    # ───────────────────────────────────────────────────────
    async def start(self) -> None:
        self._running = True
        logger.info(
            "ScheduleMonitor started (interval=%ds)",
            settings.TM_SCHEDULE_MONITOR_INTERVAL,
        )
        while self._running:
            try:
                await self._check_cycle()
            except Exception:
                logger.exception("ScheduleMonitor cycle error")
            try:
                await asyncio.sleep(settings.TM_SCHEDULE_MONITOR_INTERVAL)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        self._running = False
        logger.info("ScheduleMonitor stop requested")

    # ───────────────────────────────────────────────────────
    # check cycle
    # ───────────────────────────────────────────────────────
    async def _check_cycle(self) -> None:
        now = datetime.utcnow()

        async with async_session() as session:
            stmt = select(MaintenanceCard).where(
                and_(
                    MaintenanceCard.interval_days.isnot(None),
                    MaintenanceCard.is_active.is_(True),
                )
            )
            result = await session.execute(stmt)
            cards = result.scalars().all()

        for card in cards:
            if card.last_completed_at:
                days_since = (now - card.last_completed_at).days
            else:
                days_since = 999  # never completed — overdue

            if days_since >= card.interval_days:
                logger.info(
                    "Schedule threshold reached for card #%d (%s): "
                    "%d/%d days",
                    card.id,
                    card.equipment_code,
                    days_since,
                    card.interval_days,
                )
                await self._task_engine.create_task(
                    task_type="maintenance",
                    trigger_source="schedule",
                    title=f"ТО {card.maintenance_name or card.maintenance_type} — "
                    f"{card.equipment_name} ({days_since} дн.)",
                    equipment_code=card.equipment_code,
                    site_id=card.site_id,
                    maintenance_card_id=card.id,
                )
