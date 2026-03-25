"""
САНЁК v4 — Feedback processor.

Processes 👍/👎 feedback: updates SOP confidence, tracks patterns.
"""
from __future__ import annotations

import logging

from sqlalchemy import select, update, func

from models.base import async_session

logger = logging.getLogger("sanek_v4.learning.feedback")


async def process_pending_feedback():
    """
    Process unprocessed feedback entries.
    - 👍 + SOP referenced → confidence += 0.1
    - 👎 + SOP referenced → confidence -= 0.15
    """
    from models.sanek_chat_feedback import SanekChatFeedback
    from models.sanek_sop_entry import SanekSopEntry

    try:
        async with async_session() as db:
            unprocessed = (await db.execute(
                select(SanekChatFeedback)
                .where(SanekChatFeedback.processed.is_(False))
                .order_by(SanekChatFeedback.created_at)
                .limit(50)
            )).scalars().all()

            for fb in unprocessed:
                # Update SOP confidence if referenced
                if fb.sop_referenced:
                    delta = 0.1 if fb.rating == "up" else -0.15
                    for sop_id in fb.sop_referenced:
                        await db.execute(
                            update(SanekSopEntry)
                            .where(SanekSopEntry.id == sop_id)
                            .values(
                                confidence=func.greatest(0, func.least(1.0, SanekSopEntry.confidence + delta)),
                                times_referenced=SanekSopEntry.times_referenced + 1,
                                last_referenced_at=func.now(),
                            )
                        )

                # Mark as processed
                fb.processed = True
                fb.processed_at = func.now()

            await db.commit()

        if unprocessed:
            logger.info("Processed %d feedback entries", len(unprocessed))

    except Exception as e:
        logger.warning("Feedback processing error: %s", e)
