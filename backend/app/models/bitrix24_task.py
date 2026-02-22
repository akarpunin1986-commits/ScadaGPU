"""Phase 7 — Bitrix24Task: local tracking of tasks created in Bitrix24.

Used for duplicate protection and status synchronization.
Fully isolated — can be dropped without affecting core SCADA.
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Bitrix24Task(Base):
    __tablename__ = "bitrix24_tasks"

    __table_args__ = (
        Index("ix_bitrix24_tasks_source", "source_type", "source_id"),
        Index("ix_bitrix24_tasks_status", "status"),
        Index("ix_bitrix24_tasks_bitrix_id", "bitrix_task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bitrix_task_id: Mapped[int] = mapped_column()
    source_type: Mapped[str] = mapped_column(String(30))       # "maintenance" | "alarm"
    source_id: Mapped[int] = mapped_column()                    # alert_id or alarm_event_id
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True,
    )
    system_code: Mapped[str | None] = mapped_column(String(50), default=None)
    task_title: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    responsible_id: Mapped[int | None] = mapped_column(nullable=True)
    responsible_name: Mapped[str | None] = mapped_column(String(100), default=None)
    priority: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(default=None)
    bitrix_data: Mapped[str | None] = mapped_column(Text, default=None)  # JSON snapshot
