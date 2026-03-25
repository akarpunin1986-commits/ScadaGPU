"""
Maintenance Value Poller — background service updating equipment operating values.

Reads from Redis cache (modbus metrics), calculates calendar-based values,
and updates equipment_units.current_value.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import select

from config import settings
from models.base import async_session
from models.equipment_unit import EquipmentUnit

logger = logging.getLogger("scada.maintenance")


class MaintenanceValuePoller:
    """Background poller that updates current_value for all active equipment."""

    def __init__(self, redis):
        self.redis = redis
        self._running = False

    async def poll_all(self):
        """Update current_value for all active equipment_units."""
        async with async_session() as session:
            equipment_list = (await session.execute(
                select(EquipmentUnit).where(EquipmentUnit.is_active.is_(True))
            )).scalars().all()

            updated = 0
            for eq in equipment_list:
                try:
                    new_value = await self._read_value(eq)
                    if new_value is not None and new_value != eq.current_value:
                        eq.current_value = new_value
                        eq.current_value_updated_at = datetime.utcnow()
                        updated += 1
                except Exception as exc:
                    logger.error(
                        "Failed to poll value for equipment %d (%s): %s",
                        eq.id, eq.code, exc,
                    )

            if updated > 0:
                await session.commit()
                logger.debug("Value poller updated %d/%d equipment", updated, len(equipment_list))

    async def _read_value(self, eq: EquipmentUnit) -> int | None:
        """Read current value based on hours_source type."""
        source = eq.hours_source
        config = eq.hours_source_config or {}

        if source == "modbus":
            return await self._read_modbus(eq, config)
        elif source == "calendar":
            return self._calc_calendar(eq, config)
        elif source == "manual":
            # Manual values are updated via API, skip polling
            return None
        elif source == "external":
            # Future: external API integration
            return None
        else:
            logger.warning("Unknown hours_source '%s' for equipment %d", source, eq.id)
            return None

    async def _read_modbus(self, eq: EquipmentUnit, config: dict) -> int | None:
        """Read value from Redis cache (already polled by ModbusPoller).

        Expected config: {"device_id": 1, "metric": "run_hours"}
        Redis key: device:{device_id}:metrics — JSON with all metric values.
        """
        device_id = config.get("device_id")
        metric_name = config.get("metric", "run_hours")
        if not device_id:
            logger.warning(
                "Missing device_id in modbus config for equipment %d", eq.id,
            )
            return None

        # Primary: device:{id}:metrics (ModbusPoller writes here)
        redis_key = f"device:{device_id}:metrics"
        raw = await self.redis.get(redis_key)
        if not raw:
            logger.debug("No Redis data for key %s (equipment %d)", redis_key, eq.id)
            return None

        try:
            metrics = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid JSON in Redis key %s", redis_key)
            return None

        # Read by metric name (e.g. "run_hours")
        value = metrics.get(metric_name)
        if value is None:
            # Fallback: try register number if config has it
            register = config.get("register")
            if register is not None:
                value = metrics.get(str(register))

        if value is None:
            return None

        try:
            return int(float(value))
        except (ValueError, TypeError):
            logger.warning(
                "Non-numeric value for equipment %d, metric %s: %s",
                eq.id, metric_name, value,
            )
            return None

    def _calc_calendar(self, eq: EquipmentUnit, config: dict) -> int | None:
        """Calculate virtual hours from calendar.

        Expected config: {"hours_per_day": 16, "working_days": "mon-sat"}
        Formula: (now - epoch_date).days * hours_per_day
        """
        hours_per_day = config.get("hours_per_day", 0)
        if hours_per_day <= 0:
            return None

        if not eq.epoch_date:
            return eq.epoch_value

        days_elapsed = (datetime.utcnow() - eq.epoch_date).days
        if days_elapsed < 0:
            days_elapsed = 0

        # Virtual hours = epoch_value + days * hours_per_day
        return eq.epoch_value + (days_elapsed * hours_per_day)

    async def run_loop(self):
        """Background loop: poll every MAINT_VALUE_POLL_INTERVAL seconds."""
        self._running = True
        interval = settings.MAINT_VALUE_POLL_INTERVAL
        logger.info("MaintenanceValuePoller started (interval=%ds)", interval)

        while self._running:
            try:
                await self.poll_all()
            except Exception as exc:
                logger.error("ValuePoller loop error: %s", exc, exc_info=True)

            await asyncio.sleep(interval)

    def stop(self):
        """Signal the loop to stop."""
        self._running = False
        logger.info("MaintenanceValuePoller stop requested")
