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
    # Sanity bounds: values outside these ranges are treated as corrupt
    # (e.g., from RS485 frame mixing in the Ethernet-RS485 converter)
    _BOUNDS = {
        # Voltages: phase 0-300V, line 0-500V
        "gen_uab": (0, 500), "gen_ubc": (0, 500), "gen_uca": (0, 500),
        "mains_uab": (0, 500), "mains_ubc": (0, 500), "mains_uca": (0, 500),
        "busbar_uab": (0, 500), "busbar_ubc": (0, 500), "busbar_uca": (0, 500),
        # Frequencies: 0-70 Hz
        "gen_freq": (0, 70), "mains_freq": (0, 70), "busbar_freq": (0, 70),
        # Currents: 0-5000 A
        "current_a": (0, 5000), "current_b": (0, 5000), "current_c": (0, 5000),
        "mains_ia": (0, 5000), "mains_ib": (0, 5000), "mains_ic": (0, 5000),
        "busbar_current": (0, 5000),
        # Power: -2000..+2000 kW / kVAr
        "power_total": (-2000, 2000),
        "power_a": (-2000, 2000), "power_b": (-2000, 2000), "power_c": (-2000, 2000),
        "reactive_total": (-2000, 2000),
        "mains_total_p": (-2000, 2000),
        "mains_p_a": (-2000, 2000), "mains_p_b": (-2000, 2000), "mains_p_c": (-2000, 2000),
        "mains_total_q": (-2000, 2000),
        "busbar_p": (-2000, 2000), "busbar_q": (-2000, 2000),
        # Engine
        "engine_speed": (0, 5000),
        "coolant_temp": (-50, 200), "oil_temp": (-50, 200),
        "oil_pressure": (0, 1000),
        "battery_volt": (0, 60),
        "fuel_level": (0, 100), "load_pct": (-50, 150),
    }

    @classmethod
    def _sanitize(cls, key: str, val) -> float | None:
        """Return val if within sane bounds, else None."""
        if val is None:
            return None
        try:
            v = float(val)
        except (TypeError, ValueError):
            return None
        bounds = cls._BOUNDS.get(key)
        if bounds and not (bounds[0] <= v <= bounds[1]):
            logger.debug("Sanitize: %s=%.1f out of bounds %s → None", key, v, bounds)
            return None
        return v

    @classmethod
    def _to_row(cls, p: dict) -> dict:
        """Convert Redis payload to MetricsData column dict with sanity checks."""
        ts = p.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                ts = datetime.now(timezone.utc)
        # Strip timezone info — DB column is TIMESTAMP WITHOUT TIME ZONE
        if ts and hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)

        san = cls._sanitize  # shorthand
        return {
            "device_id": p.get("device_id"),
            "device_type": p.get("device_type", "unknown"),
            "timestamp": ts,
            "online": p.get("online", False),
            "gen_uab": san("gen_uab", p.get("gen_uab")),
            "gen_ubc": san("gen_ubc", p.get("gen_ubc")),
            "gen_uca": san("gen_uca", p.get("gen_uca")),
            "gen_freq": san("gen_freq", p.get("gen_freq")),
            "mains_uab": san("mains_uab", p.get("mains_uab")),
            "mains_ubc": san("mains_ubc", p.get("mains_ubc")),
            "mains_uca": san("mains_uca", p.get("mains_uca")),
            "mains_freq": san("mains_freq", p.get("mains_freq")),
            "current_a": san("current_a", p.get("current_a")),
            "current_b": san("current_b", p.get("current_b")),
            "current_c": san("current_c", p.get("current_c")),
            "power_total": san("power_total", p.get("power_total")),
            "power_a": san("power_a", p.get("power_a")),
            "power_b": san("power_b", p.get("power_b")),
            "power_c": san("power_c", p.get("power_c")),
            "reactive_total": san("reactive_total", p.get("reactive_total")),
            "engine_speed": san("engine_speed", p.get("engine_speed")),
            "coolant_temp": san("coolant_temp", p.get("coolant_temp")),
            "oil_pressure": san("oil_pressure", p.get("oil_pressure")),
            "oil_temp": san("oil_temp", p.get("oil_temp")),
            "battery_volt": san("battery_volt", p.get("battery_volt")),
            "fuel_level": san("fuel_level", p.get("fuel_level")),
            "load_pct": san("load_pct", p.get("load_pct")),
            "fuel_pressure": p.get("fuel_pressure"),
            "turbo_pressure": p.get("turbo_pressure"),
            "fuel_consumption": p.get("fuel_consumption"),
            # --- Mains power (HGM9560 SPR) ---
            "mains_total_p": san("mains_total_p", p.get("mains_total_p")),
            "mains_p_a": san("mains_p_a", p.get("mains_p_a")),
            "mains_p_b": san("mains_p_b", p.get("mains_p_b")),
            "mains_p_c": san("mains_p_c", p.get("mains_p_c")),
            "mains_total_q": san("mains_total_q", p.get("mains_total_q")),
            "mains_ia": san("mains_ia", p.get("mains_ia")),
            "mains_ib": san("mains_ib", p.get("mains_ib")),
            "mains_ic": san("mains_ic", p.get("mains_ic")),
            # --- Busbar (HGM9560 SPR) ---
            "busbar_uab": san("busbar_uab", p.get("busbar_uab")),
            "busbar_ubc": san("busbar_ubc", p.get("busbar_ubc")),
            "busbar_uca": san("busbar_uca", p.get("busbar_uca")),
            "busbar_freq": san("busbar_freq", p.get("busbar_freq")),
            "busbar_current": san("busbar_current", p.get("busbar_current")),
            "busbar_p": san("busbar_p", p.get("busbar_p")),
            "busbar_q": san("busbar_q", p.get("busbar_q")),
            # --- Accumulated ---
            "run_hours": p.get("run_hours") or p.get("running_hours_a"),
            "energy_kwh": p.get("energy_kwh") or p.get("accum_kwh"),
            "gen_status": p.get("gen_status"),
        }
