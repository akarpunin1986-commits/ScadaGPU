"""
Универсальный Data API — один endpoint для ВСЕХ данных ScadaGPU.

POST /api/data/query   — запрос данных по схеме
GET  /api/data/schema  — получить схему для LLM

Версия: 1.0  |  Март 2026
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.data_schema import (
    AGG_SQL,
    DATA_SCHEMA,
    GROUP_BY_SECONDS,
    get_schema_summary,
)
from models import Device
from models.base import get_session

logger = logging.getLogger("data_api")

router = APIRouter(prefix="/api/data", tags=["data"])

# ─────────────────────────────────────────────
# Request / Response models
# ─────────────────────────────────────────────


class DataQuery(BaseModel):
    entity: str = Field(..., description="Сущность: sites/devices/metrics/metrics_history/alarms/events/incidents/memory/maintenance_logs/gas_prices")
    filters: dict[str, Any] = Field(default_factory=dict, description="Фильтры: {'device_id': 1, 'severity': 'critical'}")
    fields: list[str] | None = Field(None, description="Какие поля вернуть (по умолчанию — все)")
    period: str | None = Field(None, description="Период: today/yesterday/last_1h/last_24h/last_7d/last_30d/this_week/this_month/all_time или дата '2026-03-10' или диапазон '2026-03-01:2026-03-10'")
    aggregation: str | None = Field(None, description="Агрегация: avg/min/max/sum/count")
    group_by: str | None = Field(None, description="Группировка: 5min/10min/30min/hour/day/week")
    limit: int = Field(200, ge=1, le=5000, description="Макс. записей (default 200)")
    order_by: str | None = Field(None, description="Поле сортировки")
    order_desc: bool = Field(True, description="По убыванию (default True)")
    include_relations: bool = Field(False, description="True = подтянуть имена устройств/объектов автоматически")


class DataResponse(BaseModel):
    entity: str
    count: int
    period: str | None = None
    filters: dict[str, Any] = {}
    group_by: str | None = None
    aggregation: str | None = None
    data: list[dict[str, Any]]


# ─────────────────────────────────────────────
# Safe identifier regex (SQL injection prevention)
# ─────────────────────────────────────────────
_SAFE_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _resolve_period(period: str) -> tuple[datetime | None, datetime | None]:
    """Convert string period → (start, end) as naive UTC datetimes.

    The DB stores naive UTC timestamps (via datetime.utcnow()), so we must
    return naive UTC datetimes for comparison.
    Periods like "today" / "yesterday" are interpreted in MSK (UTC+3).
    """
    now_utc = datetime.utcnow()
    now_msk = now_utc + timedelta(hours=3)  # MSK = UTC+3

    _map = {
        "today":      (now_msk.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3), now_utc),
        "yesterday":  (
            (now_msk - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3),
            now_msk.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3),
        ),
        "last_1h":    (now_utc - timedelta(hours=1), now_utc),
        "last_6h":    (now_utc - timedelta(hours=6), now_utc),
        "last_24h":   (now_utc - timedelta(hours=24), now_utc),
        "last_7d":    (now_utc - timedelta(days=7), now_utc),
        "last_30d":   (now_utc - timedelta(days=30), now_utc),
        "this_week":  (
            (now_msk - timedelta(days=now_msk.weekday())).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3),
            now_utc,
        ),
        "this_month": (
            now_msk.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3),
            now_utc,
        ),
        "all_time":   (None, now_utc),
    }

    if period in _map:
        return _map[period]

    # Single date: "2026-03-10" (interpreted as MSK → convert to UTC)
    if len(period) == 10 and period[4] == "-":
        try:
            day_start_msk = datetime.fromisoformat(period)
            day_start_utc = day_start_msk - timedelta(hours=3)
            return day_start_utc, day_start_utc + timedelta(days=1)
        except ValueError:
            return None, None

    # Range: "2026-03-01:2026-03-10" (MSK → UTC)
    if ":" in period and len(period) > 10:
        parts = period.split(":", 1)
        try:
            s = datetime.fromisoformat(parts[0]) - timedelta(hours=3)
            e = datetime.fromisoformat(parts[1]) - timedelta(hours=3) + timedelta(days=1)
            return s, e
        except ValueError:
            return None, None

    return None, None


# ─────────────────────────────────────────────
# Main endpoint
# ─────────────────────────────────────────────


@router.post("/query", response_model=DataResponse)
async def query_data(
    query: DataQuery,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DataResponse:
    """
    Универсальный запрос данных ScadaGPU.
    Санёк вызывает этот endpoint через инструмент query_data.
    """
    schema = DATA_SCHEMA.get(query.entity)
    if not schema:
        return DataResponse(
            entity=query.entity,
            count=0,
            data=[{"error": f"Неизвестная сущность: {query.entity}", "available": list(DATA_SCHEMA.keys())}],
        )

    # Redis source (live metrics)
    if schema.get("source") == "redis":
        data = await _query_redis(query, request)
        return DataResponse(entity=query.entity, count=len(data), filters=query.filters, data=data)

    # Time-series aggregated query (metrics_history with group_by)
    if query.entity == "metrics_history" and query.group_by:
        data = await _query_timeseries(query, schema, session)
        return DataResponse(
            entity=query.entity,
            count=len(data),
            period=query.period,
            filters=query.filters,
            group_by=query.group_by,
            aggregation=query.aggregation,
            data=data,
        )

    # Standard SQL query
    data = await _query_sql(query, schema, session)

    # Подтянуть связанные данные (device_name, site_name)
    if query.include_relations and schema.get("relations") and data:
        data = await _enrich_with_relations(data, schema["relations"], session)

    return DataResponse(
        entity=query.entity,
        count=len(data),
        period=query.period,
        filters=query.filters,
        aggregation=query.aggregation,
        group_by=query.group_by,
        data=data,
    )


# ─────────────────────────────────────────────
# Redis handler (live metrics)
# ─────────────────────────────────────────────


async def _query_redis(query: DataQuery, request: Request) -> list[dict]:
    redis = request.app.state.redis
    device_ids: list[int] = []

    if "device_id" in query.filters:
        device_ids = [int(query.filters["device_id"])]
    elif "site_id" in query.filters:
        device_ids = await _get_device_ids_for_site(int(query.filters["site_id"]))
    else:
        # All devices
        from core.websocket import get_all_metrics_from_redis
        return await get_all_metrics_from_redis(redis)

    results = []
    for did in device_ids:
        raw = await redis.get(f"device:{did}:metrics")
        if raw:
            try:
                data = json.loads(raw)
                data["device_id"] = did
                # Filter fields if requested
                if query.fields:
                    data = {k: v for k, v in data.items() if k in query.fields or k == "device_id"}
                results.append(data)
            except (json.JSONDecodeError, TypeError):
                pass
    return results


# ─────────────────────────────────────────────
# Time-series aggregation (metrics_history)
# ─────────────────────────────────────────────


async def _query_timeseries(
    query: DataQuery,
    schema: dict,
    session: AsyncSession,
) -> list[dict]:
    """Time-bucketed aggregation via PostgreSQL — same pattern as /downsampled."""
    bucket_seconds = GROUP_BY_SECONDS.get(query.group_by, 3600)
    agg_mode = (query.aggregation or "avg").lower()
    sql_func = AGG_SQL.get(agg_mode, "AVG")

    # Determine fields to aggregate
    if query.fields:
        agg_fields = [f for f in query.fields if _SAFE_IDENT.match(f) and f in schema["fields"]]
    else:
        # Default useful fields
        agg_fields = ["power_total", "coolant_temp", "oil_temp", "oil_pressure",
                       "gen_freq", "fuel_consumption", "load_pct", "mains_total_p"]

    if not agg_fields:
        agg_fields = ["power_total"]

    # Build aggregation parts
    if agg_mode == "count":
        agg_parts = "COUNT(*) AS record_count"
    else:
        agg_parts = ", ".join(f"{sql_func}({f}) AS {f}" for f in agg_fields)
        agg_parts += ", COUNT(*) AS sample_count"

    # WHERE
    where_parts = []
    params: dict[str, Any] = {"bucket": bucket_seconds}

    if "device_id" in query.filters:
        where_parts.append("device_id = :device_id")
        params["device_id"] = int(query.filters["device_id"])
    elif "site_id" in query.filters:
        dev_ids = await _get_device_ids_for_site(int(query.filters["site_id"]))
        if dev_ids:
            where_parts.append(f"device_id = ANY(:device_ids)")
            params["device_ids"] = dev_ids

    # Period
    if query.period and schema.get("period"):
        start, end = _resolve_period(query.period)
        if start:
            where_parts.append("timestamp >= :period_start")
            params["period_start"] = start
        if end:
            where_parts.append("timestamp <= :period_end")
            params["period_end"] = end
    else:
        # Default: last 24h (naive UTC)
        params["period_start"] = datetime.utcnow() - timedelta(hours=24)
        params["period_end"] = datetime.utcnow()
        where_parts.append("timestamp >= :period_start")
        where_parts.append("timestamp <= :period_end")

    where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    # Add device_id to SELECT if querying multiple devices
    device_id_select = ""
    device_id_group = ""
    if "site_id" in query.filters and "device_id" not in query.filters:
        device_id_select = "device_id, "
        device_id_group = ", device_id"

    sql = text(
        f"SELECT "
        f"  {device_id_select}"
        f"  to_timestamp(floor(extract(epoch from timestamp) / :bucket) * :bucket) "
        f"    AT TIME ZONE 'UTC' AS bucket, "
        f"  {agg_parts} "
        f"FROM metrics_data "
        f"{where_clause} "
        f"GROUP BY bucket{device_id_group} ORDER BY bucket ASC "
        f"LIMIT :limit"
    )
    params["limit"] = query.limit

    result = await session.execute(sql, params)
    rows = [dict(row._mapping) for row in result.all()]

    # Round floats for readability
    for row in rows:
        for k, v in row.items():
            if isinstance(v, float):
                row[k] = round(v, 2)

    return rows


# ─────────────────────────────────────────────
# Standard SQL query (alarms, events, etc.)
# ─────────────────────────────────────────────


async def _query_sql(
    query: DataQuery,
    schema: dict,
    session: AsyncSession,
) -> list[dict]:
    """Build and execute a safe SQL query from schema + filters."""
    table = schema["table"]
    ts_col = schema.get("ts_col")

    # SELECT fields
    if query.fields:
        safe_fields = []
        for f in query.fields:
            field_def = schema["fields"].get(f)
            if field_def and _SAFE_IDENT.match(field_def.get("col", f)):
                safe_fields.append(field_def["col"])
        select_clause = ", ".join(safe_fields) if safe_fields else "*"
    else:
        select_clause = "*"

    # WHERE
    where_parts = []
    params: dict[str, Any] = {}
    allowed_filters = set(schema.get("filters", []))

    for key, value in query.filters.items():
        if key not in allowed_filters:
            continue
        field_def = schema["fields"].get(key)
        if not field_def:
            continue
        col = field_def.get("col", key)
        if not _SAFE_IDENT.match(col):
            continue

        # Handle site_id filter by resolving to device_ids (for tables with device_id)
        if key == "site_id" and "site_id" not in [fd.get("col") for fd in schema["fields"].values()]:
            dev_ids = await _get_device_ids_for_site(int(value))
            if dev_ids and "device_id" in [fd.get("col") for fd in schema["fields"].values()]:
                where_parts.append("device_id = ANY(:site_device_ids)")
                params["site_device_ids"] = dev_ids
            continue

        param_name = f"f_{key}"
        where_parts.append(f"{col} = :{param_name}")
        params[param_name] = value

    # Period filter
    if query.period and ts_col and schema.get("period"):
        start, end = _resolve_period(query.period)
        if start:
            where_parts.append(f"{ts_col} >= :period_start")
            params["period_start"] = start
        if end:
            where_parts.append(f"{ts_col} <= :period_end")
            params["period_end"] = end

    where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    # Aggregation with group_by (non-timeseries: count alarms by day, etc.)
    if query.aggregation and query.group_by and ts_col:
        return await _query_sql_grouped(query, schema, table, ts_col, where_clause, params, session)

    # ORDER BY
    order_col = query.order_by or schema.get("order_default", "id")
    if not _SAFE_IDENT.match(order_col):
        order_col = schema.get("order_default", "id")
    order_dir = "DESC" if query.order_desc else "ASC"

    sql = text(f"SELECT {select_clause} FROM {table} {where_clause} ORDER BY {order_col} {order_dir} LIMIT :limit")
    params["limit"] = query.limit

    result = await session.execute(sql, params)
    rows = [dict(row._mapping) for row in result.all()]

    # Serialize datetimes
    for row in rows:
        for k, v in row.items():
            if isinstance(v, datetime):
                row[k] = v.isoformat()

    return rows


async def _query_sql_grouped(
    query: DataQuery,
    schema: dict,
    table: str,
    ts_col: str,
    where_clause: str,
    params: dict,
    session: AsyncSession,
) -> list[dict]:
    """GROUP BY time bucket for non-timeseries tables (alarms, events)."""
    bucket_seconds = GROUP_BY_SECONDS.get(query.group_by, 86400)
    agg_mode = (query.aggregation or "count").lower()

    if agg_mode == "count":
        agg_part = "COUNT(*) AS count"
    else:
        # For non-numeric tables, count is the only sensible aggregation
        agg_part = "COUNT(*) AS count"

    sql = text(
        f"SELECT "
        f"  to_timestamp(floor(extract(epoch from {ts_col}) / :bucket) * :bucket) "
        f"    AT TIME ZONE 'UTC' AS bucket, "
        f"  {agg_part} "
        f"FROM {table} "
        f"{where_clause} "
        f"GROUP BY bucket ORDER BY bucket ASC "
        f"LIMIT :limit"
    )
    params["bucket"] = bucket_seconds
    params["limit"] = query.limit

    result = await session.execute(sql, params)
    rows = [dict(row._mapping) for row in result.all()]

    for row in rows:
        for k, v in row.items():
            if isinstance(v, datetime):
                row[k] = v.isoformat()

    return rows


# ─────────────────────────────────────────────
# Schema endpoint (for LLM introspection)
# ─────────────────────────────────────────────


@router.get("/schema")
async def get_data_schema():
    """Возвращает схему всех доступных данных — для LLM."""
    return get_schema_summary()


# ─────────────────────────────────────────────
# Relations enrichment (include_relations=True)
# ─────────────────────────────────────────────


async def _enrich_with_relations(
    rows: list[dict],
    relations: dict,
    session: AsyncSession,
) -> list[dict]:
    """Подтягивает связанные данные (device_name, site_name и т.п.).

    Делает один батч-запрос на каждую связь — не N+1.
    """
    for fk_field, relation in relations.items():
        # Собрать все уникальные ID
        ids = list({row[fk_field] for row in rows if row.get(fk_field)})
        if not ids:
            continue

        # Найти таблицу связанной сущности
        related_schema = DATA_SCHEMA.get(relation["entity"], {})
        table = related_schema.get("table", relation["entity"])
        fields = [f for f in relation["include_fields"] if _SAFE_IDENT.match(f)]
        if not fields:
            continue

        fields_sql = ", ".join(fields)

        # Один запрос для всех ID
        placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
        params = {f"id_{i}": id_ for i, id_ in enumerate(ids)}

        sql = text(f"SELECT id, {fields_sql} FROM {table} WHERE id IN ({placeholders})")
        result = await session.execute(sql, params)
        related_map = {row._mapping["id"]: dict(row._mapping) for row in result.all()}

        # Обогатить каждую строку
        rename_map = relation.get("rename", {})
        for row in rows:
            fk_value = row.get(fk_field)
            if fk_value and fk_value in related_map:
                related = related_map[fk_value]
                for field in fields:
                    target_name = rename_map.get(field, f"{relation['entity']}_{field}")
                    # Не перезаписывать если поле уже есть
                    if target_name not in row:
                        row[target_name] = related.get(field)

    return rows


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


async def _get_device_ids_for_site(site_id: int) -> list[int]:
    """Get device IDs for a site from database."""
    async for session in get_session():
        stmt = select(Device.id).where(Device.site_id == site_id)
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]
    return []
