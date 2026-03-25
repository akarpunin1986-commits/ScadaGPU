"""
САНЁК v4 — Session memory.

Auto-generates summaries of significant conversations for cross-session context.
"""
from __future__ import annotations

import logging

from sqlalchemy import select, desc

from models.base import async_session

logger = logging.getLogger("sanek_v4.learning.memory")


async def save_session_summary(
    session_id: str,
    user_message: str,
    assistant_response: str,
    tools_used: list[dict],
    iterations: int,
) -> None:
    """
    Save a session summary if the conversation was significant (3+ tools used).
    Called after 'done' event in chat_stream_v4.
    """
    if len(tools_used) < 3:
        return  # Not significant enough

    from models.sanek_session_mem import SanekSessionMemory

    # Build summary from the conversation
    tool_names = list(set(t["tool"] for t in tools_used))
    summary = _build_summary(user_message, assistant_response, tool_names, iterations)

    if not summary or len(summary) < 20:
        return

    # Extract key facts
    key_facts = {
        "question": user_message[:200],
        "tools": tool_names,
        "iterations": iterations,
    }

    # Determine importance (more tools = more important)
    importance = min(1.0, 0.3 + len(tools_used) * 0.1)

    try:
        async with async_session() as db:
            # Upsert — update if session_id exists
            existing = (await db.execute(
                select(SanekSessionMemory)
                .where(SanekSessionMemory.session_id == session_id)
            )).scalar_one_or_none()

            if existing:
                existing.summary = summary
                existing.key_facts = key_facts
                existing.importance = max(existing.importance, importance)
            else:
                db.add(SanekSessionMemory(
                    session_id=session_id,
                    summary=summary,
                    key_facts=key_facts,
                    importance=importance,
                ))

            await db.commit()

    except Exception as e:
        logger.warning("Failed to save session memory: %s", e)


def _build_summary(question: str, answer: str, tools: list[str], iterations: int) -> str:
    """Build a concise summary from conversation."""
    # Take first 100 chars of question and first 200 of answer
    q_short = question[:100].strip()
    a_short = answer[:300].strip()

    # Remove formatting
    for ch in ["**", "📊", "⚡", "🔧", "⚠️", "📌", "💡", "📡", "📈", "💰"]:
        a_short = a_short.replace(ch, "")

    return f"Вопрос: {q_short} | Ответ: {a_short} | Tools: {', '.join(tools[:5])}"


async def load_recent_memories(limit: int = 5) -> list[str]:
    """Load recent session summaries for system prompt injection."""
    from models.sanek_session_mem import SanekSessionMemory

    try:
        async with async_session() as db:
            rows = (await db.execute(
                select(SanekSessionMemory)
                .where(SanekSessionMemory.expires_at.is_(None) |
                       (SanekSessionMemory.expires_at > func.now()))
                .order_by(desc(SanekSessionMemory.importance), desc(SanekSessionMemory.created_at))
                .limit(limit)
            )).scalars().all()

        return [r.summary for r in rows]

    except Exception as e:
        logger.warning("Failed to load memories: %s", e)
        return []


# Need func import for expires_at check
from sqlalchemy import func
