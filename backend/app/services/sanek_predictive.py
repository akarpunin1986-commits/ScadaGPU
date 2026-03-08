"""Predictive Analytics — linear regression on metrics trends.

Runs as a background task every SANEK_PREDICTIVE_INTERVAL seconds.
For each online generator, queries last 30 min of metrics,
fits linear trend, extrapolates to threshold breach.
Publishes alerts via Redis pub/sub → WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger("scada.sanek_predictive")

# Thresholds: metric_name → (direction, warning_threshold, shutdown_threshold, unit)
PREDICTIVE_THRESHOLDS: dict[str, tuple[str, float, float, str]] = {
    "coolant_temp": ("rising", 85.0, 95.0, "°C"),
    "oil_pressure": ("falling", 250.0, 200.0, "kPa"),
    "load_pct": ("rising", 90.0, 105.0, "%"),
    "gen_freq": ("rising", 51.5, 52.0, "Hz"),
}

# Min data points for regression
_MIN_POINTS = 10
# Min R² for trend to be considered significant
_MIN_R_SQUARED = 0.6
# Max extrapolation window (minutes)
_MAX_EXTRAPOLATION_MIN = 60


class PredictiveAnalytics:
    """Background service for predictive metric trend analysis."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        redis: Any,
        interval: int = 900,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._interval = interval
        self._running = False

    async def start(self) -> None:
        """Main loop — runs until stopped."""
        self._running = True
        logger.info("PredictiveAnalytics started (interval=%ds)", self._interval)

        while self._running:
            try:
                await self._analyze_all_devices()
            except Exception as exc:
                logger.error("PredictiveAnalytics: cycle error: %s", exc, exc_info=True)

            # Sleep in small increments for responsive shutdown
            for _ in range(self._interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

        logger.info("PredictiveAnalytics stopped")

    async def stop(self) -> None:
        self._running = False

    async def _analyze_all_devices(self) -> None:
        """Analyze trends for all online generators."""
        from models.device import Device

        async with self._session_factory() as session:
            stmt = select(Device).where(Device.device_type == "generator")
            result = await session.execute(stmt)
            devices = result.scalars().all()

        for device in devices:
            # Check if device is online via Redis
            try:
                raw = await self._redis.get(f"device:{device.id}:metrics")
                if not raw:
                    continue
                current = json.loads(raw)
                if not current.get("online", False):
                    continue
            except Exception:
                continue

            await self._analyze_device(device.id, device.site_id, current)

    async def _analyze_device(
        self,
        device_id: int,
        site_id: int | None,
        current_metrics: dict,
    ) -> None:
        """Analyze metric trends for a single device."""
        from models.metrics_data import MetricsData

        cutoff = datetime.utcnow() - timedelta(minutes=30)

        async with self._session_factory() as session:
            stmt = (
                select(MetricsData)
                .where(MetricsData.device_id == device_id)
                .where(MetricsData.timestamp >= cutoff)
                .order_by(MetricsData.timestamp)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        if len(rows) < _MIN_POINTS:
            return

        for metric_name, (direction, warn_threshold, shutdown_threshold, unit) in PREDICTIVE_THRESHOLDS.items():
            values = []
            timestamps = []

            for row in rows:
                val = getattr(row, metric_name, None)
                if val is not None:
                    values.append(float(val))
                    timestamps.append(row.timestamp.timestamp())

            if len(values) < _MIN_POINTS:
                continue

            # Linear regression
            x = np.array(timestamps)
            y = np.array(values)

            # Normalize x for numerical stability
            x_mean = x.mean()
            x_norm = x - x_mean

            try:
                coeffs = np.polyfit(x_norm, y, 1)
                slope = coeffs[0]  # units per second
            except (np.linalg.LinAlgError, ValueError):
                continue

            # R² calculation
            y_pred = np.polyval(coeffs, x_norm)
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - y.mean()) ** 2)
            r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

            if r_squared < _MIN_R_SQUARED:
                continue

            # Check direction
            if direction == "rising" and slope <= 0:
                continue
            if direction == "falling" and slope >= 0:
                continue

            # Extrapolate to threshold
            current_val = values[-1]
            threshold = warn_threshold

            if direction == "rising":
                if current_val >= threshold:
                    continue  # Already above threshold
                time_to_breach_sec = (threshold - current_val) / slope if slope > 0 else float("inf")
            else:
                if current_val <= threshold:
                    continue  # Already below threshold
                time_to_breach_sec = (current_val - threshold) / abs(slope) if slope != 0 else float("inf")

            time_to_breach_min = time_to_breach_sec / 60.0

            if time_to_breach_min > _MAX_EXTRAPOLATION_MIN or time_to_breach_min <= 0:
                continue

            # Determine severity
            severity = "warning"
            if direction == "rising" and current_val + slope * time_to_breach_sec >= shutdown_threshold:
                severity = "critical"
            elif direction == "falling" and current_val + slope * time_to_breach_sec <= shutdown_threshold:
                severity = "critical"

            predicted_value = current_val + slope * time_to_breach_sec

            message = (
                f"Прогноз: {metric_name} достигнет порога {threshold}{unit} "
                f"через ~{time_to_breach_min:.0f} мин "
                f"(текущее: {current_val:.1f}{unit}, тренд: {slope * 60:.2f}{unit}/мин, R²={r_squared:.2f})"
            )

            logger.warning(
                "PredictiveAnalytics: device=%d metric=%s → breach in %.0f min (R²=%.2f)",
                device_id, metric_name, time_to_breach_min, r_squared,
            )

            # Save to DB
            await self._save_alert(
                device_id=device_id,
                site_id=site_id,
                metric_name=metric_name,
                current_value=current_val,
                predicted_value=predicted_value,
                threshold_value=threshold,
                time_to_breach_min=time_to_breach_min,
                trend_slope=slope * 60,  # per minute
                r_squared=r_squared,
                severity=severity,
                message=message,
            )

            # Publish to Redis for WebSocket
            await self._publish_alert(device_id, metric_name, message, severity)

    async def _save_alert(self, **kwargs: Any) -> None:
        """Save predictive alert to database."""
        from models.predictive_alert import SanekPredictiveAlert

        try:
            async with self._session_factory() as session:
                alert = SanekPredictiveAlert(**kwargs)
                session.add(alert)
                await session.commit()
        except Exception as exc:
            logger.error("PredictiveAnalytics: save failed: %s", exc)

    async def _publish_alert(
        self,
        device_id: int,
        metric_name: str,
        message: str,
        severity: str,
    ) -> None:
        """Publish alert to Redis pub/sub for WebSocket delivery."""
        try:
            payload = json.dumps({
                "type": "predictive_alert",
                "device_id": device_id,
                "metric_name": metric_name,
                "message": message,
                "severity": severity,
            }, ensure_ascii=False)
            await self._redis.publish("scada:predictive", payload)
        except Exception as exc:
            logger.warning("PredictiveAnalytics: publish failed: %s", exc)
