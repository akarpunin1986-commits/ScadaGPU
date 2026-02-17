"""Phase 3 — Maintenance (ТО) models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


# ---------------------------------------------------------------------------
# MaintenanceTemplate — регламент ТО (например, "Стандартный регламент")
# ---------------------------------------------------------------------------

class MaintenanceTemplate(TimestampMixin, Base):
    __tablename__ = "maintenance_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500), default=None)
    is_default: Mapped[bool] = mapped_column(default=False)

    # Relationships
    intervals: Mapped[list[MaintenanceInterval]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="MaintenanceInterval.sort_order",
    )

    def __repr__(self) -> str:
        return f"<MaintenanceTemplate {self.name}>"


# ---------------------------------------------------------------------------
# MaintenanceInterval — интервал внутри регламента (ТО-1 250ч, ТО-2 500ч ...)
# ---------------------------------------------------------------------------

class MaintenanceInterval(Base):
    __tablename__ = "maintenance_intervals"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_templates.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(50))        # "ТО-1"
    code: Mapped[str] = mapped_column(String(20))         # "to1"
    hours: Mapped[int] = mapped_column()                  # 250
    sort_order: Mapped[int] = mapped_column(default=0)

    # Relationships
    template: Mapped[MaintenanceTemplate] = relationship(back_populates="intervals")
    tasks: Mapped[list[MaintenanceTask]] = relationship(
        back_populates="interval",
        cascade="all, delete-orphan",
        order_by="MaintenanceTask.sort_order",
    )
    logs: Mapped[list[MaintenanceLog]] = relationship(back_populates="interval")

    def __repr__(self) -> str:
        return f"<MaintenanceInterval {self.name} ({self.hours}h)>"


# ---------------------------------------------------------------------------
# MaintenanceTask — задача внутри интервала (чеклист-пункт)
# ---------------------------------------------------------------------------

class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    interval_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_intervals.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(String(500))
    is_critical: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(default=0)

    # Relationships
    interval: Mapped[MaintenanceInterval] = relationship(back_populates="tasks")

    def __repr__(self) -> str:
        return f"<MaintenanceTask {'[!]' if self.is_critical else ''}{self.text[:40]}>"


# ---------------------------------------------------------------------------
# MaintenanceLog — запись о выполненном ТО (привязка к device + interval)
# ---------------------------------------------------------------------------

class MaintenanceLog(Base):
    __tablename__ = "maintenance_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    interval_id: Mapped[int | None] = mapped_column(
        ForeignKey("maintenance_intervals.id", ondelete="SET NULL"),
        nullable=True,
    )
    performed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    engine_hours: Mapped[float] = mapped_column()           # Моточасы на момент ТО
    completed_count: Mapped[int] = mapped_column()           # Сколько задач выполнено
    total_count: Mapped[int] = mapped_column()               # Всего задач в интервале
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    performed_by: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    device = relationship("Device", back_populates="maintenance_logs")
    interval: Mapped[MaintenanceInterval | None] = relationship(back_populates="logs")
    items: Mapped[list[MaintenanceLogItem]] = relationship(
        back_populates="log",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<MaintenanceLog device={self.device_id} hours={self.engine_hours}>"


# ---------------------------------------------------------------------------
# MaintenanceLogItem — конкретная задача в рамках выполненного ТО
# ---------------------------------------------------------------------------

class MaintenanceLogItem(Base):
    __tablename__ = "maintenance_log_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    log_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_logs.id", ondelete="CASCADE")
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("maintenance_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_text: Mapped[str] = mapped_column(String(500))     # Снапшот текста задачи
    is_completed: Mapped[bool] = mapped_column(default=False)
    is_critical: Mapped[bool] = mapped_column(default=False) # Снапшот критичности

    # Relationships
    log: Mapped[MaintenanceLog] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<MaintenanceLogItem {'✓' if self.is_completed else '✗'} {self.task_text[:30]}>"
