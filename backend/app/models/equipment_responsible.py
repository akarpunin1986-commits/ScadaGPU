"""EquipmentResponsible — кто за какое оборудование отвечает.

Каждая строка = один ответственный за конкретное оборудование.
equipment_code уникален — один ответственный на оборудование.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class EquipmentResponsible(Base):
    __tablename__ = "equipment_responsible"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    equipment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    site_code: Mapped[str | None] = mapped_column(String(20), nullable=True)  # mkz, yakz
    responsible_bitrix_id: Mapped[int] = mapped_column(Integer, nullable=False)
    responsible_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
