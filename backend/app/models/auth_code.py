"""AuthCode — одноразовые коды авторизации (Фаза 1).

Код 6 цифр, TTL 5 минут, макс 3 попытки.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AuthCode(Base):
    __tablename__ = "auth_codes"

    __table_args__ = (
        Index("ix_auth_codes_user", "user_id", "is_used", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scada_users.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
