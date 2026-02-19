"""Phase 6 — Metrics data persistent storage.

One row per device per poll cycle (~every 2 seconds).
Wide table with nullable floats for all generator + ATS metrics.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class MetricsData(Base):
    __tablename__ = "metrics_data"

    __table_args__ = (
        Index("ix_metrics_data_device_ts", "device_id", "timestamp"),
        Index("ix_metrics_data_ts", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    device_type: Mapped[str] = mapped_column(String(20))
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now())
    online: Mapped[bool] = mapped_column(default=True)

    # --- Voltage ---
    gen_uab: Mapped[float | None] = mapped_column(Float, default=None)
    gen_ubc: Mapped[float | None] = mapped_column(Float, default=None)
    gen_uca: Mapped[float | None] = mapped_column(Float, default=None)
    gen_freq: Mapped[float | None] = mapped_column(Float, default=None)
    mains_uab: Mapped[float | None] = mapped_column(Float, default=None)
    mains_ubc: Mapped[float | None] = mapped_column(Float, default=None)
    mains_uca: Mapped[float | None] = mapped_column(Float, default=None)
    mains_freq: Mapped[float | None] = mapped_column(Float, default=None)

    # --- Current ---
    current_a: Mapped[float | None] = mapped_column(Float, default=None)
    current_b: Mapped[float | None] = mapped_column(Float, default=None)
    current_c: Mapped[float | None] = mapped_column(Float, default=None)

    # --- Power ---
    power_total: Mapped[float | None] = mapped_column(Float, default=None)
    power_a: Mapped[float | None] = mapped_column(Float, default=None)
    power_b: Mapped[float | None] = mapped_column(Float, default=None)
    power_c: Mapped[float | None] = mapped_column(Float, default=None)
    reactive_total: Mapped[float | None] = mapped_column(Float, default=None)

    # --- Engine ---
    engine_speed: Mapped[float | None] = mapped_column(Float, default=None)
    coolant_temp: Mapped[float | None] = mapped_column(Float, default=None)
    oil_pressure: Mapped[float | None] = mapped_column(Float, default=None)
    oil_temp: Mapped[float | None] = mapped_column(Float, default=None)
    battery_volt: Mapped[float | None] = mapped_column(Float, default=None)
    fuel_level: Mapped[float | None] = mapped_column(Float, default=None)
    load_pct: Mapped[float | None] = mapped_column(Float, default=None)
    fuel_pressure: Mapped[float | None] = mapped_column(Float, default=None)
    turbo_pressure: Mapped[float | None] = mapped_column(Float, default=None)
    fuel_consumption: Mapped[float | None] = mapped_column(Float, default=None)

    # --- Accumulated ---
    run_hours: Mapped[float | None] = mapped_column(Float, default=None)
    energy_kwh: Mapped[float | None] = mapped_column(Float, default=None)
    gen_status: Mapped[int | None] = mapped_column(Integer, default=None)
