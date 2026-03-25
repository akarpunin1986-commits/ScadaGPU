"""
САНЁК v4 — Learning tools.

save_sop_entry — saves a resolved incident as SOP for future reference.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, func, or_

from models.base import async_session
from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek_v4.tools.learning")


@registry.tool(
    name="save_sop_entry",
    description=(
        "Сохранить решённый инцидент как SOP (Standard Operating Procedure). "
        "Вызывай когда оператор подтвердил решение проблемы и ты хочешь запомнить это. "
        "ОБЯЗАТЕЛЬНО: спроси у оператора подтверждение перед сохранением. "
        "В следующий раз при похожей проблеме ты найдёшь этот SOP через search_knowledge."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "incident_type": {
                "type": "string",
                "enum": ["alarm", "power_drop", "efficiency_drop", "maintenance",
                         "startup_issue", "communication_issue", "other"],
                "description": "Тип инцидента",
            },
            "device_id": {
                "type": "string",
                "description": "Устройство (mkz_gen1, yakz_gen2...)",
            },
            "alarm_code": {
                "type": "string",
                "description": "Код аларма если есть",
            },
            "symptoms": {
                "type": "object",
                "description": "Симптомы: ключевые метрики на момент инцидента. Пример: {\"coolant_temp_c\": 97, \"power_kw\": 95}",
            },
            "diagnosis": {
                "type": "string",
                "description": "Что оказалось причиной",
            },
            "resolution": {
                "type": "string",
                "description": "Что конкретно помогло решить проблему",
            },
            "resolution_time_minutes": {
                "type": "integer",
                "description": "Сколько заняло решение (минут)",
            },
            "resolved_by": {
                "type": "string",
                "description": "Кто решил (имя оператора/инженера)",
            },
        },
        "required": ["incident_type", "device_id", "symptoms", "diagnosis", "resolution"],
    },
)
async def save_sop_entry(
    incident_type: str,
    device_id: str,
    symptoms: dict,
    diagnosis: str,
    resolution: str,
    alarm_code: str | None = None,
    resolution_time_minutes: int | None = None,
    resolved_by: str | None = None,
) -> dict:
    """Save a resolved incident as SOP entry."""
    from models.sanek_sop_entry import SanekSopEntry
    from services.sanek_v4.device_map import DEVICE_MAP

    # Resolve site_code
    site_code = None
    dev_info = DEVICE_MAP.get(device_id)
    if dev_info:
        site_code = dev_info.get("site_code")

    try:
        from datetime import datetime, timedelta
        async with async_session() as db:
            # Check for duplicate (same device + same diagnosis in last 24h)
            cutoff = datetime.utcnow() - timedelta(hours=24)
            recent = await db.execute(
                select(func.count(SanekSopEntry.id)).where(
                    SanekSopEntry.device_id == device_id,
                    SanekSopEntry.diagnosis == diagnosis,
                    SanekSopEntry.created_at > cutoff,
                )
            )
            if recent.scalar_one() > 0:
                return {
                    "status": "duplicate",
                    "message": f"SOP с таким диагнозом для {device_id} уже записан за последние 24ч.",
                }

            entry = SanekSopEntry(
                incident_type=incident_type,
                device_id=device_id,
                site_code=site_code,
                alarm_code=alarm_code,
                symptoms=symptoms,
                diagnosis=diagnosis,
                resolution=resolution,
                resolution_time_minutes=resolution_time_minutes,
                resolved_by=resolved_by,
                confidence=0.6,  # operator-confirmed starts at 0.6
                source="dialog",
            )
            db.add(entry)
            await db.commit()
            await db.refresh(entry)

            return {
                "status": "saved",
                "sop_id": entry.id,
                "message": (
                    f"SOP #{entry.id} сохранён: {incident_type} на {device_id}. "
                    f"Диагноз: {diagnosis[:80]}. Решение: {resolution[:80]}. "
                    f"Confidence: 0.6. В следующий раз найду через search_knowledge."
                ),
            }

    except Exception as e:
        logger.exception("Failed to save SOP: %s", e)
        return {"error": f"Не удалось сохранить SOP: {str(e)}"}
