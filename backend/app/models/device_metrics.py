"""Universal device metrics storage with JSONB.

Stores metrics for ANY device type (furnaces, extruders, etc.)
in a flexible key-value format. Existing generators continue using
the wide MetricsData table for performance; new equipment types use this.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DeviceMetrics(Base):
    """Universal metrics storage with JSONB data column.

    Example row:
        device_id = 7
        device_type = "furnace"
        data = {
            "zone1_temp": 845.2,
            "zone2_temp": 830.1,
            "zone3_temp": 812.5,
            "heater_power": 45.2,
            "exhaust_temp": 320.0,
            "status": 2
        }
    """
    __tablename__ = "device_metrics"

    __table_args__ = (
        Index("ix_device_metrics_device_ts", "device_id", "timestamp"),
        Index("ix_device_metrics_ts", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    device_type: Mapped[str] = mapped_column(String(50))
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now())
    online: Mapped[bool] = mapped_column(default=True)

    # All metrics as JSONB — flexible, indexable, queryable
    data: Mapped[dict] = mapped_column(JSONB, default=dict)

    def __repr__(self) -> str:
        return f"<DeviceMetrics device={self.device_id} ts={self.timestamp}>"
