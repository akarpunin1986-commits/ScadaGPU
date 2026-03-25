"""
Pydantic response models for Maintenance Lifecycle v2.0.

Includes:
- AI Parser input/output schemas (ParsedMaintenanceCard)
- API Response models (MaintenanceDashboard, EquipmentStatus)
- Card preview schema for parsed documents
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# ─── AI Parser input/output ───────────────────────────────────────────

class ParsedSparePart(BaseModel):
    part_number: Optional[str] = None
    name: str
    unit: str = "шт."
    quantity: float = 1.0
    model_filter: Optional[str] = None


class ParsedInterval(BaseModel):
    name: str
    code: str
    interval_value: Optional[int] = None
    interval_type: str = "hours"
    calendar_days: Optional[int] = None
    labor_hours: Optional[float] = None
    is_periodic: bool = True
    is_overhaul: bool = False
    includes: List[str] = Field(default_factory=list)
    specific_work_items: List[str] = Field(default_factory=list)
    spare_parts: List[ParsedSparePart] = Field(default_factory=list)


class ParsedEquipmentInfo(BaseModel):
    manufacturer: Optional[str] = None
    equipment_type: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None


class ParsedMaintenanceCard(BaseModel):
    equipment_info: ParsedEquipmentInfo = Field(default_factory=ParsedEquipmentInfo)
    intervals: List[ParsedInterval] = Field(default_factory=list)
    notes: Optional[str] = None


# ─── API Response models ──────────────────────────────────────────────

class NextMaintenance(BaseModel):
    interval_name: str
    interval_code: str
    interval_type: str
    remaining_hours: Optional[int] = None
    remaining_days: Optional[int] = None
    urgency_score: float
    target_value: Optional[int] = None
    card_name: Optional[str] = None


class EquipmentStatus(BaseModel):
    equipment_id: int
    equipment_name: str
    equipment_type: str
    site_name: str
    hours_source: str
    current_value: int
    epoch_value: int
    operating_hours: int
    days_since_epoch: int
    responsible_name: Optional[str] = None
    next_maintenance: Optional[NextMaintenance] = None
    upcoming: List[NextMaintenance] = Field(default_factory=list)
    last_maintenance_date: Optional[datetime] = None
    last_maintenance_code: Optional[str] = None
    status: str = "ok"  # ok | warning | overdue | no_card


class MaintenanceDashboard(BaseModel):
    total_equipment: int
    ok_count: int
    warning_count: int
    overdue_count: int
    no_card_count: int
    equipment: List[EquipmentStatus]


class ParsedCardPreview(BaseModel):
    card_id: int
    name: str
    manufacturer: Optional[str] = None
    equipment_type: Optional[str] = None
    parse_confidence: Optional[float] = None
    intervals_count: int
    work_items_count: int
    spare_parts_count: int
    status: str


# ─── CRUD request bodies for card editing ────────────────────────────

class UpdateCardBody(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    manufacturer: Optional[str] = None
    equipment_type: Optional[str] = None
    model_filter: Optional[str] = None

class UpdateIntervalBody(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    interval_type: Optional[str] = None
    interval_hours: Optional[int] = None
    interval_days: Optional[int] = None
    labor_hours: Optional[float] = None
    is_periodic: Optional[bool] = None
    is_overhaul: Optional[bool] = None
    warn_threshold: Optional[int] = None
    task_threshold: Optional[int] = None
    description: Optional[str] = None

class CreateIntervalBody(BaseModel):
    name: str
    code: str
    interval_type: str = "hours"
    interval_hours: Optional[int] = None
    interval_days: Optional[int] = None
    labor_hours: Optional[float] = None
    is_periodic: bool = True
    is_overhaul: bool = False

class UpdateWorkItemBody(BaseModel):
    work_description: Optional[str] = None
    requires_photo: Optional[bool] = None
    photo_type: Optional[str] = None

class CreateWorkItemBody(BaseModel):
    work_description: str
    requires_photo: bool = False
    photo_type: Optional[str] = None

class UpdateSparePartBody(BaseModel):
    part_name: Optional[str] = None
    part_number: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None

class CreateSparePartBody(BaseModel):
    part_name: str
    part_number: Optional[str] = None
    quantity: float = 1.0
    unit: str = "шт."
