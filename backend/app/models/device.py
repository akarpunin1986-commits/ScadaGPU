import enum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class DeviceType(str, enum.Enum):
    GENERATOR = "generator"  # HGM9520N
    ATS = "ats"  # HGM9560 (ШПР)


class ModbusProtocol(str, enum.Enum):
    TCP = "tcp"  # HGM9520N — Modbus TCP
    RTU_OVER_TCP = "rtu_over_tcp"  # HGM9560 — Modbus RTU через конвертер


class Device(TimestampMixin, Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    device_type: Mapped[DeviceType]
    ip_address: Mapped[str] = mapped_column(String(45))
    port: Mapped[int] = mapped_column(default=502)
    slave_id: Mapped[int] = mapped_column(default=1)
    protocol: Mapped[ModbusProtocol]
    is_active: Mapped[bool] = mapped_column(default=True)
    description: Mapped[str | None] = mapped_column(String(500), default=None)

    site = relationship("Site", back_populates="devices")
    maintenance_logs = relationship(
        "MaintenanceLog",
        back_populates="device",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Device {self.name} ({self.device_type.value}) @ {self.ip_address}>"
