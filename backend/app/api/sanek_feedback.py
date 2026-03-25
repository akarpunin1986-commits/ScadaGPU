"""SANEK v2.1 Module A — Feedback Loop API.

POST /api/sanek/incidents/{incident_id}/feedback — operator rates diagnosis
GET  /api/sanek/feedback/stats — accuracy statistics
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_session
from models.agent_incident import AgentIncident
from models.feedback import SanekFeedback, SanekPatternStats

router = APIRouter(prefix="/api/sanek", tags=["sanek-feedback"])
logger = logging.getLogger("scada.api.sanek_feedback")

VALID_ASSESSMENTS = {"correct", "partial", "incorrect"}


class FeedbackRequest(BaseModel):
    assessment: str
    actual_root_cause: str | None = None
    operator_notes: str | None = None
    submitted_by: str | None = None


class FeedbackResponse(BaseModel):
    status: str
    incident_id: int
    message: str = ""


@router.post("/incidents/{incident_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    incident_id: int,
    body: FeedbackRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> FeedbackResponse:
    """Operator submits feedback on incident diagnosis."""
    if body.assessment not in VALID_ASSESSMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid assessment '{body.assessment}'. Must be one of: {VALID_ASSESSMENTS}",
        )

    # 1. Check incident exists
    stmt = select(AgentIncident).where(AgentIncident.id == incident_id)
    result = await session.execute(stmt)
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    # 2. Check no duplicate feedback (UNIQUE constraint)
    existing = await session.execute(
        select(SanekFeedback).where(SanekFeedback.incident_id == incident_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Feedback already submitted for this incident")

    # 3. Insert feedback
    feedback = SanekFeedback(
        incident_id=incident_id,
        assessment=body.assessment,
        actual_root_cause=body.actual_root_cause,
        operator_notes=body.operator_notes,
        submitted_by=body.submitted_by or "anonymous",
    )
    session.add(feedback)

    # 4. Update incident feedback_status
    incident.feedback_status = body.assessment
    await session.commit()

    logger.info(
        "Feedback saved: incident=%d assessment=%s",
        incident_id, body.assessment,
    )

    # 5. Background tasks: reinforce pattern / update embedding
    sanek_agent = getattr(request.app.state, "sanek_agent", None)
    if sanek_agent:
        if body.assessment == "correct":
            asyncio.create_task(sanek_agent._reinforce_pattern(incident_id))
        elif body.assessment == "incorrect":
            asyncio.create_task(
                sanek_agent._update_incident_embedding(incident_id, confirmed=False)
            )

    return FeedbackResponse(
        status="saved",
        incident_id=incident_id,
        message="Оценка сохранена",
    )


@router.get("/feedback/stats")
async def feedback_stats(
    days: int = 30,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Accuracy statistics for dashboard widget."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    # Total counts by assessment
    stmt = (
        select(
            func.count().label("total"),
            func.count().filter(SanekFeedback.assessment == "correct").label("correct"),
            func.count().filter(SanekFeedback.assessment == "partial").label("partial"),
            func.count().filter(SanekFeedback.assessment == "incorrect").label("incorrect"),
        )
        .where(SanekFeedback.created_at >= cutoff)
    )
    result = await session.execute(stmt)
    row = result.one()
    total = row.total or 0
    correct = row.correct or 0
    partial = row.partial or 0
    incorrect = row.incorrect or 0

    stats: dict = {
        "total_assessed": total,
        "correct": correct,
        "correct_pct": round(correct / total * 100, 1) if total else 0,
        "partial": partial,
        "partial_pct": round(partial / total * 100, 1) if total else 0,
        "incorrect": incorrect,
        "incorrect_pct": round(incorrect / total * 100, 1) if total else 0,
        "period_days": days,
    }

    # By pattern (correlation_pattern_id)
    by_pattern_stmt = (
        select(
            AgentIncident.correlation_pattern_id,
            func.count().label("total"),
            func.count().filter(SanekFeedback.assessment == "correct").label("correct"),
        )
        .join(SanekFeedback, SanekFeedback.incident_id == AgentIncident.id)
        .where(SanekFeedback.created_at >= cutoff)
        .where(AgentIncident.correlation_pattern_id.isnot(None))
        .group_by(AgentIncident.correlation_pattern_id)
    )
    pattern_rows = await session.execute(by_pattern_stmt)
    by_pattern = {}
    for p in pattern_rows.all():
        if p.correlation_pattern_id:
            by_pattern[p.correlation_pattern_id] = {
                "total": p.total,
                "correct": p.correct,
                "pct": round(p.correct / p.total * 100, 1) if p.total else 0,
            }
    stats["by_pattern"] = by_pattern

    # By device
    by_device_stmt = (
        select(
            AgentIncident.device_id,
            func.count().label("total"),
            func.count().filter(SanekFeedback.assessment == "correct").label("correct"),
        )
        .join(SanekFeedback, SanekFeedback.incident_id == AgentIncident.id)
        .where(SanekFeedback.created_at >= cutoff)
        .group_by(AgentIncident.device_id)
    )
    device_rows = await session.execute(by_device_stmt)
    by_device = {}
    for d in device_rows.all():
        by_device[str(d.device_id)] = {
            "total": d.total,
            "correct_pct": round(d.correct / d.total * 100, 1) if d.total else 0,
        }
    stats["by_device"] = by_device

    return stats


# ═══════════ V3 Feedback Endpoint ═══════════

@router.post("/feedback")
async def submit_feedback_v3(request: Request):
    """V3 feedback: session-based (no incident_id required)."""
    from fastapi.responses import JSONResponse
    try:
        from services.sanek_learning import process_feedback
        body = await request.json()
        result = await process_feedback(
            session_id=body.get("session_id", ""),
            message_index=body.get("message_index", 0),
            feedback=body.get("feedback", "correct"),
            correct_answer=body.get("correct_answer"),
            real_cause=body.get("real_cause"),
            feedback_detail=body.get("feedback_detail"),
            context=body.get("context", {}),
        )
        return JSONResponse(result)
    except Exception as e:
        logger.error("V3 feedback error: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)
