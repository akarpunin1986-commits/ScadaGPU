"""Alarm Reference — structured knowledge about known alarm codes.

Maps (controller, alarm_code) to typical causes, operator actions,
related alarms, and possible cascading effects.
Used by SanekAgent to provide structured context for LLM analysis.
"""
from __future__ import annotations

from datetime import datetime

from typing import Optional

from sqlalchemy import ARRAY, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SanekAlarmReference(Base):
    __tablename__ = "sanek_alarm_reference"

    __table_args__ = (
        Index("ix_sanek_alarm_ref_controller", "controller"),
        Index("ix_sanek_alarm_ref_code", "alarm_code"),
        Index(
            "ix_sanek_alarm_ref_ctrl_code",
            "controller", "alarm_code",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    controller: Mapped[str] = mapped_column(String(50))
    alarm_code: Mapped[str] = mapped_column(String(50))
    alarm_name_ru: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))
    typical_causes: Mapped[dict] = mapped_column(JSONB, default=list)
    immediate_actions: Mapped[dict] = mapped_column(JSONB, default=list)
    related_alarms: Mapped[list] = mapped_column(ARRAY(Text), default=list)
    possible_cascade: Mapped[list] = mapped_column(ARRAY(Text), default=list)
    manual_reference: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(20), server_default="confirmed")
    source: Mapped[str] = mapped_column(String(50), server_default="manual_seed")
    extracted_from: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
