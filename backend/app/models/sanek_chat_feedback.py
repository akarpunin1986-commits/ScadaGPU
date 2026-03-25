"""SANEK v4 Self-Learning — Chat feedback (thumbs up/down).

Per-message feedback from operators. Updates SOP confidence.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SanekChatFeedback(Base):
    __tablename__ = "sanek_chat_feedback"

    __table_args__ = (
        Index("idx_chat_fb_session", "session_id"),
        Index("idx_chat_fb_rating", "rating"),
        Index("idx_chat_fb_processed", "processed"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    session_id: Mapped[str] = mapped_column(String(64))
    message_index: Mapped[int] = mapped_column(Integer)
    rating: Mapped[str] = mapped_column(String(4))  # 'up' or 'down'
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Context
    user_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    sanek_answer_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_used: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sop_referenced: Mapped[list | None] = mapped_column(ARRAY(Integer), nullable=True)

    # Processing
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)
