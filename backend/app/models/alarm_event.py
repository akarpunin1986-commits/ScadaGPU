"""Phase 6 — Alarm events persistent storage.

Each row = one alarm occurrence.
is_active=True on appear, cleared_at + is_active=False on clear.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AlarmSeverityEvent(str, enum.Enum):
    error = "error"
    warning = "warning"
    mains = "mains"


class AlarmEvent(Base):
    __tablename__ = "alarm_events"

    __table_args__ = (
        Index("ix_alarm_events_device_occurred", "device_id", "occurred_at"),
        Index("ix_alarm_events_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    alarm_code: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(String(200))
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    cleared_at: Mapped[datetime | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
