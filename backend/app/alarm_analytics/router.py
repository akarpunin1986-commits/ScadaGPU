"""Alarm Analytics API — REST endpoints for alarm events with analysis.

GET /api/alarm-analytics/events          — list with filters
GET /api/alarm-analytics/events/{id}     — single event with snapshot + analysis
GET /api/alarm-analytics/active          — only active alarms
GET /api/alarm-analytics/definitions     — alarm code lookup (for frontend fallback)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_session
from alarm_analytics.models import AlarmAnalyticsEvent
from alarm_analytics.alarm_definitions import (
    ALARM_MAP_HGM9560, ALARM_MAP_HGM9520N,
)

router = APIRouter(prefix="/api/alarm-analytics", tags=["alarm-analytics"])
logger = logging.getLogger("scada.alarm_analytics.router")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AlarmAnalyticsEventOut(BaseModel):
    id: int
    device_id: int
    device_type: str
    alarm_code: str
    alarm_name: str
    alarm_name_ru: str
    alarm_severity: str
    alarm_register: int
    alarm_bit: int
    occurred_at: datetime
    cleared_at: Optional[datetime] = None
    is_active: bool
    metrics_snapshot: Optional[dict] = None
    analysis_result: Optional[dict] = None

    model_config = {"from_attributes": True}


class AlarmAnalyticsEventBrief(BaseModel):
    id: int
    device_id: int
    device_type: str
    alarm_code: str
    alarm_name: str
    alarm_name_ru: str
    alarm_severity: str
    occurred_at: datetime
    cleared_at: Optional[datetime] = None
    is_active: bool

    model_config = {"from_attributes": True}


class AlarmDefinitionOut(BaseModel):
    code: str
    name: str
    name_ru: str
    severity: str
    register_field: str
    bit: int


# ---------------------------------------------------------------------------
# ENDPOINTS
# ---------------------------------------------------------------------------

@router.get("/events", response_model=list[AlarmAnalyticsEventBrief])
async def list_events(
    device_id: Optional[int] = Query(None),
    alarm_code: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    severity: Optional[str] = Query(None),
    last_hours: Optional[float] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> list[AlarmAnalyticsEventBrief]:
    """List alarm analytics events with filters and pagination."""
    stmt = select(AlarmAnalyticsEvent)
    conditions = []

    if device_id is not None:
        conditions.append(AlarmAnalyticsEvent.device_id == device_id)
    if alarm_code is not None:
        conditions.append(AlarmAnalyticsEvent.alarm_code == alarm_code)
    if is_active is not None:
        conditions.append(AlarmAnalyticsEvent.is_active == is_active)
    if severity is not None:
        conditions.append(AlarmAnalyticsEvent.alarm_severity == severity)
    if last_hours is not None:
        cutoff = datetime.utcnow() - timedelta(hours=last_hours)
        conditions.append(AlarmAnalyticsEvent.occurred_at >= cutoff)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(desc(AlarmAnalyticsEvent.occurred_at)).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/events/{event_id}", response_model=AlarmAnalyticsEventOut)
async def get_event(
    event_id: int,
    session: AsyncSession = Depends(get_session),
) -> AlarmAnalyticsEventOut:
    """Get single alarm analytics event with full snapshot and analysis."""
    stmt = select(AlarmAnalyticsEvent).where(AlarmAnalyticsEvent.id == event_id)
    result = await session.execute(stmt)
    event = result.scalar_one_or_none()
    if not event:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/active", response_model=list[AlarmAnalyticsEventBrief])
async def get_active(
    device_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[AlarmAnalyticsEventBrief]:
    """Return only currently active alarm analytics events."""
    stmt = select(AlarmAnalyticsEvent).where(
        AlarmAnalyticsEvent.is_active == True  # noqa: E712
    )
    if device_id is not None:
        stmt = stmt.where(AlarmAnalyticsEvent.device_id == device_id)
    stmt = stmt.order_by(desc(AlarmAnalyticsEvent.occurred_at))
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/definitions", response_model=list[AlarmDefinitionOut])
async def get_definitions(
    device_type: Optional[str] = Query(None, description="ats or generator"),
) -> list[AlarmDefinitionOut]:
    """Return alarm definitions for frontend lookup (no DB needed)."""
    result = []

    maps_to_query = []
    if device_type is None or device_type == "ats":
        maps_to_query.append(ALARM_MAP_HGM9560)
    if device_type is None or device_type == "generator":
        maps_to_query.append(ALARM_MAP_HGM9520N)

    for alarm_map in maps_to_query:
        for (field, bit), defn in alarm_map.items():
            result.append(AlarmDefinitionOut(
                code=defn["code"],
                name=defn["name"],
                name_ru=defn["name_ru"],
                severity=defn["severity"],
                register_field=field,
                bit=bit,
            ))

    return result
