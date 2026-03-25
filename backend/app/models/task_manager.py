"""Task Manager module — 9 models for maintenance cards, tasks,
communications, incidents, escalation, metrics snapshots,
quality checks, decision log, and offline queue.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


# ---------------------------------------------------------------------------
# 1. MaintenanceCard
# ---------------------------------------------------------------------------
class MaintenanceCard(Base):
    __tablename__ = "maintenance_cards"

    __table_args__ = (
        UniqueConstraint(
            "equipment_code", "maintenance_type",
            name="uq_card_equipment_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_code: Mapped[str] = mapped_column(String(100))
    equipment_name: Mapped[str] = mapped_column(String(255))
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )
    equipment_type: Mapped[str | None] = mapped_column(String(50), default=None)
    maintenance_type: Mapped[str] = mapped_column(String(50))
    maintenance_name: Mapped[str | None] = mapped_column(String(255), default=None)
    interval_hours: Mapped[int | None] = mapped_column(default=None)
    interval_days: Mapped[int | None] = mapped_column(default=None)
    last_completed_at: Mapped[datetime | None] = mapped_column(default=None)
    last_completed_hours: Mapped[int | None] = mapped_column(default=None)
    checklist_items: Mapped[dict | None] = mapped_column(JSONB, default=list)
    source_file: Mapped[str | None] = mapped_column(String(500), default=None)
    source_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    parsed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    bitrix_responsible_id: Mapped[int | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# 2. ScadaTask
# ---------------------------------------------------------------------------
class ScadaTask(Base):
    __tablename__ = "scada_tasks"

    __table_args__ = (
        Index("ix_scada_tasks_equipment_status", "equipment_code", "status"),
        Index("ix_scada_tasks_type_status", "task_type", "status"),
        Index("ix_scada_tasks_responsible", "responsible_user_id"),
        Index("ix_scada_tasks_status_deadline", "status", "deadline"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_type: Mapped[str] = mapped_column(String(30))
    trigger_source: Mapped[str] = mapped_column(String(30))
    equipment_code: Mapped[str | None] = mapped_column(String(100), default=None)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )
    maintenance_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("maintenance_cards.id", ondelete="SET NULL"), nullable=True
    )
    alarm_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("alarm_events.id", ondelete="SET NULL"), nullable=True
    )
    bitrix_task_id: Mapped[int | None] = mapped_column(default=None)
    bitrix_group_id: Mapped[int | None] = mapped_column(default=46)
    responsible_user_id: Mapped[int] = mapped_column()
    responsible_name: Mapped[str | None] = mapped_column(String(255), default=None)
    creator: Mapped[str | None] = mapped_column(String(50), default="sanek")
    status: Mapped[str] = mapped_column(String(30), default="created")
    priority: Mapped[int] = mapped_column(default=1)
    deadline: Mapped[datetime] = mapped_column()
    escalation_level: Mapped[int] = mapped_column(default=0)
    last_escalation_at: Mapped[datetime | None] = mapped_column(default=None)
    quality_status: Mapped[str | None] = mapped_column(String(30), default=None)
    quality_score: Mapped[float | None] = mapped_column(Float, default=None)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    tags: Mapped[dict | None] = mapped_column(JSONB, default=list)
    alarm_name: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    closed_at: Mapped[datetime | None] = mapped_column(default=None)


# ---------------------------------------------------------------------------
# 3. TaskCommunication
# ---------------------------------------------------------------------------
class TaskCommunication(Base):
    __tablename__ = "task_communications"

    __table_args__ = (
        Index("ix_task_communications_task_created", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("scada_tasks.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(10))
    sender: Mapped[str] = mapped_column(String(100))
    recipient_user_id: Mapped[int | None] = mapped_column(default=None)
    recipient_name: Mapped[str | None] = mapped_column(String(255), default=None)
    recipient_role: Mapped[str | None] = mapped_column(String(30), default=None)
    message_type: Mapped[str] = mapped_column(String(30))
    message_text: Mapped[str] = mapped_column(Text)
    bitrix_message_id: Mapped[int | None] = mapped_column(default=None)
    bitrix_comment_id: Mapped[int | None] = mapped_column(default=None)
    read_at: Mapped[datetime | None] = mapped_column(default=None)
    responded_at: Mapped[datetime | None] = mapped_column(default=None)
    response_text: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# 4. IncidentReport
# ---------------------------------------------------------------------------
class IncidentReport(Base):
    __tablename__ = "incident_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("scada_tasks.id", ondelete="CASCADE"), unique=True
    )
    root_cause: Mapped[str | None] = mapped_column(Text, default=None)
    resolution_plan: Mapped[str | None] = mapped_column(Text, default=None)
    estimated_fix_time: Mapped[datetime | None] = mapped_column(default=None)
    actual_fix_time: Mapped[datetime | None] = mapped_column(default=None)
    actions_taken: Mapped[str | None] = mapped_column(Text, default=None)
    completeness_score: Mapped[float | None] = mapped_column(Float, default=None)
    completeness_details: Mapped[dict | None] = mapped_column(JSONB, default=None)
    sanek_assessment: Mapped[str | None] = mapped_column(Text, default=None)
    iteration_count: Mapped[int] = mapped_column(default=0)
    saved_to_knowledge: Mapped[bool] = mapped_column(default=False)
    similar_incidents: Mapped[dict | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# 5. EscalationLog
# ---------------------------------------------------------------------------
class EscalationLog(Base):
    __tablename__ = "escalation_log"

    __table_args__ = (
        Index("ix_escalation_log_task_level", "task_id", "level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("scada_tasks.id", ondelete="CASCADE")
    )
    level: Mapped[int] = mapped_column()
    level_name: Mapped[str | None] = mapped_column(String(30), default=None)
    target_user_id: Mapped[int | None] = mapped_column(default=None)
    target_name: Mapped[str | None] = mapped_column(String(255), default=None)
    target_role: Mapped[str | None] = mapped_column(String(30), default=None)
    reason: Mapped[str | None] = mapped_column(String(500), default=None)
    channel: Mapped[str | None] = mapped_column(String(20), default=None)
    message_text: Mapped[str | None] = mapped_column(Text, default=None)
    response_received: Mapped[bool] = mapped_column(default=False)
    response_at: Mapped[datetime | None] = mapped_column(default=None)
    response_text: Mapped[str | None] = mapped_column(Text, default=None)
    resolved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# 6. MetricsSnapshot
# ---------------------------------------------------------------------------
class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshots"

    __table_args__ = (
        Index("ix_metrics_snapshots_task_type", "task_id", "snapshot_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("scada_tasks.id", ondelete="CASCADE")
    )
    snapshot_type: Mapped[str] = mapped_column(String(10))
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    metrics_data: Mapped[dict] = mapped_column(JSONB)
    captured_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# 7. TaskQualityCheck
# ---------------------------------------------------------------------------
class TaskQualityCheck(Base):
    __tablename__ = "task_quality_checks"

    __table_args__ = (
        Index("ix_task_quality_checks_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("scada_tasks.id", ondelete="CASCADE")
    )
    check_type: Mapped[str] = mapped_column(String(30))
    passed: Mapped[bool] = mapped_column()
    details: Mapped[dict | None] = mapped_column(JSONB, default=None)
    checked_at: Mapped[datetime] = mapped_column(server_default=func.now())
    checked_by: Mapped[str | None] = mapped_column(String(50), default="sanek")


# ---------------------------------------------------------------------------
# 8. SanekDecisionLog
# ---------------------------------------------------------------------------
class SanekDecisionLog(Base):
    __tablename__ = "sanek_decision_log"

    __table_args__ = (
        Index("ix_sanek_decision_log_task", "task_id"),
        Index("ix_sanek_decision_log_type_created", "decision_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("scada_tasks.id", ondelete="SET NULL"), nullable=True
    )
    decision_type: Mapped[str] = mapped_column(String(50))
    decision_data: Mapped[dict | None] = mapped_column(JSONB, default=None)
    reasoning: Mapped[str | None] = mapped_column(Text, default=None)
    triggered_by: Mapped[str | None] = mapped_column(String(50), default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# 9. OfflineQueue
# ---------------------------------------------------------------------------
class OfflineQueue(Base):
    __tablename__ = "offline_queue"

    __table_args__ = (
        Index("ix_offline_queue_status_retry", "status", "next_retry_at"),
        Index("ix_offline_queue_priority", "priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    action_type: Mapped[str] = mapped_column(String(100))
    method: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict] = mapped_column(JSONB)
    priority: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    next_retry_at: Mapped[datetime | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
