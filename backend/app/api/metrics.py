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
                return [json.loads(raw)]
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
                    results.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    pass
        return results

    from core.websocket import get_all_metrics_from_redis
    return await get_all_metrics_from_redis(redis)


async def _get_device_ids_for_site(site_id: int, request: Request) -> list[int]:
    """Fetch device IDs belonging to a site from the database."""
    async for session in get_session():
        session: AsyncSession
        stmt = select(Device.id).where(Device.site_id == site_id)
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]
    return []
