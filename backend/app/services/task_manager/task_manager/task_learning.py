"""Task learning — analyze historical data for incident patterns and TO effectiveness."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from config import settings
from models.base import async_session
from models.task_manager import (
    MetricsSnapshot,
    ScadaTask,
    TaskQualityCheck,
)
from models.sanek_sop_entry import SanekSopEntry

logger = logging.getLogger("scada.task_manager")


class TaskLearningProcessor:
    """Three learning loops analyzing historical task data.

    1. Incident patterns — repeated alarms per equipment
    2. TO effectiveness — metrics improvement after maintenance
    """

    def __init__(self, redis):
        self._redis = redis
        self._running = False
        self._task: asyncio.Task | None = None

    # ───────────────────────────────────────────────────────
    # Lifecycle
    # ───────────────────────────────────────────────────────
    async def start(self) -> None:
        """Start the periodic learning loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("TaskLearningProcessor started (interval=%ds)", settings.TM_LEARNING_INTERVAL)

    async def stop(self) -> None:
        """Stop the learning loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TaskLearningProcessor stopped")

    async def _loop(self) -> None:
        """Periodic loop: run learning cycle every TM_LEARNING_INTERVAL seconds."""
        while self._running:
            try:
                await self._learning_cycle()
            except Exception:
                logger.exception("learning: cycle failed")
            await asyncio.sleep(settings.TM_LEARNING_INTERVAL)

    # ───────────────────────────────────────────────────────
    # Main cycle
    # ───────────────────────────────────────────────────────
    async def _learning_cycle(self) -> None:
        """Execute all learning analyses."""
        logger.info("learning: starting cycle")
        await self._learn_incident_patterns()
        await self._learn_to_effectiveness()
        logger.info("learning: cycle complete")

    # ───────────────────────────────────────────────────────
    # 1. Incident patterns
    # ───────────────────────────────────────────────────────
    async def _learn_incident_patterns(self) -> None:
        """GROUP BY alarm_name, equipment_code — detect recurring incidents.

        If same alarm fires >3 times in 30 days → log warning + create insight.
        """
        cutoff = datetime.utcnow() - timedelta(days=30)

        async with async_session() as session:
            stmt = (
                select(
                    ScadaTask.alarm_name,
                    ScadaTask.equipment_code,
                    func.count(ScadaTask.id).label("cnt"),
                )
                .where(
                    ScadaTask.task_type == "incident",
                    ScadaTask.alarm_name.isnot(None),
                    ScadaTask.created_at >= cutoff,
                )
                .group_by(ScadaTask.alarm_name, ScadaTask.equipment_code)
                .having(func.count(ScadaTask.id) > 1)
                .order_by(func.count(ScadaTask.id).desc())
            )

            rows = (await session.execute(stmt)).all()

            for alarm_name, equipment_code, count in rows:
                if count > 3:
                    logger.warning(
                        "learning: RECURRING alarm '%s' on %s — %d times in 30d",
                        alarm_name,
                        equipment_code,
                        count,
                    )

                    # Publish insight to Redis for Sanek
                    insight = {
                        "type": "recurring_alarm",
                        "alarm_name": alarm_name,
                        "equipment_code": equipment_code,
                        "count_30d": count,
                        "recommendation": (
                            f"Alarm '{alarm_name}' on {equipment_code} fired "
                            f"{count} times in 30 days. Consider root-cause analysis."
                        ),
                    }
                    try:
                        await self._redis.publish(
                            "learning:insights",
                            str(insight),
                        )
                    except Exception:
                        logger.debug("learning: redis publish failed (non-critical)")
                else:
                    logger.debug(
                        "learning: alarm '%s' on %s — %d times (below threshold)",
                        alarm_name,
                        equipment_code,
                        count,
                    )

    # ───────────────────────────────────────────────────────
    # 2. TO effectiveness
    # ───────────────────────────────────────────────────────
    async def _learn_to_effectiveness(self) -> None:
        """Analyze completed maintenance tasks with before/after snapshots.

        Compare metrics improvement to evaluate TO effectiveness.
        """
        async with async_session() as session:
            # Find completed maintenance tasks with quality checks
            stmt = (
                select(ScadaTask)
                .where(
                    ScadaTask.task_type == "maintenance",
                    ScadaTask.status == "completed",
                    ScadaTask.quality_score.isnot(None),
                )
                .order_by(ScadaTask.completed_at.desc())
                .limit(50)
            )

            tasks = (await session.execute(stmt)).scalars().all()

            if not tasks:
                logger.debug("learning: no completed maintenance tasks with quality data")
                return

            total_score = 0.0
            scored_count = 0
            low_quality = []

            for task in tasks:
                total_score += task.quality_score
                scored_count += 1
                if task.quality_score < 0.5:
                    low_quality.append({
                        "task_id": task.id,
                        "equipment": task.equipment_code,
                        "score": task.quality_score,
                        "title": task.title,
                    })

            avg_score = total_score / scored_count if scored_count else 0

            logger.info(
                "learning: TO effectiveness — %d tasks, avg_score=%.2f, low_quality=%d",
                scored_count,
                avg_score,
                len(low_quality),
            )

            if low_quality:
                logger.warning(
                    "learning: %d maintenance tasks with low quality: %s",
                    len(low_quality),
                    [lq["equipment"] for lq in low_quality],
                )

    # ───────────────────────────────────────────────────────
    # save_learning_data
    # ───────────────────────────────────────────────────────
    async def save_learning_data(
        self, task: ScadaTask, quality_check: TaskQualityCheck
    ) -> None:
        """Save resolved incident data to sanek_sop_entries for knowledge reuse.

        Only saves if task has resolution info (description or incident report).
        """
        if not task.description:
            logger.debug("learning: task %d has no description, skip SOP save", task.id)
            return

        if task.task_type != "incident":
            return

        async with async_session() as session:
            # Check if SOP entry already exists for this alarm
            if task.alarm_name:
                existing = await session.execute(
                    select(SanekSopEntry).where(
                        SanekSopEntry.alarm_code == task.alarm_name,
                        SanekSopEntry.device_id.isnot(None),
                    ).limit(1)
                )
                if existing.scalar_one_or_none():
                    logger.debug(
                        "learning: SOP entry for alarm '%s' already exists",
                        task.alarm_name,
                    )
                    return

            sop = SanekSopEntry(
                incident_type="alarm",
                alarm_code=task.alarm_name,
                device_id=None,  # Could resolve from equipment_code
                symptoms=task.title,
                root_cause=task.description,
                resolution=task.description,
                confidence=quality_check.details.get("score", 0.5)
                if quality_check.details
                else 0.5,
                source="task_learning",
                tags=[task.equipment_code, task.task_type]
                if task.equipment_code
                else [task.task_type],
            )
            session.add(sop)
            await session.commit()

            logger.info(
                "learning: saved SOP entry for task %d (alarm=%s)",
                task.id,
                task.alarm_name,
            )
