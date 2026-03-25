"""ScadaRule — автоматические правила СКАДА.

Правило = КОГДА (триггер) → ЧТО ДЕЛАТЬ (действие) + КТО (исполнитель) + КОНТРОЛЬ (Санёк).

Типы триггеров:
- alarm: любой аларм / конкретный alarm_code / severity >= HIGH
- metric_threshold: параметр выше/ниже порога (oil_pressure < 3.0)
- schedule: по расписанию (каждые N часов/дней)
- hours_threshold: моточасы достигли порога
- manual: ручной запуск через UI или Санька

Типы действий:
- create_task: создать задачу в Б24
- notify: уведомить через чат (без задачи)
- create_task_and_notify: задача + уведомление
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ScadaRule(Base):
    __tablename__ = "scada_rules"

    __table_args__ = (
        Index("ix_rules_active", "is_active"),
        Index("ix_rules_trigger", "trigger_type"),
        Index("ix_rules_site", "site_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Мета
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), default="user")  # user:{id}, sanek

    # Привязка к объекту
    site_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sites.id"), nullable=True)
    equipment_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ТРИГГЕР
    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # alarm, metric_threshold, schedule, hours_threshold
    trigger_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # alarm: {"severity_min": "HIGH", "alarm_codes": [101,102], "any": true}
    # metric_threshold: {"metric": "oil_pressure", "operator": "<", "value": 3.0, "device_id": 1}
    # schedule: {"interval_hours": 24, "interval_days": null}
    # hours_threshold: {"interval_hours": 250, "maintenance_type": "to_1"}

    # ДЕЙСТВИЕ
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # create_task, notify, create_task_and_notify
    action_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # create_task: {"task_type": "maintenance", "priority": 2, "deadline_days": 7, "checklist": [...]}
    # notify: {"message_template": "⚠ Аларм {alarm_name} на {equipment}"}
    # create_task_and_notify: объединение обоих

    # ИСПОЛНИТЕЛЬ
    executor_bitrix_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    executor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # НАБЛЮДАТЕЛИ
    watchers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # [{"bitrix_id": 1, "name": "Ермолаев Кирилл"}]

    # КОНТРОЛЬ САНЬКА
    sanek_control: Mapped[bool] = mapped_column(Boolean, default=True)
    # Если true — Санёк контролирует исполнение (эскалация, дедлайны)
    sanek_control_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # {"escalation_enabled": true, "reminder_hours": 4, "max_escalation_level": 3}

    # Статистика
    times_triggered: Mapped[int] = mapped_column(Integer, default=0)
    last_triggered_at: Mapped[datetime | None] = mapped_column(nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
