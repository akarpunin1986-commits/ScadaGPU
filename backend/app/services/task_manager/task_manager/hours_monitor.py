"""Background monitor — check running_hours_b vs MaintenanceCard intervals."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_

from config import settings
from models.base import async_session
from models.task_manager import MaintenanceCard

logger = logging.getLogger("scada.task_manager")


class HoursThresholdMonitor:
    """Polls device running hours from Redis and creates tasks
    when a MaintenanceCard hour-based interval is reached."""

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
            "HoursThresholdMonitor started (interval=%ds)",
            settings.TM_HOURS_MONITOR_INTERVAL,
        )
        while self._running:
            try:
                await self._check_cycle()
            except Exception:
                logger.exception("HoursThresholdMonitor cycle error")
            try:
                await asyncio.sleep(settings.TM_HOURS_MONITOR_INTERVAL)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        self._running = False
        logger.info("HoursThresholdMonitor stop requested")

    # ───────────────────────────────────────────────────────
    # check cycle
    # ───────────────────────────────────────────────────────
    async def _check_cycle(self) -> None:
        async with async_session() as session:
            stmt = select(MaintenanceCard).where(
                and_(
                    MaintenanceCard.interval_hours.isnot(None),
                    MaintenanceCard.is_active.is_(True),
                )
            )
            result = await session.execute(stmt)
            cards = result.scalars().all()

        if not cards:
            return

        # Parse equipment → device mapping once
        try:
            device_map: dict[str, list[int]] = json.loads(settings.EQUIPMENT_DEVICE_MAP)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid EQUIPMENT_DEVICE_MAP, skipping hours check")
            return

        for card in cards:
            device_ids = device_map.get(card.equipment_code, [])
            if not device_ids:
                continue

            # Redis pipeline: get running_hours_b for all devices
            pipe = self._redis.pipeline()
            for did in device_ids:
                pipe.hget(f"metrics:{did}:latest", "running_hours_b")
            values = await pipe.execute()

            # Parse hours, skip None
            hours_list: list[float] = []
            for val in values:
                if val is not None:
                    raw = val.decode() if isinstance(val, bytes) else val
                    try:
                        hours_list.append(float(raw))
                    except (ValueError, TypeError):
                        pass

            if not hours_list:
                continue

            max_hours = max(hours_list)
            last_completed = card.last_completed_hours or 0
            hours_since_last = max_hours - last_completed

            if hours_since_last >= card.interval_hours:
                logger.info(
                    "Hours threshold reached for card #%d (%s): %.0f/%.0f h",
                    card.id,
                    card.equipment_code,
                    hours_since_last,
                    card.interval_hours,
                )
                await self._task_engine.create_task(
                    task_type="maintenance",
                    trigger_source="hours_threshold",
                    title=f"ТО {card.maintenance_name or card.maintenance_type} — "
                    f"{card.equipment_name} ({hours_since_last:.0f} ч)",
                    equipment_code=card.equipment_code,
                    site_id=card.site_id,
                    maintenance_card_id=card.id,
                )
            elif hours_since_last >= card.interval_hours * 0.9:
                logger.warning(
                    "Approaching hours threshold for card #%d (%s): "
                    "%.0f/%.0f h (90%%)",
                    card.id,
                    card.equipment_code,
                    hours_since_last,
                    card.interval_hours,
                )
