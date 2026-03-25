"""Incident Auto-Poller — automatically asks executor about alarm incidents.

Flow:
1. Subscribes to Redis `alarms:new` channel
2. On critical alarm → find equipment_responsible → send B24 bot message "Что случилось?"
3. Track response in task_communications
4. If no response within INCIDENT_POLL_TIMEOUT → escalate to manager
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_, func

from config import settings
from models.base import async_session
from models.task_manager import (
    IncidentReport,
    ScadaTask,
    TaskCommunication,
    EscalationLog,
)
from services.task_manager.resilient_api import log_decision, resilient_b24_call

logger = logging.getLogger("scada.incident_poller")

# ── Config defaults ──────────────────────────────────────────────
INCIDENT_POLL_INTERVAL = getattr(settings, "INCIDENT_POLL_INTERVAL", 300)  # 5 min
INCIDENT_RESPONSE_TIMEOUT = getattr(settings, "INCIDENT_RESPONSE_TIMEOUT", 1800)  # 30 min
INCIDENT_SEVERITY_THRESHOLD = ("SHUTDOWN", "TRIP_STOP", "BLOCK", "COMMON")  # alarm types that trigger polling


class IncidentAutoPoller:
    """Background service: monitors alarms, auto-asks executors, escalates on silence."""

    def __init__(self, redis, task_engine=None):
        self._redis = redis
        self._task_engine = task_engine
        self._running = False
        # Pending stored in Redis (survives restarts): incident:pending:{task_id} → JSON

    async def start(self) -> None:
        self._running = True
        logger.info("IncidentAutoPoller started (poll=%ds, timeout=%ds)",
                     INCIDENT_POLL_INTERVAL, INCIDENT_RESPONSE_TIMEOUT)
        asyncio.create_task(self._subscribe_alarms())
        while self._running:
            try:
                await self._check_pending_responses()
            except Exception:
                logger.exception("IncidentAutoPoller cycle error")
            await asyncio.sleep(INCIDENT_POLL_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        logger.info("IncidentAutoPoller stopped")

    # ── Subscribe to alarm events ──────────────────────────────
    async def _subscribe_alarms(self) -> None:
        """Listen for new alarms via Redis PubSub and auto-create incident tasks."""
        try:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe("alarms:new")
            logger.info("IncidentAutoPoller subscribed to alarms:new")

            async for msg in pubsub.listen():
                if not self._running:
                    break
                if msg["type"] != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                    await self._handle_alarm(data)
                except Exception:
                    logger.exception("Error handling alarm event")
        except Exception:
            logger.exception("IncidentAutoPoller subscription error")

    async def _handle_alarm(self, alarm: dict) -> None:
        """Process a new alarm — create task + ask executor."""
        alarm_type = alarm.get("alarm_type", "")
        severity = alarm.get("severity", "")

        # Only handle critical alarms
        if alarm_type not in INCIDENT_SEVERITY_THRESHOLD and severity != "error":
            return

        device_id = alarm.get("device_id")
        device_name = alarm.get("device_name", "")
        alarm_name = alarm.get("alarm_name", alarm.get("code", "Unknown"))
        alarm_desc = alarm.get("description", "")
        equipment_code = alarm.get("equipment_code", device_name)
        site_id = alarm.get("site_id")

        # Check deduplication
        if self._task_engine:
            is_dup = await self._task_engine.check_duplicate(
                equipment_code=equipment_code,
                task_type="incident",
                alarm_name=alarm_name,
            )
            if is_dup:
                logger.debug("Duplicate incident for %s/%s, skipping", equipment_code, alarm_name)
                return

        # Create incident task
        if not self._task_engine:
            logger.warning("No task_engine configured, cannot create incident task")
            return
        task = await self._task_engine.create_task(
            task_type="incident",
            trigger_source="alarm_detector",
            title=f"Авария: {alarm_name} — {device_name}",
            priority=3,  # critical
            equipment_code=equipment_code,
            site_id=site_id,
            alarm_name=alarm_name,
            description=f"Автоматически создано по аларму: {alarm_desc}",
            creator="incident_poller",
        )
        if not task:
            logger.warning("Failed to create incident task for %s", alarm_name)
            return

        logger.info("Incident task #%d created for alarm %s on %s", task.id, alarm_name, device_name)

        # Ask executor
        executor_id = task.responsible_user_id
        if executor_id:
            await self._ask_executor(task, executor_id, alarm_name, device_name)

    async def _ask_executor(self, task: ScadaTask, executor_id: int,
                            alarm_name: str, device_name: str) -> None:
        """Send B24 bot message to executor asking what happened."""
        message = (
            f"⚠️ [b]Авария: {alarm_name}[/b]\n"
            f"Оборудование: {device_name}\n"
            f"Задача: #{task.id}\n\n"
            f"Что случилось? Опишите ситуацию."
        )

        result = await resilient_b24_call(
            "imbot.message.add",
            {
                "BOT_ID": getattr(settings, "BITRIX24_BOT_ID", 228),
                "DIALOG_ID": str(executor_id),
                "MESSAGE": message,
                "KEYBOARD": [
                    {"TEXT": "Уже на месте", "COMMAND": "incident_response", "COMMAND_PARAMS": f"task={task.id}&status=onsite",
                     "BG_COLOR": "#29619b", "TEXT_COLOR": "#fff", "BLOCK": "Y"},
                    {"TEXT": "Нужна помощь", "COMMAND": "incident_response", "COMMAND_PARAMS": f"task={task.id}&status=need_help",
                     "BG_COLOR": "#ff4060", "TEXT_COLOR": "#fff", "BLOCK": "Y"},
                ],
            },
            self._redis,
            priority=2,
        )

        # Log communication
        async with async_session() as session:
            comm = TaskCommunication(
                task_id=task.id,
                channel="b24_chat",
                direction="outbound",
                sender="sanek_bot",
                recipient_user_id=executor_id,
                recipient_name=task.responsible_name or "",
                recipient_role="executor",
                message_type="incident_inquiry",
                message_text=message,
            )
            session.add(comm)
            await session.commit()

        # Track pending in Redis (survives restarts, TTL = 2x timeout)
        pending_data = json.dumps({
            "asked_at": datetime.utcnow().isoformat(),
            "executor_id": executor_id,
            "executor_name": task.responsible_name or "",
            "alarm_name": alarm_name,
        })
        await self._redis.set(
            f"incident:pending:{task.id}", pending_data,
            ex=INCIDENT_RESPONSE_TIMEOUT * 2,
        )

        await log_decision(
            task_id=task.id,
            decision_type="incident_inquiry_sent",
            decision_data={"executor_id": executor_id, "alarm_name": alarm_name},
            reasoning="Auto-sent incident inquiry to executor after alarm detection",
            triggered_by="incident_poller",
        )

        logger.info("Incident inquiry sent to user %d for task #%d", executor_id, task.id)

    # ── Check for pending responses ──────────────────────────
    async def _check_pending_responses(self) -> None:
        """Check if executors responded to incident inquiries (from Redis)."""
        now = datetime.utcnow()

        # Scan Redis for pending incidents
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match="incident:pending:*", count=50)
            for key in keys:
                try:
                    raw = await self._redis.get(key)
                    if not raw:
                        continue
                    info = json.loads(raw)
                    task_id = int(key.decode().split(":")[-1]) if isinstance(key, bytes) else int(str(key).split(":")[-1])
                    asked_at = datetime.fromisoformat(info["asked_at"])
                    elapsed = (now - asked_at).total_seconds()

                    async with async_session() as session:
                        response = (await session.execute(
                            select(TaskCommunication).where(
                                and_(
                                    TaskCommunication.task_id == task_id,
                                    TaskCommunication.direction == "inbound",
                                    TaskCommunication.created_at > asked_at.replace(tzinfo=None),
                                )
                            ).limit(1)
                        )).scalar_one_or_none()

                        if response:
                            logger.info("Response received for task #%d from executor", task_id)
                            await self._redis.delete(key)
                            continue

                        if elapsed > INCIDENT_RESPONSE_TIMEOUT:
                            logger.warning("No response for task #%d after %d sec, escalating",
                                           task_id, int(elapsed))
                            await self._escalate_no_response(session, task_id, info)
                            await self._redis.delete(key)

                except Exception:
                    logger.exception("Error checking pending incident %s", key)

            if cursor == 0:
                break

    async def _escalate_no_response(self, session, task_id: int, info: dict) -> None:
        """Escalate when executor doesn't respond."""
        task = await session.get(ScadaTask, task_id)
        if not task:
            return

        # Find manager
        try:
            employees_raw = await self._redis.get("b24:company:employees")
            employees = json.loads(employees_raw) if employees_raw else []
        except Exception:
            employees = []

        manager = None
        for emp in employees:
            if emp.get("is_head") and emp.get("department_id") == _get_dept_for_user(employees, info["executor_id"]):
                manager = emp
                break

        target_name = "Руководитель"
        target_id = None
        if manager:
            target_id = manager.get("id") or manager.get("bitrix_id")
            target_name = manager.get("name", "Руководитель")

        # Send escalation message
        message = (
            f"🔴 [b]Исполнитель не ответил на инцидент![/b]\n"
            f"Задача: #{task_id} — {task.title}\n"
            f"Исполнитель: {info.get('executor_name', '?')} — не ответил {int((datetime.utcnow() - info['asked_at']).total_seconds() / 60)} мин.\n"
            f"Алярм: {info.get('alarm_name', '?')}\n\n"
            f"Требуется вмешательство."
        )

        if target_id:
            await resilient_b24_call(
                "imbot.message.add",
                {
                    "BOT_ID": getattr(settings, "BITRIX24_BOT_ID", 228),
                    "DIALOG_ID": str(target_id),
                    "MESSAGE": message,
                },
                self._redis,
                priority=3,
            )

        # Log escalation
        esc = EscalationLog(
            task_id=task_id,
            level=3,
            level_name="manager_escalation",
            target_user_id=target_id,
            target_name=target_name,
            target_role="manager",
            reason="Executor did not respond to incident inquiry",
            channel="b24_chat",
            message_text=message,
        )
        session.add(esc)

        # Update task
        task.escalation_level = max(task.escalation_level or 0, 3)
        task.last_escalation_at = datetime.utcnow()

        await session.commit()

        await log_decision(
            task_id=task_id,
            decision_type="incident_escalation",
            decision_data={"target_id": target_id, "target_name": target_name, "reason": "no_response"},
            reasoning=f"Executor {info.get('executor_name')} did not respond within {INCIDENT_RESPONSE_TIMEOUT}s",
            triggered_by="incident_poller",
        )

        logger.info("Escalated task #%d to manager %s (no executor response)", task_id, target_name)


def _get_dept_for_user(employees: list, user_id: int) -> int | None:
    """Find department_id for a user."""
    for emp in employees:
        uid = emp.get("id") or emp.get("bitrix_id")
        if uid and int(uid) == int(user_id):
            return emp.get("department_id")
    return None
