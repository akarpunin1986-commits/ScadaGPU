"""SanekAgent — autonomous AI incident analysis results.

Each row = one autonomous analysis triggered by alarm/event/maintenance alert.
Status lifecycle: pending → analyzing → completed / failed.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AgentIncident(Base):
    __tablename__ = "agent_incidents"

    __table_args__ = (
        Index("ix_agent_incidents_device_id", "device_id"),
        Index("ix_agent_incidents_site_id", "site_id"),
        Index("ix_agent_incidents_created_at", "created_at"),
        Index("ix_agent_incidents_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=True
    )
    alarm_code: Mapped[str] = mapped_column(String(50))
    trigger_channel: Mapped[str] = mapped_column(String(50))
    trigger_payload: Mapped[dict | None] = mapped_column(JSONB, default=None)
    analysis: Mapped[dict | None] = mapped_column(JSONB, default=None)
    cause: Mapped[str | None] = mapped_column(Text, default=None)
    recommendation: Mapped[str | None] = mapped_column(Text, default=None)
    llm_provider: Mapped[str | None] = mapped_column(String(20), default=None)
    llm_model: Mapped[str | None] = mapped_column(String(100), default=None)
    llm_tokens_used: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    sop_actions: Mapped[dict | None] = mapped_column(JSONB, default=None)
