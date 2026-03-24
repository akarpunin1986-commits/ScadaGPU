"""Sanek memory — persistent memory entries for self-learning."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SanekMemory(Base):
    __tablename__ = "sanek_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="fact")  # fact, instruction, correction
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)  # feedback, outcome_tracker, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<SanekMemory #{self.id} [{self.category}]>"
