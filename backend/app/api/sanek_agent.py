"""REST API for SanekAgent incident reports."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.base import get_session
from models.agent_incident import AgentIncident

router = APIRouter(prefix="/api/sanek-agent", tags=["sanek-agent"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AgentIncidentOut(BaseModel):
    id: int
    device_id: int
    site_id: int
    alarm_code: str
    trigger_channel: str
    recommendation: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    status: str
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class AgentIncidentDetailOut(AgentIncidentOut):
    trigger_payload: dict | None = None
    analysis: dict | None = None
    llm_tokens_used: int | None = None


class AgentStatusOut(BaseModel):
    enabled: bool
    debounce_seconds: int
    cooldown_seconds: int
    incidents_today: int
    incidents_total: int
    last_analysis_at: datetime | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/reports", response_model=list[AgentIncidentOut])
async def get_reports(
    site_id: Optional[int] = Query(None),
    device_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="Filter by status: pending, analyzing, completed, failed"),
    last_hours: Optional[float] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> list[AgentIncidentOut]:
    """Return SanekAgent incident reports with filtering."""
    stmt = select(AgentIncident).order_by(desc(AgentIncident.created_at))

    if site_id is not None:
        stmt = stmt.where(AgentIncident.site_id == site_id)
    if device_id is not None:
        stmt = stmt.where(AgentIncident.device_id == device_id)
    if status is not None:
        stmt = stmt.where(AgentIncident.status == status)
    if last_hours is not None:
        cutoff = datetime.utcnow() - timedelta(hours=last_hours)
        stmt = stmt.where(AgentIncident.created_at >= cutoff)

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/reports/{incident_id}", response_model=AgentIncidentDetailOut)
async def get_report_detail(
    incident_id: int,
    session: AsyncSession = Depends(get_session),
) -> AgentIncidentDetailOut:
    """Return detailed SanekAgent incident report including analysis payload."""
    stmt = select(AgentIncident).where(AgentIncident.id == incident_id)
    result = await session.execute(stmt)
    incident = result.scalar_one_or_none()
    if incident is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("/status", response_model=AgentStatusOut)
async def get_agent_status(
    session: AsyncSession = Depends(get_session),
) -> AgentStatusOut:
    """Return SanekAgent module status and statistics."""
    # Today's incidents
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = await session.execute(
        select(func.count()).select_from(AgentIncident).where(
            AgentIncident.created_at >= today_start
        )
    )
    incidents_today = today_count.scalar() or 0

    # Total incidents
    total_count = await session.execute(
        select(func.count()).select_from(AgentIncident)
    )
    incidents_total = total_count.scalar() or 0

    # Last analysis
    last_stmt = (
        select(AgentIncident.completed_at)
        .where(AgentIncident.status == "completed")
        .order_by(desc(AgentIncident.completed_at))
        .limit(1)
    )
    last_result = await session.execute(last_stmt)
    last_at = last_result.scalar_one_or_none()

    return AgentStatusOut(
        enabled=settings.SANEK_AGENT_ENABLED,
        debounce_seconds=settings.SANEK_AGENT_DEBOUNCE,
        cooldown_seconds=settings.SANEK_AGENT_COOLDOWN,
        incidents_today=incidents_today,
        incidents_total=incidents_total,
        last_analysis_at=last_at,
    )
