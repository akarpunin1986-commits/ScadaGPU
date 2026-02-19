"""Phase 6 — History API: metrics history, alarm events, disk usage.

Endpoints for reading stored metrics and alarms from PostgreSQL.
Supports time range queries, field filtering, downsampling for charts.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, func, and_, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import get_session
from models.metrics_data import MetricsData
from models.alarm_event import AlarmEvent

router = APIRouter(prefix="/api/history", tags=["history"])
logger = logging.getLogger("scada.history")

# Valid metric field names for filtering
METRIC_FIELDS = {
    c.key for c in MetricsData.__table__.columns
    if c.key not in ("id", "device_id", "device_type")
}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class MetricsPointOut(BaseModel):
    model_config = {"from_attributes": True}


class AlarmEventOut(BaseModel):
    id: int
    device_id: int
    alarm_code: str
    severity: str
    message: str
    occurred_at: datetime
    cleared_at: Optional[datetime] = None
    is_active: bool
    model_config = {"from_attributes": True}


class DiskUsageOut(BaseModel):
    db_size_mb: float
    max_db_size_mb: int
    usage_pct: float
    metrics_table_size_mb: float
    metrics_row_count: int
    alarms_row_count: int


class MetricsStatsOut(BaseModel):
    device_id: int
    total_rows: int
    oldest: Optional[datetime] = None
    newest: Optional[datetime] = None
    days_stored: float = 0


# ---------------------------------------------------------------------------
# METRICS ENDPOINTS
# ---------------------------------------------------------------------------
@router.get("/metrics/{device_id}")
async def get_metrics_history(
    device_id: int,
    start: Optional[datetime] = Query(None, description="Start (ISO 8601)"),
    end: Optional[datetime] = Query(None, description="End (ISO 8601)"),
    last_hours: Optional[float] = Query(None, description="Last N hours"),
    last_minutes: Optional[float] = Query(None, description="Last N minutes"),
    fields: Optional[str] = Query(None, description="Comma-sep field names (e.g. power_total,gen_uab)"),
    limit: int = Query(1000, le=10000),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Return raw metrics history for a device.

    Time range:
    - ?last_minutes=5  (last 5 min)
    - ?last_hours=1    (last 1 hour)
    - ?start=...&end=...  (explicit range)
    - default: last 1 hour

    Field filtering:
    - ?fields=power_total,gen_uab,coolant_temp
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

    stmt = (
        select(MetricsData)
        .where(
            and_(
                MetricsData.device_id == device_id,
                MetricsData.timestamp >= start_ts,
                MetricsData.timestamp <= end_ts,
            )
        )
        .order_by(MetricsData.timestamp.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    if fields:
        requested = {"timestamp", "online"} | {
            f.strip() for f in fields.split(",") if f.strip() in METRIC_FIELDS
        }
        return [
            {k: getattr(row, k, None) for k in requested if hasattr(row, k)}
            for row in rows
        ]
    return [_row_to_dict(row) for row in rows]


@router.get("/metrics/{device_id}/latest")
async def get_latest_metrics(
    device_id: int,
    count: int = Query(1, le=100, description="Number of latest readings"),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Return the N most recent metrics readings for a device."""
    stmt = (
        select(MetricsData)
        .where(MetricsData.device_id == device_id)
        .order_by(MetricsData.timestamp.desc())
        .limit(count)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    rows.reverse()  # oldest first
    return [_row_to_dict(row) for row in rows]


@router.get("/metrics/{device_id}/downsampled")
async def get_metrics_downsampled(
    device_id: int,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    last_hours: float = Query(24),
    bucket_seconds: int = Query(60, ge=1, description="Aggregation bucket in seconds"),
    fields: str = Query("power_total", description="Comma-sep fields to average"),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Return downsampled (averaged) metrics for charting over long periods.

    Groups by time buckets and returns AVG of requested fields.
    Example: ?last_hours=24&bucket_seconds=300&fields=power_total,gen_uab
    """
    now = datetime.utcnow()
    if start is not None:
        start_ts = start
        end_ts = end or now
    else:
        start_ts = now - timedelta(hours=last_hours)
        end_ts = now

    field_list = [f.strip() for f in fields.split(",") if f.strip() in METRIC_FIELDS]
    if not field_list:
        field_list = ["power_total"]

    # Build time-bucket aggregation SQL
    agg_parts = ", ".join(f"AVG({f}) AS {f}" for f in field_list)
    sql = text(
        f"SELECT "
        f"  to_timestamp(floor(extract(epoch from timestamp) / :bucket) * :bucket) "
        f"    AT TIME ZONE 'UTC' AS bucket, "
        f"  {agg_parts}, "
        f"  COUNT(*) AS sample_count "
        f"FROM metrics_data "
        f"WHERE device_id = :device_id "
        f"  AND timestamp >= :start AND timestamp <= :end_ts "
        f"GROUP BY bucket ORDER BY bucket ASC"
    )
    result = await session.execute(sql, {
        "device_id": device_id,
        "start": start_ts,
        "end_ts": end_ts,
        "bucket": bucket_seconds,
    })
    return [dict(row._mapping) for row in result.all()]


@router.get("/metrics/{device_id}/stats")
async def get_metrics_stats(
    device_id: int,
    session: AsyncSession = Depends(get_session),
) -> MetricsStatsOut:
    """Return statistics about stored metrics for a device."""
    stmt = select(
        func.count(MetricsData.id),
        func.min(MetricsData.timestamp),
        func.max(MetricsData.timestamp),
    ).where(MetricsData.device_id == device_id)
    result = await session.execute(stmt)
    row = result.one()
    total, oldest, newest = row[0], row[1], row[2]

    days = 0.0
    if oldest and newest:
        days = (newest - oldest).total_seconds() / 86400

    return MetricsStatsOut(
        device_id=device_id,
        total_rows=total,
        oldest=oldest,
        newest=newest,
        days_stored=round(days, 2),
    )


# ---------------------------------------------------------------------------
# ALARM ENDPOINTS
# ---------------------------------------------------------------------------
@router.get("/alarms", response_model=list[AlarmEventOut])
async def get_alarm_events(
    device_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(None),
    severity: Optional[str] = Query(None),
    last_hours: Optional[float] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> list[AlarmEventOut]:
    """Return alarm events with filtering and pagination."""
    stmt = select(AlarmEvent)
    conditions = []
    if device_id is not None:
        conditions.append(AlarmEvent.device_id == device_id)
    if is_active is not None:
        conditions.append(AlarmEvent.is_active == is_active)
    if severity is not None:
        conditions.append(AlarmEvent.severity == severity)
    if last_hours is not None:
        cutoff = datetime.utcnow() - timedelta(hours=last_hours)
        conditions.append(AlarmEvent.occurred_at >= cutoff)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(desc(AlarmEvent.occurred_at)).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/alarms/active", response_model=list[AlarmEventOut])
async def get_active_alarms(
    device_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[AlarmEventOut]:
    """Return only currently active alarms."""
    stmt = select(AlarmEvent).where(AlarmEvent.is_active == True)
    if device_id is not None:
        stmt = stmt.where(AlarmEvent.device_id == device_id)
    stmt = stmt.order_by(desc(AlarmEvent.occurred_at))
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# DISK USAGE ENDPOINT
# ---------------------------------------------------------------------------
@router.get("/disk", response_model=DiskUsageOut)
async def get_disk_usage(
    session: AsyncSession = Depends(get_session),
) -> DiskUsageOut:
    """Return current database and table disk usage statistics."""
    r1 = await session.execute(text("SELECT pg_database_size(current_database())"))
    db_bytes = r1.scalar() or 0
    db_mb = db_bytes / (1024 * 1024)

    try:
        r2 = await session.execute(text("SELECT pg_total_relation_size('metrics_data')"))
        table_mb = (r2.scalar() or 0) / (1024 * 1024)
    except Exception:
        table_mb = 0

    try:
        r3 = await session.execute(
            text("SELECT reltuples::bigint FROM pg_class WHERE relname='metrics_data'")
        )
        metrics_count = r3.scalar() or 0
    except Exception:
        metrics_count = 0

    try:
        r4 = await session.execute(
            text("SELECT reltuples::bigint FROM pg_class WHERE relname='alarm_events'")
        )
        alarms_count = r4.scalar() or 0
    except Exception:
        alarms_count = 0

    max_mb = settings.DISK_MAX_DB_SIZE_MB
    pct = (db_mb / max_mb * 100) if max_mb else 0

    return DiskUsageOut(
        db_size_mb=round(db_mb, 1),
        max_db_size_mb=max_mb,
        usage_pct=round(pct, 1),
        metrics_table_size_mb=round(table_mb, 1),
        metrics_row_count=int(metrics_count),
        alarms_row_count=int(alarms_count),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_dict(row: MetricsData) -> dict:
    """Convert ORM row to dict, excluding SQLAlchemy internals."""
    return {
        c.key: getattr(row, c.key)
        for c in row.__table__.columns
        if c.key != "id"
    }
