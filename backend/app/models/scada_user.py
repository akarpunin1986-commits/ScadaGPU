"""ScadaUser — пользователь СКАДЫ с привязкой к Битрикс24.

RBAC: admin / operator / viewer.
Иерархия из Б24 (hierarchy_level 1-5, user_weight 0.0-1.0).
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class ScadaUser(Base):
    __tablename__ = "scada_users"

    __table_args__ = (
        Index("ix_scada_users_bitrix_id", "bitrix_id", unique=True),
        Index("ix_scada_users_email", "email", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bitrix_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.viewer.value, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_department_head: Mapped[bool] = mapped_column(Boolean, default=False)
    manager_bitrix_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hierarchy_level: Mapped[int] = mapped_column(Integer, default=5)
    user_weight: Mapped[float] = mapped_column(Float, default=0.3)

    # OAuth tokens (Фаза 2)
    bitrix_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    bitrix_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    bitrix_token_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    last_login: Mapped[datetime | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
