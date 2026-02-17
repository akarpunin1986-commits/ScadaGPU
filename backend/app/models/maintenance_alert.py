"""Maintenance alert model — persistent storage for TO warnings."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class AlertSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"
    overdue = "overdue"


class AlertStatus(str, enum.Enum):
    active = "active"
    acknowledged = "acknowledged"
    resolved = "resolved"


class MaintenanceAlert(Base):
    __tablename__ = "maintenance_alerts"

    __table_args__ = (
        UniqueConstraint(
            "device_id", "interval_id", "status",
            name="uq_maintenance_alerts_device_interval_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    interval_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_intervals.id", ondelete="CASCADE")
    )

    severity: Mapped[AlertSeverity]
    status: Mapped[AlertStatus] = mapped_column(default=AlertStatus.active)

    engine_hours: Mapped[float] = mapped_column()
    hours_remaining: Mapped[float] = mapped_column()
    interval_name: Mapped[str] = mapped_column(String(50))
    interval_hours: Mapped[int] = mapped_column()
    device_name: Mapped[str] = mapped_column(String(100))
    site_code: Mapped[str] = mapped_column(String(50), default="")

    message: Mapped[str] = mapped_column(String(500))
    acknowledged_by: Mapped[str | None] = mapped_column(String(100), default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    device = relationship("Device")
    interval = relationship("MaintenanceInterval")

    def __repr__(self) -> str:
        return f"<MaintenanceAlert {self.severity.value} device={self.device_id} {self.interval_name}>"
