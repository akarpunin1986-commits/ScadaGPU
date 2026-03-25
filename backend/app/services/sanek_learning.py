"""САНЁК v3 — Feedback Loop & Learning.
Адаптировано к реальной модели SanekFeedback:
  - поле assessment (не feedback)
  - incident_id (FK)
  - session_id/message_index/correct_answer/context/feedback_detail — добавляются миграцией
"""
from __future__ import annotations
import logging
from datetime import datetime
from sqlalchemy import select, and_
from models.base import async_session
from models.feedback import SanekFeedback, SanekPatternStats
from models.sop_procedure import SopProcedure
from models.sanek_memory import SanekMemory

logger = logging.getLogger("sanek.learning")


async def process_feedback(session_id: str, message_index: int, feedback: str,
                           correct_answer: str = None, real_cause: str = None,
                           feedback_detail: str = None,
                           context: dict = None) -> dict:
    """
    feedback: "correct" | "incorrect" | "partial"
    feedback_detail: "wrong_cause" | "wrong_data" | "wrong_action" | "incomplete" | "hallucination"
    """
    context = context or {}
    pid = ""
    sop_created = False

    async with async_session() as db:
        # Записать фидбек — новые поля могут не существовать до миграции
        fb_kwargs = dict(
            incident_id=context.get("incident_id", 1),  # fallback для v3 без incident
            assessment=feedback,  # реальное имя поля в модели
            actual_root_cause=correct_answer,
            operator_notes=context.get("question", ""),
        )
        # Пробуем добавить новые поля (появятся после миграции)
        try:
            fb = SanekFeedback(**fb_kwargs)
            # Попробовать установить новые поля динамически
            if hasattr(fb, 'session_id'):
                fb.session_id = session_id
            if hasattr(fb, 'message_index'):
                fb.message_index = message_index
            if hasattr(fb, 'correct_answer'):
                fb.correct_answer = correct_answer
            if hasattr(fb, 'context'):
                fb.context = context
            if hasattr(fb, 'feedback_detail') and feedback_detail:
                fb.feedback_detail = feedback_detail
            db.add(fb)
        except Exception as e:
            logger.warning("Feedback save: %s", e)

        # Pattern stats — confidence scoring
        pid = ":".join(filter(None, [context.get("device_type"), context.get("alarm_code")]))
        if pid:
            p = (await db.execute(select(SanekPatternStats).where(SanekPatternStats.pattern_id == pid))).scalar_one_or_none()
            if p:
                p.total_count += 1
                if feedback == "correct":
                    p.correct_count += 1
                p.updated_at = datetime.utcnow()
                try:
                    if hasattr(p, 'last_context'):
                        p.last_context = context
                except Exception:
                    pass
            else:
                kwargs = dict(pattern_id=pid, total_count=1,
                    correct_count=1 if feedback == "correct" else 0)
                try:
                    kwargs["last_context"] = context
                    db.add(SanekPatternStats(**kwargs))
                except TypeError:
                    kwargs.pop("last_context", None)
                    db.add(SanekPatternStats(**kwargs))

        # Auto-SOP — создать/обновить при incorrect
        if feedback == "incorrect" and real_cause and context.get("alarm_code"):
            ac, dt = context["alarm_code"], context.get("device_type", "generator")
            existing = (await db.execute(select(SopProcedure).where(and_(
                SopProcedure.alarm_code == ac, SopProcedure.device_type == dt
            )))).scalar_one_or_none()

            if existing:
                existing.root_cause = real_cause
                existing.updated_at = datetime.utcnow()
                if hasattr(existing, 'source'):
                    existing.source = "feedback"
                # Обогатить actions на основе feedback_detail
                if feedback_detail == "wrong_action" and correct_answer:
                    existing.actions_json = [{"step": 1, "action": correct_answer}]
                elif feedback_detail == "incomplete" and correct_answer:
                    actions = existing.actions_json or []
                    actions.append({"step": len(actions) + 1, "action": correct_answer})
                    existing.actions_json = actions
            else:
                sop_kwargs = dict(alarm_code=ac, device_type=dt,
                    description="SOP из фидбека оператора", root_cause=real_cause,
                    actions_json=[{"step": 1, "action": f"Проверить: {real_cause}"}])
                try:
                    sop_kwargs["source"] = "feedback"
                    db.add(SopProcedure(**sop_kwargs))
                except TypeError:
                    sop_kwargs.pop("source", None)
                    db.add(SopProcedure(**sop_kwargs))
            sop_created = True

        # Запомнить коррекцию как hard fact
        if feedback == "incorrect" and correct_answer:
            db.add(SanekMemory(content=f"КОРРЕКЦИЯ: {context.get('question','?')} → {correct_answer}",
                               category="instruction", source="feedback"))

        # Hallucination — жёсткое правило
        if feedback_detail == "hallucination":
            db.add(SanekMemory(
                content=f"ЗАПРЕТ: Не выдумывать данные по {context.get('alarm_code', '?')}. "
                        f"Всегда вызывать tool для проверки.",
                category="instruction", source="feedback"))

        await db.commit()

    return {"status": "processed", "feedback": feedback, "pattern_id": pid,
            "sop_created": sop_created}
