"""Device Type Registry & Universal Metrics API.

Provides:
- CRUD for device type registry (metrics schemas, thresholds, statuses)
- Universal metrics query endpoint (JSONB-based, any device type)
- Device context endpoint (current state + type info for LLM)
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_, desc, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import JSONB

from models import get_session
from models.device import Device
from models.device_type_registry import DeviceTypeRegistry
from models.device_metrics import DeviceMetrics

router = APIRouter(prefix="/api/registry", tags=["device-registry"])
logger = logging.getLogger("scada.registry")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class DeviceTypeOut(BaseModel):
    id: int
    type_code: str
    display_name: str
    description: str | None = None
    metrics_schema: dict
    thresholds: dict
    statuses: dict
    nominal_values: dict
    status_field: str | None = None
    running_status_code: int | None = None
    model_config = {"from_attributes": True}


class DeviceTypeCreate(BaseModel):
    type_code: str
    display_name: str
    description: str | None = None
    metrics_schema: dict = {}
    thresholds: dict = {}
    statuses: dict = {}
    nominal_values: dict = {}
    status_field: str | None = None
    running_status_code: int | None = None


class DeviceContextOut(BaseModel):
    """Full device context for LLM — type info + current values."""
    device_id: int
    device_name: str
    device_type: str
    site_id: int
    type_info: DeviceTypeOut | None = None
    current_metrics: dict | None = None
    is_online: bool = False
    last_update: datetime | None = None


# ---------------------------------------------------------------------------
# Registry CRUD
# ---------------------------------------------------------------------------
@router.get("/types", response_model=list[DeviceTypeOut])
async def list_device_types(
    session: AsyncSession = Depends(get_session),
) -> list[DeviceTypeOut]:
    """List all registered device types."""
    result = await session.execute(
        select(DeviceTypeRegistry).order_by(DeviceTypeRegistry.type_code)
    )
    return list(result.scalars().all())


@router.get("/types/{type_code}", response_model=DeviceTypeOut)
async def get_device_type(
    type_code: str,
    session: AsyncSession = Depends(get_session),
) -> DeviceTypeOut:
    """Get a specific device type definition."""
    result = await session.execute(
        select(DeviceTypeRegistry).where(DeviceTypeRegistry.type_code == type_code)
    )
    reg = result.scalar_one_or_none()
    if not reg:
        raise HTTPException(404, f"Device type '{type_code}' not found")
    return reg


@router.post("/types", response_model=DeviceTypeOut)
async def create_device_type(
    body: DeviceTypeCreate,
    session: AsyncSession = Depends(get_session),
) -> DeviceTypeOut:
    """Register a new device type (e.g., furnace, extruder)."""
    existing = await session.execute(
        select(DeviceTypeRegistry).where(DeviceTypeRegistry.type_code == body.type_code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Device type '{body.type_code}' already exists")

    reg = DeviceTypeRegistry(**body.model_dump())
    session.add(reg)
    await session.commit()
    await session.refresh(reg)
    logger.info("Created device type: %s", reg.type_code)
    return reg


@router.put("/types/{type_code}", response_model=DeviceTypeOut)
async def update_device_type(
    type_code: str,
    body: DeviceTypeCreate,
    session: AsyncSession = Depends(get_session),
) -> DeviceTypeOut:
    """Update a device type definition."""
    result = await session.execute(
        select(DeviceTypeRegistry).where(DeviceTypeRegistry.type_code == type_code)
    )
    reg = result.scalar_one_or_none()
    if not reg:
        raise HTTPException(404, f"Device type '{type_code}' not found")

    for key, val in body.model_dump().items():
        setattr(reg, key, val)
    await session.commit()
    await session.refresh(reg)
    logger.info("Updated device type: %s", reg.type_code)
    return reg


# ---------------------------------------------------------------------------
# Universal metrics query (JSONB)
# ---------------------------------------------------------------------------
@router.get("/metrics/{device_id}")
async def query_device_metrics(
    device_id: int,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    last_hours: Optional[float] = Query(None),
    last_minutes: Optional[float] = Query(None),
    metrics: Optional[str] = Query(None, description="Comma-sep metric names to extract"),
    aggregation: Optional[str] = Query(None, description="avg|min|max|last — aggregate over period"),
    bucket_minutes: Optional[int] = Query(None, description="Group by time buckets (minutes)"),
    limit: int = Query(5000, le=50000),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Query metrics for any device type from device_metrics (JSONB).

    Also falls back to metrics_data (wide table) for generators/ATS.
    """
    now = datetime.utcnow()
    if last_minutes is not None:
        start_ts = now - timedelta(minutes=last_minutes)
        end_ts = now
    elif last_hours is not None:
        start_ts = now - timedelta(hours=last_hours)
        end_ts = now
    elif start is not None:
        start_ts = start
        end_ts = end or now
    else:
        start_ts = now - timedelta(hours=1)
        end_ts = now

    parsed_metrics = None
    if metrics:
        parsed_metrics = [m.strip() for m in metrics.split(",") if m.strip()]

    # Try JSONB table first
    stmt = (
        select(DeviceMetrics)
        .where(and_(
            DeviceMetrics.device_id == device_id,
            DeviceMetrics.timestamp >= start_ts,
            DeviceMetrics.timestamp <= end_ts,
        ))
        .order_by(DeviceMetrics.timestamp.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    if rows:
        # Extract requested metrics from JSONB
        output = []
        for r in rows:
            row_dict = {"timestamp": r.timestamp, "online": r.online}
            data = r.data or {}
            if parsed_metrics:
                for m in parsed_metrics:
                    row_dict[m] = data.get(m)
            else:
                row_dict.update(data)
            output.append(row_dict)

        _mkeys = parsed_metrics or list((rows[0].data or {}).keys())
        # Apply bucketing + aggregation
        if bucket_minutes and output:
            return _bucket_aggregate(output, _mkeys, bucket_minutes, aggregation or "avg")
        # Apply aggregation only (no bucketing) → single result
        if aggregation and output:
            return [_aggregate(output, _mkeys, aggregation)]

        return output

    # Fallback: try wide MetricsData table (for generators/ATS)
    from models.metrics_data import MetricsData
    stmt2 = (
        select(MetricsData)
        .where(and_(
            MetricsData.device_id == device_id,
            MetricsData.timestamp >= start_ts,
            MetricsData.timestamp <= end_ts,
        ))
        .order_by(MetricsData.timestamp.asc())
        .limit(limit)
    )
    result2 = await session.execute(stmt2)
    rows2 = result2.scalars().all()

    if not rows2:
        return []

    output2 = []
    for r in rows2:
        row_dict = {"timestamp": r.timestamp, "online": r.online}
        if parsed_metrics:
            for m in parsed_metrics:
                row_dict[m] = getattr(r, m, None)
        else:
            # Return all non-null fields
            for c in r.__table__.columns:
                if c.key not in ("id", "device_id", "device_type"):
                    val = getattr(r, c.key, None)
                    if val is not None:
                        row_dict[c.key] = val
        output2.append(row_dict)

    _mkeys2 = parsed_metrics or [k for k in output2[0] if k not in ("timestamp", "online")]
    # Apply bucketing + aggregation
    if bucket_minutes and output2:
        return _bucket_aggregate(output2, _mkeys2, bucket_minutes, aggregation or "avg")
    # Apply aggregation only (no bucketing) → single result
    if aggregation and output2:
        return [_aggregate(output2, _mkeys2, aggregation)]

    return output2


# ---------------------------------------------------------------------------
# Device context (for LLM auto-injection)
# ---------------------------------------------------------------------------
@router.get("/context/{device_id}", response_model=DeviceContextOut)
async def get_device_context(
    device_id: int,
    session: AsyncSession = Depends(get_session),
) -> DeviceContextOut:
    """Get full device context: type info + current metrics.

    Used by Sanek to understand any device type automatically.
    """
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, f"Device {device_id} not found")

    # Get type registry
    type_info = None
    result = await session.execute(
        select(DeviceTypeRegistry).where(
            DeviceTypeRegistry.type_code == device.device_type.value
        )
    )
    type_info = result.scalar_one_or_none()

    # Get latest metrics (try JSONB first, then wide table)
    current_metrics = None
    is_online = False
    last_update = None

    # Try JSONB
    stmt = (
        select(DeviceMetrics)
        .where(DeviceMetrics.device_id == device_id)
        .order_by(DeviceMetrics.timestamp.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    latest = result.scalar_one_or_none()
    if latest:
        current_metrics = latest.data
        is_online = latest.online
        last_update = latest.timestamp
    else:
        # Fallback to wide table
        from models.metrics_data import MetricsData
        stmt2 = (
            select(MetricsData)
            .where(MetricsData.device_id == device_id)
            .order_by(MetricsData.timestamp.desc())
            .limit(1)
        )
        result2 = await session.execute(stmt2)
        latest2 = result2.scalar_one_or_none()
        if latest2:
            current_metrics = {
                c.key: getattr(latest2, c.key)
                for c in latest2.__table__.columns
                if c.key not in ("id", "device_id", "device_type") and getattr(latest2, c.key) is not None
            }
            is_online = latest2.online
            last_update = latest2.timestamp

    return DeviceContextOut(
        device_id=device.id,
        device_name=device.name,
        device_type=device.device_type.value,
        site_id=device.site_id,
        type_info=type_info,
        current_metrics=current_metrics,
        is_online=is_online,
        last_update=last_update,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _aggregate(rows: list[dict], metric_keys: list[str], mode: str) -> dict:
    """Aggregate rows into a single summary."""
    result = {"aggregation": mode, "count": len(rows)}
    if not rows:
        return result

    if mode == "last":
        last = rows[-1]
        for k in metric_keys:
            result[k] = last.get(k)
        result["timestamp"] = last.get("timestamp")
        return result

    for k in metric_keys:
        values = [r.get(k) for r in rows if r.get(k) is not None and isinstance(r.get(k), (int, float))]
        if not values:
            result[k] = None
            continue
        if mode == "avg":
            result[k] = round(sum(values) / len(values), 2)
        elif mode == "min":
            result[k] = min(values)
        elif mode == "max":
            result[k] = max(values)
    return result


def _bucket_aggregate(rows: list[dict], metric_keys: list[str], bucket_min: int, mode: str = "avg") -> list[dict]:
    """Group rows into time buckets and aggregate with specified mode (avg/min/max/last)."""
    if not rows:
        return []

    bucket_sec = bucket_min * 60
    buckets: dict[int, list[dict]] = {}

    for r in rows:
        ts = r.get("timestamp")
        if not ts:
            continue
        if isinstance(ts, datetime):
            epoch = int(ts.timestamp())
        else:
            continue
        bucket_key = (epoch // bucket_sec) * bucket_sec
        buckets.setdefault(bucket_key, []).append(r)

    output = []
    for bk in sorted(buckets.keys()):
        group = buckets[bk]
        agg = _aggregate(group, metric_keys, mode)
        agg["timestamp"] = datetime.utcfromtimestamp(bk)
        agg["sample_count"] = len(group)
        if "aggregation" in agg:
            del agg["aggregation"]
        if "count" in agg:
            del agg["count"]
        output.append(agg)

    return output
