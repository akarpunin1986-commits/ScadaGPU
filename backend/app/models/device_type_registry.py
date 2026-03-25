"""Device Type Registry — dynamic device type definitions.

Stores metric names, units, thresholds, statuses, and nominal values
per device type. Allows adding new equipment types (furnaces, extruders, etc.)
without code changes.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DeviceTypeRegistry(Base):
    """Registry of device types with their metric definitions and thresholds.

    Example row:
        type_code = "generator"
        display_name = "Генератор газопоршневой"
        metrics_schema = {
            "power_total": {"unit": "кВт", "description": "Активная мощность"},
            "coolant_temp": {"unit": "°C", "description": "Температура ОЖ"},
            "engine_speed": {"unit": "об/мин", "description": "Обороты двигателя"},
            ...
        }
        thresholds = {
            "coolant_temp": {"warn": 90, "critical": 105},
            "oil_pressure": {"warn_low": 2.0, "critical_low": 1.5},
            ...
        }
        statuses = {
            "0": "Стоп", "9": "Работа", "12": "Аварийный стоп", ...
        }
        nominal_values = {
            "power": 160, "power_unit": "кВт"
        }
    """
    __tablename__ = "device_type_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    type_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    # Metric definitions: {metric_name: {unit, description, format}}
    metrics_schema: Mapped[dict] = mapped_column(JSON, default=dict)

    # Anomaly thresholds: {metric_name: {warn, critical, warn_low, critical_low}}
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)

    # Status code mapping: {"0": "Стоп", "9": "Работа", ...}
    statuses: Mapped[dict] = mapped_column(JSON, default=dict)

    # Nominal/rated values: {power: 160, power_unit: "кВт", temp: 850, ...}
    nominal_values: Mapped[dict] = mapped_column(JSON, default=dict)

    # Status field name in metrics (e.g. "gen_status" for generators)
    status_field: Mapped[str | None] = mapped_column(String(50), default=None)

    # "Running" status code (e.g. 9 for generators)
    running_status_code: Mapped[int | None] = mapped_column(default=None)

    # v3: Extended knowledge fields
    purpose: Mapped[str | None] = mapped_column(Text, default=None)
    manufacturer_info: Mapped[dict] = mapped_column(JSON, default=dict)
    operating_principles: Mapped[str | None] = mapped_column(Text, default=None)
    typical_issues: Mapped[list] = mapped_column(JSON, default=list)
    maintenance_notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<DeviceTypeRegistry {self.type_code}: {self.display_name}>"
