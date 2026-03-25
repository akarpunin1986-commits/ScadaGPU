"""ScadaGPU — Fire-and-forget activity logging."""
from __future__ import annotations

import logging

from models.base import async_session
from models.user_activity import UserActivity

logger = logging.getLogger("scada.activity")


async def log_activity(
    user_id: int | None,
    action: str,
    target_device_id: int | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    source: str = "scada",
) -> None:
    """Write a single activity record.

    This is designed for fire-and-forget usage: it opens its own
    session and silently catches any exception so that a logging
    failure never disrupts the calling code-path.
    """
    try:
        async with async_session() as session:
            entry = UserActivity(
                user_id=user_id,
                action=action,
                target_device_id=target_device_id,
                details=details,
                ip_address=ip_address,
                source=source,
            )
            session.add(entry)
            await session.commit()
    except Exception:
        logger.exception("Failed to log activity action=%s user_id=%s", action, user_id)
