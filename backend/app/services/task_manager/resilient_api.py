"""Resilient API wrapper — try execute, queue on failure."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import settings
from models.base import async_session
from models.task_manager import OfflineQueue, SanekDecisionLog
from services.bitrix_bot import b24_app_call

logger = logging.getLogger("scada.task_manager")


# ───────────────────────────────────────────────────────────
# resilient_b24_call
# ───────────────────────────────────────────────────────────
async def resilient_b24_call(
    method: str,
    params: dict,
    redis,
    priority: int = 0,
) -> dict | None:
    """Call Bitrix24 API with timeout; on failure queue for retry.

    Returns the API result dict on success, or ``None`` when the call
    was queued for later processing.
    """
    try:
        result = await asyncio.wait_for(
            b24_app_call(method, params, redis=redis),
            timeout=settings.OFFLINE_EXTERNAL_TIMEOUT,
        )
        return result
    except Exception as exc:
        logger.warning(
            "B24 call %s failed (%s), enqueueing for offline retry",
            method,
            exc,
        )
        await enqueue_offline(
            action_type=f"b24:{method}",
            method=method,
            params=params,
            priority=priority,
        )
        return None


# ───────────────────────────────────────────────────────────
# enqueue_offline
# ───────────────────────────────────────────────────────────
async def enqueue_offline(
    action_type: str,
    method: str,
    params: dict,
    priority: int = 0,
) -> None:
    """Insert a pending item into the offline queue for later retry."""
    now = datetime.utcnow()
    item = OfflineQueue(
        action_type=action_type,
        method=method,
        params=params,
        priority=priority,
        status="pending",
        next_retry_at=now + timedelta(seconds=30),
    )
    try:
        async with async_session() as session:
            session.add(item)
            await session.commit()
        logger.info(
            "Enqueued offline item: %s %s (priority=%d)",
            action_type,
            method,
            priority,
        )
    except Exception:
        logger.exception("Failed to enqueue offline item %s", method)


# ───────────────────────────────────────────────────────────
# log_decision
# ───────────────────────────────────────────────────────────
async def log_decision(
    task_id: int | None,
    decision_type: str,
    decision_data: dict | None,
    reasoning: str | None,
    triggered_by: str | None,
) -> None:
    """Fire-and-forget insert into SanekDecisionLog.

    Errors are swallowed to avoid impacting the caller's flow.
    """
    try:
        entry = SanekDecisionLog(
            task_id=task_id,
            decision_type=decision_type,
            decision_data=decision_data,
            reasoning=reasoning,
            triggered_by=triggered_by,
        )
        async with async_session() as session:
            session.add(entry)
            await session.commit()
    except Exception:
        logger.debug(
            "log_decision suppressed error for task_id=%s type=%s",
            task_id,
            decision_type,
            exc_info=True,
        )
