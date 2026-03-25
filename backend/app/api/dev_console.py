"""ScadaGPU — Dev Console API router (/api/dev-console). Admin only."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.auth import require_role
from models.base import get_session
from models.scada_user import ScadaUser
from models.ai_chat import AiChatMessage
from models.task_manager import OfflineQueue, SanekDecisionLog, TaskCommunication

logger = logging.getLogger("scada.task_manager")

router = APIRouter(prefix="/api/dev-console", tags=["dev-console"])


# ---------------------------------------------------------------------------
#  Decision Log
# ---------------------------------------------------------------------------

@router.get("/decisions")
async def list_decisions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(require_role("admin")),
):
    """List SanekDecisionLog entries."""
    stmt = (
        select(SanekDecisionLog)
        .order_by(SanekDecisionLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()

    return [
        {
            "id": d.id,
            "task_id": d.task_id,
            "decision_type": d.decision_type,
            "decision_data": d.decision_data,
            "reasoning": d.reasoning,
            "triggered_by": d.triggered_by,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: int,
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(require_role("admin")),
):
    """Get a single decision log entry."""
    decision = await session.get(SanekDecisionLog, decision_id)
    if not decision:
        raise HTTPException(404, "Decision not found")

    return {
        "id": decision.id,
        "task_id": decision.task_id,
        "decision_type": decision.decision_type,
        "decision_data": decision.decision_data,
        "reasoning": decision.reasoning,
        "triggered_by": decision.triggered_by,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


# ---------------------------------------------------------------------------
#  Communications — ВСЯ переписка Санька (ai_chat_messages + task_communications)
# ---------------------------------------------------------------------------

@router.get("/communications")
async def list_communications(
    limit: int = Query(50, ge=1, le=200),
    session_id: str | None = Query(None),
    user_filter: int | None = Query(None, alias="user_id"),
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(require_role("admin")),
):
    """All Sanek chat messages with user names."""
    from sqlalchemy.orm import aliased

    stmt = (
        select(AiChatMessage, ScadaUser.name.label("user_name"))
        .outerjoin(ScadaUser, AiChatMessage.user_id == ScadaUser.id)
        .order_by(AiChatMessage.created_at.desc())
        .limit(limit)
    )
    if session_id:
        stmt = stmt.where(AiChatMessage.session_id == session_id)
    if user_filter:
        stmt = stmt.where(AiChatMessage.user_id == user_filter)

    rows = (await session.execute(stmt)).all()

    return [
        {
            "id": m.id,
            "session_id": m.session_id,
            "role": m.role,
            "content": (m.content[:500] + "..." if m.content and len(m.content) > 500 else m.content),
            "source": getattr(m, "source", "scada"),
            "user_id": getattr(m, "user_id", None),
            "user_name": uname or None,
            "tool_name": m.tool_name if hasattr(m, "tool_name") else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m, uname in rows
    ]


@router.get("/communications/sessions")
async def list_chat_sessions(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(require_role("admin")),
):
    """List unique chat sessions with message count and user name."""
    # Get user_id per session (first user message)
    stmt = (
        select(
            AiChatMessage.session_id,
            func.count(AiChatMessage.id).label("msg_count"),
            func.min(AiChatMessage.created_at).label("started_at"),
            func.max(AiChatMessage.created_at).label("last_at"),
            func.max(AiChatMessage.user_id).label("uid"),
            func.max(AiChatMessage.source).label("src"),
        )
        .group_by(AiChatMessage.session_id)
        .order_by(func.max(AiChatMessage.created_at).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    # Batch load user names
    user_ids = {r.uid for r in rows if r.uid}
    user_names = {}
    if user_ids:
        ustmt = select(ScadaUser.id, ScadaUser.name).where(ScadaUser.id.in_(user_ids))
        for uid, uname in (await session.execute(ustmt)).all():
            user_names[uid] = uname

    return [
        {
            "session_id": r.session_id,
            "msg_count": r.msg_count,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "last_at": r.last_at.isoformat() if r.last_at else None,
            "user_name": user_names.get(r.uid),
            "source": r.src,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
#  Offline Queue
# ---------------------------------------------------------------------------

@router.get("/offline-queue")
async def offline_queue_stats(
    session: AsyncSession = Depends(get_session),
    user: ScadaUser = Depends(require_role("admin")),
):
    """Get OfflineQueue stats by status."""
    stmt = select(
        OfflineQueue.status,
        func.count(OfflineQueue.id),
    ).group_by(OfflineQueue.status)

    rows = (await session.execute(stmt)).all()
    counts = {status: cnt for status, cnt in rows}

    return {
        "pending": counts.get("pending", 0),
        "processing": counts.get("processing", 0),
        "failed": counts.get("failed", 0),
        "completed": counts.get("completed", 0),
    }
