"""SANEK v4 Self-Learning — Session memory (cross-session context).

Auto-generated summaries of significant conversations.
Loaded into system prompt for cross-session awareness.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SanekSessionMemory(Base):
    __tablename__ = "sanek_session_memory"

    __table_args__ = (
        Index("idx_sess_mem_importance", "importance"),
        Index("idx_sess_mem_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    session_id: Mapped[str] = mapped_column(String(64), unique=True)
    summary: Mapped[str] = mapped_column(Text)
    key_facts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
