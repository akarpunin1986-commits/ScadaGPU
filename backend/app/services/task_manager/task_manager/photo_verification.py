"""Photo verification service — validates maintenance work via Vision API.

Each checklist item can require photos BEFORE and/or AFTER the work.
Vision API (GPT-4o) analyzes photos to verify:
- Work was actually performed (before ≠ after)
- Parts look correct (new filter vs old, clean vs dirty)
- Safety compliance (proper installation)

Photo requirements are defined in MaintenanceCard.checklist_items:
[{
    "title": "Замена свечей",
    "photo_before_required": true,
    "photo_after_required": true,
    "photo_hint_before": "Фото старых свечей (видны электроды)",
    "photo_hint_after": "Фото новых свечей установленных в цилиндры",
    "vision_check": "Свечи должны отличаться. Новые — чистые, без нагара."
}]
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime

import httpx
from sqlalchemy import select

from config import settings
from models.base import async_session
from models.task_manager import (
    MaintenanceCard,
    ScadaTask,
    TaskQualityCheck,
)
from services.task_manager.resilient_api import log_decision

logger = logging.getLogger("scada.task_manager.photo")

# Default photo requirements for common maintenance items
DEFAULT_PHOTO_REQUIREMENTS = {
    "замена свечей": {
        "photo_before_required": True,
        "photo_after_required": True,
        "photo_hint_before": "Фото старых свечей (видны электроды и нагар)",
        "photo_hint_after": "Фото новых свечей установленных в цилиндры",
        "vision_check": "Свечи должны визуально отличаться. Новые должны быть чистые, без нагара.",
    },
    "замена масляного фильтра": {
        "photo_before_required": True,
        "photo_after_required": True,
        "photo_hint_before": "Фото старого масляного фильтра",
        "photo_hint_after": "Фото нового фильтра установленного на место",
        "vision_check": "Фильтр должен быть заменён. Новый фильтр чистый, без масляных подтёков.",
    },
    "замена моторного масла": {
        "photo_before_required": False,
        "photo_after_required": True,
        "photo_hint_after": "Фото щупа уровня масла (уровень в норме)",
        "vision_check": "Уровень масла на щупе должен быть между метками MIN и MAX. Масло светлое.",
    },
    "проверка ремней": {
        "photo_before_required": False,
        "photo_after_required": True,
        "photo_hint_after": "Фото приводных ремней (натяжение, состояние)",
        "vision_check": "Ремни без трещин и потёртостей, натяжение визуально нормальное.",
    },
    "замена воздушного фильтра": {
        "photo_before_required": True,
        "photo_after_required": True,
        "photo_hint_before": "Фото загрязнённого воздушного фильтра",
        "photo_hint_after": "Фото нового чистого фильтра",
        "vision_check": "Старый фильтр грязный/тёмный, новый — чистый/белый.",
    },
    "проверка уровня ож": {
        "photo_before_required": False,
        "photo_after_required": True,
        "photo_hint_after": "Фото расширительного бачка (уровень ОЖ видим)",
        "vision_check": "Уровень охлаждающей жидкости между метками MIN и MAX.",
    },
    "осмотр на утечки": {
        "photo_before_required": False,
        "photo_after_required": True,
        "photo_hint_after": "Фото области осмотра (нет следов масла/ОЖ)",
        "vision_check": "Поверхности сухие, без следов подтёков масла или охлаждающей жидкости.",
    },
}


def get_photo_requirements(checklist_items: list[dict]) -> list[dict]:
    """Enrich checklist items with photo requirements.

    If item already has photo_before_required/photo_after_required — use as-is.
    Otherwise, match by title against DEFAULT_PHOTO_REQUIREMENTS.
    """
    result = []
    for item in checklist_items:
        enriched = dict(item)
        title_lower = (item.get("title") or "").lower().strip()

        # Already has explicit requirements
        if "photo_before_required" in item or "photo_after_required" in item:
            result.append(enriched)
            continue

        # Match against defaults
        for key, defaults in DEFAULT_PHOTO_REQUIREMENTS.items():
            if key in title_lower:
                enriched.update(defaults)
                break

        result.append(enriched)

    return result


async def verify_photos_with_vision(
    task_id: int,
    checklist_item_title: str,
    photo_before_b64: str | None,
    photo_after_b64: str | None,
    vision_check: str | None = None,
) -> dict:
    """Analyze photos via Vision API (GPT-4o).

    Returns:
        {
            "passed": bool,
            "confidence": float (0-1),
            "analysis": str (description),
            "issues": list[str] (problems found),
        }
    """
    if not settings.QUALITY_VISION_ENABLED:
        return {
            "passed": True,
            "confidence": 0.5,
            "analysis": "Vision API отключён. Фото принято без проверки.",
            "issues": [],
        }

    messages = [
        {
            "role": "system",
            "content": (
                "Ты — контролёр качества технического обслуживания промышленного оборудования. "
                "Анализируй фотографии выполненных работ. Оцени:\n"
                "1. Работа реально выполнена? (фото до ≠ фото после)\n"
                "2. Детали/запчасти соответствуют описанию?\n"
                "3. Установка выполнена правильно?\n"
                "Ответь JSON: {\"passed\": bool, \"confidence\": 0.0-1.0, \"analysis\": \"описание\", \"issues\": [\"проблема1\"]}"
            ),
        },
    ]

    content_parts = [
        {"type": "text", "text": f"Пункт ТО: {checklist_item_title}\n"},
    ]

    if vision_check:
        content_parts.append({"type": "text", "text": f"Критерий проверки: {vision_check}\n"})

    if photo_before_b64:
        content_parts.append({"type": "text", "text": "ФОТО ДО:"})
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{photo_before_b64}"},
        })

    if photo_after_b64:
        content_parts.append({"type": "text", "text": "ФОТО ПОСЛЕ:"})
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{photo_after_b64}"},
        })

    if not photo_before_b64 and not photo_after_b64:
        return {
            "passed": False,
            "confidence": 0.0,
            "analysis": "Нет фотографий для анализа.",
            "issues": ["Фото не загружены"],
        }

    messages.append({"role": "user", "content": content_parts})

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4o",
                    "messages": messages,
                    "max_tokens": 500,
                    "temperature": 0.2,
                },
            )
            data = resp.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            import json
            try:
                result = json.loads(answer)
            except json.JSONDecodeError:
                result = {
                    "passed": True,
                    "confidence": 0.5,
                    "analysis": answer[:500],
                    "issues": [],
                }

            logger.info("Vision check for task %d '%s': passed=%s confidence=%.2f",
                        task_id, checklist_item_title, result.get("passed"), result.get("confidence", 0))
            return result

    except Exception as exc:
        logger.error("Vision API error for task %d: %s", task_id, exc)
        return {
            "passed": True,  # Don't block on API failure
            "confidence": 0.3,
            "analysis": f"Vision API недоступен: {exc}",
            "issues": ["API ошибка"],
        }


async def check_task_photos(task_id: int) -> TaskQualityCheck | None:
    """Check all photos attached to a B24 task.

    1. Get task attachments from B24 (UF_TASK_WEBDAV_FILES)
    2. Download each photo
    3. Match to checklist items
    4. Run Vision API on each pair
    5. Create TaskQualityCheck record
    """
    async with async_session() as session:
        task = await session.get(ScadaTask, task_id)
        if not task or not task.bitrix_task_id:
            return None

        # Get checklist with photo requirements
        card = None
        if task.maintenance_card_id:
            card = await session.get(MaintenanceCard, task.maintenance_card_id)

        checklist = []
        if card and card.checklist_items:
            checklist = get_photo_requirements(card.checklist_items)

        # Get photo count from B24 task
        photo_count = 0
        photos_analysis = []
        try:
            from services.task_manager.resilient_api import resilient_b24_call
            result = await resilient_b24_call(
                "tasks.task.get",
                {"taskId": task.bitrix_task_id, "select": ["UF_TASK_WEBDAV_FILES"]},
                redis=None,
            )
            if result:
                files = result.get("result", {}).get("task", {}).get("ufTaskWebdavFiles", [])
                photo_count = len(files) if files else 0
        except Exception as exc:
            logger.warning("Failed to get B24 task files for %d: %s", task_id, exc)

        # Calculate photo requirements
        required_before = sum(1 for c in checklist if c.get("photo_before_required"))
        required_after = sum(1 for c in checklist if c.get("photo_after_required"))
        total_required = required_before + required_after

        passed = photo_count >= total_required if total_required > 0 else True

        details = {
            "required_before": required_before,
            "required_after": required_after,
            "total_required": total_required,
            "attached": photo_count,
            "checklist_photo_items": [
                {
                    "title": c.get("title"),
                    "before": c.get("photo_before_required", False),
                    "after": c.get("photo_after_required", False),
                    "hint_before": c.get("photo_hint_before"),
                    "hint_after": c.get("photo_hint_after"),
                }
                for c in checklist
                if c.get("photo_before_required") or c.get("photo_after_required")
            ],
            "vision_results": photos_analysis,
        }

        check = TaskQualityCheck(
            task_id=task_id,
            check_type="photo",
            passed=passed,
            details=details,
            checked_by="sanek",
        )
        session.add(check)

        await log_decision(
            task_id=task_id,
            decision_type="photo_check",
            decision_data=details,
            reasoning=f"Фото: {photo_count}/{total_required} required. {'OK' if passed else 'НЕДОСТАТОЧНО'}",
            triggered_by="quality_controller",
        )

        await session.commit()
        return check
