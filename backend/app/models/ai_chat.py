"""AI Chat Messages — persistent conversation history for Sanek assistant.

Stores chat messages grouped by session_id. Each session is one conversation.
No foreign keys — fully isolated from core SCADA models.
"""
from datetime import datetime

from sqlalchemy import Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AiChatMessage(Base):
    __tablename__ = "ai_chat_messages"

    __table_args__ = (
        Index("ix_ai_chat_session", "session_id"),
        Index("ix_ai_chat_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50))        # UUID grouping
    role: Mapped[str] = mapped_column(String(20))               # user|assistant|system|tool
    content: Mapped[str] = mapped_column(Text, default="")      # message text
    tool_calls: Mapped[str | None] = mapped_column(Text, default=None)   # JSON of tool calls
    tool_name: Mapped[str | None] = mapped_column(String(50), default=None)  # tool name if role=tool
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
