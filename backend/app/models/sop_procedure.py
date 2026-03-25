"""SOP Procedures — Standard Operating Procedures for alarm types.

Each row = one procedure linked to (alarm_code, device_type, root_cause).
The SOP Engine queries this table during incident analysis to provide
precise operator action steps instead of generic LLM recommendations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SopProcedure(Base):
    __tablename__ = "sop_procedures"

    __table_args__ = (
        Index("ix_sop_procedures_alarm_code", "alarm_code"),
        Index("ix_sop_procedures_device_type", "device_type"),
        Index("ix_sop_procedures_root_cause", "root_cause"),
        Index(
            "ix_sop_procedures_alarm_device_cause",
            "alarm_code", "device_type", "root_cause",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alarm_code: Mapped[str] = mapped_column(String(64))
    device_type: Mapped[str] = mapped_column(String(64))
    root_cause: Mapped[str | None] = mapped_column(String(128), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    actions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
