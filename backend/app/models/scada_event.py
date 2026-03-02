"""SCADA event journal — persistent storage of all system events.

Categories: GEN_STATUS, MODE_CHANGE, ATS_STATUS, MAINS, OPERATOR, SYSTEM.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ScadaEvent(Base):
    __tablename__ = "scada_events"

    __table_args__ = (
        Index("ix_scada_events_device_created", "device_id", "created_at"),
        Index("ix_scada_events_category", "category"),
        Index("ix_scada_events_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    category: Mapped[str] = mapped_column(String(20))       # GEN_STATUS, MODE_CHANGE, ATS_STATUS, MAINS, OPERATOR, SYSTEM
    event_code: Mapped[str] = mapped_column(String(40))     # running, standby, auto, manual, cmd_start, online, offline...
    message: Mapped[str] = mapped_column(String(300))       # Human-readable: "Генератор 1 → Работа под нагрузкой"
    old_value: Mapped[str | None] = mapped_column(String(60), default=None)
    new_value: Mapped[str | None] = mapped_column(String(60), default=None)
    details: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
