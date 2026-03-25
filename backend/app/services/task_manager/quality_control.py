"""Quality verification of completed tasks — checklist + metrics checks."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import settings
from models.base import async_session
from models.task_manager import (
    MaintenanceCard,
    MetricsSnapshot,
    ScadaTask,
    TaskQualityCheck,
)
from services.task_manager.resilient_api import log_decision, resilient_b24_call

logger = logging.getLogger("scada.task_manager")

# Weight coefficients for overall quality score
CHECKLIST_WEIGHT = 0.5
METRICS_WEIGHT = 0.5

# Key metrics to compare before/after maintenance
KEY_METRICS = ["oil_pressure", "coolant_temp", "power_output"]


class QualityController:
    """Verify quality of completed tasks via checklists and metrics."""

    def __init__(self, redis):
        self._redis = redis

    # ───────────────────────────────────────────────────────
    # on_task_completed
    # ───────────────────────────────────────────────────────
    async def on_task_completed(self, task_id: int) -> None:
        """Run quality checks after a task is marked completed.

        1. Load task + card (if maintenance)
        2. Set quality_status = "pending_review"
        3. Check B24 checklist completion
        4. Create TaskQualityCheck for checklist
        5. Schedule metrics_after snapshot for maintenance
        6. Calculate overall quality_score
        7. If score >= 0.7 → passed, else → failed
        """
        async with async_session() as session:
            task = await session.get(ScadaTask, task_id)
            if not task:
                logger.warning("quality: task %d not found", task_id)
                return

            task.quality_status = "pending_review"
            await session.commit()

            # Load maintenance card if linked
            card: MaintenanceCard | None = None
            if task.maintenance_card_id:
                card = await session.get(MaintenanceCard, task.maintenance_card_id)

            # ── Checklist check ──
            checklist_score = await self._check_checklist(session, task)

            # ── Metrics snapshot (schedule "after") ──
            metrics_score: float | None = None
            if card and task.task_type == "maintenance":
                delay_hours = settings.QUALITY_METRICS_SNAPSHOT_DELAY_HOURS
                logger.info(
                    "quality: scheduling metrics_after snapshot for task %d "
                    "in %d hours",
                    task_id,
                    delay_hours,
                )
                asyncio.get_event_loop().call_later(
                    delay_hours * 3600,
                    lambda tid=task_id: asyncio.ensure_future(
                        self.check_metrics_improvement(tid)
                    ),
                )

            # ── Calculate overall score ──
            if metrics_score is not None:
                quality_score = (
                    checklist_score * CHECKLIST_WEIGHT
                    + metrics_score * METRICS_WEIGHT
                )
            else:
                # No metrics check yet — use checklist only
                quality_score = checklist_score

            task.quality_score = round(quality_score, 2)

            if quality_score >= 0.7:
                task.quality_status = "passed"
                logger.info(
                    "quality: task %d PASSED (score=%.2f)", task_id, quality_score
                )
                # Update card completion data
                if card:
                    card.last_completed_at = datetime.utcnow()
                    # Use actual device running hours (not task duration!)
                    if task.equipment_code:
                        try:
                            hours_key = f"running_hours:{task.equipment_code}"
                            raw = await self._redis.get(hours_key)
                            if raw:
                                card.last_completed_hours = int(float(raw))
                        except Exception:
                            pass  # leave unchanged if Redis unavailable
            else:
                task.quality_status = "failed"
                logger.warning(
                    "quality: task %d FAILED (score=%.2f) — notifying supervisor",
                    task_id,
                    quality_score,
                )
                await self._notify_supervisor(task, quality_score)

            await log_decision(
                decision_type="quality_assessment",
                task_id=task_id,
                reasoning=f"score={quality_score:.2f} checklist={checklist_score:.2f}",
                data={"quality_score": quality_score, "checklist": checklist_score},
            )

            await session.commit()

    # ───────────────────────────────────────────────────────
    # _check_checklist
    # ───────────────────────────────────────────────────────
    async def _check_checklist(
        self, session, task: ScadaTask
    ) -> float:
        """Check B24 checklist completion and create quality record."""
        if not task.bitrix_task_id:
            logger.debug("quality: task %d has no bitrix_task_id, skip checklist", task.id)
            return 1.0  # No checklist to verify

        data = await resilient_b24_call(
            "task.checklistitem.getlist",
            {"TASKID": task.bitrix_task_id},
            redis=self._redis,
        )

        if data is None:
            logger.warning("quality: B24 checklist call failed for task %d", task.id)
            return 0.5  # Uncertain — give half score

        items = data.get("result", [])
        if not items:
            return 1.0  # Empty checklist = all done

        total = len(items)
        completed = sum(1 for it in items if it.get("IS_COMPLETE") == "Y")
        missing = [
            it.get("TITLE", "?") for it in items if it.get("IS_COMPLETE") != "Y"
        ]

        all_done = completed == total
        score = completed / total if total > 0 else 1.0

        check = TaskQualityCheck(
            task_id=task.id,
            check_type="checklist",
            passed=all_done,
            details={
                "total": total,
                "completed": completed,
                "missing": missing,
            },
        )
        session.add(check)
        await session.flush()

        logger.info(
            "quality: checklist task %d — %d/%d done (score=%.2f)",
            task.id, completed, total, score,
        )
        return score

    # ───────────────────────────────────────────────────────
    # check_metrics_improvement
    # ───────────────────────────────────────────────────────
    async def check_metrics_improvement(self, task_id: int) -> float:
        """Compare before/after MetricsSnapshots and score improvement."""
        async with async_session() as session:
            stmt_before = select(MetricsSnapshot).where(
                MetricsSnapshot.task_id == task_id,
                MetricsSnapshot.snapshot_type == "before",
            )
            stmt_after = select(MetricsSnapshot).where(
                MetricsSnapshot.task_id == task_id,
                MetricsSnapshot.snapshot_type == "after",
            )

            before = (await session.execute(stmt_before)).scalar_one_or_none()
            after = (await session.execute(stmt_after)).scalar_one_or_none()

            if not before or not after:
                logger.warning(
                    "quality: missing snapshots for task %d (before=%s after=%s)",
                    task_id,
                    bool(before),
                    bool(after),
                )
                return 0.5

            improvements = []
            degradations = []

            for metric in KEY_METRICS:
                val_before = before.metrics_data.get(metric)
                val_after = after.metrics_data.get(metric)
                if val_before is None or val_after is None:
                    continue

                diff = val_after - val_before
                entry = {"metric": metric, "before": val_before, "after": val_after, "diff": diff}

                if metric == "coolant_temp":
                    # Lower temp = better
                    if diff <= 0:
                        improvements.append(entry)
                    else:
                        degradations.append(entry)
                else:
                    # Higher = better for pressure and power
                    if diff >= 0:
                        improvements.append(entry)
                    else:
                        degradations.append(entry)

            total_compared = len(improvements) + len(degradations)
            score = len(improvements) / total_compared if total_compared > 0 else 0.5

            check = TaskQualityCheck(
                task_id=task_id,
                check_type="metrics",
                passed=score >= 0.5,
                details={
                    "improvements": improvements,
                    "degradations": degradations,
                    "score": round(score, 2),
                },
            )
            session.add(check)
            await session.commit()

            logger.info(
                "quality: metrics task %d — %d improvements, %d degradations (score=%.2f)",
                task_id,
                len(improvements),
                len(degradations),
                score,
            )
            return score

    # ───────────────────────────────────────────────────────
    # _notify_supervisor
    # ───────────────────────────────────────────────────────
    async def _notify_supervisor(self, task: ScadaTask, score: float) -> None:
        """Send notification to supervisor about failed quality check."""
        message = (
            f"⚠️ Качество задачи #{task.id} ниже порога\n"
            f"Задача: {task.title}\n"
            f"Оценка: {score:.0%}\n"
            f"Статус: требуется проверка"
        )
        logger.warning("quality: supervisor notification — %s", message)
        # TODO: send via B24 bot notification when ready
