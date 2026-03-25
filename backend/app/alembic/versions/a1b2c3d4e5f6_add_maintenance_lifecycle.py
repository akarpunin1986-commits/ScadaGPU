"""add maintenance lifecycle v2

Revision ID: a1b2c3d4e5f6
Revises: z3a4b5c6d7e8
Create Date: 2026-03-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "z3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. ALTER TABLE equipment_units ─────────────────────────────────
    op.add_column("equipment_units", sa.Column("hours_source", sa.VARCHAR(20), server_default="manual"))
    op.add_column("equipment_units", sa.Column("hours_source_config", JSONB, server_default="{}"))
    op.add_column("equipment_units", sa.Column("epoch_value", sa.Integer(), server_default="0"))
    op.add_column("equipment_units", sa.Column("epoch_date", sa.DateTime()))
    op.add_column("equipment_units", sa.Column("epoch_reason", sa.VARCHAR(50), server_default="initial"))
    op.add_column("equipment_units", sa.Column("current_value", sa.Integer(), server_default="0"))
    op.add_column("equipment_units", sa.Column("current_value_updated_at", sa.DateTime()))
    op.add_column("equipment_units", sa.Column("responsible_bitrix_id", sa.Integer()))
    op.add_column("equipment_units", sa.Column("responsible_name", sa.VARCHAR(100)))
    op.add_column("equipment_units", sa.Column("bitrix_equipment_id", sa.Integer()))
    op.add_column("equipment_units", sa.Column("serial_number", sa.VARCHAR(100)))
    op.add_column("equipment_units", sa.Column("total_starts", sa.Integer(), server_default="0"))

    # ── 2. CREATE TABLE maintenance_cards_v2 ──────────────────────────
    op.create_table(
        "maintenance_cards_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.VARCHAR(200), nullable=False),
        sa.Column("manufacturer", sa.VARCHAR(100)),
        sa.Column("equipment_type", sa.VARCHAR(50)),
        sa.Column("model", sa.VARCHAR(100)),
        sa.Column("description", sa.Text()),
        sa.Column("source_type", sa.VARCHAR(20), server_default="manual"),
        sa.Column("source_file", sa.VARCHAR(500)),
        sa.Column("parse_confidence", sa.Float()),
        sa.Column("parsed_at", sa.DateTime()),
        sa.Column("parsed_by", sa.VARCHAR(50)),
        sa.Column("status", sa.VARCHAR(20), server_default="draft"),
        sa.Column("approved_by", sa.Integer()),
        sa.Column("approved_at", sa.DateTime()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── 3. CREATE TABLE card_intervals ────────────────────────────────
    op.create_table(
        "card_intervals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("maintenance_cards_v2.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.VARCHAR(200), nullable=False),
        sa.Column("code", sa.VARCHAR(20), nullable=False),
        sa.Column("interval_value", sa.Integer()),
        sa.Column("interval_type", sa.VARCHAR(20), server_default="hours"),
        sa.Column("calendar_days", sa.Integer()),
        sa.Column("labor_hours", sa.Float()),
        sa.Column("is_periodic", sa.Boolean(), server_default="true"),
        sa.Column("is_overhaul", sa.Boolean(), server_default="false"),
        sa.Column("includes", JSONB, server_default="[]"),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("card_id", "code", name="uq_card_intervals_card_code"),
    )

    # ── 4. CREATE TABLE card_work_items ───────────────────────────────
    op.create_table(
        "card_work_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("interval_id", sa.Integer(), sa.ForeignKey("card_intervals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── 5. CREATE TABLE card_spare_parts ──────────────────────────────
    op.create_table(
        "card_spare_parts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("interval_id", sa.Integer(), sa.ForeignKey("card_intervals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("part_number", sa.VARCHAR(100)),
        sa.Column("name", sa.VARCHAR(200), nullable=False),
        sa.Column("unit", sa.VARCHAR(20), server_default="шт."),
        sa.Column("quantity", sa.Float(), server_default="1"),
        sa.Column("model_filter", sa.VARCHAR(100)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── 6. CREATE TABLE equipment_card_links ──────────────────────────
    op.create_table(
        "equipment_card_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipment_units.id", ondelete="CASCADE"), nullable=False),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("maintenance_cards_v2.id", ondelete="CASCADE"), nullable=False),
        sa.Column("linked_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("linked_by", sa.VARCHAR(100)),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.UniqueConstraint("equipment_id", "card_id", name="uq_equipment_card_links_eq_card"),
    )

    # ── 7. CREATE TABLE maintenance_log_v2 ────────────────────────────
    op.create_table(
        "maintenance_log_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipment_units.id"), nullable=False),
        sa.Column("interval_id", sa.Integer(), sa.ForeignKey("card_intervals.id")),
        sa.Column("interval_code", sa.VARCHAR(30), nullable=False),
        sa.Column("value_at_maintenance", sa.Integer()),
        sa.Column("operating_hours", sa.Integer()),
        sa.Column("days_at_maintenance", sa.Integer()),
        sa.Column("is_cascade", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("performed_date", sa.DateTime(), nullable=False),
        sa.Column("performed_by", sa.VARCHAR(100)),
        sa.Column("performed_by_bitrix_id", sa.Integer()),
        sa.Column("scada_task_id", sa.Integer(), sa.ForeignKey("scada_tasks.id", ondelete="SET NULL")),
        sa.Column("bitrix_task_id", sa.Integer()),
        sa.Column("quality_score", sa.Numeric(3, 2)),
        sa.Column("checklist_completed", sa.Boolean(), server_default="false"),
        sa.Column("photos_verified", sa.Boolean(), server_default="false"),
        sa.Column("is_overhaul", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_mlog2_equipment", "maintenance_log_v2", ["equipment_id"])
    op.create_index("ix_mlog2_code", "maintenance_log_v2", ["equipment_id", "interval_code"])
    op.create_index("ix_mlog2_date", "maintenance_log_v2", ["performed_date"])

    # ── 8. CREATE TABLE epoch_history ─────────────────────────────────
    op.create_table(
        "epoch_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipment_units.id"), nullable=False),
        sa.Column("old_epoch_value", sa.Integer(), nullable=False),
        sa.Column("new_epoch_value", sa.Integer(), nullable=False),
        sa.Column("old_epoch_date", sa.DateTime()),
        sa.Column("new_epoch_date", sa.DateTime()),
        sa.Column("reason", sa.VARCHAR(50), nullable=False),
        sa.Column("changed_by", sa.VARCHAR(100)),
        sa.Column("changed_by_bitrix_id", sa.Integer()),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("notes", sa.Text()),
    )

    # ── 9. CREATE TABLE card_parse_log ────────────────────────────────
    op.create_table(
        "card_parse_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("maintenance_cards_v2.id", ondelete="CASCADE")),
        sa.Column("filename", sa.VARCHAR(500)),
        sa.Column("file_size", sa.Integer()),
        sa.Column("model_used", sa.VARCHAR(50)),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("confidence", sa.Float()),
        sa.Column("intervals_found", sa.Integer()),
        sa.Column("work_items_found", sa.Integer()),
        sa.Column("spare_parts_found", sa.Integer()),
        sa.Column("raw_response", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("status", sa.VARCHAR(20), server_default="success"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("card_parse_log")
    op.drop_table("epoch_history")
    op.drop_index("ix_maintenance_log_v2_interval_code", table_name="maintenance_log_v2")
    op.drop_index("ix_maintenance_log_v2_performed_at", table_name="maintenance_log_v2")
    op.drop_index("ix_maintenance_log_v2_equipment_id", table_name="maintenance_log_v2")
    op.drop_table("maintenance_log_v2")
    op.drop_table("equipment_card_links")
    op.drop_table("card_spare_parts")
    op.drop_table("card_work_items")
    op.drop_table("card_intervals")
    op.drop_table("maintenance_cards_v2")

    # Remove columns from equipment_units
    op.drop_column("equipment_units", "total_starts")
    op.drop_column("equipment_units", "serial_number")
    op.drop_column("equipment_units", "bitrix_equipment_id")
    op.drop_column("equipment_units", "responsible_name")
    op.drop_column("equipment_units", "responsible_bitrix_id")
    op.drop_column("equipment_units", "current_value_updated_at")
    op.drop_column("equipment_units", "current_value")
    op.drop_column("equipment_units", "epoch_reason")
    op.drop_column("equipment_units", "epoch_date")
    op.drop_column("equipment_units", "epoch_value")
    op.drop_column("equipment_units", "hours_source_config")
    op.drop_column("equipment_units", "hours_source")
