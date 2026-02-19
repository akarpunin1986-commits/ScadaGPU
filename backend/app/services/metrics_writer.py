"""Phase 6 — MetricsWriter: batched async persistence of metrics to PostgreSQL.

Subscribes to Redis PubSub 'metrics:updates' (same channel as WebSocket bridge).
Batches payloads and bulk-inserts to metrics_data table.
Fully decoupled from poller — never blocks or slows the 2s poll cycle.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("scada.metrics_writer")


class MetricsWriter:

    def __init__(
        self,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        batch_size: int = 50,
        flush_interval: float = 5.0,
    ):
        self.redis = redis
        self.session_factory = session_factory
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._running = False
        self._buffer: list[dict] = []
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._running = True
        logger.info(
            "MetricsWriter started (batch=%d, flush=%.1fs)",
            self.batch_size, self.flush_interval,
        )
        await asyncio.gather(
            self._subscribe(),
            self._periodic_flush(),
        )

    async def stop(self) -> None:
        self._running = False
        async with self._lock:
            await self._flush()
        logger.info("MetricsWriter stopped")

    # ------------------------------------------------------------------
    async def _subscribe(self) -> None:
        while self._running:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe("metrics:updates")
                async for msg in pubsub.listen():
                    if not self._running:
                        break
                    if msg["type"] != "message":
                        continue
                    raw = msg["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    async with self._lock:
                        self._buffer.append(data)
                        if len(self._buffer) >= self.batch_size:
                            await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("MetricsWriter subscribe error: %s, retry in 2s", exc)
                await asyncio.sleep(2)
            finally:
                try:
                    await pubsub.unsubscribe("metrics:updates")
                    await pubsub.close()
                except Exception:
                    pass

    async def _periodic_flush(self) -> None:
        while self._running:
            await asyncio.sleep(self.flush_interval)
            async with self._lock:
                if self._buffer:
                    await self._flush()

    async def _flush(self) -> None:
        if not self._buffer:
            return
        batch = self._buffer.copy()
        self._buffer.clear()

        rows = [self._to_row(p) for p in batch]
        try:
            from models.metrics_data import MetricsData
            async with self.session_factory() as session:
                await session.execute(insert(MetricsData), rows)
                await session.commit()
            logger.debug("MetricsWriter flushed %d rows", len(rows))
        except Exception as exc:
            logger.error("MetricsWriter flush error (%d rows): %s", len(rows), exc)

    # ------------------------------------------------------------------
    @staticmethod
    def _to_row(p: dict) -> dict:
        """Convert Redis payload to MetricsData column dict."""
        ts = p.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                ts = datetime.utcnow()
        # Strip timezone info — DB column is TIMESTAMP WITHOUT TIME ZONE
        if ts and hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        return {
            "device_id": p.get("device_id"),
            "device_type": p.get("device_type", "unknown"),
            "timestamp": ts,
            "online": p.get("online", False),
            "gen_uab": p.get("gen_uab"),
            "gen_ubc": p.get("gen_ubc"),
            "gen_uca": p.get("gen_uca"),
            "gen_freq": p.get("gen_freq"),
            "mains_uab": p.get("mains_uab"),
            "mains_ubc": p.get("mains_ubc"),
            "mains_uca": p.get("mains_uca"),
            "mains_freq": p.get("mains_freq"),
            "current_a": p.get("current_a"),
            "current_b": p.get("current_b"),
            "current_c": p.get("current_c"),
            "power_total": p.get("power_total"),
            "power_a": p.get("power_a"),
            "power_b": p.get("power_b"),
            "power_c": p.get("power_c"),
            "reactive_total": p.get("reactive_total"),
            "engine_speed": p.get("engine_speed"),
            "coolant_temp": p.get("coolant_temp"),
            "oil_pressure": p.get("oil_pressure"),
            "oil_temp": p.get("oil_temp"),
            "battery_volt": p.get("battery_volt") or p.get("battery_v"),
            "fuel_level": p.get("fuel_level"),
            "load_pct": p.get("load_pct"),
            "fuel_pressure": p.get("fuel_pressure"),
            "turbo_pressure": p.get("turbo_pressure"),
            "fuel_consumption": p.get("fuel_consumption"),
            "run_hours": p.get("run_hours"),
            "energy_kwh": p.get("energy_kwh"),
            "gen_status": p.get("gen_status"),
        }
