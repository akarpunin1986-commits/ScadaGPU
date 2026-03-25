"""SANEK v4 Self-Learning — SOP entries from experience.

Each row = one solved incident. Created from dialog when operator confirms resolution.
Searched via search_knowledge tool alongside documentation.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SanekSopEntry(Base):
    __tablename__ = "sanek_sop_entries"

    __table_args__ = (
        Index("idx_sop_entry_incident", "incident_type"),
        Index("idx_sop_entry_device", "device_id"),
        Index("idx_sop_entry_alarm", "alarm_code"),
        Index("idx_sop_entry_confidence", "confidence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # What happened
    incident_type: Mapped[str] = mapped_column(String(64))
    # 'alarm', 'power_drop', 'efficiency_drop', 'maintenance', 'startup_issue', 'communication_issue', 'other'
    device_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    site_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    alarm_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Symptoms (what Sanek observed)
    symptoms: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Diagnosis + resolution
    diagnosis: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str] = mapped_column(Text)

    # Metadata
    resolution_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Learning metrics
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    times_referenced: Mapped[int] = mapped_column(Integer, default=0)
    last_referenced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="dialog")
    # 'dialog', 'manual', 'auto_extract'
