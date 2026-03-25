"""DepartmentRoleMapping — маппинг отделов Б24 → роли СКАДА.

Один маппинг на отдел (department_id UNIQUE).
Приоритет: mapping > auto_role_from_hierarchy.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DepartmentRoleMapping(Base):
    __tablename__ = "department_role_mapping"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    department_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
