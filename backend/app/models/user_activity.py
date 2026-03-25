"""UserActivity — журнал действий пользователей.

Логирует: login, logout, modbus_command, chat_message, alarm_ack и т.д.
source: 'scada' (веб) или 'bitrix_chat' (Б24).
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ActivityType(str, enum.Enum):
    login = "login"
    logout = "logout"
    page_view = "page_view"
    modbus_command = "modbus_command"
    power_limit_change = "power_limit_change"
    chat_message = "chat_message"
    chat_message_b24 = "chat_message_b24"
    alarm_ack = "alarm_ack"
    settings_change = "settings_change"
    user_role_change = "user_role_change"
    bitrix_task_create = "bitrix_task_create"
    report_generate = "report_generate"
    bot_reset_context = "bot_reset_context"


class UserActivity(Base):
    __tablename__ = "user_activity_log"

    __table_args__ = (
        Index("ix_activity_user", "user_id", "created_at"),
        Index("ix_activity_action", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scada_users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    target_device_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("devices.id"), nullable=True
    )
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="scada")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
