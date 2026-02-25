"""Alarm Analytics Detector — subscribes to Redis, detects bit transitions.

Listens to 'metrics:updates' channel. For each payload:
1. Extracts alarm register fields (alarm_reg_XX for 9560, alarm_sd_X etc for 9520N)
2. Compares each bit with previous state
3. On 0->1: captures snapshot, runs analysis, INSERT into alarm_analytics_events
4. On 1->0: UPDATE cleared_at, is_active=False

All exceptions are caught internally — never propagates errors outward.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.base import engine
from alarm_analytics.models import AlarmAnalyticsEvent
from alarm_analytics.alarm_definitions import get_alarm_map, get_alarm_fields
from alarm_analytics.snapshot import build_snapshot
from alarm_analytics.analyzer import analyze

logger = logging.getLogger("scada.alarm_analytics.detector")


class AlarmAnalyticsDetector:
    """Detects individual alarm bit transitions and persists to DB."""

    def __init__(
        self,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.redis = redis
        self.session_factory = session_factory
        self._running = False
        # device_id -> {field_name: register_value}
        self._prev_bits: dict[int, dict[str, int]] = {}

    async def _ensure_table(self) -> None:
        """Create alarm_analytics_events table if it doesn't exist."""
        try:
            async with engine.begin() as conn:
                await conn.run_sync(
                    AlarmAnalyticsEvent.__table__.create,
                    checkfirst=True,
                )
            logger.info("alarm_analytics_events table ensured")
        except Exception as exc:
            logger.error("Failed to create alarm_analytics_events table: %s", exc)

    async def start(self) -> None:
        self._running = True
        await self._ensure_table()
        await self._load_active()
        logger.info(
            "AlarmAnalyticsDetector started (loaded %d device states)",
            len(self._prev_bits),
        )
        await self._subscribe()

    async def stop(self) -> None:
        self._running = False
        logger.info("AlarmAnalyticsDetector stopped")

    # ------------------------------------------------------------------
    async def _load_active(self) -> None:
        """Load active alarm_analytics_events to reconstruct bit state after restart."""
        try:
            async with self.session_factory() as session:
                stmt = select(AlarmAnalyticsEvent).where(
                    AlarmAnalyticsEvent.is_active == True  # noqa: E712
                )
                result = await session.execute(stmt)
                for alarm in result.scalars().all():
                    did = alarm.device_id
                    if did not in self._prev_bits:
                        self._prev_bits[did] = {}
                    # Reconstruct: set the bit in the register field
                    # We store register field as alarm_code prefix mapping
                    # Find which register field this alarm belongs to
                    alarm_map = get_alarm_map(alarm.device_type)
                    for (field, bit), defn in alarm_map.items():
                        if defn["code"] == alarm.alarm_code:
                            current_val = self._prev_bits[did].get(field, 0)
                            self._prev_bits[did][field] = current_val | (1 << bit)
                            break
        except Exception as exc:
            logger.warning("AlarmAnalyticsDetector failed to load active: %s", exc)

    async def _subscribe(self) -> None:
        """Subscribe to Redis metrics:updates and process payloads."""
        while self._running:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe("metrics:updates")
                async for msg in pubsub.listen():
                    if not self._running:
                        break
                    if msg["type"] != "message":
                        continue
                    raw = msg["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    # Process in try/except — never propagate errors
                    try:
                        await self._process(payload)
                    except Exception as exc:
                        logger.error("AlarmAnalyticsDetector process error: %s", exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("AlarmAnalyticsDetector subscribe error: %s", exc)
                await asyncio.sleep(2)
            finally:
                try:
                    await pubsub.unsubscribe("metrics:updates")
                    await pubsub.close()
                except Exception:
                    pass

    @staticmethod
    def _extract_controller_time(payload: dict) -> datetime | None:
        """Extract controller RTC time from payload, return None if unavailable."""
        ct_str = payload.get("controller_time")
        if ct_str:
            try:
                return datetime.fromisoformat(ct_str)
            except (ValueError, TypeError):
                pass
        return None

    async def _process(self, payload: dict) -> None:
        """Process a single metrics payload — detect bit transitions."""
        device_id = payload.get("device_id")
        device_type = payload.get("device_type", "")
        online = payload.get("online", True)

        if device_id is None or not online:
            return

        # Use controller RTC time if available, otherwise server time
        now = self._extract_controller_time(payload) or datetime.utcnow()

        alarm_map = get_alarm_map(device_type)
        alarm_fields = get_alarm_fields(device_type)

        if not alarm_map or not alarm_fields:
            return  # Unknown device type — skip

        prev = self._prev_bits.get(device_id, {})
        current: dict[str, int] = {}

        # Extract current alarm register values from payload
        for field in alarm_fields:
            val = payload.get(field)
            if val is not None:
                current[field] = int(val)

        if not current:
            return  # No alarm data in this payload

        # Detect transitions for each known (field, bit) combination
        new_alarms: list[tuple[str, int, dict]] = []  # (field, bit, definition)
        cleared_alarms: list[tuple[str, int, dict]] = []

        for (field, bit), defn in alarm_map.items():
            if field not in current:
                continue

            cur_bit = bool(current[field] & (1 << bit))
            prev_val = prev.get(field, 0)
            was_bit = bool(prev_val & (1 << bit))

            if cur_bit and not was_bit:
                new_alarms.append((field, bit, defn))
            elif not cur_bit and was_bit:
                cleared_alarms.append((field, bit, defn))

        # Process transitions
        if new_alarms or cleared_alarms:
            # Build snapshot once for all new alarms in this cycle
            snapshot = None
            if new_alarms:
                snapshot = build_snapshot(device_type, payload)

            try:
                async with self.session_factory() as session:
                    for field, bit, defn in new_alarms:
                        analysis = analyze(
                            defn["code"], device_type, snapshot, defn
                        )
                        event = AlarmAnalyticsEvent(
                            device_id=device_id,
                            device_type=device_type,
                            alarm_code=defn["code"],
                            alarm_name=defn["name"],
                            alarm_name_ru=defn["name_ru"],
                            alarm_severity=defn["severity"],
                            alarm_register=int(field.split("_")[-1]) if field[-1].isdigit() else 0,
                            alarm_bit=bit,
                            is_active=True,
                            occurred_at=now,
                            metrics_snapshot=snapshot,
                            analysis_result=analysis,
                        )
                        session.add(event)
                        logger.info(
                            "AA ALARM ON: device=%d code=%s name=%s",
                            device_id, defn["code"], defn["name"],
                        )

                    for field, bit, defn in cleared_alarms:
                        stmt = select(AlarmAnalyticsEvent).where(
                            and_(
                                AlarmAnalyticsEvent.device_id == device_id,
                                AlarmAnalyticsEvent.alarm_code == defn["code"],
                                AlarmAnalyticsEvent.is_active == True,  # noqa: E712
                            )
                        ).order_by(AlarmAnalyticsEvent.occurred_at.desc())
                        result = await session.execute(stmt)
                        active_alarms = result.scalars().all()
                        for active_alarm in active_alarms:
                            active_alarm.cleared_at = now
                            active_alarm.is_active = False
                        if active_alarms:
                            logger.info(
                                "AA ALARM OFF: device=%d code=%s (%d cleared)",
                                device_id, defn["code"], len(active_alarms),
                            )

                    await session.commit()
            except Exception as exc:
                logger.error("AlarmAnalyticsDetector DB error: %s", exc)

        # Update previous state
        self._prev_bits[device_id] = current
