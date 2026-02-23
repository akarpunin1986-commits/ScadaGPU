"""
Phase 2 — REST endpoint for metrics snapshot from Redis.

GET /api/metrics                → all devices
GET /api/metrics?device_id=1    → specific device
GET /api/metrics?site_id=1      → devices belonging to a site
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Device, get_session

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _enrich_metrics(data: dict) -> dict:
    """Add computed fields for AI and dashboard consumption."""
    # For ATS (ШПР): total site load = mains_total_p + busbar_p
    if data.get("device_type") == "ats":
        mains_p = data.get("mains_total_p") or 0
        busbar_p = data.get("busbar_p") or 0
        data["load_total_p"] = round(mains_p + busbar_p, 1)
        mains_q = data.get("mains_total_q") or 0
        busbar_q = data.get("busbar_q") or 0
        data["load_total_q"] = round(mains_q + busbar_q, 1)
    return data


@router.get("")
async def get_metrics(
    request: Request,
    device_id: int | None = Query(None, description="Filter by device ID"),
    site_id: int | None = Query(None, description="Filter by site ID"),
) -> list[dict]:
    """Return latest metrics snapshot from Redis."""
    redis = request.app.state.redis

    if device_id is not None:
        raw = await redis.get(f"device:{device_id}:metrics")
        if raw:
            try:
                return [_enrich_metrics(json.loads(raw))]
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    if site_id is not None:
        device_ids = await _get_device_ids_for_site(site_id, request)
        results = []
        for did in device_ids:
            raw = await redis.get(f"device:{did}:metrics")
            if raw:
                try:
                    results.append(_enrich_metrics(json.loads(raw)))
                except (json.JSONDecodeError, TypeError):
                    pass
        return results

    from core.websocket import get_all_metrics_from_redis
    raw_list = await get_all_metrics_from_redis(redis)
    return [_enrich_metrics(m) for m in raw_list]


async def _get_device_ids_for_site(site_id: int, request: Request) -> list[int]:
    """Fetch device IDs belonging to a site from the database."""
    async for session in get_session():
        session: AsyncSession
        stmt = select(Device.id).where(Device.site_id == site_id)
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]
    return []
