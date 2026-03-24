"""САНЁК v3 — ActionOutcomeTracker. Анализ 'до/после' каждого действия."""
from __future__ import annotations
import asyncio, json, logging
from datetime import datetime
from models.base import async_session
from models.sanek_action import SanekAction
from models.sanek_memory import SanekMemory

logger = logging.getLogger("sanek.outcomes")

CHECKPOINTS = [5, 15, 60]  # минут после действия


class ActionOutcomeTracker:
    async def schedule_tracking(self, action_id: int):
        for minutes in CHECKPOINTS:
            asyncio.create_task(self._delayed_check(action_id, minutes))

    async def _delayed_check(self, action_id: int, delay_minutes: int):
        await asyncio.sleep(delay_minutes * 60)
        try:
            from services.redis_utils import _get_redis
            redis = await _get_redis()

            async with async_session() as db:
                action = await db.get(SanekAction, action_id)
                if not action:
                    return
                raw = await redis.get(f"device:{action.device_id}:metrics")
                after = json.loads(raw) if raw else {}
                before = (action.result or {}).get('_before_snapshot', {})
                analysis = self._compare(before, after, action.action_type)

                outcomes = getattr(action, 'outcome_analysis', None) or []
                outcomes.append({
                    'minutes_after': delay_minutes,
                    'timestamp': datetime.utcnow().isoformat(),
                    'metrics_after': {k: after.get(k) for k in
                        ['power_total', 'coolant_temp', 'oil_pressure', 'gen_status', 'engine_speed']},
                    'assessment': analysis['verdict'],
                    'details': analysis['details']
                })
                action.outcome_analysis = outcomes
                await db.commit()

                if delay_minutes == 60 and analysis['verdict'] == 'worse':
                    await self._record_negative_outcome(action, analysis)
        except Exception as e:
            logger.error("Outcome check %d/%dmin: %s", action_id, delay_minutes, e)

    def _compare(self, before: dict, after: dict, action_type: str) -> dict:
        if action_type == 'set_power_limit':
            target = before.get('_target_power')
            actual = after.get('power_total', 0)
            if target and abs(actual - target) < 10:
                return {'verdict': 'better', 'details': f'Мощность достигла {actual} кВт'}
            return {'verdict': 'same', 'details': f'Мощность {actual} кВт'}

        if action_type in ('start_generator', 'stop_generator'):
            expected = 9 if 'start' in action_type else 0
            actual = after.get('gen_status')
            if actual == expected:
                return {'verdict': 'better', 'details': f'gen_status={actual} как ожидалось'}
            if actual == 12:
                return {'verdict': 'worse', 'details': 'Аварийный стоп после действия!'}
            return {'verdict': 'same', 'details': f'gen_status={actual}, ожидался {expected}'}

        return {'verdict': 'unknown', 'details': 'Не могу оценить'}

    async def _record_negative_outcome(self, action, analysis):
        try:
            from models.learning_insight import LearningInsight
            async with async_session() as db:
                db.add(LearningInsight(
                    insight_type="action_outcome", source="outcome_tracker",
                    alarm_code=None, device_type="generator",
                    content={
                        'action_type': action.action_type, 'action_params': action.params,
                        'verdict': analysis['verdict'], 'details': analysis['details'],
                        'device_id': action.device_id,
                    },
                    confidence=1.0, sample_size=1
                ))
                db.add(SanekMemory(
                    content=f"OUTCOME: {action.action_type} на device {action.device_id} — "
                            f"{analysis['verdict']}. {analysis['details']}",
                    category="fact", source="outcome_tracker"
                ))
                await db.commit()
        except Exception as e:
            logger.error("Record negative: %s", e)
