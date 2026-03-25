"""Background supervisor — escalation and incident report oversight."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_

from config import settings
from models.base import async_session
from models.task_manager import (
    EscalationLog,
    ScadaTask,
    TaskCommunication,
)
from services.task_manager.resilient_api import log_decision, resilient_b24_call

logger = logging.getLogger("scada.task_manager")


# ───────────────────────────────────────────────────────────
# Escalation level definitions
# ───────────────────────────────────────────────────────────
ESCALATION_LEVELS = {
    1: {"name": "soft_reminder", "target": "executor", "channel": "b24_task_comment"},
    2: {"name": "hard_reminder", "target": "executor", "channel": "b24_chat"},
    3: {"name": "manager_escalation", "target": "manager", "channel": "b24_chat"},
    4: {"name": "founder_escalation", "target": "founder", "channel": "b24_chat"},
}


class TaskSupervisor:
    """Periodically reviews open tasks: escalates overdue items
    and monitors incident report completeness."""

    def __init__(self, redis):
        self._redis = redis
        self._running = False

    # ───────────────────────────────────────────────────────
    # lifecycle
    # ───────────────────────────────────────────────────────
    async def start(self) -> None:
        self._running = True
        logger.info(
            "TaskSupervisor started (interval=%ds)",
            settings.TM_SUPERVISOR_INTERVAL,
        )
        while self._running:
            try:
                await self._supervision_cycle()
            except Exception:
                logger.exception("TaskSupervisor cycle error")
            try:
                await asyncio.sleep(settings.TM_SUPERVISOR_INTERVAL)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        self._running = False
        logger.info("TaskSupervisor stop requested")

    # ───────────────────────────────────────────────────────
    # supervision cycle
    # ───────────────────────────────────────────────────────
    async def _supervision_cycle(self) -> None:
        now = datetime.utcnow()
        cutoff_48h = now - timedelta(hours=48)

        async with async_session() as session:
            # 1. Load all open tasks
            stmt = (
                select(ScadaTask)
                .where(ScadaTask.status.notin_(["completed", "closed"]))
                .order_by(ScadaTask.priority.desc(), ScadaTask.deadline)
            )
            result = await session.execute(stmt)
            tasks = result.scalars().all()

            if not tasks:
                return

            # 2. Batch load recent communications (48h window)
            task_ids = [t.id for t in tasks]
            comm_stmt = select(TaskCommunication).where(
                and_(
                    TaskCommunication.task_id.in_(task_ids),
                    TaskCommunication.created_at >= cutoff_48h,
                )
            )
            comm_result = await session.execute(comm_stmt)
            all_comms = comm_result.scalars().all()

            # 3. Group responses by task_id
            responses_by_task: dict[int, list[TaskCommunication]] = {}
            for comm in all_comms:
                responses_by_task.setdefault(comm.task_id, []).append(comm)

            # 4. Check each task
            for task in tasks:
                cached = responses_by_task.get(task.id, [])
                await self._check_task(session, task, cached, now)

            # 5. Single commit at end
            await session.commit()

    # ───────────────────────────────────────────────────────
    # check individual task
    # ───────────────────────────────────────────────────────
    async def _check_task(
        self,
        session,
        task: ScadaTask,
        cached_responses: list[TaskCommunication],
        now: datetime,
    ) -> None:
        if not task.deadline:
            return  # no deadline → no escalation

        time_to_deadline = (task.deadline - now).total_seconds() / 3600  # hours
        time_overdue = -time_to_deadline if time_to_deadline < 0 else 0  # hours

        # Cooldown: only blocks SAME level re-escalation, not progression to NEXT level
        cooldown_hours = settings.TM_ESCALATION_COOLDOWN_HOURS
        in_cooldown = False
        if task.last_escalation_at:
            hours_since_escalation = (
                now - task.last_escalation_at
            ).total_seconds() / 3600
            if hours_since_escalation < cooldown_hours:
                in_cooldown = True

        # Has executor responded?
        has_response = any(
            c.direction == "inbound" for c in cached_responses
        )
        # Has manager responded? (check recipient_role)
        has_manager_response = any(
            c.direction == "inbound" and c.recipient_role == "manager"
            for c in cached_responses
        )

        current_level = task.escalation_level or 0

        # Sequential escalation logic — cooldown only blocks same-level repeat
        if time_overdue > 24 and not has_manager_response and current_level < 4:
            await self._escalate(session, task, 4, "overdue_24h_no_manager_response", now)
        elif time_overdue > settings.ESCALATION_HARD_HOURS and not has_response and current_level < 3:
            await self._escalate(session, task, 3, "overdue_no_response", now)
        elif time_overdue > 0 and current_level < 2:
            if not in_cooldown:
                await self._escalate(session, task, 2, f"overdue_{time_overdue:.0f}h", now)
        elif 0 < time_to_deadline <= settings.ESCALATION_SOFT_REMINDER_HOURS and current_level < 1:
            if not in_cooldown:
                await self._escalate(session, task, 1, "approaching_deadline", now)

    # ───────────────────────────────────────────────────────
    # escalate
    # ───────────────────────────────────────────────────────
    async def _escalate(
        self,
        session,
        task: ScadaTask,
        level: int,
        reason: str,
        now: datetime,
    ) -> None:
        level_info = ESCALATION_LEVELS.get(level)
        if not level_info:
            return

        # 1. Determine target user
        target_user_id, target_name, target_role = await self._resolve_target(
            task, level_info["target"]
        )

        # 2. Format message
        deadline_str = task.deadline.strftime("%d.%m.%Y %H:%M")
        if level <= 2:
            message = (
                f"⚠️ Задача \"{task.title}\" (#{task.id})\n"
                f"Дедлайн: {deadline_str}\n"
                f"Ответственный: {task.responsible_name}\n"
                f"Статус: {task.status} | Причина: {reason}"
            )
        else:
            message = (
                f"🔴 Эскалация L{level}: \"{task.title}\" (#{task.id})\n"
                f"Дедлайн: {deadline_str}\n"
                f"Ответственный: {task.responsible_name}\n"
                f"Уровень: {level_info['name']} | Причина: {reason}\n"
                f"Требуется вмешательство."
            )

        # 3. Send via resilient_b24_call
        channel = level_info["channel"]
        if channel == "b24_chat":
            await resilient_b24_call(
                "imbot.message.add",
                {
                    "DIALOG_ID": str(target_user_id),
                    "MESSAGE": message,
                    "BOT_ID": settings.BITRIX24_BOT_ID,
                },
                self._redis,
                priority=level,
            )
        elif channel == "b24_task_comment" and task.bitrix_task_id:
            await resilient_b24_call(
                "task.commentitem.add",
                {
                    "TASKID": task.bitrix_task_id,
                    "FIELDS": {"POST_MESSAGE": message},
                },
                self._redis,
                priority=level,
            )

        # 4. Update task escalation state (no commit — caller commits)
        task.escalation_level = level
        task.last_escalation_at = now

        # 5. Insert EscalationLog
        esc_log = EscalationLog(
            task_id=task.id,
            level=level,
            level_name=level_info["name"],
            target_user_id=target_user_id,
            target_name=target_name,
            target_role=target_role,
            reason=reason,
            channel=channel,
            message_text=message,
        )
        session.add(esc_log)

        # 5b. Record in task_communications for audit trail
        comm = TaskCommunication(
            task_id=task.id,
            channel=channel,
            direction="outbound",
            sender="system",
            recipient_user_id=target_user_id,
            recipient_name=target_name,
            recipient_role=target_role,
            message_type="escalation",
            message_text=message,
        )
        session.add(comm)

        # 6. Log decision (no commit)
        await log_decision(
            task_id=task.id,
            decision_type="escalation",
            decision_data={
                "level": level,
                "level_name": level_info["name"],
                "target_user_id": target_user_id,
                "reason": reason,
            },
            reasoning=f"Escalated task #{task.id} to L{level} ({reason})",
            triggered_by="task_supervisor",
        )

        logger.info(
            "Escalated task #%d → L%d (%s) → user %s (%s)",
            task.id,
            level,
            reason,
            target_user_id,
            target_name,
        )

    # ───────────────────────────────────────────────────────
    # resolve escalation target
    # ───────────────────────────────────────────────────────
    async def _resolve_target(
        self,
        task: ScadaTask,
        target_type: str,
    ) -> tuple[int, str, str]:
        """Resolve target user for escalation from company:employees cache.

        Returns (user_id, name, role).
        """
        if target_type == "executor":
            return task.responsible_user_id, task.responsible_name or "executor", "executor"

        # Load company employees from Redis cache
        try:
            raw = await self._redis.get("company:employees")
            if raw:
                employees = json.loads(
                    raw.decode() if isinstance(raw, bytes) else raw
                )
            else:
                employees = []
        except Exception:
            logger.debug("Could not load company:employees from Redis")
            employees = []

        if target_type == "manager":
            # Find manager of the executor in hierarchy
            manager = self._find_manager(employees, task.responsible_user_id)
            if manager:
                return manager["id"], manager.get("name", "manager"), "manager"
            # Fallback: settings
            return settings.BITRIX24_FALLBACK_RESPONSIBLE_ID, "manager", "manager"

        if target_type == "founder":
            # Find user with highest weight (>= 0.9)
            founder = self._find_founder(employees)
            if founder:
                return founder["id"], founder.get("name", "founder"), "founder"
            return settings.BITRIX24_FALLBACK_RESPONSIBLE_ID, "founder", "founder"

        return task.responsible_user_id, task.responsible_name or "unknown", target_type

    @staticmethod
    def _find_manager(
        employees: list[dict], user_id: int
    ) -> dict | None:
        """Look up the direct manager from the employees list."""
        for emp in employees:
            if emp.get("id") == user_id:
                manager_id = emp.get("manager_id")
                if manager_id:
                    for m in employees:
                        if m.get("id") == manager_id:
                            return m
        return None

    @staticmethod
    def _find_founder(employees: list[dict]) -> dict | None:
        """Find user with user_weight >= 0.9 (founder/top management)."""
        best = None
        best_weight = 0.0
        for emp in employees:
            w = emp.get("user_weight", 0)
            if isinstance(w, (int, float)) and w >= 0.9 and w > best_weight:
                best = emp
                best_weight = w
        return best
