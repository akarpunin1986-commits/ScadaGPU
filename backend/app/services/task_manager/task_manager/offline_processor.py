"""Background processor for offline queue items."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_

from config import settings
from models.base import async_session
from models.task_manager import OfflineQueue
from services.bitrix_bot import b24_app_call

logger = logging.getLogger("scada.task_manager")


class OfflineProcessor:
    """Drains the offline queue by retrying queued B24 API calls."""

    def __init__(self, redis):
        self._redis = redis
        self._running = False

    # ───────────────────────────────────────────────────────
    # lifecycle
    # ───────────────────────────────────────────────────────
    async def start(self) -> None:
        """Run the drain loop until stopped."""
        self._running = True
        logger.info("OfflineProcessor started (interval=%ds)", settings.TM_OFFLINE_DRAIN_INTERVAL)
        while self._running:
            try:
                await self._drain_cycle()
            except Exception:
                logger.exception("OfflineProcessor drain cycle error")
            try:
                await asyncio.sleep(settings.TM_OFFLINE_DRAIN_INTERVAL)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        """Signal the processor to stop after the current cycle."""
        self._running = False
        logger.info("OfflineProcessor stop requested")

    # ───────────────────────────────────────────────────────
    # drain cycle
    # ───────────────────────────────────────────────────────
    async def _drain_cycle(self) -> None:
        now = datetime.utcnow()
        async with async_session() as session:
            # Fetch pending items ready for retry
            stmt = (
                select(OfflineQueue)
                .where(
                    and_(
                        OfflineQueue.status == "pending",
                        OfflineQueue.next_retry_at <= now,
                    )
                )
                .order_by(OfflineQueue.priority.desc(), OfflineQueue.created_at)
                .limit(20)
            )
            result = await session.execute(stmt)
            items = result.scalars().all()

            if not items:
                return

            logger.info("OfflineProcessor: processing %d queued items", len(items))

            for item in items:
                item.status = "processing"
                await session.flush()

                try:
                    await asyncio.wait_for(
                        b24_app_call(item.method, item.params, redis=self._redis),
                        timeout=settings.OFFLINE_EXTERNAL_TIMEOUT,
                    )
                    # Success
                    item.status = "completed"
                    item.completed_at = datetime.utcnow()
                    logger.info(
                        "OfflineQueue #%d completed: %s", item.id, item.method
                    )
                except Exception as exc:
                    item.attempts += 1
                    item.last_error = str(exc)[:2000]

                    if item.attempts >= item.max_attempts:
                        item.status = "failed"
                        logger.error(
                            "OfflineQueue #%d permanently failed after %d attempts: %s",
                            item.id,
                            item.attempts,
                            item.method,
                        )
                    else:
                        # Exponential backoff: 30s * 2^attempts
                        backoff = timedelta(seconds=30 * (2 ** item.attempts))
                        item.next_retry_at = datetime.utcnow() + backoff
                        item.status = "pending"
                        logger.warning(
                            "OfflineQueue #%d retry #%d in %s: %s",
                            item.id,
                            item.attempts,
                            backoff,
                            item.method,
                        )

            await session.commit()
