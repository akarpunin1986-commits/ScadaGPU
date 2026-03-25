"""
Maintenance Lifecycle v2.0 — Core lifecycle service.

Handles: equipment status, next maintenance determination, interval overlap,
maintenance recording with cascade, epoch resets, work item inheritance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.maintenance_lifecycle import (
    CardInterval,
    EquipmentCardLink,
    EpochHistory,
    MaintenanceCardV2,
    MaintenanceLogV2,
)
from models.equipment_unit import EquipmentUnit
from schemas.maintenance import EquipmentStatus, NextMaintenance

logger = logging.getLogger("scada.maintenance")

MAX_OVERLAP_CHECKS = 20
MAX_WORK_ITEM_DEPTH = 8


# ── Equipment status ─────────────────────────────────────────────────


async def get_equipment_status(
    equipment_id: int, session: AsyncSession
) -> EquipmentStatus:
    """Full status: operating_hours, next maintenance, upcoming list."""
    eq = (await session.execute(
        select(EquipmentUnit)
        .options(selectinload(EquipmentUnit.site))
        .where(EquipmentUnit.id == equipment_id)
    )).scalar_one_or_none()
    if not eq:
        raise ValueError(f"Equipment {equipment_id} not found")

    operating_hours = (eq.current_value or 0) - (eq.epoch_value or 0)
    days_since_epoch = (
        (datetime.utcnow() - eq.epoch_date).days if eq.epoch_date else 0
    )

    # Get site name (eager loaded)
    site_name = eq.site.name if eq.site else ""

    # Next & upcoming maintenance
    next_maint = await determine_next_maintenance(equipment_id, session)
    upcoming = await determine_all_upcoming(equipment_id, session)

    # Last maintenance
    last_log = (await session.execute(
        select(MaintenanceLogV2)
        .where(MaintenanceLogV2.equipment_id == equipment_id)
        .order_by(MaintenanceLogV2.performed_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    # Determine status
    status = "no_card"
    if upcoming:
        if any(u.urgency_score <= 0 for u in upcoming):
            status = "overdue"
        elif any(u.urgency_score <= 1.0 for u in upcoming):
            status = "warning"
        else:
            status = "ok"
    else:
        # Check if any cards linked
        link_count = (await session.execute(
            select(func.count(EquipmentCardLink.id)).where(
                and_(
                    EquipmentCardLink.equipment_id == equipment_id,
                    EquipmentCardLink.is_active.is_(True),
                )
            )
        )).scalar() or 0
        if link_count > 0:
            status = "ok"

    return EquipmentStatus(
        equipment_id=eq.id,
        equipment_name=eq.name,
        equipment_type=eq.unit_type,
        site_name=site_name,
        hours_source=eq.hours_source,
        current_value=eq.current_value,
        epoch_value=eq.epoch_value,
        operating_hours=operating_hours,
        days_since_epoch=days_since_epoch,
        responsible_name=eq.responsible_name,
        next_maintenance=next_maint,
        upcoming=upcoming,
        last_maintenance_date=last_log.performed_date if last_log else None,
        last_maintenance_code=last_log.interval_code if last_log else None,
        status=status,
    )


# ── Next maintenance ─────────────────────────────────────────────────


async def determine_next_maintenance(
    equipment_id: int, session: AsyncSession
) -> Optional[NextMaintenance]:
    """Find the single most urgent next maintenance."""
    upcoming = await determine_all_upcoming(equipment_id, session, limit=1)
    return upcoming[0] if upcoming else None


async def determine_all_upcoming(
    equipment_id: int, session: AsyncSession, limit: int = 5
) -> list[NextMaintenance]:
    """ALL upcoming maintenance sorted by urgency_score ASC (most urgent first)."""
    eq = (await session.execute(
        select(EquipmentUnit).where(EquipmentUnit.id == equipment_id)
    )).scalar_one_or_none()
    if not eq:
        return []

    operating_hours = eq.current_value - eq.epoch_value
    days_since_epoch = (
        (datetime.utcnow() - eq.epoch_date).days if eq.epoch_date else 0
    )

    # Get all active card links
    links = (await session.execute(
        select(EquipmentCardLink).where(
            and_(
                EquipmentCardLink.equipment_id == equipment_id,
                EquipmentCardLink.is_active.is_(True),
            )
        )
    )).scalars().all()

    if not links:
        return []

    # Build last-done map: {interval_code: MaintenanceLogV2}
    logs = (await session.execute(
        select(MaintenanceLogV2)
        .where(MaintenanceLogV2.equipment_id == equipment_id)
        .order_by(MaintenanceLogV2.performed_date.desc())
    )).scalars().all()

    last_done_map: dict[str, MaintenanceLogV2] = {}
    for log_entry in logs:
        if log_entry.interval_code not in last_done_map:
            last_done_map[log_entry.interval_code] = log_entry

    results: list[NextMaintenance] = []

    for link in links:
        # Load card and its intervals
        card = (await session.execute(
            select(MaintenanceCardV2).where(MaintenanceCardV2.id == link.card_id)
        )).scalar_one_or_none()
        if not card or card.status != "active":
            continue

        intervals = (await session.execute(
            select(CardInterval)
            .where(CardInterval.card_id == card.id)
            .order_by(CardInterval.sort_order)
        )).scalars().all()

        # Intervals from the SAME card (for overlap checks)
        same_card_intervals = list(intervals)

        # hours_per_day for calendar equipment with hours intervals
        hours_per_day = 0
        if eq.hours_source == "calendar":
            config = eq.hours_source_config or {}
            hours_per_day = config.get("hours_per_day", 0)

        for interval in intervals:
            point = _calc_next_point(
                interval=interval,
                operating_hours=operating_hours,
                days_since_epoch=days_since_epoch,
                last_done_map=last_done_map,
                same_card_intervals=same_card_intervals,
                hours_per_day=hours_per_day,
            )
            if point:
                point.card_name = card.name
                results.append(point)

    # Sort by urgency (lower = more urgent, negative = overdue)
    results.sort(key=lambda x: x.urgency_score)
    return results[:limit]


# ── Internal calculation ──────────────────────────────────────────────


def _calc_next_point(
    interval: CardInterval,
    operating_hours: int,
    days_since_epoch: int,
    last_done_map: dict[str, MaintenanceLogV2],
    same_card_intervals: list[CardInterval],
    hours_per_day: int = 0,
) -> Optional[NextMaintenance]:
    """Calculate next maintenance point for one interval."""
    itype = interval.interval_type
    ih = interval.interval_hours
    idays = interval.interval_days
    code = interval.code

    # Warn thresholds (fallback to config import deferred)
    from config import settings
    warn_h = interval.warn_threshold or settings.MAINT_HOURS_WARN
    warn_d = interval.warn_threshold or settings.MAINT_DAYS_WARN

    if itype == "hours":
        if not ih or ih <= 0:
            return None

        # For calendar equipment with hours intervals: virtual hours
        effective_hours = operating_hours
        if hours_per_day > 0 and operating_hours == 0:
            effective_hours = days_since_epoch * hours_per_day

        next_threshold = _find_next_own_threshold(
            interval, effective_hours, same_card_intervals
        )
        if next_threshold is None:
            return None

        remaining = next_threshold - effective_hours
        urgency_score = remaining / warn_h if warn_h > 0 else remaining

        return NextMaintenance(
            interval_name=interval.name,
            interval_code=code,
            interval_type=itype,
            remaining_hours=remaining,
            urgency_score=round(urgency_score, 3),
            target_value=next_threshold,
        )

    elif itype == "calendar_days":
        if not idays or idays <= 0:
            return None

        last_done = last_done_map.get(code)
        if last_done:
            days_since_last = (datetime.utcnow() - last_done.performed_date).days
        else:
            days_since_last = days_since_epoch

        remaining = idays - days_since_last
        urgency_score = remaining / warn_d if warn_d > 0 else remaining

        return NextMaintenance(
            interval_name=interval.name,
            interval_code=code,
            interval_type=itype,
            remaining_days=remaining,
            urgency_score=round(urgency_score, 3),
        )

    elif itype == "hours_or_days":
        # Calculate both, return the more urgent one
        hours_point = None
        days_point = None

        if ih and ih > 0:
            effective_hours = operating_hours
            if hours_per_day > 0 and operating_hours == 0:
                effective_hours = days_since_epoch * hours_per_day

            next_h = _find_next_own_threshold(interval, effective_hours, same_card_intervals)
            if next_h is not None:
                rem_h = next_h - effective_hours
                urg_h = rem_h / warn_h if warn_h > 0 else rem_h
                hours_point = NextMaintenance(
                    interval_name=interval.name,
                    interval_code=code,
                    interval_type="hours",
                    remaining_hours=rem_h,
                    urgency_score=round(urg_h, 3),
                    target_value=next_h,
                )

        if idays and idays > 0:
            last_done = last_done_map.get(code)
            if last_done:
                ds = (datetime.utcnow() - last_done.performed_date).days
            else:
                ds = days_since_epoch
            rem_d = idays - ds
            urg_d = rem_d / warn_d if warn_d > 0 else rem_d
            days_point = NextMaintenance(
                interval_name=interval.name,
                interval_code=code,
                interval_type="calendar_days",
                remaining_days=rem_d,
                urgency_score=round(urg_d, 3),
            )

        # Return the more urgent one
        if hours_point and days_point:
            return hours_point if hours_point.urgency_score <= days_point.urgency_score else days_point
        return hours_point or days_point

    elif itype == "once":
        # Check if done in current cycle (since last epoch)
        last_done = last_done_map.get(code)
        if last_done:
            # If done after epoch_date, skip
            return None
        # Not done yet — urgent
        return NextMaintenance(
            interval_name=interval.name,
            interval_code=code,
            interval_type=itype,
            remaining_hours=0,
            urgency_score=-1.0,  # overdue
        )

    return None


def _get_highest_interval_at_point(
    hours: int, same_card_intervals: list[CardInterval]
) -> Optional[CardInterval]:
    """At this hours mark — which is the largest interval that's a multiple?

    Example: at 2000h with TO-1(500h), TO-2(1000h), TO-3(2000h) → returns TO-3.
    """
    candidates = []
    for iv in same_card_intervals:
        if iv.interval_type not in ("hours", "hours_or_days"):
            continue
        if not iv.interval_hours or iv.interval_hours <= 0:
            continue
        if hours % iv.interval_hours == 0:
            candidates.append(iv)

    if not candidates:
        return None
    # Return the one with the highest interval_hours
    return max(candidates, key=lambda x: x.interval_hours or 0)


def _find_next_own_threshold(
    interval: CardInterval,
    operating_hours: int,
    same_card_intervals: list[CardInterval],
) -> Optional[int]:
    """Find next threshold where this interval is NOT overlapped by a larger one.

    Max 20 checks to prevent infinite loops.
    """
    ih = interval.interval_hours
    if not ih or ih <= 0:
        return None

    # Next base threshold
    if operating_hours <= 0:
        next_val = ih
    else:
        next_val = ((operating_hours // ih) + 1) * ih

    for _ in range(MAX_OVERLAP_CHECKS):
        highest = _get_highest_interval_at_point(next_val, same_card_intervals)
        if highest is None or highest.id == interval.id:
            # No overlap or this IS the highest — this is our threshold
            return next_val
        if (highest.interval_hours or 0) <= (ih or 0):
            # We are the highest or equal
            return next_val
        # Overlapped by a larger interval, skip to next
        next_val += ih

    # Exhausted checks — return the last value
    logger.warning(
        "Overlap check exhausted for interval %s (code=%s) at %d hours",
        interval.name, interval.code, operating_hours,
    )
    return next_val


# ── Record maintenance ────────────────────────────────────────────────


async def record_maintenance(
    equipment_id: int,
    interval_code: str,
    performed_by: str,
    performed_date: datetime,
    session: AsyncSession,
    notes: str | None = None,
    scada_task_id: int | None = None,
    performed_by_bitrix_id: int | None = None,
) -> MaintenanceLogV2:
    """Record maintenance execution + CASCADE nested intervals."""
    # Deduplication by scada_task_id
    if scada_task_id:
        existing = (await session.execute(
            select(MaintenanceLogV2).where(
                and_(
                    MaintenanceLogV2.equipment_id == equipment_id,
                    MaintenanceLogV2.scada_task_id == scada_task_id,
                    MaintenanceLogV2.interval_code == interval_code,
                )
            )
        )).scalar_one_or_none()
        if existing:
            logger.info(
                "Duplicate maintenance record skipped: eq=%d, code=%s, task=%d",
                equipment_id, interval_code, scada_task_id,
            )
            return existing

    # Get equipment
    eq = (await session.execute(
        select(EquipmentUnit).where(EquipmentUnit.id == equipment_id)
    )).scalar_one_or_none()
    if not eq:
        raise ValueError(f"Equipment {equipment_id} not found")

    operating_hours = eq.current_value - eq.epoch_value
    days_since_epoch = (
        (datetime.utcnow() - eq.epoch_date).days if eq.epoch_date else 0
    )

    # Find interval by code (from any linked active card)
    links = (await session.execute(
        select(EquipmentCardLink).where(
            and_(
                EquipmentCardLink.equipment_id == equipment_id,
                EquipmentCardLink.is_active.is_(True),
            )
        )
    )).scalars().all()

    target_interval: CardInterval | None = None
    for link in links:
        iv = (await session.execute(
            select(CardInterval).where(
                and_(
                    CardInterval.card_id == link.card_id,
                    CardInterval.code == interval_code,
                )
            )
        )).scalar_one_or_none()
        if iv:
            target_interval = iv
            break

    # Create main log entry
    log_entry = MaintenanceLogV2(
        equipment_id=equipment_id,
        interval_id=target_interval.id if target_interval else None,
        interval_code=interval_code,
        value_at_maintenance=eq.current_value,
        operating_hours=operating_hours,
        days_at_maintenance=days_since_epoch,
        is_cascade=False,
        performed_date=performed_date,
        performed_by=performed_by,
        performed_by_bitrix_id=performed_by_bitrix_id,
        scada_task_id=scada_task_id,
        is_overhaul=target_interval.is_overhaul if target_interval else False,
        notes=notes,
    )
    session.add(log_entry)

    # CASCADE: record nested intervals (includes)
    if target_interval and target_interval.includes:
        for nested_code in target_interval.includes:
            cascade_iv = None
            for link in links:
                found = (await session.execute(
                    select(CardInterval).where(
                        and_(
                            CardInterval.card_id == link.card_id,
                            CardInterval.code == nested_code,
                        )
                    )
                )).scalar_one_or_none()
                if found:
                    cascade_iv = found
                    break

            cascade_log = MaintenanceLogV2(
                equipment_id=equipment_id,
                interval_id=cascade_iv.id if cascade_iv else None,
                interval_code=nested_code,
                value_at_maintenance=eq.current_value,
                operating_hours=operating_hours,
                days_at_maintenance=days_since_epoch,
                is_cascade=True,
                performed_date=performed_date,
                performed_by=performed_by,
                performed_by_bitrix_id=performed_by_bitrix_id,
                scada_task_id=scada_task_id,
                notes=f"Cascade from {interval_code}",
            )
            session.add(cascade_log)

    # If overhaul → reset epoch
    if target_interval and target_interval.is_overhaul:
        await reset_epoch(
            equipment_id=equipment_id,
            reason="overhaul",
            session=session,
            changed_by=performed_by,
            notes=f"Auto-reset after overhaul ({interval_code})",
        )

    await session.commit()
    logger.info(
        "Maintenance recorded: eq=%d, code=%s, hours=%d, by=%s",
        equipment_id, interval_code, operating_hours, performed_by,
    )
    return log_entry


# ── Epoch reset ───────────────────────────────────────────────────────


async def reset_epoch(
    equipment_id: int,
    reason: str,
    session: AsyncSession,
    changed_by: str | None = None,
    changed_by_bitrix_id: int | None = None,
    notes: str | None = None,
) -> EpochHistory:
    """Reset epoch: epoch_value = current_value, epoch_date = now()."""
    eq = (await session.execute(
        select(EquipmentUnit).where(EquipmentUnit.id == equipment_id)
    )).scalar_one_or_none()
    if not eq:
        raise ValueError(f"Equipment {equipment_id} not found")

    old_value = eq.epoch_value
    old_date = eq.epoch_date

    # Record history
    history = EpochHistory(
        equipment_id=equipment_id,
        old_epoch_value=old_value,
        new_epoch_value=eq.current_value,
        old_epoch_date=old_date,
        new_epoch_date=datetime.utcnow(),
        reason=reason,
        changed_by=changed_by,
        changed_by_bitrix_id=changed_by_bitrix_id,
        notes=notes,
    )
    session.add(history)

    # Update equipment
    eq.epoch_value = eq.current_value
    eq.epoch_date = datetime.utcnow()
    eq.epoch_reason = reason

    logger.info(
        "Epoch reset: eq=%d, old=%d, new=%d, reason=%s",
        equipment_id, old_value, eq.current_value, reason,
    )
    return history


# ── Work item inheritance ─────────────────────────────────────────────


async def get_all_work_items(
    interval_id: int,
    card_id: int,
    session: AsyncSession,
    _visited: set | None = None,
) -> list[dict]:
    """Recursively collect inherited work items.

    _visited set prevents cycles. Max depth MAX_WORK_ITEM_DEPTH.
    """
    if _visited is None:
        _visited = set()

    if interval_id in _visited:
        logger.warning("Cycle detected in work item inheritance: interval_id=%d", interval_id)
        return []
    if len(_visited) >= MAX_WORK_ITEM_DEPTH:
        logger.warning("Max depth reached in work item inheritance: interval_id=%d", interval_id)
        return []

    _visited.add(interval_id)

    # Get this interval's own work items
    from models.maintenance_lifecycle import CardWorkItem

    items_result = (await session.execute(
        select(CardWorkItem)
        .where(CardWorkItem.interval_id == interval_id)
        .order_by(CardWorkItem.sort_order)
    )).scalars().all()

    result = [
        {
            "id": wi.id,
            "interval_id": interval_id,
            "work_description": wi.work_description,
            "is_specific": wi.is_specific,
            "requires_photo": wi.requires_photo,
            "photo_type": wi.photo_type,
            "inherited": False,
        }
        for wi in items_result
    ]

    # Get interval to check includes
    interval = (await session.execute(
        select(CardInterval).where(CardInterval.id == interval_id)
    )).scalar_one_or_none()

    if interval and interval.includes:
        for included_code in interval.includes:
            # Find included interval in same card
            included_iv = (await session.execute(
                select(CardInterval).where(
                    and_(
                        CardInterval.card_id == card_id,
                        CardInterval.code == included_code,
                    )
                )
            )).scalar_one_or_none()

            if included_iv:
                inherited_items = await get_all_work_items(
                    included_iv.id, card_id, session, _visited
                )
                for item in inherited_items:
                    item["inherited"] = True
                result.extend(inherited_items)

    return result


# ── Dashboard ─────────────────────────────────────────────────────────


async def get_all_equipment_status(
    session: AsyncSession,
    site_id: int | None = None,
    equipment_type: str | None = None,
) -> list[EquipmentStatus]:
    """Dashboard: all equipment with maintenance status."""
    stmt = select(EquipmentUnit).where(EquipmentUnit.is_active.is_(True))
    if site_id:
        stmt = stmt.where(EquipmentUnit.site_id == site_id)
    if equipment_type:
        stmt = stmt.where(EquipmentUnit.unit_type == equipment_type)

    equipment_list = (await session.execute(stmt)).scalars().all()
    results = []

    for eq in equipment_list:
        try:
            status = await get_equipment_status(eq.id, session)
            results.append(status)
        except Exception as exc:
            logger.error("Failed to get status for equipment %d: %s", eq.id, exc)
            results.append(EquipmentStatus(
                equipment_id=eq.id,
                equipment_name=eq.name,
                equipment_type=eq.unit_type,
                site_name="",
                hours_source=eq.hours_source,
                current_value=eq.current_value,
                epoch_value=eq.epoch_value,
                operating_hours=eq.current_value - eq.epoch_value,
                days_since_epoch=0,
                responsible_name=eq.responsible_name,
                status="no_card",
            ))

    return results
