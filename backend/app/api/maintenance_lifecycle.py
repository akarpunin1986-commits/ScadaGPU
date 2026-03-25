"""ScadaGPU — Maintenance Lifecycle v2.0 API router (/api/maintenance)."""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from middleware.auth import get_optional_user
from models.base import async_session
from models.equipment_unit import EquipmentUnit
from models.maintenance_lifecycle import (
    CardInterval,
    CardParseLog,
    CardSparePart,
    CardWorkItem,
    EquipmentCardLink,
    EpochHistory,
    MaintenanceCardV2,
    MaintenanceLogV2,
)
from schemas.maintenance import (
    EquipmentStatus,
    ParsedCardPreview,
    UpdateCardBody,
    UpdateIntervalBody,
    CreateIntervalBody,
    UpdateWorkItemBody,
    CreateWorkItemBody,
    UpdateSparePartBody,
    CreateSparePartBody,
)
from services.maintenance import card_parser
from services.maintenance import lifecycle

logger = logging.getLogger("scada.maintenance_lifecycle")

router = APIRouter(prefix="/api/maintenance", tags=["maintenance-lifecycle"], redirect_slashes=False)

UPLOAD_DIR = Path("/opt/scada/uploads/maintenance")


# ---------------------------------------------------------------------------
#  Pydantic request schemas
# ---------------------------------------------------------------------------

class ConfirmBody(BaseModel):
    confirmed_by: str

class LinkBody(BaseModel):
    equipment_ids: list[int]
    linked_by: str

class RecordMaintenanceBody(BaseModel):
    interval_code: str
    performed_by: str
    notes: str | None = None

class ResetEpochBody(BaseModel):
    reason: str
    notes: str | None = None
    changed_by: str

class SetEpochBody(BaseModel):
    epoch_value: int
    reason: str = "Установлено из настроек"
    changed_by: str = "UI"

class ManualHoursBody(BaseModel):
    value: int


# ---------------------------------------------------------------------------
#  1. POST /cards/upload — multipart file upload, parse card
# ---------------------------------------------------------------------------

@router.post("/cards/upload")
async def upload_card(
    request: Request,
    file: UploadFile = File(...),
    method: str = Query("auto", regex="^(auto|vision)$"),
):
    """Upload maintenance card file (PDF/Word), parse via AI."""
    user = await get_optional_user(request)

    # Validate extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".pdf", ".docx", ".doc"):
        raise HTTPException(400, f"Unsupported file type: {ext}. Use .pdf or .docx")

    # Ensure upload dir exists
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Save file
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{file.filename}"
    dest = UPLOAD_DIR / safe_name

    try:
        with open(dest, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as exc:
        logger.exception("Failed to save uploaded file: %s", exc)
        raise HTTPException(500, "Failed to save file")

    # Parse
    try:
        result = await card_parser.parse_card(str(dest), method=method)
    except Exception as exc:
        logger.exception("Card parsing failed: %s", exc)
        raise HTTPException(422, f"Parsing failed: {exc}")

    # Save parsed card to DB as draft
    parsed_data = result.get("parsed")
    if not parsed_data:
        raise HTTPException(422, "Parsing returned no data")

    from decimal import Decimal as _Decimal

    async with async_session() as session:
        eq_info = parsed_data.equipment_info if hasattr(parsed_data, 'equipment_info') else None
        card = MaintenanceCardV2(
            name=f"{(eq_info.manufacturer if eq_info else None) or 'Unknown'} — {(eq_info.equipment_type if eq_info else None) or 'equipment'}",
            manufacturer=eq_info.manufacturer if eq_info else None,
            equipment_type=eq_info.equipment_type if eq_info else None,
            model_filter=eq_info.model if eq_info else None,
            source_file_name=file.filename,
            source_file_path=str(dest),
            parsed_at=datetime.utcnow(),
            parsed_by="gpt",
            parse_confidence=_Decimal(str(result.get("confidence", 0.0))),
            status="draft",
            notes=parsed_data.notes if hasattr(parsed_data, 'notes') else None,
            raw_parsed_json=parsed_data.model_dump() if hasattr(parsed_data, 'model_dump') else None,
        )
        session.add(card)
        await session.flush()  # get card.id

        intervals_count = 0
        work_items_count = 0
        spare_parts_count = 0

        for sort_idx, iv in enumerate(parsed_data.intervals if hasattr(parsed_data, 'intervals') else []):
            interval = CardInterval(
                card_id=card.id,
                name=iv.name,
                code=iv.code,
                interval_type=iv.interval_type,
                interval_hours=iv.interval_value,
                interval_days=iv.calendar_days,
                is_periodic=iv.is_periodic,
                is_overhaul=iv.is_overhaul,
                labor_hours=_Decimal(str(iv.labor_hours)) if iv.labor_hours else None,
                includes=iv.includes or [],
                sort_order=sort_idx,
            )
            session.add(interval)
            await session.flush()
            intervals_count += 1

            for wi_idx, work_desc in enumerate(iv.specific_work_items or []):
                session.add(CardWorkItem(
                    interval_id=interval.id,
                    description=work_desc,
                    sort_order=wi_idx,
                ))
                work_items_count += 1

            for sp_idx, sp in enumerate(iv.spare_parts or []):
                session.add(CardSparePart(
                    interval_id=interval.id,
                    part_number=sp.part_number,
                    name=sp.name,
                    unit=sp.unit,
                    quantity=_Decimal(str(sp.quantity)),
                    model_filter=sp.model_filter,
                ))
                spare_parts_count += 1

        # Link parse log to card
        if result.get("parse_log_id"):
            from sqlalchemy import update
            await session.execute(
                update(CardParseLog).where(CardParseLog.id == result["parse_log_id"]).values(card_id=card.id)
            )

        await session.commit()

        logger.info("Card saved as draft: id=%d, name=%s, intervals=%d, work=%d, parts=%d",
                     card.id, card.name, intervals_count, work_items_count, spare_parts_count)

        return ParsedCardPreview(
            card_id=card.id,
            name=card.name,
            manufacturer=card.manufacturer,
            equipment_type=card.equipment_type,
            parse_confidence=float(card.parse_confidence) if card.parse_confidence else None,
            intervals_count=intervals_count,
            work_items_count=work_items_count,
            spare_parts_count=spare_parts_count,
            status=card.status,
        )


# ---------------------------------------------------------------------------
#  2. GET /cards — list all cards
# ---------------------------------------------------------------------------

@router.get("/cards")
async def list_cards(
    status: str | None = Query(None),
    equipment_type: str | None = Query(None),
):
    """List all MaintenanceCardV2 with intervals summary and linked equipment."""
    async with async_session() as session:
        stmt = select(MaintenanceCardV2).order_by(MaintenanceCardV2.id.desc())
        if status:
            stmt = stmt.where(MaintenanceCardV2.status == status)
        if equipment_type:
            stmt = stmt.where(MaintenanceCardV2.equipment_type == equipment_type)

        cards = (await session.execute(stmt)).scalars().all()
        result = []
        for c in cards:
            # Load intervals summary
            intervals_stmt = select(CardInterval).where(
                CardInterval.card_id == c.id
            ).order_by(CardInterval.sort_order)
            intervals = (await session.execute(intervals_stmt)).scalars().all()

            # Count work items and spare parts
            work_count = 0
            spare_count = 0
            for iv in intervals:
                wi_cnt = (await session.execute(
                    select(func.count()).where(CardWorkItem.interval_id == iv.id)
                )).scalar() or 0
                sp_cnt = (await session.execute(
                    select(func.count()).where(CardSparePart.interval_id == iv.id)
                )).scalar() or 0
                work_count += wi_cnt
                spare_count += sp_cnt

            # Load linked equipment with site info
            links_stmt = select(EquipmentCardLink, EquipmentUnit).join(
                EquipmentUnit, EquipmentUnit.id == EquipmentCardLink.equipment_id
            ).where(
                EquipmentCardLink.card_id == c.id,
                EquipmentCardLink.is_active == True,
            )
            links = (await session.execute(links_stmt)).all()

            from models.site import Site
            linked_eq = []
            for link, eq in links:
                site = await session.get(Site, eq.site_id) if eq.site_id else None
                linked_eq.append({
                    "equipment_id": eq.id,
                    "equipment_name": eq.name,
                    "equipment_code": eq.code,
                    "site_id": eq.site_id,
                    "site_name": site.name if site else None,
                })

            result.append({
                "id": c.id,
                "name": c.name,
                "manufacturer": c.manufacturer,
                "equipment_type": c.equipment_type,
                "status": c.status,
                "parse_confidence": float(c.parse_confidence) if c.parse_confidence else None,
                "source_file_name": c.source_file_name,
                "source_file_url": f"/api/maintenance/cards/{c.id}/file" if c.source_file_path else None,
                "confirmed_by": c.confirmed_by,
                "confirmed_at": c.confirmed_at.isoformat() if c.confirmed_at else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "intervals": [
                    {
                        "name": iv.name,
                        "code": iv.code,
                        "interval_hours": iv.interval_hours,
                        "interval_days": iv.interval_days,
                    }
                    for iv in intervals
                ],
                "work_items_count": work_count,
                "spare_parts_count": spare_count,
                "linked_equipment": linked_eq,
            })
        return result


# ---------------------------------------------------------------------------
#  2b. GET /cards/{id}/file — download original file
# ---------------------------------------------------------------------------

@router.get("/cards/{card_id}/file")
async def download_card_file(card_id: int):
    """Download the original uploaded PDF/Word file for a maintenance card."""
    from fastapi.responses import FileResponse

    async with async_session() as session:
        card = await session.get(MaintenanceCardV2, card_id)
        if not card:
            raise HTTPException(404, "Card not found")
        if not card.source_file_path:
            raise HTTPException(404, "Original file not available")
        fpath = card.source_file_path
        if not os.path.exists(fpath):
            raise HTTPException(404, f"File not found on disk: {card.source_file_name}")
        return FileResponse(
            fpath,
            filename=card.source_file_name or os.path.basename(fpath),
            media_type="application/octet-stream",
        )


# ---------------------------------------------------------------------------
#  3. GET /cards/{id} — card details with intervals, work items, spare parts
# ---------------------------------------------------------------------------

@router.get("/cards/{card_id}")
async def get_card(card_id: int):
    """Card details with intervals, work items, spare parts."""
    async with async_session() as session:
        card = await session.get(MaintenanceCardV2, card_id)
        if not card:
            raise HTTPException(404, "Card not found")

        intervals = (await session.execute(
            select(CardInterval)
            .where(CardInterval.card_id == card_id)
            .order_by(CardInterval.sort_order)
        )).scalars().all()

        intervals_out = []
        for iv in intervals:
            work_items = (await session.execute(
                select(CardWorkItem)
                .where(CardWorkItem.interval_id == iv.id)
                .order_by(CardWorkItem.sort_order)
            )).scalars().all()

            spare_parts = (await session.execute(
                select(CardSparePart)
                .where(CardSparePart.interval_id == iv.id)
                .order_by(CardSparePart.id)
            )).scalars().all()

            intervals_out.append({
                "id": iv.id,
                "name": iv.name,
                "code": iv.code,
                "interval_type": iv.interval_type,
                "interval_hours": iv.interval_hours,
                "interval_days": iv.interval_days,
                "labor_hours": float(iv.labor_hours) if iv.labor_hours else None,
                "is_periodic": iv.is_periodic,
                "is_overhaul": iv.is_overhaul,
                "includes": iv.includes or [],
                "sort_order": iv.sort_order,
                "work_items": [
                    {
                        "id": wi.id,
                        "work_description": wi.description,
                    }
                    for wi in work_items
                ],
                "spare_parts": [
                    {
                        "id": sp.id,
                        "part_number": sp.part_number,
                        "name": sp.name,
                        "unit": sp.unit,
                        "quantity": float(sp.quantity) if sp.quantity else None,
                    }
                    for sp in spare_parts
                ],
            })

        # Linked equipment
        links = (await session.execute(
            select(EquipmentCardLink).where(EquipmentCardLink.card_id == card_id)
        )).scalars().all()

        return {
            "id": card.id,
            "name": card.name,
            "manufacturer": card.manufacturer,
            "equipment_type": card.equipment_type,
            "model_filter": card.model_filter,
            "status": card.status,
            "parse_confidence": float(card.parse_confidence) if card.parse_confidence else None,
            "source_file_name": card.source_file_name,
            "confirmed_by": card.confirmed_by,
            "confirmed_at": card.confirmed_at.isoformat() if card.confirmed_at else None,
            "notes": card.notes,
            "created_at": card.created_at.isoformat() if card.created_at else None,
            "intervals": intervals_out,
            "linked_equipment": [
                {"equipment_id": lk.equipment_id, "is_active": lk.is_active, "linked_by": lk.linked_by}
                for lk in links
            ],
        }


# ---------------------------------------------------------------------------
#  4. POST /cards/{id}/confirm — confirm parsed card
# ---------------------------------------------------------------------------

@router.post("/cards/{card_id}/confirm")
async def confirm_card(card_id: int, body: ConfirmBody):
    """Confirm a draft card (draft → confirmed)."""
    async with async_session() as session:
        card = await session.get(MaintenanceCardV2, card_id)
        if not card:
            raise HTTPException(404, "Card not found")
        if card.status != "draft":
            raise HTTPException(400, f"Card status is '{card.status}', expected 'draft'")

        card.status = "confirmed"
        card.confirmed_by = body.confirmed_by
        card.confirmed_at = datetime.utcnow()
        await session.commit()

        return {"status": "confirmed", "card_id": card.id, "confirmed_by": body.confirmed_by}


# ---------------------------------------------------------------------------
#  5. POST /cards/{id}/link — link card to equipment
# ---------------------------------------------------------------------------

@router.post("/cards/{card_id}/link")
async def link_card(card_id: int, body: LinkBody):
    """Link card to one or more equipment units."""
    async with async_session() as session:
        card = await session.get(MaintenanceCardV2, card_id)
        if not card:
            raise HTTPException(404, "Card not found")

        linked = []
        for eq_id in body.equipment_ids:
            # Check equipment exists
            eq = await session.get(EquipmentUnit, eq_id)
            if not eq:
                continue

            # Skip if already linked
            existing = (await session.execute(
                select(EquipmentCardLink).where(
                    EquipmentCardLink.card_id == card_id,
                    EquipmentCardLink.equipment_id == eq_id,
                )
            )).scalar_one_or_none()
            if existing:
                existing.is_active = True
                linked.append(eq_id)
                continue

            link = EquipmentCardLink(
                card_id=card_id,
                equipment_id=eq_id,
                linked_by=body.linked_by,
                is_active=True,
            )
            session.add(link)
            linked.append(eq_id)

        # Activate card if confirmed
        if card.status == "confirmed":
            card.status = "active"

        await session.commit()
        return {"status": "linked", "card_id": card_id, "equipment_ids": linked}


# ---------------------------------------------------------------------------
#  6. DELETE /cards/{id}/link/{equipment_id} — unlink
# ---------------------------------------------------------------------------

@router.delete("/cards/{card_id}/link/{equipment_id}")
async def unlink_card(card_id: int, equipment_id: int):
    """Unlink card from equipment (soft deactivate)."""
    async with async_session() as session:
        link = (await session.execute(
            select(EquipmentCardLink).where(
                EquipmentCardLink.card_id == card_id,
                EquipmentCardLink.equipment_id == equipment_id,
            )
        )).scalar_one_or_none()
        if not link:
            raise HTTPException(404, "Link not found")

        link.is_active = False
        await session.commit()
        return {"status": "unlinked", "card_id": card_id, "equipment_id": equipment_id}


# ---------------------------------------------------------------------------
#  7. POST /cards/{id}/reparse — re-parse card
# ---------------------------------------------------------------------------

@router.post("/cards/{card_id}/reparse")
async def reparse_card(card_id: int, method: str = Query("auto", regex="^(auto|vision)$")):
    """Re-parse an existing card from its source file."""
    async with async_session() as session:
        card = await session.get(MaintenanceCardV2, card_id)
        if not card:
            raise HTTPException(404, "Card not found")
        if not card.source_file_path or not os.path.exists(card.source_file_path):
            raise HTTPException(400, "Source file not found for re-parsing")

    try:
        result = await card_parser.parse_card(card.source_file_path, method=method)
    except Exception as exc:
        logger.exception("Re-parse failed for card %d: %s", card_id, exc)
        raise HTTPException(422, f"Re-parsing failed: {exc}")

    return {
        "status": "reparsed",
        "card_id": card_id,
        "method": result.get("method"),
        "confidence": result.get("confidence"),
    }


# ---------------------------------------------------------------------------
#  8. GET /equipment — all equipment with maintenance status
# ---------------------------------------------------------------------------

@router.get("/equipment")
async def list_equipment(
    site_id: int | None = Query(None),
    equipment_type: str | None = Query(None),
):
    """All equipment with maintenance status + linked card info."""
    async with async_session() as session:
        statuses = await lifecycle.get_all_equipment_status(
            session, site_id=site_id, equipment_type=equipment_type,
        )
        # Enrich with linked card info for each equipment
        result = []
        for s in statuses:
            d = s.model_dump()
            eq_id = d.get("equipment_id")
            if eq_id:
                links = (await session.execute(
                    select(EquipmentCardLink, MaintenanceCardV2)
                    .join(MaintenanceCardV2, MaintenanceCardV2.id == EquipmentCardLink.card_id)
                    .where(EquipmentCardLink.equipment_id == eq_id, EquipmentCardLink.is_active == True)
                )).all()
                if links:
                    link, card = links[0]
                    d["card"] = {
                        "id": card.id,
                        "name": card.name,
                        "source_file_name": card.source_file_name,
                        "source_file_url": f"/api/maintenance/cards/{card.id}/file" if card.source_file_path else None,
                    }
                else:
                    d["card"] = None
            else:
                d["card"] = None
            result.append(d)
        return result


# ---------------------------------------------------------------------------
#  9. GET /equipment/{id}/status — detailed equipment status
# ---------------------------------------------------------------------------

@router.get("/equipment/{equipment_id}/status")
async def get_equipment_status(equipment_id: int):
    """Detailed equipment maintenance status."""
    async with async_session() as session:
        try:
            status = await lifecycle.get_equipment_status(equipment_id, session)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return status.model_dump()


# ---------------------------------------------------------------------------
#  10. POST /equipment/{id}/record — record maintenance
# ---------------------------------------------------------------------------

@router.post("/equipment/{equipment_id}/record")
async def record_maintenance(equipment_id: int, body: RecordMaintenanceBody):
    """Record completed maintenance for equipment."""
    async with async_session() as session:
        try:
            log_entry = await lifecycle.record_maintenance(
                equipment_id=equipment_id,
                interval_code=body.interval_code,
                performed_by=body.performed_by,
                performed_date=datetime.utcnow(),
                session=session,
                notes=body.notes,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc))

        return {
            "status": "recorded",
            "log_id": log_entry.id,
            "equipment_id": equipment_id,
            "interval_code": body.interval_code,
            "performed_by": body.performed_by,
        }


# ---------------------------------------------------------------------------
#  11. POST /equipment/{id}/reset-epoch — reset epoch
# ---------------------------------------------------------------------------

@router.post("/equipment/{equipment_id}/reset-epoch")
async def reset_epoch(equipment_id: int, body: ResetEpochBody):
    """Reset epoch for equipment."""
    async with async_session() as session:
        try:
            history = await lifecycle.reset_epoch(
                equipment_id=equipment_id,
                reason=body.reason,
                session=session,
                changed_by=body.changed_by,
                notes=body.notes,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        await session.commit()
        return {
            "status": "epoch_reset",
            "equipment_id": equipment_id,
            "old_value": history.old_epoch_value,
            "new_value": history.new_epoch_value,
            "reason": body.reason,
        }


# ---------------------------------------------------------------------------
#  11b. POST /equipment/{id}/set-epoch — set epoch to specific value
# ---------------------------------------------------------------------------

@router.post("/equipment/{equipment_id}/set-epoch")
async def set_epoch(equipment_id: int, body: SetEpochBody):
    """Set epoch to a specific motel hours value (e.g., from last known TO)."""
    async with async_session() as session:
        eq = await session.get(EquipmentUnit, equipment_id)
        if not eq:
            raise HTTPException(404, "Equipment not found")

        old_value = eq.epoch_value
        eq.epoch_value = body.epoch_value
        eq.epoch_date = datetime.utcnow()
        eq.epoch_reason = body.reason
        await session.commit()

        return {
            "status": "epoch_set",
            "equipment_id": equipment_id,
            "old_epoch": old_value,
            "new_epoch": body.epoch_value,
        }


# ---------------------------------------------------------------------------
#  12. GET /equipment/{id}/history — maintenance log
# ---------------------------------------------------------------------------

@router.get("/equipment/{equipment_id}/history")
async def get_equipment_history(
    equipment_id: int,
    limit: int = Query(50, ge=1, le=200),
):
    """Maintenance log for equipment."""
    async with async_session() as session:
        stmt = (
            select(MaintenanceLogV2)
            .where(MaintenanceLogV2.equipment_id == equipment_id)
            .order_by(MaintenanceLogV2.performed_date.desc())
            .limit(limit)
        )
        logs = (await session.execute(stmt)).scalars().all()

        return [
            {
                "id": log.id,
                "interval_code": log.interval_code,
                "value_at_maintenance": log.value_at_maintenance,
                "operating_hours": log.operating_hours,
                "days_at_maintenance": log.days_at_maintenance,
                "is_cascade": log.is_cascade,
                "is_overhaul": log.is_overhaul,
                "performed_date": log.performed_date.isoformat() if log.performed_date else None,
                "performed_by": log.performed_by,
                "notes": log.notes,
            }
            for log in logs
        ]


# ---------------------------------------------------------------------------
#  13. POST /equipment/{id}/hours — manual hours update
# ---------------------------------------------------------------------------

@router.post("/equipment/{equipment_id}/hours")
async def update_hours(equipment_id: int, body: ManualHoursBody):
    """Manual hours update for equipment."""
    async with async_session() as session:
        eq = await session.get(EquipmentUnit, equipment_id)
        if not eq:
            raise HTTPException(404, "Equipment not found")

        old_value = eq.current_value
        eq.current_value = body.value
        eq.current_value_updated_at = datetime.utcnow()
        await session.commit()

        return {
            "status": "updated",
            "equipment_id": equipment_id,
            "old_value": old_value,
            "new_value": body.value,
        }


# ---------------------------------------------------------------------------
#  14. GET /dashboard/overdue — all overdue equipment
# ---------------------------------------------------------------------------

@router.get("/dashboard/overdue")
async def get_overdue():
    """All equipment with overdue maintenance."""
    async with async_session() as session:
        all_statuses = await lifecycle.get_all_equipment_status(session)
        overdue = [s.model_dump() for s in all_statuses if s.status == "overdue"]
        return {"overdue_count": len(overdue), "equipment": overdue}


# ===========================================================================
#  CRUD endpoints for card editing (TODO #1)
# ===========================================================================

# ---------------------------------------------------------------------------
#  15. PATCH /cards/{id} — update card fields
# ---------------------------------------------------------------------------

@router.patch("/cards/{card_id}")
async def update_card(card_id: int, body: UpdateCardBody):
    """Update card name, notes, manufacturer, equipment_type, model_filter."""
    async with async_session() as session:
        card = await session.get(MaintenanceCardV2, card_id)
        if not card:
            raise HTTPException(404, "Card not found")

        for field in ("name", "notes", "manufacturer", "equipment_type", "model_filter"):
            val = getattr(body, field, None)
            if val is not None:
                setattr(card, field, val)

        card.updated_at = datetime.utcnow()
        await session.commit()
        return {"status": "updated", "card_id": card.id}


# ---------------------------------------------------------------------------
#  16. PATCH /intervals/{id} — update interval
# ---------------------------------------------------------------------------

@router.patch("/intervals/{interval_id}")
async def update_interval(interval_id: int, body: UpdateIntervalBody):
    """Update interval fields (hours, days, thresholds, etc.)."""
    async with async_session() as session:
        iv = await session.get(CardInterval, interval_id)
        if not iv:
            raise HTTPException(404, "Interval not found")

        for field in (
            "name", "code", "interval_type", "interval_hours", "interval_days",
            "labor_hours", "is_periodic", "is_overhaul", "warn_threshold",
            "task_threshold", "description",
        ):
            val = getattr(body, field, None)
            if val is not None:
                setattr(iv, field, val)

        await session.commit()
        return {"status": "updated", "interval_id": iv.id}


# ---------------------------------------------------------------------------
#  17. POST /cards/{id}/intervals — add new interval
# ---------------------------------------------------------------------------

@router.post("/cards/{card_id}/intervals")
async def create_interval(card_id: int, body: CreateIntervalBody):
    """Add a new interval to a card."""
    async with async_session() as session:
        card = await session.get(MaintenanceCardV2, card_id)
        if not card:
            raise HTTPException(404, "Card not found")

        # Determine sort_order
        max_order = (await session.execute(
            select(func.max(CardInterval.sort_order)).where(CardInterval.card_id == card_id)
        )).scalar() or 0

        iv = CardInterval(
            card_id=card_id,
            name=body.name,
            code=body.code,
            interval_type=body.interval_type,
            interval_hours=body.interval_hours,
            interval_days=body.interval_days,
            labor_hours=body.labor_hours,
            is_periodic=body.is_periodic,
            is_overhaul=body.is_overhaul,
            sort_order=max_order + 1,
        )
        session.add(iv)
        await session.commit()
        await session.refresh(iv)
        return {"status": "created", "interval_id": iv.id}


# ---------------------------------------------------------------------------
#  18. DELETE /intervals/{id} — delete interval (cascades work items + spare parts)
# ---------------------------------------------------------------------------

@router.delete("/intervals/{interval_id}")
async def delete_interval(interval_id: int):
    """Delete interval and its work items + spare parts."""
    async with async_session() as session:
        iv = await session.get(CardInterval, interval_id)
        if not iv:
            raise HTTPException(404, "Interval not found")

        # Delete work items and spare parts first
        await session.execute(
            CardWorkItem.__table__.delete().where(CardWorkItem.interval_id == interval_id)
        )
        await session.execute(
            CardSparePart.__table__.delete().where(CardSparePart.interval_id == interval_id)
        )
        await session.delete(iv)
        await session.commit()
        return {"status": "deleted", "interval_id": interval_id}


# ---------------------------------------------------------------------------
#  19. PATCH /work-items/{id} — update work item
# ---------------------------------------------------------------------------

@router.patch("/work-items/{item_id}")
async def update_work_item(item_id: int, body: UpdateWorkItemBody):
    """Update work item description or photo settings."""
    async with async_session() as session:
        wi = await session.get(CardWorkItem, item_id)
        if not wi:
            raise HTTPException(404, "Work item not found")

        for body_field, model_field in [("work_description", "description")]:
            val = getattr(body, body_field, None)
            if val is not None:
                setattr(wi, model_field, val)
        for field in ():
            val = getattr(body, field, None)
            if val is not None:
                setattr(wi, field, val)

        await session.commit()
        return {"status": "updated", "item_id": wi.id}


# ---------------------------------------------------------------------------
#  20. POST /intervals/{id}/work-items — add work item
# ---------------------------------------------------------------------------

@router.post("/intervals/{interval_id}/work-items")
async def create_work_item(interval_id: int, body: CreateWorkItemBody):
    """Add a work item to an interval."""
    async with async_session() as session:
        iv = await session.get(CardInterval, interval_id)
        if not iv:
            raise HTTPException(404, "Interval not found")

        max_order = (await session.execute(
            select(func.max(CardWorkItem.sort_order)).where(CardWorkItem.interval_id == interval_id)
        )).scalar() or 0

        wi = CardWorkItem(
            interval_id=interval_id,
            description=body.work_description,
            requires_photo=body.requires_photo,
            photo_type=body.photo_type,
            sort_order=max_order + 1,
        )
        session.add(wi)
        await session.commit()
        await session.refresh(wi)
        return {"status": "created", "item_id": wi.id}


# ---------------------------------------------------------------------------
#  21. DELETE /work-items/{id} — delete work item
# ---------------------------------------------------------------------------

@router.delete("/work-items/{item_id}")
async def delete_work_item(item_id: int):
    """Delete a work item."""
    async with async_session() as session:
        wi = await session.get(CardWorkItem, item_id)
        if not wi:
            raise HTTPException(404, "Work item not found")

        await session.delete(wi)
        await session.commit()
        return {"status": "deleted", "item_id": item_id}


# ---------------------------------------------------------------------------
#  22. PATCH /spare-parts/{id} — update spare part
# ---------------------------------------------------------------------------

@router.patch("/spare-parts/{part_id}")
async def update_spare_part(part_id: int, body: UpdateSparePartBody):
    """Update spare part fields."""
    async with async_session() as session:
        sp = await session.get(CardSparePart, part_id)
        if not sp:
            raise HTTPException(404, "Spare part not found")

        field_map = {"part_name": "name", "part_number": "part_number", "quantity": "quantity", "unit": "unit"}
        for body_field, model_field in field_map.items():
            val = getattr(body, body_field, None)
            if val is not None:
                setattr(sp, model_field, val)

        await session.commit()
        return {"status": "updated", "part_id": sp.id}


# ---------------------------------------------------------------------------
#  23. POST /intervals/{id}/spare-parts — add spare part
# ---------------------------------------------------------------------------

@router.post("/intervals/{interval_id}/spare-parts")
async def create_spare_part(interval_id: int, body: CreateSparePartBody):
    """Add a spare part to an interval."""
    async with async_session() as session:
        iv = await session.get(CardInterval, interval_id)
        if not iv:
            raise HTTPException(404, "Interval not found")

        sp = CardSparePart(
            interval_id=interval_id,
            name=body.part_name,
            part_number=body.part_number,
            quantity=body.quantity,
            unit=body.unit,
        )
        session.add(sp)
        await session.commit()
        await session.refresh(sp)
        return {"status": "created", "part_id": sp.id}


# ---------------------------------------------------------------------------
#  24. DELETE /spare-parts/{id} — delete spare part
# ---------------------------------------------------------------------------

@router.delete("/spare-parts/{part_id}")
async def delete_spare_part(part_id: int):
    """Delete a spare part."""
    async with async_session() as session:
        sp = await session.get(CardSparePart, part_id)
        if not sp:
            raise HTTPException(404, "Spare part not found")

        await session.delete(sp)
        await session.commit()
        return {"status": "deleted", "part_id": part_id}
