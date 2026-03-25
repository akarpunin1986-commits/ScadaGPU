"""
Maintenance Alert Service — background service checking for approaching/due/overdue maintenance.

Creates notifications via Bitrix24 bot, tasks via TaskEngine, and escalations.
Uses Redis cooldowns to prevent alert flooding.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import and_, select

from config import settings
from models.base import async_session
from models.equipment_unit import EquipmentUnit
from models.maintenance_lifecycle import CardInterval, EquipmentCardLink
from schemas.maintenance import NextMaintenance

logger = logging.getLogger("scada.maintenance")

# Alert types
ALERT_APPROACHING = "approaching"
ALERT_TASK_DUE = "task_due"
ALERT_OVERDUE = "overdue"


class MaintenanceAlertService:
    """Background service checking equipment for approaching/due/overdue maintenance."""

    def __init__(self, redis):
        self.redis = redis
        self._running = False
        self._task_engine = None

    def _get_task_engine(self):
        """Lazy-load TaskEngine to avoid circular imports."""
        if self._task_engine is None:
            from services.task_manager.task_engine import TaskEngine
            self._task_engine = TaskEngine(self.redis)
        return self._task_engine

    async def check_all(self):
        """Check all active equipment for approaching/due/overdue maintenance."""
        from services.maintenance.lifecycle import determine_all_upcoming

        async with async_session() as session:
            # Get all active equipment with linked cards
            equipment_ids = (await session.execute(
                select(EquipmentCardLink.equipment_id)
                .where(EquipmentCardLink.is_active.is_(True))
                .distinct()
            )).scalars().all()

            if not equipment_ids:
                return

            alerts_sent = 0
            tasks_created = 0

            for eq_id in equipment_ids:
                try:
                    eq = (await session.execute(
                        select(EquipmentUnit).where(EquipmentUnit.id == eq_id)
                    )).scalar_one_or_none()
                    if not eq or not eq.is_active:
                        continue

                    upcoming = await determine_all_upcoming(eq_id, session, limit=10)
                    if not upcoming:
                        continue

                    for maint in upcoming:
                        result = await self._process_alert(eq, maint, session)
                        if result == ALERT_APPROACHING:
                            alerts_sent += 1
                        elif result == ALERT_TASK_DUE:
                            tasks_created += 1
                        elif result == ALERT_OVERDUE:
                            alerts_sent += 1
                            tasks_created += 1

                except Exception as exc:
                    logger.error(
                        "Alert check failed for equipment %d: %s", eq_id, exc,
                        exc_info=True,
                    )

            if alerts_sent > 0 or tasks_created > 0:
                logger.info(
                    "Alert cycle: %d equipment checked, %d alerts sent, %d tasks created",
                    len(equipment_ids), alerts_sent, tasks_created,
                )

    async def _process_alert(
        self,
        eq: EquipmentUnit,
        maint: NextMaintenance,
        session,
    ) -> str | None:
        """Process a single maintenance point. Returns alert type or None."""
        code = maint.interval_code

        # Get per-interval thresholds or fallback to global config
        warn_threshold = await self._get_threshold(
            eq.id, code, "warn", session
        )
        task_threshold = await self._get_threshold(
            eq.id, code, "task", session
        )

        remaining = self._get_remaining(maint)
        if remaining is None:
            return None

        # Check cooldown
        cooldown_key = f"maint:alert:{eq.id}:{code}"
        if await self.redis.exists(cooldown_key):
            return None

        alert_type = None

        if remaining <= 0:
            # OVERDUE
            alert_type = ALERT_OVERDUE
            await self._send_overdue_alert(eq, maint, remaining)
            await self._create_maintenance_task(eq, maint, priority=2)
        elif remaining <= task_threshold:
            # TASK_DUE
            alert_type = ALERT_TASK_DUE
            await self._create_maintenance_task(eq, maint, priority=1)
        elif remaining <= warn_threshold:
            # APPROACHING
            alert_type = ALERT_APPROACHING
            await self._send_approaching_alert(eq, maint, remaining)

        # Set cooldown
        if alert_type:
            cooldown_ttl = settings.MAINT_ALERT_COOLDOWN_HOURS * 3600
            await self.redis.set(cooldown_key, alert_type, ex=cooldown_ttl)
            logger.info(
                "Alert [%s]: eq=%d (%s), interval=%s, remaining=%s",
                alert_type, eq.id, eq.code, code, remaining,
            )

        return alert_type

    def _get_remaining(self, maint: NextMaintenance) -> int | None:
        """Get remaining value (hours or days) from NextMaintenance."""
        if maint.remaining_hours is not None:
            return maint.remaining_hours
        if maint.remaining_days is not None:
            return maint.remaining_days
        return None

    async def _get_threshold(
        self, equipment_id: int, interval_code: str, kind: str, session
    ) -> int:
        """Get threshold for interval. Per-interval first, then global config."""
        # Try per-interval threshold
        links = (await session.execute(
            select(EquipmentCardLink).where(
                and_(
                    EquipmentCardLink.equipment_id == equipment_id,
                    EquipmentCardLink.is_active.is_(True),
                )
            )
        )).scalars().all()

        for link in links:
            interval = (await session.execute(
                select(CardInterval).where(
                    and_(
                        CardInterval.card_id == link.card_id,
                        CardInterval.code == interval_code,
                    )
                )
            )).scalar_one_or_none()

            if interval:
                if kind == "warn" and interval.warn_threshold:
                    return interval.warn_threshold
                if kind == "task" and interval.task_threshold:
                    return interval.task_threshold

                # Use hours vs days config based on interval type
                if interval.interval_type in ("hours", "hours_or_days"):
                    return (
                        settings.MAINT_HOURS_WARN
                        if kind == "warn"
                        else settings.MAINT_HOURS_TASK
                    )
                else:
                    return (
                        settings.MAINT_DAYS_WARN
                        if kind == "warn"
                        else settings.MAINT_DAYS_TASK
                    )

        # Fallback to global hours config
        return settings.MAINT_HOURS_WARN if kind == "warn" else settings.MAINT_HOURS_TASK

    async def _send_approaching_alert(
        self, eq: EquipmentUnit, maint: NextMaintenance, remaining: int
    ):
        """Send approaching maintenance notification via Bitrix24 bot."""
        unit_label = "ч" if maint.remaining_hours is not None else "дн"
        card_label = f" ({maint.card_name})" if maint.card_name else ""
        message = (
            f"[b]Приближается ТО[/b]\n"
            f"Оборудование: {eq.name} ({eq.code})\n"
            f"Интервал: {maint.interval_name}{card_label}\n"
            f"Осталось: {remaining} {unit_label}\n"
        )
        await self._notify_responsible(eq, message)

    async def _send_overdue_alert(
        self, eq: EquipmentUnit, maint: NextMaintenance, remaining: int
    ):
        """Send overdue maintenance alert via Bitrix24 bot."""
        unit_label = "ч" if maint.remaining_hours is not None else "дн"
        card_label = f" ({maint.card_name})" if maint.card_name else ""
        overdue_val = abs(remaining)
        message = (
            f"[b]ПРОСРОЧЕНО ТО![/b]\n"
            f"Оборудование: {eq.name} ({eq.code})\n"
            f"Интервал: {maint.interval_name}{card_label}\n"
            f"Просрочено на: {overdue_val} {unit_label}\n"
        )
        await self._notify_responsible(eq, message)

    async def _notify_responsible(self, eq: EquipmentUnit, message: str):
        """Send message to responsible person via Bitrix24 bot (BOT_ID=228)."""
        if not eq.responsible_bitrix_id:
            logger.debug(
                "No responsible_bitrix_id for equipment %d, skipping bot notification",
                eq.id,
            )
            return

        try:
            from services.bitrix_bot import b24_app_call

            await b24_app_call(
                "imbot.message.add",
                {
                    "BOT_ID": 228,
                    "DIALOG_ID": str(eq.responsible_bitrix_id),
                    "MESSAGE": message,
                },
                redis=self.redis,
            )
        except Exception as exc:
            logger.error(
                "Failed to send bot notification for equipment %d: %s",
                eq.id, exc,
            )

    async def _create_maintenance_task(
        self, eq: EquipmentUnit, maint: NextMaintenance, priority: int = 1
    ):
        """Create maintenance task via TaskEngine with checklist from CardWorkItem."""
        from models.maintenance_lifecycle import CardWorkItem, CardSparePart, MaintenanceCardV2

        try:
            engine = self._get_task_engine()
            card_label = f" ({maint.card_name})" if maint.card_name else ""
            title = f"ТО: {maint.interval_name} — {eq.name}{card_label}"

            remaining = self._get_remaining(maint)
            unit_label = "ч" if maint.remaining_hours is not None else "дн"

            # Load checklist from CardWorkItem + spare parts
            checklist_text = ""
            async with async_session() as sess:
                # Find interval by code across linked cards
                links = (await sess.execute(
                    select(EquipmentCardLink).where(
                        and_(
                            EquipmentCardLink.equipment_id == eq.id,
                            EquipmentCardLink.is_active.is_(True),
                        )
                    )
                )).scalars().all()

                interval = None
                for link in links:
                    interval = (await sess.execute(
                        select(CardInterval).where(
                            and_(
                                CardInterval.card_id == link.card_id,
                                CardInterval.code == maint.interval_code,
                            )
                        )
                    )).scalar_one_or_none()
                    if interval:
                        break

                if interval:
                    # Get work items
                    work_items = (await sess.execute(
                        select(CardWorkItem)
                        .where(CardWorkItem.interval_id == interval.id)
                        .order_by(CardWorkItem.sort_order)
                    )).scalars().all()

                    # Get spare parts
                    spare_parts = (await sess.execute(
                        select(CardSparePart)
                        .where(CardSparePart.interval_id == interval.id)
                        .order_by(CardSparePart.sort_order)
                    )).scalars().all()

                    if work_items:
                        checklist_text += "\n\nЧек-лист работ:\n"
                        for i, wi in enumerate(work_items, 1):
                            checklist_text += f"  {i}. {wi.description}\n"

                    if spare_parts:
                        checklist_text += "\nМатериалы и запчасти:\n"
                        for sp in spare_parts:
                            qty = f" x{sp.quantity}" if sp.quantity and sp.quantity != 1 else ""
                            art = f" (арт. {sp.part_number})" if sp.part_number else ""
                            checklist_text += f"  • {sp.name}{art}{qty} {sp.unit or ''}\n"

                    # Include nested intervals (includes)
                    if interval.includes:
                        for nested_code in interval.includes:
                            nested_iv = (await sess.execute(
                                select(CardInterval).where(
                                    and_(
                                        CardInterval.card_id == interval.card_id,
                                        CardInterval.code == nested_code,
                                    )
                                )
                            )).scalar_one_or_none()
                            if nested_iv:
                                nested_wi = (await sess.execute(
                                    select(CardWorkItem)
                                    .where(CardWorkItem.interval_id == nested_iv.id)
                                    .order_by(CardWorkItem.sort_order)
                                )).scalars().all()
                                if nested_wi:
                                    checklist_text += f"\nВключает {nested_iv.name}:\n"
                                    for wi in nested_wi:
                                        checklist_text += f"  • {wi.description}\n"

            desc = (
                f"Требуется выполнить {maint.interval_name} для {eq.name} ({eq.code}).\n"
                f"Осталось: {remaining} {unit_label}."
                f"{checklist_text}"
            )

            await engine.create_task(
                task_type="maintenance",
                trigger_source="maint_alert",
                title=title,
                priority=priority,
                equipment_code=eq.code,
                site_id=eq.site_id,
                description=desc,
                responsible_user_id=eq.responsible_bitrix_id,
                responsible_name=eq.responsible_name,
                alarm_name=maint.interval_code,  # reuse field to store interval_code
            )
            logger.info(
                "Maintenance task created: eq=%d (%s), interval=%s, priority=%d, checklist=%d items",
                eq.id, eq.code, maint.interval_code, priority,
                len(checklist_text.splitlines()) if checklist_text else 0,
            )
        except Exception as exc:
            logger.error(
                "Failed to create maintenance task for equipment %d: %s",
                eq.id, exc, exc_info=True,
            )

    async def run_loop(self):
        """Background loop: check every MAINT_ALERT_INTERVAL seconds."""
        self._running = True
        interval = settings.MAINT_ALERT_INTERVAL
        logger.info("MaintenanceAlertService started (interval=%ds)", interval)

        while self._running:
            try:
                await self.check_all()
            except Exception as exc:
                logger.error("AlertService loop error: %s", exc, exc_info=True)

            await asyncio.sleep(interval)

    def stop(self):
        """Signal the loop to stop."""
        self._running = False
        logger.info("MaintenanceAlertService stop requested")
