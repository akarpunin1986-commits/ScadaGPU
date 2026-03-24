"""SANEK Chat API — RAG-enhanced conversational interface.

POST /api/sanek/chat/message  — send message, get AI response with RAG context
GET  /api/sanek/chat/sessions/{id} — get session history
DELETE /api/sanek/chat/sessions/{id} — clear session
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import get_session
from models.alarm_reference import SanekAlarmReference

router = APIRouter(prefix="/api/sanek/chat", tags=["sanek-chat"])
logger = logging.getLogger("scada.api.sanek_chat")

_HISTORY_TTL = 3600  # 1 hour
_MAX_HISTORY = 50
_CHAT_TIMEOUT = 180  # seconds — allow multiple tool call rounds

# Known alarm codes for extraction from user messages
_KNOWN_ALARM_CODES = [
    "TRIP_STOP", "SHUTDOWN", "OVER_FREQUENCY", "OVER_VOLTAGE",
    "OVER_POWER", "LOW_OIL_PRESSURE", "HIGH_COOLANT_TEMP",
    "CONN_LOST", "SYNC_FAIL", "MIN_SETS_NOT_REACHED",
    "LOSS_OF_EXCITATION", "OVER_CURRENT", "UNDER_FREQUENCY",
    "LOW_FUEL_PRESSURE", "HIGH_OIL_TEMP", "ENGINE_SHUTDOWN",
]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatMessageIn(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatSource(BaseModel):
    title: str
    source: str
    score: float = 0.0


class ChatMessageOut(BaseModel):
    response: str
    session_id: str
    sources: list[ChatSource] = []


class ChatHistoryOut(BaseModel):
    session_id: str
    messages: list[dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_key(session_id: str) -> str:
    return f"sanek:chat:{session_id}"


def _extract_alarm_codes(message: str) -> list[str]:
    """Extract known alarm codes from user message."""
    msg_upper = message.upper().replace("-", "_").replace(" ", "_")
    found = [code for code in _KNOWN_ALARM_CODES if code in msg_upper]
    found += re.findall(r'\bE\d{3}\b', msg_upper)
    return list(set(found))


async def _lookup_alarm_references(
    codes: list[str], session: AsyncSession,
) -> list[str]:
    """Fetch alarm reference data from DB and format as context strings."""
    context_parts = []
    for code in codes:
        stmt = select(SanekAlarmReference).where(
            SanekAlarmReference.alarm_code == code,
        ).limit(1)
        result = await session.execute(stmt)
        ref = result.scalar_one_or_none()
        if not ref:
            continue

        causes_list = ref.typical_causes if isinstance(ref.typical_causes, list) else []
        causes = "\n".join(
            f"  - {c.get('cause', '?')} ({int(c.get('probability', 0) * 100)}%)"
            for c in causes_list
        )
        actions_list = ref.immediate_actions if isinstance(ref.immediate_actions, list) else []
        actions = "\n".join(
            f"  {a.get('step', '?')}. {a.get('action', '?')}"
            for a in actions_list
        )
        related = ", ".join(ref.related_alarms or [])
        cascade = ", ".join(ref.possible_cascade or [])

        context_parts.append(
            f"=== СПРАВОЧНИК: {ref.alarm_code} — {ref.alarm_name_ru} ===\n"
            f"Контроллер: {ref.controller} | Severity: {ref.severity}\n"
            f"Типичные причины:\n{causes}\n"
            f"Немедленные действия:\n{actions}\n"
            f"Связанные аварии: {related}\n"
            f"Возможные каскады: {cascade}"
        )
    return context_parts


def _dedup_rag_results(hits: list[dict]) -> list[dict]:
    """Deduplicate RAG results by content hash."""
    seen: set[str] = set()
    unique: list[dict] = []
    for h in hits:
        key = hashlib.md5(h.get("content", "")[:100].encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique


async def _build_chat_context(
    message: str,
    rag_hits: list[dict],
    session: AsyncSession,
) -> tuple[str, list[ChatSource]]:
    """Build enriched context from alarm_reference + RAG. Returns (context_str, sources)."""
    context_parts: list[str] = []
    sources: list[ChatSource] = []

    # 1. Alarm Reference lookup
    alarm_codes = _extract_alarm_codes(message)
    if alarm_codes:
        ref_parts = await _lookup_alarm_references(alarm_codes, session)
        context_parts.extend(ref_parts)
        for code in alarm_codes:
            sources.append(ChatSource(
                title=f"Alarm Reference: {code}",
                source="sanek_alarm_reference",
                score=1.0,
            ))

    # 2. RAG — dedup + format
    unique_rag = _dedup_rag_results(rag_hits)
    if unique_rag:
        context_parts.append("=== МАНУАЛЫ И ПРОЦЕДУРЫ ===")
        for r in unique_rag[:4]:
            context_parts.append(
                f"[{r.get('source', '?')} | score={r.get('score', 0):.2f}]\n"
                f"{r.get('content', '')[:500]}"
            )
            sources.append(ChatSource(
                title=r.get("title", ""),
                source=r.get("source", ""),
                score=r.get("score", 0.0),
            ))

    context = "\n\n".join(context_parts)
    if not context:
        context = "Контекст из базы знаний не найден."
    return context, sources


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/message", response_model=ChatMessageOut)
async def chat_message(
    body: ChatMessageIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ChatMessageOut:
    """Send message to SANEK chat (v4 agentic, non-streaming)."""
    from services.sanek_v4 import sanek_v4_complete

    session_id = body.session_id or str(uuid.uuid4())

    try:
        response_text, _ = await asyncio.wait_for(
            sanek_v4_complete(
                message=body.message,
                session_id=session_id,
                source="sanek_chat",
            ),
            timeout=_CHAT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("Chat v4 timed out (%ds)", _CHAT_TIMEOUT)
        response_text = (
            "⏱ Превышено время ожидания ответа. "
            "Попробуйте упростить вопрос или повторить позже."
        )
    except Exception as exc:
        logger.error("Chat v4 failed: %s", exc)
        response_text = f"❌ Ошибка: {str(exc)[:200]}"

    return ChatMessageOut(
        response=response_text,
        session_id=session_id,
        sources=[],
    )


@router.get("/sessions/{session_id}", response_model=ChatHistoryOut)
async def get_session_history(session_id: str, request: Request) -> ChatHistoryOut:
    """Get chat session history."""
    redis = request.app.state.redis
    raw = await redis.get(_session_key(session_id))
    if raw:
        messages = json.loads(raw if isinstance(raw, str) else raw.decode())
    else:
        messages = []
    return ChatHistoryOut(session_id=session_id, messages=messages)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict:
    """Clear chat session."""
    redis = request.app.state.redis
    await redis.delete(_session_key(session_id))
    return {"success": True, "session_id": session_id}
