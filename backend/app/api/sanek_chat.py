"""SANEK Chat API — RAG-enhanced conversational interface.

POST /api/sanek/chat/message  — send message, get AI response with RAG context
GET  /api/sanek/chat/sessions/{id} — get session history
DELETE /api/sanek/chat/sessions/{id} — clear session
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import get_session

router = APIRouter(prefix="/api/sanek/chat", tags=["sanek-chat"])
logger = logging.getLogger("scada.api.sanek_chat")

_HISTORY_TTL = 3600  # 1 hour
_MAX_HISTORY = 50


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
# Redis session helpers
# ---------------------------------------------------------------------------

async def _get_redis():
    """Get Redis client from app state."""
    import aioredis
    # Use the shared Redis connection
    from models.base import engine
    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return redis


def _session_key(session_id: str) -> str:
    return f"sanek:chat:{session_id}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/message", response_model=ChatMessageOut)
async def chat_message(
    body: ChatMessageIn,
    session: AsyncSession = Depends(get_session),
) -> ChatMessageOut:
    """Send message to SANEK chat with RAG context."""
    import aioredis

    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        # Session management
        session_id = body.session_id or str(uuid.uuid4())
        key = _session_key(session_id)

        # Load history from Redis
        raw_history = await redis.get(key)
        history: list[dict] = json.loads(raw_history) if raw_history else []

        # RAG search for context
        sources: list[ChatSource] = []
        rag_context = ""
        if settings.SANEK_RAG_ENABLED:
            try:
                from services.sanek_rag.rag_retriever import RagRetriever
                rag = RagRetriever(settings.CHROMADB_HOST, settings.CHROMADB_PORT)
                await rag.initialize()
                hits = await rag.search(
                    query=body.message,
                    top_k=settings.SANEK_RAG_TOP_K,
                    min_score=settings.SANEK_RAG_MIN_SCORE,
                )
                if hits:
                    rag_parts = ["Контекст из базы знаний (мануалы):"]
                    for h in hits[:3]:
                        rag_parts.append(f"— {h.get('title', '')}: {h.get('content', '')[:400]}")
                        sources.append(ChatSource(
                            title=h.get("title", ""),
                            source=h.get("source", ""),
                            score=h.get("score", 0.0),
                        ))
                    rag_context = "\n".join(rag_parts)
            except Exception as exc:
                logger.warning("Chat RAG search failed: %s", exc)

        # Build messages for LLM
        system_prompt = (
            "Ты — Санёк, AI-ассистент оператора газопоршневых электростанций. "
            "Отвечай на русском, кратко и по делу. Используй предоставленный контекст из мануалов."
        )
        if rag_context:
            system_prompt += f"\n\n{rag_context}"

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-_MAX_HISTORY:])
        messages.append({"role": "user", "content": body.message})

        # Call LLM
        from services.sanek import SanekAssistant
        from models.ai_provider import AiProviderConfig
        async with session.begin():
            from sqlalchemy import select
            stmt = select(AiProviderConfig).where(AiProviderConfig.is_active == True).limit(1)
            result = await session.execute(stmt)
            provider_cfg = result.scalar_one_or_none()

        if not provider_cfg:
            raise HTTPException(status_code=503, detail="AI провайдер не настроен")

        assistant = SanekAssistant(
            provider=provider_cfg.provider,
            api_key=provider_cfg.api_key,
            model=provider_cfg.model,
        )

        # Use only messages (no system for SanekAssistant, it adds its own)
        chat_messages = history[-_MAX_HISTORY:] + [{"role": "user", "content": body.message}]
        if rag_context:
            # Inject RAG context as a system hint before user message
            chat_messages.insert(-1, {
                "role": "system",
                "content": rag_context,
            })

        llm_response = await assistant.chat(chat_messages)
        response_text = llm_response.get("message", "Нет ответа")

        # Update history
        history.append({"role": "user", "content": body.message})
        history.append({"role": "assistant", "content": response_text})

        # Trim and save
        if len(history) > _MAX_HISTORY * 2:
            history = history[-_MAX_HISTORY * 2:]
        await redis.set(key, json.dumps(history, ensure_ascii=False), ex=_HISTORY_TTL)

        return ChatMessageOut(
            response=response_text,
            session_id=session_id,
            sources=sources,
        )

    finally:
        await redis.close()


@router.get("/sessions/{session_id}", response_model=ChatHistoryOut)
async def get_session_history(session_id: str) -> ChatHistoryOut:
    """Get chat session history."""
    import aioredis
    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        raw = await redis.get(_session_key(session_id))
        messages = json.loads(raw) if raw else []
        return ChatHistoryOut(session_id=session_id, messages=messages)
    finally:
        await redis.close()


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Clear chat session."""
    import aioredis
    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await redis.delete(_session_key(session_id))
        return {"success": True, "session_id": session_id}
    finally:
        await redis.close()
