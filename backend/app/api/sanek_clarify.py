"""SANEK v2.2 — Clarification dialog API.

POST /api/sanek/incidents/{incident_id}/clarify — operator submits answer
GET  /api/sanek/incidents/{incident_id}/clarify — get current question (for UI)
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_session
from models.agent_incident import AgentIncident

router = APIRouter(prefix="/api/sanek/incidents", tags=["sanek-clarify"])
logger = logging.getLogger("scada.api.sanek_clarify")


class ClarifyRequest(BaseModel):
    answer: str


class ClarifyResponse(BaseModel):
    status: str
    incident_id: int
    message: str = ""


@router.post("/{incident_id}/clarify", response_model=ClarifyResponse)
async def submit_clarification(
    incident_id: int,
    body: ClarifyRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ClarifyResponse:
    """Operator submits clarification answer."""
    # 1. Check incident exists and is in 'clarifying' status
    stmt = select(AgentIncident).where(AgentIncident.id == incident_id)
    result = await session.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    if incident.status != "clarifying":
        raise HTTPException(
            status_code=409,
            detail=f"Incident {incident_id} is not awaiting clarification (status={incident.status})",
        )

    # 2. Check Redis context exists (not timed out)
    redis = request.app.state.redis
    ctx_key = f"sanek:clarify:{incident_id}"
    ctx_raw = await redis.get(ctx_key)
    if not ctx_raw:
        raise HTTPException(
            status_code=410,
            detail=f"Clarification for incident {incident_id} has timed out",
        )

    # 3. Get SanekAgent and resume pipeline
    sanek_agent = getattr(request.app.state, "sanek_agent", None)
    if not sanek_agent:
        raise HTTPException(status_code=503, detail="SanekAgent is not running")

    # Fire-and-forget: resume pipeline in background
    asyncio.create_task(
        sanek_agent._resume_after_clarification(incident_id, body.answer)
    )

    logger.info(
        "Clarification answer received for incident=%d: %s",
        incident_id, body.answer[:200],
    )

    return ClarifyResponse(
        status="received",
        incident_id=incident_id,
        message="Ответ принят, анализ возобновлён",
    )


@router.get("/{incident_id}/clarify")
async def get_clarification(
    incident_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get current clarification question for an incident."""
    stmt = select(AgentIncident).where(AgentIncident.id == incident_id)
    result = await session.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    if incident.status != "clarifying":
        return {
            "status": incident.status,
            "incident_id": incident_id,
            "clarification": None,
        }

    # Try to get full context from Redis
    redis = request.app.state.redis
    ctx_key = f"sanek:clarify:{incident_id}"
    ctx_raw = await redis.get(ctx_key)

    clarification_data = None
    if ctx_raw:
        ctx = json.loads(ctx_raw)
        clarification_data = ctx.get("clarification", {})
        clarification_data["preliminary_diagnosis"] = ctx.get("parsed_sections", {}).get("cause", "")
        clarification_data["confidence"] = ctx.get("confidence", 0)
        clarification_data["asked_at"] = ctx.get("asked_at")
    else:
        # Redis expired but DB still says clarifying — return from DB
        clarification_data = {
            "question": incident.clarification_question,
            "preliminary_diagnosis": incident.preliminary_diagnosis,
            "confidence": incident.preliminary_confidence,
            "asked_at": incident.clarification_asked_at.isoformat() if incident.clarification_asked_at else None,
            "timed_out": True,
        }

    return {
        "status": "clarifying",
        "incident_id": incident_id,
        "clarification": clarification_data,
    }
