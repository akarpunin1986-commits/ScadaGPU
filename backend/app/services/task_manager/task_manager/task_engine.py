"""TaskEngine — core task creation, deduplication, B24 sync."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import asyncio
from sqlalchemy import select, and_, func

from config import settings
from models.base import async_session
from models.task_manager import (
    IncidentReport,
    MaintenanceCard,
    MetricsSnapshot,
    ScadaTask,
)
from services.task_manager.resilient_api import log_decision, resilient_b24_call

logger = logging.getLogger("scada.task_manager")


class TaskEngine:
    """Core engine for SCADA task lifecycle: create, deduplicate, sync to B24."""

    def __init__(self, redis):
        self._redis = redis

    # ───────────────────────────────────────────────────────
    # create_task  (TZ §5.3)
    # ───────────────────────────────────────────────────────
    async def create_task(
        self,
        task_type: str,
        trigger_source: str,
        title: str,
        priority: int = 1,
        equipment_code: str | None = None,
        site_id: int | None = None,
        maintenance_card_id: int | None = None,
        alarm_event_id: int | None = None,
        alarm_name: str | None = None,
        description: str | None = None,
        deadline: datetime | None = None,
        creator: str = "sanek",
        responsible_user_id: int | None = None,
        responsible_name: str | None = None,
    ) -> ScadaTask | None:
        """Create a ScadaTask, push to Bitrix24, handle checklists and snapshots."""
        async with async_session() as session:
            # 1. Load maintenance card if provided
            card: MaintenanceCard | None = None
            if maintenance_card_id:
                card = await session.get(MaintenanceCard, maintenance_card_id)

            # 2. Deduplication
            maintenance_type = card.maintenance_type if card else None
            if await self.check_duplicate(
                equipment_code, task_type, maintenance_type, alarm_name
            ):
                logger.info(
                    "Task duplicate skipped: type=%s equipment=%s alarm=%s",
                    task_type,
                    equipment_code,
                    alarm_name,
                )
                return None

            # 3. Resolve responsible
            if not responsible_user_id:
                responsible_user_id = await self._resolve_responsible(
                    equipment_code, card
                )
            if not responsible_name:
                responsible_name = f"user_{responsible_user_id}"

            # 4. Calculate deadline
            if not deadline:
                deadline = self._calculate_deadline(priority)

            # 5. Generate tags
            tags = self._generate_tags(task_type, equipment_code, maintenance_type)

            # 6. Create ScadaTask in DB
            task = ScadaTask(
                task_type=task_type,
                trigger_source=trigger_source,
                equipment_code=equipment_code,
                site_id=site_id,
                maintenance_card_id=maintenance_card_id,
                alarm_event_id=alarm_event_id,
                alarm_name=alarm_name,
                bitrix_group_id=settings.B24_TASK_GROUP_ID,
                responsible_user_id=responsible_user_id,
                responsible_name=responsible_name,
                creator=creator,
                status="created",
                priority=priority,
                deadline=deadline,
                title=title,
                description=description,
                tags=tags,
            )
            session.add(task)
            await session.flush()  # get task.id

            # 7. Create B24 task
            b24_task_params = {
                "fields": {
                    "TITLE": title,
                    "DESCRIPTION": description or "",
                    "RESPONSIBLE_ID": responsible_user_id,
                    "CREATED_BY": settings.B24_SANEK_USER_ID,
                    "GROUP_ID": settings.B24_TASK_GROUP_ID,
                    "PRIORITY": "2" if priority >= 3 else "1",
                    "DEADLINE": deadline.strftime("%Y-%m-%dT%H:%M:%S+03:00"),
                    "TAGS": tags,
                }
            }
            b24_result = await resilient_b24_call(
                "tasks.task.add", b24_task_params, self._redis, priority=priority
            )
            if b24_result and "result" in b24_result:
                b24_task = b24_result["result"].get("task", {})
                task.bitrix_task_id = int(b24_task.get("id", 0)) or None

            # 8. Create B24 checklist if card has checklist items
            if task.bitrix_task_id and card and card.checklist_items:
                await self._create_b24_checklist(
                    task.bitrix_task_id, card.checklist_items
                )

            # 9. Capture "before" metrics snapshot for maintenance tasks
            if task_type == "maintenance" and equipment_code:
                device_ids = self._get_device_ids(equipment_code)
                for device_id in device_ids:
                    await self.capture_metrics_snapshot(
                        task.id, device_id, "before"
                    )

            # 10. Create IncidentReport for incident tasks
            if task_type == "incident":
                incident = IncidentReport(task_id=task.id)
                session.add(incident)

            # 11. Log decision
            await log_decision(
                task_id=task.id,
                decision_type="task_created",
                decision_data={
                    "task_type": task_type,
                    "equipment_code": equipment_code,
                    "priority": priority,
                    "bitrix_task_id": task.bitrix_task_id,
                },
                reasoning=f"Created {task_type} task for {equipment_code or 'N/A'} "
                f"via {trigger_source}",
                triggered_by=trigger_source,
            )

            # 12. Commit and return
            await session.commit()
            await session.refresh(task)
            logger.info(
                "Task #%d created: %s [b24=%s] equipment=%s",
                task.id,
                task_type,
                task.bitrix_task_id,
                equipment_code,
            )
            return task

    # ───────────────────────────────────────────────────────
    # check_duplicate
    # ───────────────────────────────────────────────────────
    async def check_duplicate(
        self,
        equipment_code: str | None,
        task_type: str,
        maintenance_type: str | None = None,
        alarm_name: str | None = None,
    ) -> bool:
        """Return True if an active duplicate task exists within the dedup window."""
        if not equipment_code:
            return False

        cutoff = datetime.utcnow() - timedelta(
            days=settings.TM_DEDUP_WINDOW_DAYS
        )
        async with async_session() as session:
            stmt = select(ScadaTask.id).where(
                and_(
                    ScadaTask.equipment_code == equipment_code,
                    ScadaTask.task_type == task_type,
                    ScadaTask.status.notin_(["completed", "closed"]),
                    ScadaTask.created_at > cutoff,
                )
            )
            if maintenance_type:
                # tags is JSONB array — check containment
                stmt = stmt.where(
                    ScadaTask.tags.contains([maintenance_type])
                )
            if alarm_name and task_type == "incident":
                stmt = stmt.where(ScadaTask.alarm_name == alarm_name)

            result = await session.execute(stmt.limit(1))
            return result.scalar_one_or_none() is not None

    # ───────────────────────────────────────────────────────
    # update_status
    # ───────────────────────────────────────────────────────
    async def update_status(
        self,
        task_id: int,
        new_status: str,
        user_id: int | None = None,
    ) -> ScadaTask | None:
        """Update task status with lifecycle timestamps."""
        async with async_session() as session:
            task = await session.get(ScadaTask, task_id)
            if not task:
                logger.warning("update_status: task #%d not found", task_id)
                return None

            old_status = task.status
            task.status = new_status

            now = datetime.utcnow()
            if new_status == "completed":
                task.completed_at = now
            elif new_status == "closed":
                task.closed_at = now

            await session.commit()
            await session.refresh(task)

            logger.info(
                "Task #%d status: %s → %s (by user=%s)",
                task_id,
                old_status,
                new_status,
                user_id,
            )
            return task

    # ───────────────────────────────────────────────────────
    # get_tasks
    # ───────────────────────────────────────────────────────
    async def get_tasks(
        self,
        status: str | None = None,
        task_type: str | None = None,
        equipment_code: str | None = None,
        limit: int = 50,
    ) -> list[ScadaTask]:
        """Query tasks with optional filters."""
        async with async_session() as session:
            stmt = select(ScadaTask)
            if status:
                stmt = stmt.where(ScadaTask.status == status)
            if task_type:
                stmt = stmt.where(ScadaTask.task_type == task_type)
            if equipment_code:
                stmt = stmt.where(ScadaTask.equipment_code == equipment_code)

            stmt = stmt.order_by(ScadaTask.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ───────────────────────────────────────────────────────
    # capture_metrics_snapshot
    # ───────────────────────────────────────────────────────
    async def capture_metrics_snapshot(
        self,
        task_id: int,
        device_id: int,
        snapshot_type: str,
    ) -> None:
        """Read current metrics from Redis and save as MetricsSnapshot."""
        try:
            raw = await self._redis.hgetall(f"metrics:{device_id}:latest")
            if not raw:
                logger.debug(
                    "No metrics in Redis for device %d, skipping snapshot",
                    device_id,
                )
                return

            # Decode bytes keys/values if needed
            metrics_data = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in raw.items()
            }

            snapshot = MetricsSnapshot(
                task_id=task_id,
                snapshot_type=snapshot_type,
                device_id=device_id,
                metrics_data=metrics_data,
            )
            async with async_session() as session:
                session.add(snapshot)
                await session.commit()

            logger.debug(
                "MetricsSnapshot(%s) captured for task #%d device %d",
                snapshot_type,
                task_id,
                device_id,
            )
        except Exception:
            logger.exception(
                "Failed to capture metrics snapshot for task #%d device %d",
                task_id,
                device_id,
            )

    # ───────────────────────────────────────────────────────
    # private helpers
    # ───────────────────────────────────────────────────────
    def _calculate_deadline(self, priority: int) -> datetime:
        """Map priority to a deadline datetime."""
        now = datetime.utcnow()
        if priority >= 3:
            return now + timedelta(hours=settings.DEADLINE_CRITICAL_HOURS)
        elif priority == 2:
            return now + timedelta(hours=settings.DEADLINE_HIGH_HOURS)
        else:
            return now + timedelta(days=settings.DEADLINE_NORMAL_DAYS)

    def _generate_tags(
        self,
        task_type: str,
        equipment_code: str | None,
        maintenance_type: str | None = None,
    ) -> list[str]:
        """Build a list of tags for the task."""
        tags = [task_type]
        if equipment_code:
            tags.append(equipment_code)
        if maintenance_type:
            tags.append(maintenance_type)
        return tags

    async def _resolve_responsible(
        self,
        equipment_code: str | None,
        card: MaintenanceCard | None,
    ) -> int:
        """Determine the responsible B24 user ID.

        Priority: card.bitrix_responsible_id → equipment registry → fallback.
        """
        if card and card.bitrix_responsible_id:
            return card.bitrix_responsible_id

        # Try equipment registry in Redis
        if equipment_code:
            try:
                responsible = await self._redis.hget(
                    "equipment:responsible", equipment_code
                )
                if responsible:
                    val = responsible.decode() if isinstance(responsible, bytes) else responsible
                    return int(val)
            except Exception:
                logger.debug(
                    "Could not resolve responsible from Redis for %s",
                    equipment_code,
                )

        return settings.BITRIX24_FALLBACK_RESPONSIBLE_ID

    def _get_device_ids(self, equipment_code: str) -> list[int]:
        """Resolve equipment_code to device IDs from settings."""
        try:
            mapping = json.loads(settings.EQUIPMENT_DEVICE_MAP)
            return mapping.get(equipment_code, [])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid EQUIPMENT_DEVICE_MAP config")
            return []

    async def _create_b24_checklist(
        self,
        b24_task_id: int,
        checklist_items: list | dict,
    ) -> None:
        """Create B24 checklist items via batch call."""
        items = checklist_items if isinstance(checklist_items, list) else []
        if not items:
            return

        # Build batch commands
        cmd = {}
        for idx, item in enumerate(items):
            title = item if isinstance(item, str) else item.get("title", str(item))
            encoded_title = quote(str(title))
            cmd[f"item_{idx}"] = (
                f"task.checklistitem.add?"
                f"TASKID={b24_task_id}&FIELDS[TITLE]={encoded_title}"
            )

        result = await resilient_b24_call(
            "batch", {"halt": 0, "cmd": cmd}, self._redis, priority=0
        )
        if result:
            logger.info(
                "Created %d checklist items for B24 task #%d",
                len(items),
                b24_task_id,
            )
        else:
            logger.warning(
                "Checklist batch queued offline for B24 task #%d", b24_task_id
            )
