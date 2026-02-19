"""Phase 6 — AlarmDetector: detects alarm state transitions and persists to DB.

Subscribes to Redis PubSub 'metrics:updates'. Compares alarm boolean flags
(alarm_common, alarm_shutdown, alarm_warning, alarm_block) with previous state.
On transition False→True: INSERT new alarm_event.
On transition True→False: UPDATE existing (cleared_at, is_active=False).
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.alarm_event import AlarmEvent

logger = logging.getLogger("scada.alarm_detector")

# Modbus flag → (alarm_code, severity, human message)
ALARM_FLAG_MAP = {
    "alarm_common":   ("COMMON",    "error",   "Общая авария"),
    "alarm_shutdown": ("SHUTDOWN",  "error",   "Аварийный останов"),
    "alarm_warning":  ("WARNING",   "warning", "Предупреждение"),
    "alarm_block":    ("BLOCK",     "error",   "Блокировка"),
    "alarm_trip_stop":("TRIP_STOP", "error",   "Аварийный стоп"),
}


class AlarmDetector:

    def __init__(
        self,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.redis = redis
        self.session_factory = session_factory
        self._running = False
        self._prev: dict[int, dict[str, bool]] = {}

    async def start(self) -> None:
        self._running = True
        await self._load_active()
        logger.info("AlarmDetector started (loaded %d device states)", len(self._prev))
        await self._subscribe()

    async def stop(self) -> None:
        self._running = False
        logger.info("AlarmDetector stopped")

    # ------------------------------------------------------------------
    async def _load_active(self) -> None:
        """Load active alarms from DB to init state after restart."""
        try:
            async with self.session_factory() as session:
                stmt = select(AlarmEvent).where(AlarmEvent.is_active == True)
                result = await session.execute(stmt)
                for alarm in result.scalars().all():
                    if alarm.device_id not in self._prev:
                        self._prev[alarm.device_id] = {}
                    for flag, (code, _, _) in ALARM_FLAG_MAP.items():
                        if code == alarm.alarm_code:
                            self._prev[alarm.device_id][flag] = True
        except Exception as exc:
            logger.warning("AlarmDetector failed to load active alarms: %s", exc)

    async def _subscribe(self) -> None:
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
                    await self._process(payload)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("AlarmDetector subscribe error: %s", exc)
                await asyncio.sleep(2)
            finally:
                try:
                    await pubsub.unsubscribe("metrics:updates")
                    await pubsub.close()
                except Exception:
                    pass

    async def _process(self, payload: dict) -> None:
        device_id = payload.get("device_id")
        if device_id is None:
            return

        prev = self._prev.get(device_id, {})
        current: dict[str, bool] = {}
        for flag in ALARM_FLAG_MAP:
            val = payload.get(flag)
            if val is not None:
                current[flag] = bool(val)

        if not current:
            return

        transitions: list[tuple[str, bool]] = []
        for flag, active_now in current.items():
            was_active = prev.get(flag, False)
            if active_now and not was_active:
                transitions.append((flag, True))
            elif not active_now and was_active:
                transitions.append((flag, False))

        if transitions:
            try:
                async with self.session_factory() as session:
                    for flag, appeared in transitions:
                        code, severity, message = ALARM_FLAG_MAP[flag]
                        if appeared:
                            alarm = AlarmEvent(
                                device_id=device_id,
                                alarm_code=code,
                                severity=severity,
                                message=message,
                                is_active=True,
                            )
                            session.add(alarm)
                            logger.info("ALARM ON: device=%d code=%s", device_id, code)
                        else:
                            stmt = select(AlarmEvent).where(
                                and_(
                                    AlarmEvent.device_id == device_id,
                                    AlarmEvent.alarm_code == code,
                                    AlarmEvent.is_active == True,
                                )
                            )
                            result = await session.execute(stmt)
                            active_alarm = result.scalar_one_or_none()
                            if active_alarm:
                                active_alarm.cleared_at = datetime.utcnow()
                                active_alarm.is_active = False
                                logger.info("ALARM OFF: device=%d code=%s", device_id, code)
                    await session.commit()
            except Exception as exc:
                logger.error("AlarmDetector DB error: %s", exc)

        self._prev[device_id] = current
