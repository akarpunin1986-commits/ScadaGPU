"""Alarm Analytics — own DB table (alarm_analytics_events).

Fully isolated from the main AlarmEvent model. Own table, own indexes.
Removal of this file does NOT affect SCADA operation.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AlarmAnalyticsEvent(Base):
    __tablename__ = "alarm_analytics_events"

    __table_args__ = (
        Index("ix_aa_events_device_occurred", "device_id", "occurred_at"),
        Index("ix_aa_events_active", "is_active"),
        Index("ix_aa_events_code", "alarm_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    device_type: Mapped[str] = mapped_column(String(20))  # "HGM9560" / "HGM9520N"

    alarm_code: Mapped[str] = mapped_column(String(20))     # "M001", "G_SD_0_7"
    alarm_name: Mapped[str] = mapped_column(String(100))     # "Mains Undervoltage"
    alarm_name_ru: Mapped[str] = mapped_column(String(200))  # Russian name
    alarm_severity: Mapped[str] = mapped_column(String(20))  # shutdown/warning/trip/indication/mains_trip
    alarm_register: Mapped[int] = mapped_column()            # register number
    alarm_bit: Mapped[int] = mapped_column()                 # bit number within register

    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    cleared_at: Mapped[datetime | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=True)

    metrics_snapshot: Mapped[dict | None] = mapped_column(JSON, default=None)
    analysis_result: Mapped[dict | None] = mapped_column(JSON, default=None)
