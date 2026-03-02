"""REST API for SCADA event journal."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import get_session
from models.scada_event import ScadaEvent
from models.device import Device

router = APIRouter(prefix="/api/events", tags=["events"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ScadaEventOut(BaseModel):
    id: int
    device_id: int
    device_name: str | None = None
    category: str
    event_code: str
    message: str
    old_value: str | None = None
    new_value: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ScadaEventOut])
async def get_events(
    site_id: Optional[int] = Query(None),
    device_id: Optional[int] = Query(None),
    device_ids: Optional[str] = Query(None, description="Comma-separated device IDs"),
    category: Optional[str] = Query(None, description="Comma-separated categories: GEN_STATUS,MODE_CHANGE,ATS_STATUS,MAINS,OPERATOR,SYSTEM"),
    last_hours: Optional[float] = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> list[ScadaEventOut]:
    """Return events with filtering and pagination."""
    # Resolve site_id → device IDs
    allowed_device_ids: list[int] | None = None
    if site_id is not None:
        stmt = select(Device.id).where(Device.site_id == site_id)
        result = await session.execute(stmt)
        allowed_device_ids = [row[0] for row in result.all()]
        if not allowed_device_ids:
            return []

    stmt = select(ScadaEvent)
    conditions = []

    if allowed_device_ids is not None:
        conditions.append(ScadaEvent.device_id.in_(allowed_device_ids))
    elif device_ids is not None:
        ids = [int(x.strip()) for x in device_ids.split(",") if x.strip().isdigit()]
        if ids:
            conditions.append(ScadaEvent.device_id.in_(ids))
    elif device_id is not None:
        conditions.append(ScadaEvent.device_id == device_id)

    if category is not None:
        cats = [c.strip() for c in category.split(",") if c.strip()]
        if cats:
            conditions.append(ScadaEvent.category.in_(cats))

    if last_hours is not None:
        cutoff = datetime.utcnow() - timedelta(hours=last_hours)
        conditions.append(ScadaEvent.created_at >= cutoff)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(desc(ScadaEvent.created_at)).offset(offset).limit(limit)
    result = await session.execute(stmt)
    events = list(result.scalars().all())

    # Enrich with device names
    dev_ids = {ev.device_id for ev in events}
    dev_names: dict[int, str] = {}
    if dev_ids:
        dev_result = await session.execute(
            select(Device.id, Device.name).where(Device.id.in_(dev_ids))
        )
        dev_names = {row[0]: row[1] for row in dev_result.all()}

    return [
        ScadaEventOut(
            id=ev.id,
            device_id=ev.device_id,
            device_name=dev_names.get(ev.device_id, f"#{ev.device_id}"),
            category=ev.category,
            event_code=ev.event_code,
            message=ev.message,
            old_value=ev.old_value,
            new_value=ev.new_value,
            created_at=ev.created_at,
        )
        for ev in events
    ]


@router.get("/latest", response_model=list[ScadaEventOut])
async def get_latest_events(
    site_id: Optional[int] = Query(None),
    limit: int = Query(30, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[ScadaEventOut]:
    """Return latest events for the monitoring widget (no time filter, just last N)."""
    return await get_events(
        site_id=site_id,
        device_id=None,
        device_ids=None,
        category=None,
        last_hours=None,
        limit=limit,
        offset=0,
        session=session,
    )
