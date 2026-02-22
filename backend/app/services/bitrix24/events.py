"""EventListener — subscribes to Redis channels and dispatches to TaskCreator.

The ONLY connection point between existing SCADA services and Bitrix24 module.
If this listener is not running, events simply vanish (and that's OK).
"""
import asyncio
import json
import logging

from redis.asyncio import Redis

from services.bitrix24.config import (
    REDIS_CHANNEL_MAINTENANCE, REDIS_CHANNEL_ALARMS, REDIS_CHANNEL_COMMANDS,
    ALARM_CODES_URGENT, MAINTENANCE_SEVERITY_TASK,
)

logger = logging.getLogger("scada.bitrix24.events")


class EventListener:

    def __init__(self, redis: Redis, task_creator, equipment_sync):
        self.redis = redis
        self.task_creator = task_creator
        self.equipment_sync = equipment_sync
        self._running = False

    async def listen(self) -> None:
        """Subscribe to all relevant Redis channels."""
        self._running = True
        logger.info("B24 EventListener started")

        while self._running:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe(
                    REDIS_CHANNEL_MAINTENANCE,
                    REDIS_CHANNEL_ALARMS,
                    REDIS_CHANNEL_COMMANDS,
                )
                async for msg in pubsub.listen():
                    if not self._running:
                        break
                    if msg["type"] != "message":
                        continue

                    channel = msg["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode("utf-8")
                    raw = msg["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")

                    try:
                        payload = json.loads(raw)
                        await self._dispatch(channel, payload)
                    except json.JSONDecodeError:
                        logger.debug("B24 EventListener: invalid JSON: %s", raw[:100])
                    except Exception as exc:
                        logger.error("B24 EventListener dispatch error: %s", exc)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("B24 EventListener subscribe error: %s", exc)
                await asyncio.sleep(2)
            finally:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.close()
                except Exception:
                    pass

    def stop(self) -> None:
        self._running = False

    async def _dispatch(self, channel: str, payload: dict) -> None:
        """Route events to appropriate handlers."""
        if channel == REDIS_CHANNEL_MAINTENANCE:
            await self._handle_maintenance(payload)
        elif channel == REDIS_CHANNEL_ALARMS:
            await self._handle_alarm(payload)
        elif channel == REDIS_CHANNEL_COMMANDS:
            await self._handle_command(payload)

    async def _handle_maintenance(self, payload: dict) -> None:
        """Handle maintenance alert — create task only for critical/overdue."""
        action = payload.get("action", "")
        if action not in ("created", "updated"):
            return

        alert = payload.get("alert", {})
        severity = alert.get("severity", "")
        if severity not in MAINTENANCE_SEVERITY_TASK:
            return

        logger.info(
            "B24 maintenance event: device=%s severity=%s interval=%s",
            alert.get("device_id"), severity, alert.get("interval_name"),
        )
        await self.task_creator.create_maintenance_task(alert)

    async def _handle_alarm(self, payload: dict) -> None:
        """Handle alarm event — create task only for SHUTDOWN/TRIP_STOP."""
        action = payload.get("action", "")
        if action != "created":
            return

        alarm = payload.get("alarm", {})
        alarm_code = alarm.get("alarm_code", "")
        if alarm_code not in ALARM_CODES_URGENT:
            return

        logger.info(
            "B24 alarm event: device=%s code=%s",
            alarm.get("device_id"), alarm_code,
        )
        await self.task_creator.create_alarm_task(alarm)

    async def _handle_command(self, payload: dict) -> None:
        """Handle manual commands from REST API."""
        cmd = payload.get("command", "")

        if cmd == "force_sync":
            logger.info("B24 command: force equipment sync")
            await self.equipment_sync._sync()
        elif cmd == "test_task":
            logger.info("B24 command: test task")
            # Test task is handled via REST API directly
        else:
            logger.debug("B24 unknown command: %s", cmd)
