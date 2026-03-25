"""Sanek proposed actions — control commands requiring operator confirmation."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SanekAction(Base):
    __tablename__ = "sanek_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)

    # Action definition
    action_type: Mapped[str] = mapped_column(String(50))  # set_power_limit, start_generator, stop_generator
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # {p_raw: 1000, q_raw: 0}
    reason: Mapped[str] = mapped_column(Text)  # Why Sanek proposes this

    # Status flow: proposed → confirmed → executing → completed/failed
    #              proposed → rejected
    #              proposed → expired
    status: Mapped[str] = mapped_column(String(20), default="proposed")

    # Timestamps
    proposed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Execution result
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # v3: Outcome tracking
    outcome_analysis: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Links
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("sanek_goals.id", ondelete="SET NULL"), nullable=True)
    chat_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<SanekAction #{self.id} {self.action_type} device={self.device_id} status={self.status}>"
