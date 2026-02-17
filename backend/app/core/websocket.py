"""
Phase 2 — WebSocket endpoint + Redis PubSub bridge.

WS /ws/metrics  — push realtime metrics to frontend
redis_to_ws_bridge — background task: Redis PubSub → ConnectionManager.broadcast
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

logger = logging.getLogger("scada.websocket")

router = APIRouter()


# ---------------------------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)
        logger.info("WS client connected (%d total)", len(self.connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)
        logger.info("WS client disconnected (%d remaining)", len(self.connections))

    async def broadcast(self, message: str) -> None:
        dead: list[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.connections:
                self.connections.remove(ws)
        if dead:
            logger.debug("Removed %d dead WS connections", len(dead))


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Helper: get all device metrics from Redis
# ---------------------------------------------------------------------------

async def get_all_metrics_from_redis(redis: Redis) -> list[dict]:
    """Scan Redis for all device:*:metrics keys and return parsed list."""
    metrics: list[dict] = []
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match="device:*:metrics", count=100)
        for key in keys:
            raw = await redis.get(key)
            if raw:
                try:
                    metrics.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    pass
        if cursor == 0:
            break
    return metrics


# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        redis: Redis = websocket.app.state.redis
        snapshot = await get_all_metrics_from_redis(redis)
        await websocket.send_json({"type": "snapshot", "data": snapshot})

        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:
        logger.debug("WS error: %s", exc)
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Redis → WebSocket Bridge (background task)
# ---------------------------------------------------------------------------

async def redis_to_ws_bridge(redis: Redis) -> None:
    """Subscribe to Redis PubSub 'metrics:updates' and broadcast to all WS clients."""
    logger.info("Redis→WS bridge started, subscribing to metrics:updates")
    pubsub = redis.pubsub()
    await pubsub.subscribe("metrics:updates")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                payload = message["data"]
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                await manager.broadcast(payload)
    except Exception as exc:
        logger.error("Redis→WS bridge error: %s", exc)
    finally:
        await pubsub.unsubscribe("metrics:updates")
        await pubsub.close()
