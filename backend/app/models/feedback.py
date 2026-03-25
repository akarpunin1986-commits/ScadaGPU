"""SANEK v2.1 Module A — Feedback Loop models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SanekFeedback(Base):
    __tablename__ = "sanek_feedback"

    __table_args__ = (
        UniqueConstraint("incident_id", name="unique_feedback_per_incident"),
        Index("idx_sanek_feedback_incident", "incident_id"),
        Index("idx_sanek_feedback_assessment", "assessment"),
        Index("idx_sanek_feedback_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("agent_incidents.id"), nullable=False
    )
    assessment: Mapped[str] = mapped_column(String(20), nullable=False)
    actual_root_cause: Mapped[str | None] = mapped_column(Text, default=None)
    operator_notes: Mapped[str | None] = mapped_column(Text, default=None)
    submitted_by: Mapped[str | None] = mapped_column(String(50), default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # v3: Extended feedback fields (added by migration)
    session_id: Mapped[str | None] = mapped_column(String(50), default=None)
    message_index: Mapped[int | None] = mapped_column(Integer, default=None)
    correct_answer: Mapped[str | None] = mapped_column(Text, default=None)
    context: Mapped[dict | None] = mapped_column(JSON, default=None)
    feedback_detail: Mapped[str | None] = mapped_column(String(50), default=None)
    # "wrong_cause" | "wrong_data" | "wrong_action" | "incomplete" | "hallucination"


class SanekPatternStats(Base):
    __tablename__ = "sanek_pattern_stats"

    pattern_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    correct_count: Mapped[int] = mapped_column(server_default="0")
    total_count: Mapped[int] = mapped_column(server_default="0")
    last_confirmed: Mapped[datetime | None] = mapped_column(default=None)
    last_incorrect: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # v3: Context for confidence scoring
    last_context: Mapped[dict | None] = mapped_column(JSON, default=None)
