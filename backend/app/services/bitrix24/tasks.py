"""TaskCreator — creates and tracks Bitrix24 tasks.

Creates tasks for maintenance alerts (critical/overdue) and alarm events
(SHUTDOWN/TRIP_STOP). Uses dynamic roles from EquipmentSync cache.
Protects against duplicates via local bitrix24_tasks table.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from models.bitrix24_task import Bitrix24Task
from models.device import Device
from models.maintenance import MaintenanceTask
from services.bitrix24.client import Bitrix24Client, Bitrix24Error
from services.bitrix24.config import (
    TASK_TITLE_MAINTENANCE, TASK_TITLE_ALARM,
    B24_CLOSED_STATUSES,
)

logger = logging.getLogger("scada.bitrix24.tasks")


class TaskCreator:

    def __init__(
        self,
        client: Bitrix24Client,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        equipment_sync,  # EquipmentSync instance (avoid circular import)
    ):
        self.client = client
        self.redis = redis
        self.session_factory = session_factory
        self.equipment_sync = equipment_sync

    # ─── Maintenance Task ─────────────────────────────────────────────

    async def create_maintenance_task(self, alert_data: dict) -> int | None:
        """Create Bitrix24 task from maintenance alert event."""
        device_id = alert_data.get("device_id")
        alert_id = alert_data.get("id")
        interval_name = alert_data.get("interval_name", "ТО")
        severity = alert_data.get("severity", "")
        engine_hours = alert_data.get("engine_hours", 0)
        hours_remaining = alert_data.get("hours_remaining", 0)

        if not device_id:
            return None

        # 1. Get device → system_code
        device, system_code = await self._get_device_info(device_id)
        if not device:
            logger.warning("B24 TaskCreator: device %d not found", device_id)
            return None

        # 2. Get roles from cache
        equipment = await self.equipment_sync.get_roles(system_code) if system_code else None

        # 3. Check duplicates
        if await self._has_open_task("maintenance", device_id, source_id=alert_id):
            logger.debug("B24 skip duplicate: maintenance alert=%d device=%d", alert_id or 0, device_id)
            return None

        # 4. Build task
        device_name = equipment.get("name", device.name) if equipment else device.name
        model = equipment.get("model", "") if equipment else ""
        responsible_id = (
            equipment.get("responsible_id") if equipment
            else settings.BITRIX24_FALLBACK_RESPONSIBLE_ID
        )
        accomplice_ids = equipment.get("accomplice_ids", []) if equipment else []
        auditor_ids = equipment.get("auditor_ids", []) if equipment else []

        title = TASK_TITLE_MAINTENANCE.format(
            interval_name=interval_name,
            device_name=device_name,
            model=model,
        )

        description = (
            f"Требуется {interval_name}\n\n"
            f"Устройство: {device_name}\n"
            f"Модель: {model}\n"
            f"Наработка: {engine_hours:.1f} м/ч\n"
            f"Осталось до ТО: {hours_remaining:.1f} м/ч\n"
            f"Уровень: {severity}\n"
            f"\nСоздано автоматически системой SCADA"
        )

        priority = 2 if severity == "overdue" else 1
        deadline = datetime.utcnow() + timedelta(days=3 if severity == "overdue" else 7)

        try:
            task_result = await self.client.create_task({
                "TITLE": title,
                "DESCRIPTION": description,
                "RESPONSIBLE_ID": responsible_id or settings.BITRIX24_FALLBACK_RESPONSIBLE_ID,
                "ACCOMPLICES": accomplice_ids,
                "AUDITORS": auditor_ids,
                "CREATED_BY": settings.BITRIX24_FALLBACK_RESPONSIBLE_ID,
                "GROUP_ID": settings.BITRIX24_GROUP_ID,
                "PRIORITY": priority,
                "DEADLINE": deadline.strftime("%Y-%m-%dT17:00:00"),
                "TAGS": ["ТО", interval_name.lower().replace("-", "_")],
                "ALLOW_CHANGE_DEADLINE": "Y",
            })
        except Bitrix24Error as exc:
            logger.error("B24 create maintenance task failed: %s", exc)
            return None

        bitrix_task_id = self._extract_task_id(task_result)
        if not bitrix_task_id:
            logger.error("B24 no task_id in response: %s", task_result)
            return None

        logger.info(
            "B24 maintenance task created: #%d '%s' → user %s",
            bitrix_task_id, title, responsible_id,
        )

        # 5. Add checklist
        await self._add_maintenance_checklist(bitrix_task_id, alert_data)

        # 6. Save local record
        await self._save_record(
            bitrix_task_id=bitrix_task_id,
            source_type="maintenance",
            source_id=alert_id or 0,
            device_id=device_id,
            system_code=system_code,
            task_title=title,
            responsible_id=responsible_id,
            responsible_name=equipment.get("responsible_name") if equipment else None,
            priority=priority,
        )

        return bitrix_task_id

    # ─── Alarm Task ───────────────────────────────────────────────────

    async def create_alarm_task(self, alarm_data: dict) -> int | None:
        """Create urgent Bitrix24 task from alarm event."""
        device_id = alarm_data.get("device_id")
        alarm_code = alarm_data.get("alarm_code", "")
        alarm_message = alarm_data.get("message", alarm_code)
        alarm_id = alarm_data.get("id")

        if not device_id:
            return None

        # 1. Get device info
        device, system_code = await self._get_device_info(device_id)
        if not device:
            return None

        # 2. Get roles
        equipment = await self.equipment_sync.get_roles(system_code) if system_code else None

        # 3. Check duplicates (no open alarm task for this device+code in 24h)
        if await self._has_open_alarm_task(device_id, alarm_code):
            logger.debug("B24 skip duplicate: alarm %s device=%d", alarm_code, device_id)
            return None

        # 4. Build task
        device_name = equipment.get("name", device.name) if equipment else device.name
        responsible_id = (
            equipment.get("responsible_id") if equipment
            else settings.BITRIX24_FALLBACK_RESPONSIBLE_ID
        )
        accomplice_ids = equipment.get("accomplice_ids", []) if equipment else []
        auditor_ids = equipment.get("auditor_ids", []) if equipment else []

        title = TASK_TITLE_ALARM.format(
            alarm_code=alarm_code,
            device_name=device_name,
        )

        description = (
            f"АВАРИЯ на устройстве!\n\n"
            f"Код: {alarm_code}\n"
            f"Сообщение: {alarm_message}\n"
            f"Устройство: {device_name}\n"
            f"\nТребуется немедленное вмешательство.\n"
            f"Создано автоматически системой SCADA"
        )

        deadline = datetime.utcnow() + timedelta(days=1)

        try:
            task_result = await self.client.create_task({
                "TITLE": title,
                "DESCRIPTION": description,
                "RESPONSIBLE_ID": responsible_id or settings.BITRIX24_FALLBACK_RESPONSIBLE_ID,
                "ACCOMPLICES": accomplice_ids,
                "AUDITORS": auditor_ids,
                "CREATED_BY": settings.BITRIX24_FALLBACK_RESPONSIBLE_ID,
                "GROUP_ID": settings.BITRIX24_GROUP_ID,
                "PRIORITY": 2,  # HIGH
                "DEADLINE": deadline.strftime("%Y-%m-%dT17:00:00"),
                "TAGS": ["АВАРИЯ", alarm_code],
                "ALLOW_CHANGE_DEADLINE": "Y",
            })
        except Bitrix24Error as exc:
            logger.error("B24 create alarm task failed: %s", exc)
            return None

        bitrix_task_id = self._extract_task_id(task_result)
        if not bitrix_task_id:
            return None

        logger.info(
            "B24 alarm task created: #%d '%s' → user %s",
            bitrix_task_id, title, responsible_id,
        )

        await self._save_record(
            bitrix_task_id=bitrix_task_id,
            source_type="alarm",
            source_id=alarm_id or 0,
            device_id=device_id,
            system_code=system_code,
            task_title=title,
            responsible_id=responsible_id,
            responsible_name=equipment.get("responsible_name") if equipment else None,
            priority=2,
        )

        return bitrix_task_id

    # ─── Task Status Sync ─────────────────────────────────────────────

    async def sync_status_loop(self) -> None:
        """Periodically check if tasks are closed in Bitrix24."""
        while True:
            await asyncio.sleep(settings.BITRIX24_TASK_CHECK_INTERVAL)
            try:
                await self._sync_task_statuses()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("B24 task status sync error: %s", exc)

    async def _sync_task_statuses(self) -> None:
        """Check open local tasks against Bitrix24."""
        async with self.session_factory() as session:
            stmt = select(Bitrix24Task).where(Bitrix24Task.status != "closed").limit(100)
            result = await session.execute(stmt)
            tasks = result.scalars().all()

            if not tasks:
                return

            closed_count = 0
            for task in tasks:
                try:
                    b24_task = await self.client.get_task(task.bitrix_task_id)
                    if b24_task:
                        status = str(b24_task.get("status", ""))
                        if status in B24_CLOSED_STATUSES:
                            task.status = "closed"
                            task.closed_at = datetime.utcnow()
                            closed_count += 1
                except Exception as exc:
                    logger.debug("B24 status check error for task #%d: %s", task.bitrix_task_id, exc)

            if closed_count:
                await session.commit()
                logger.info("B24 status sync: closed %d tasks", closed_count)

    # ─── Helpers ──────────────────────────────────────────────────────

    async def _get_device_info(self, device_id: int) -> tuple:
        """Get Device and its system_code from DB."""
        try:
            async with self.session_factory() as session:
                device = await session.get(Device, device_id)
                if device:
                    return device, device.system_code
        except Exception as exc:
            logger.error("B24 get device %d error: %s", device_id, exc)
        return None, None

    async def _has_open_task(self, source_type: str, device_id: int, source_id: int | None = None) -> bool:
        """Check if there is already an open task for this source."""
        try:
            async with self.session_factory() as session:
                stmt = select(Bitrix24Task).where(
                    and_(
                        Bitrix24Task.source_type == source_type,
                        Bitrix24Task.device_id == device_id,
                        Bitrix24Task.status != "closed",
                    )
                )
                if source_id:
                    stmt = stmt.where(Bitrix24Task.source_id == source_id)
                result = await session.execute(stmt)
                return result.scalar_one_or_none() is not None
        except Exception:
            return False

    async def _has_open_alarm_task(self, device_id: int, alarm_code: str) -> bool:
        """Check if there is an open alarm task for this device+code in last 24h."""
        try:
            async with self.session_factory() as session:
                cutoff = datetime.utcnow() - timedelta(hours=24)
                stmt = select(Bitrix24Task).where(
                    and_(
                        Bitrix24Task.source_type == "alarm",
                        Bitrix24Task.device_id == device_id,
                        Bitrix24Task.status != "closed",
                        Bitrix24Task.created_at >= cutoff,
                    )
                )
                result = await session.execute(stmt)
                existing = result.scalars().all()
                for task in existing:
                    if alarm_code in (task.task_title or ""):
                        return True
        except Exception:
            return False
        return False

    async def _add_maintenance_checklist(self, task_id: int, alert_data: dict) -> None:
        """Add checklist items from maintenance_tasks to Bitrix24 task."""
        interval_id = alert_data.get("interval_id")
        if not interval_id:
            return

        try:
            async with self.session_factory() as session:
                stmt = (
                    select(MaintenanceTask)
                    .where(MaintenanceTask.interval_id == interval_id)
                    .order_by(MaintenanceTask.sort_order)
                )
                result = await session.execute(stmt)
                tasks = result.scalars().all()

                for mt in tasks:
                    try:
                        await self.client.add_checklist_item(
                            task_id, mt.text,
                        )
                    except Exception as exc:
                        logger.debug("B24 checklist item error: %s", exc)
                        break  # Rate limit or other issue

                if tasks:
                    logger.info("B24 added %d checklist items to task #%d", len(tasks), task_id)
        except Exception as exc:
            logger.error("B24 checklist query error: %s", exc)

    async def _save_record(self, **kwargs) -> None:
        """Save local tracking record."""
        try:
            async with self.session_factory() as session:
                record = Bitrix24Task(**kwargs)
                session.add(record)
                await session.commit()
        except Exception as exc:
            logger.error("B24 save record error: %s", exc)

    @staticmethod
    def _extract_task_id(result: dict) -> int | None:
        """Extract task ID from Bitrix24 response."""
        task = result.get("task", {})
        if isinstance(task, dict):
            tid = task.get("id")
        else:
            tid = task
        try:
            return int(tid) if tid else None
        except (ValueError, TypeError):
            return None
