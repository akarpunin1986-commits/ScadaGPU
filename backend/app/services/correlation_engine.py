"""САНЁК v3 — CorrelationEngine. Precursors + threshold suggestions."""
from __future__ import annotations
import json, logging
from datetime import datetime, timedelta
from sqlalchemy import select, and_, func
from models.base import async_session
from models.alarm_event import AlarmEvent
from models.metrics_data import MetricsData
from models.device import Device, DeviceType
from models.learning_insight import LearningInsight
from models.feedback import SanekFeedback

logger = logging.getLogger("sanek.correlation")

MONITORED_METRICS = ['coolant_temp', 'oil_pressure', 'engine_speed', 'power_total']


async def run_correlation_analysis():
    logger.info("CorrelationEngine: starting weekly analysis")
    try:
        async with async_session() as db:
            cutoff = datetime.utcnow() - timedelta(days=60)
            repeating = (await db.execute(
                select(AlarmEvent.alarm_code, AlarmEvent.device_id, func.count().label("cnt"))
                .where(AlarmEvent.occurred_at >= cutoff)
                .group_by(AlarmEvent.alarm_code, AlarmEvent.device_id)
                .having(func.count() >= 3)
            )).all()

        for alarm_code, device_id, cnt in repeating:
            try:
                precursors = await _find_precursors(alarm_code, [device_id])
                for p in precursors:
                    await _save_insight("precursor", "correlation_engine",
                                       alarm_code=alarm_code, content=p,
                                       confidence=p['confidence'], sample_size=cnt)
            except Exception as e:
                logger.error("Precursor %s/%d: %s", alarm_code, device_id, e)

        await _check_threshold_suggestions()
        logger.info("CorrelationEngine: completed")
    except Exception as e:
        logger.error("CorrelationEngine: %s", e, exc_info=True)


async def _find_precursors(alarm_code: str, device_ids: list[int],
                           lookback_minutes: int = 30) -> list[dict]:
    async with async_session() as db:
        occurrences = (await db.execute(
            select(AlarmEvent.device_id, AlarmEvent.occurred_at)
            .where(and_(
                AlarmEvent.alarm_code == alarm_code,
                AlarmEvent.device_id.in_(device_ids),
                AlarmEvent.occurred_at >= datetime.utcnow() - timedelta(days=60)
            ))
        )).all()
        if len(occurrences) < 3:
            return []

        precursor_candidates = {}
        for device_id, occurred_at in occurrences:
            window_start = occurred_at - timedelta(minutes=lookback_minutes)
            rows = (await db.execute(
                select(MetricsData)
                .where(and_(
                    MetricsData.device_id == device_id,
                    MetricsData.timestamp.between(window_start, occurred_at)
                ))
                .order_by(MetricsData.timestamp)
            )).scalars().all()
            if len(rows) < 5:
                continue
            for field in MONITORED_METRICS:
                values = [getattr(r, field) for r in rows if getattr(r, field) is not None]
                if len(values) < 5:
                    continue
                third = len(values) // 3
                if third < 2:
                    continue
                avg_start = sum(values[:third]) / third
                avg_end = sum(values[-third:]) / third
                delta = avg_end - avg_start
                if abs(delta) > 0.1:
                    precursor_candidates.setdefault(field, []).append({
                        'start_avg': round(avg_start, 2), 'end_avg': round(avg_end, 2),
                        'trend': 'rising' if delta > 0 else 'falling', 'delta': round(delta, 2)
                    })

        precursors = []
        for field, observations in precursor_candidates.items():
            if len(observations) < 0.7 * len(occurrences):
                continue
            trends = [o['trend'] for o in observations]
            dominant = max(set(trends), key=trends.count)
            ratio = trends.count(dominant) / len(observations)
            if ratio >= 0.7:
                avg_delta = sum(o['delta'] for o in observations) / len(observations)
                avg_end = sum(o['end_avg'] for o in observations) / len(observations)
                precursors.append({
                    'precursor_metric': field, 'trend': dominant,
                    'avg_delta': round(avg_delta, 2),
                    'threshold_suggestion': round(avg_end, 1),
                    'lookback_minutes': lookback_minutes,
                    'confidence': round(ratio, 2), 'sample_size': len(occurrences)
                })
        return precursors


async def _check_threshold_suggestions():
    """False positives из фидбека → предложение коррекции порогов."""
    try:
        async with async_session() as db:
            cutoff = datetime.utcnow() - timedelta(days=60)
            # Используем assessment (реальное имя поля в нашей модели)
            feedbacks = (await db.execute(
                select(SanekFeedback)
                .where(SanekFeedback.created_at >= cutoff)
            )).scalars().all()

            by_alarm = {}
            for fb in feedbacks:
                # context может не существовать до миграции
                ctx = getattr(fb, 'context', None) or {}
                ac = ctx.get('alarm_code') if isinstance(ctx, dict) else None
                if not ac:
                    continue
                by_alarm.setdefault(ac, {'correct': 0, 'incorrect': 0})
                if fb.assessment == 'correct':
                    by_alarm[ac]['correct'] += 1
                elif fb.assessment == 'incorrect':
                    by_alarm[ac]['incorrect'] += 1

            for ac, counts in by_alarm.items():
                total = counts['correct'] + counts['incorrect']
                if total < 5:
                    continue
                false_rate = counts['incorrect'] / total
                if false_rate > 0.4:
                    await _save_insight(
                        "threshold_suggestion", "correlation_engine",
                        alarm_code=ac,
                        content={
                            'alarm_code': ac,
                            'reason': f"False positive rate: {false_rate:.0%} ({counts['incorrect']}/{total})",
                            'suggestion': 'Рассмотреть расширение порога или добавить исключение'
                        },
                        confidence=false_rate, sample_size=total
                    )
    except Exception as e:
        logger.error("Threshold suggestions: %s", e)


async def _save_insight(insight_type: str, source: str, alarm_code: str = None,
                        content: dict = None, confidence: float = 0.5, sample_size: int = 0):
    async with async_session() as db:
        key_field = (content or {}).get('precursor_metric', '')
        existing = (await db.execute(
            select(LearningInsight).where(and_(
                LearningInsight.insight_type == insight_type,
                LearningInsight.source == source,
                LearningInsight.alarm_code == alarm_code
            )).limit(5)
        )).scalars().all()
        for e in existing:
            if (e.content or {}).get('precursor_metric') == key_field or not key_field:
                e.content = content
                e.confidence = confidence
                e.sample_size = sample_size
                e.updated_at = datetime.utcnow()
                await db.commit()
                return
        db.add(LearningInsight(
            insight_type=insight_type, source=source,
            alarm_code=alarm_code, content=content or {},
            confidence=confidence, sample_size=sample_size
        ))
        await db.commit()
