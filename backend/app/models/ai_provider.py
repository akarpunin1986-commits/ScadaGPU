"""AI Provider Config — persistent storage of LLM provider API keys and settings.

Stores up to 4 rows (one per provider: openai, claude, gemini, grok).
Keys are stored as plain text — DB is protected by Docker network + password.
Foundation for multi-provider AI and future "Sanek" assistant.
"""
from datetime import datetime

from sqlalchemy import String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AiProviderConfig(Base):
    __tablename__ = "ai_provider_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), unique=True)  # openai|claude|gemini|grok
    api_key: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    is_active: Mapped[bool] = mapped_column(default=False)
    is_configured: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
