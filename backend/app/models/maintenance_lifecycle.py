"""Maintenance Lifecycle v2.0 — Universal equipment maintenance models.

8 models:
- MaintenanceCardV2: parsed maintenance cards (PDF/Word)
- CardInterval: TO intervals within a card (hours/calendar/combo/once)
- CardWorkItem: specific work items per interval
- CardSparePart: spare parts per interval
- EquipmentCardLink: M:N link equipment ↔ card
- MaintenanceLogV2: maintenance execution journal
- EpochHistory: epoch reset audit trail
- CardParseLog: AI parsing audit
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, ForeignKey, Index, Integer, Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


# ── 1. MaintenanceCardV2 ──

class MaintenanceCardV2(Base):
    __tablename__ = "maintenance_cards_v2"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    equipment_type: Mapped[str | None] = mapped_column(String(50))
    model_filter: Mapped[str | None] = mapped_column(String(100))

    # Source file
    source_file_name: Mapped[str | None] = mapped_column(String(200))
    source_file_path: Mapped[str | None] = mapped_column(String(500))
    parsed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    parsed_by: Mapped[str | None] = mapped_column(String(50))
    parse_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))

    # Status: draft → confirmed → active → archived
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    notes: Mapped[str | None] = mapped_column(Text)
    raw_parsed_json: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# ── 2. CardInterval ──

class CardInterval(Base):
    __tablename__ = "card_intervals"

    __table_args__ = (
        Index("ix_ci_card", "card_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("maintenance_cards_v2.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)

    # Interval type: hours | calendar_days | hours_or_days | once
    interval_type: Mapped[str] = mapped_column(String(20), nullable=False)
    interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_periodic: Mapped[bool] = mapped_column(Boolean, server_default="true")
    is_overhaul: Mapped[bool] = mapped_column(Boolean, server_default="false")
    labor_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))

    # Per-interval alert thresholds (NULL = use global config)
    warn_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Nested intervals (codes from SAME card) — JSONB in actual DB
    includes: Mapped[list | None] = mapped_column(JSONB, server_default="[]")

    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")


# ── 3. CardWorkItem ──

class CardWorkItem(Base):
    __tablename__ = "card_work_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    interval_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("card_intervals.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)  # DB column is "description"
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")


# ── 4. CardSparePart ──

class CardSparePart(Base):
    __tablename__ = "card_spare_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    interval_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("card_intervals.id", ondelete="CASCADE"), nullable=False
    )
    part_number: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), server_default="шт.")
    quantity: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    model_filter: Mapped[str | None] = mapped_column(String(100))


# ── 5. EquipmentCardLink (M:N) ──

class EquipmentCardLink(Base):
    __tablename__ = "equipment_card_links"

    __table_args__ = (
        Index("ix_ecl_equipment", "equipment_id"),
        Index("ix_ecl_card", "card_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_units.id", ondelete="CASCADE"), nullable=False
    )
    card_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("maintenance_cards_v2.id", ondelete="CASCADE"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(server_default=func.now())
    linked_by: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


# ── 6. MaintenanceLogV2 ──

class MaintenanceLogV2(Base):
    __tablename__ = "maintenance_log_v2"

    __table_args__ = (
        Index("ix_mlog2_equipment", "equipment_id"),
        Index("ix_mlog2_code", "equipment_id", "interval_code"),
        Index("ix_mlog2_date", "performed_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_units.id"), nullable=False
    )
    interval_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("card_intervals.id"), nullable=True
    )
    interval_code: Mapped[str] = mapped_column(String(30), nullable=False)

    # Values at maintenance time (nullable depending on interval_type)
    value_at_maintenance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operating_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_at_maintenance: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Cascade
    is_cascade: Mapped[bool] = mapped_column(Boolean, server_default="false")

    # Execution
    performed_date: Mapped[datetime] = mapped_column(nullable=False)
    performed_by: Mapped[str | None] = mapped_column(String(100))
    performed_by_bitrix_id: Mapped[int | None] = mapped_column(Integer)

    # Task link
    scada_task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scada_tasks.id", ondelete="SET NULL"), nullable=True
    )
    bitrix_task_id: Mapped[int | None] = mapped_column(Integer)

    # Quality
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    checklist_completed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    photos_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")

    # Overhaul
    is_overhaul: Mapped[bool] = mapped_column(Boolean, server_default="false")

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# ── 7. EpochHistory ──

class EpochHistory(Base):
    __tablename__ = "epoch_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_units.id"), nullable=False
    )
    old_epoch_value: Mapped[int] = mapped_column(Integer, nullable=False)
    new_epoch_value: Mapped[int] = mapped_column(Integer, nullable=False)
    old_epoch_date: Mapped[datetime | None] = mapped_column(nullable=True)
    new_epoch_date: Mapped[datetime | None] = mapped_column(nullable=True)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100))
    changed_by_bitrix_id: Mapped[int | None] = mapped_column(Integer)
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text)


# ── 8. CardParseLog ──

class CardParseLog(Base):
    __tablename__ = "card_parse_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("maintenance_cards_v2.id", ondelete="SET NULL"), nullable=True
    )
    file_name: Mapped[str | None] = mapped_column(String(200))
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    parse_method: Mapped[str | None] = mapped_column(String(50))
    llm_model: Mapped[str | None] = mapped_column(String(50))

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict | None] = mapped_column(JSONB)

    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
