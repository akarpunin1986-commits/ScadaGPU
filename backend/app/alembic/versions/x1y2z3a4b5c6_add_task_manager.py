"""add task manager (maintenance cards, tasks, communications,
incidents, escalation, metrics snapshots, quality checks,
decision log, offline queue)

Revision ID: x1y2z3a4b5c6
Revises: w2x3y4z5a6b7
Create Date: 2026-03-22 12:00:00.000000

Adds:
- maintenance_cards — equipment maintenance card templates
- scada_tasks — unified task registry
- task_communications — message log per task
- incident_reports — root-cause analysis per task
- escalation_log — escalation history
- metrics_snapshots — before/after metrics capture
- task_quality_checks — quality verification results
- sanek_decision_log — AI decision audit trail
- offline_queue — retry queue for external calls
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "x1y2z3a4b5c6"
down_revision = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── maintenance_cards ──
    op.create_table(
        "maintenance_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("equipment_code", sa.String(100), nullable=False),
        sa.Column("equipment_name", sa.String(255), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("equipment_type", sa.String(50), nullable=True),
        sa.Column("maintenance_type", sa.String(50), nullable=False),
        sa.Column("maintenance_name", sa.String(255), nullable=True),
        sa.Column("interval_hours", sa.Integer(), nullable=True),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_completed_hours", sa.Integer(), nullable=True),
        sa.Column("checklist_items", JSONB(), nullable=True),
        sa.Column("source_file", sa.String(500), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("parsed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("bitrix_responsible_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("equipment_code", "maintenance_type", name="uq_card_equipment_type"),
    )

    # ── scada_tasks ──
    op.create_table(
        "scada_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_type", sa.String(30), nullable=False),
        sa.Column("trigger_source", sa.String(30), nullable=False),
        sa.Column("equipment_code", sa.String(100), nullable=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("maintenance_card_id", sa.Integer(), sa.ForeignKey("maintenance_cards.id", ondelete="SET NULL"), nullable=True),
        sa.Column("alarm_event_id", sa.Integer(), sa.ForeignKey("alarm_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bitrix_task_id", sa.Integer(), nullable=True),
        sa.Column("bitrix_group_id", sa.Integer(), nullable=True),
        sa.Column("responsible_user_id", sa.Integer(), nullable=False),
        sa.Column("responsible_name", sa.String(255), nullable=True),
        sa.Column("creator", sa.String(50), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="created"),
        sa.Column("priority", sa.Integer(), server_default="1"),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("escalation_level", sa.Integer(), server_default="0"),
        sa.Column("last_escalation_at", sa.DateTime(), nullable=True),
        sa.Column("quality_status", sa.String(30), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", JSONB(), nullable=True),
        sa.Column("alarm_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_scada_tasks_equipment_status", "scada_tasks", ["equipment_code", "status"])
    op.create_index("ix_scada_tasks_type_status", "scada_tasks", ["task_type", "status"])
    op.create_index("ix_scada_tasks_responsible", "scada_tasks", ["responsible_user_id"])
    op.create_index("ix_scada_tasks_status_deadline", "scada_tasks", ["status", "deadline"])

    # ── task_communications ──
    op.create_table(
        "task_communications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("scada_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("sender", sa.String(100), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("recipient_name", sa.String(255), nullable=True),
        sa.Column("recipient_role", sa.String(30), nullable=True),
        sa.Column("message_type", sa.String(30), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("bitrix_message_id", sa.Integer(), nullable=True),
        sa.Column("bitrix_comment_id", sa.Integer(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_task_communications_task_created", "task_communications", ["task_id", "created_at"])

    # ── incident_reports ──
    op.create_table(
        "incident_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("scada_tasks.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("resolution_plan", sa.Text(), nullable=True),
        sa.Column("estimated_fix_time", sa.DateTime(), nullable=True),
        sa.Column("actual_fix_time", sa.DateTime(), nullable=True),
        sa.Column("actions_taken", sa.Text(), nullable=True),
        sa.Column("completeness_score", sa.Float(), nullable=True),
        sa.Column("completeness_details", JSONB(), nullable=True),
        sa.Column("sanek_assessment", sa.Text(), nullable=True),
        sa.Column("iteration_count", sa.Integer(), server_default="0"),
        sa.Column("saved_to_knowledge", sa.Boolean(), server_default="false"),
        sa.Column("similar_incidents", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── escalation_log ──
    op.create_table(
        "escalation_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("scada_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("level_name", sa.String(30), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("target_name", sa.String(255), nullable=True),
        sa.Column("target_role", sa.String(30), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("response_received", sa.Boolean(), server_default="false"),
        sa.Column("response_at", sa.DateTime(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("resolved", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_escalation_log_task_level", "escalation_log", ["task_id", "level"])

    # ── metrics_snapshots ──
    op.create_table(
        "metrics_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("scada_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_type", sa.String(10), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metrics_data", JSONB(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_metrics_snapshots_task_type", "metrics_snapshots", ["task_id", "snapshot_type"])

    # ── task_quality_checks ──
    op.create_table(
        "task_quality_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("scada_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("check_type", sa.String(30), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("checked_by", sa.String(50), nullable=True),
    )
    op.create_index("ix_task_quality_checks_task", "task_quality_checks", ["task_id"])

    # ── sanek_decision_log ──
    op.create_table(
        "sanek_decision_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("scada_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision_type", sa.String(50), nullable=False),
        sa.Column("decision_data", JSONB(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_sanek_decision_log_task", "sanek_decision_log", ["task_id"])
    op.create_index("ix_sanek_decision_log_type_created", "sanek_decision_log", ["decision_type", "created_at"])

    # ── offline_queue ──
    op.create_table(
        "offline_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("method", sa.String(200), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0"),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("max_attempts", sa.Integer(), server_default="5"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_offline_queue_status_retry", "offline_queue", ["status", "next_retry_at"])
    op.create_index("ix_offline_queue_priority", "offline_queue", ["priority"])


def downgrade() -> None:
    op.drop_table("offline_queue")
    op.drop_table("sanek_decision_log")
    op.drop_table("task_quality_checks")
    op.drop_table("metrics_snapshots")
    op.drop_table("escalation_log")
    op.drop_table("incident_reports")
    op.drop_table("task_communications")
    op.drop_table("scada_tasks")
    op.drop_table("maintenance_cards")
