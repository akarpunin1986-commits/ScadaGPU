from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base


class EquipmentUnit(Base):
    __tablename__ = "equipment_units"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(50), unique=True)
    unit_type: Mapped[str] = mapped_column(String(50))
    manufacturer: Mapped[str | None] = mapped_column(String(200), default=None)
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    total_power_kw: Mapped[float | None] = mapped_column(Float, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    purpose: Mapped[str | None] = mapped_column(Text, default=None)
    components: Mapped[dict] = mapped_column(JSON, default=dict)
    infrastructure: Mapped[dict] = mapped_column(JSON, default=dict)
    documentation: Mapped[list] = mapped_column(JSON, default=list)
    responsible_person: Mapped[str | None] = mapped_column(String(200), default=None)
    responsible_contact: Mapped[str | None] = mapped_column(String(200), default=None)
    commissioning_date: Mapped[date | None] = mapped_column(Date, default=None)
    last_overhaul_date: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # === Maintenance Lifecycle v2.0 ===
    # Источник наработки: modbus | calendar | manual | external
    hours_source: Mapped[str] = mapped_column(String(20), server_default="manual")
    # Конфигурация источника (JSONB):
    # modbus: {"device_id": 1, "register": 270, "register_type": "holding"}
    # calendar: {"hours_per_day": 16, "working_days": "mon-sat"}
    # manual: {}
    hours_source_config: Mapped[dict | None] = mapped_column(JSONB, server_default="{}")

    # Epoch — точка отсчёта цикла ТО
    epoch_value: Mapped[int] = mapped_column(Integer, server_default="0")
    epoch_date: Mapped[datetime | None] = mapped_column(nullable=True)
    epoch_reason: Mapped[str] = mapped_column(String(50), server_default="initial")

    # Текущее состояние (кеш, обновляется ValuePoller)
    current_value: Mapped[int] = mapped_column(Integer, server_default="0")
    current_value_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Ответственный за ТО (из Б24 или вручную)
    responsible_bitrix_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    responsible_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Б24 маппинг
    bitrix_equipment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_starts: Mapped[int] = mapped_column(Integer, server_default="0")

    site = relationship("Site")
    devices = relationship("Device", back_populates="equipment_unit")
