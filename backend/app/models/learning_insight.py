from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, Float, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class LearningInsight(Base):
    __tablename__ = "learning_insights"
    id: Mapped[int] = mapped_column(primary_key=True)
    insight_type: Mapped[str] = mapped_column(String(50))
    # "precursor" | "correlation" | "threshold_suggestion" | "action_outcome" | "normal_range"
    source: Mapped[str] = mapped_column(String(50))
    # "correlation_engine" | "outcome_tracker" | "manual" | "feedback"
    alarm_code: Mapped[str | None] = mapped_column(String(100), default=None)
    device_type: Mapped[str | None] = mapped_column(String(50), default=None)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
