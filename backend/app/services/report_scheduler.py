"""САНЁК v3 — Scheduler: отчёты, GC, паттерны, корреляции."""
from __future__ import annotations
import json, logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, and_, func, delete
from models.base import async_session
from models.sanek_memory import SanekMemory
from models.alarm_event import AlarmEvent
from models.feedback import SanekPatternStats

logger = logging.getLogger("sanek.scheduler")


def setup_scheduler():
    s = AsyncIOScheduler(timezone="Europe/Moscow")
    s.add_job(daily_report, CronTrigger(hour=8, minute=0))
    s.add_job(weekly_report, CronTrigger(day_of_week="mon", hour=8, minute=0))
    s.add_job(memory_gc, CronTrigger(hour=3, minute=0))
    s.add_job(detect_patterns, CronTrigger(day_of_week="sun", hour=2))
    s.add_job(run_correlation_job, CronTrigger(day_of_week="sun", hour=3))
    s.add_job(decay_confidence, CronTrigger(day_of_week="sun", hour=4))
    s.start()
    logger.info("Scheduler started")
    return s


async def daily_report():
    try:
        from services.sanek_v4.tools import execute_tool
        from services.redis_utils import _get_redis
        mkz = await execute_tool("get_economics_report", {"site": "mkz", "last_days": 1})
        yakz = await execute_tool("get_economics_report", {"site": "yakz", "last_days": 1})
        alarms = await execute_tool("get_alarms", {"period": "24h"})
        redis = await _get_redis()
        await redis.publish("notifications", json.dumps({"type": "daily_report", "date": (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d"), "mkz": mkz, "yakz": yakz, "alarms": alarms}, ensure_ascii=False, default=str))
        logger.info("Daily report published")
    except Exception as e:
        logger.error("Daily report: %s", e)


async def weekly_report():
    try:
        from services.sanek_v4.tools import execute_tool
        from services.redis_utils import _get_redis
        mkz = await execute_tool("get_economics_report", {"site": "mkz", "last_days": 7})
        yakz = await execute_tool("get_economics_report", {"site": "yakz", "last_days": 7})
        redis = await _get_redis()
        await redis.publish("notifications", json.dumps({"type": "weekly_report", "mkz": mkz, "yakz": yakz}, ensure_ascii=False, default=str))
        logger.info("Weekly report published")
    except Exception as e:
        logger.error("Weekly report: %s", e)


async def memory_gc():
    """Удаляет ТОЛЬКО category='context' старше 30 дней. fact/instruction НЕ ТРОГАЕМ."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)
        async with async_session() as db:
            r = await db.execute(delete(SanekMemory).where(and_(SanekMemory.category == "context", SanekMemory.created_at < cutoff)))
            await db.commit()
            logger.info("GC: deleted %d context records", r.rowcount)
    except Exception as e:
        logger.error("GC: %s", e)


async def detect_patterns():
    """Повторяющиеся аварии: 3+ раз за 30 дней."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)
        async with async_session() as db:
            rows = (await db.execute(select(AlarmEvent.alarm_code, AlarmEvent.device_id, func.count().label("cnt")).where(AlarmEvent.occurred_at >= cutoff).group_by(AlarmEvent.alarm_code, AlarmEvent.device_id).having(func.count() >= 3))).all()
            for r in rows:
                pid = f"repeat:{r.device_id}:{r.alarm_code}"
                ex = (await db.execute(select(SanekPatternStats).where(SanekPatternStats.pattern_id == pid))).scalar_one_or_none()
                if ex:
                    ex.total_count = r.cnt
                    ex.updated_at = datetime.utcnow()
                else:
                    db.add(SanekPatternStats(pattern_id=pid, total_count=r.cnt, correct_count=0))
            await db.commit()
            logger.info("Patterns: %d repeating groups", len(rows))
    except Exception as e:
        logger.error("Patterns: %s", e)


async def run_correlation_job():
    """Еженедельный анализ корреляций и precursors."""
    try:
        from services.correlation_engine import run_correlation_analysis
        await run_correlation_analysis()
    except ImportError:
        logger.warning("correlation_engine not available yet")
    except Exception as e:
        logger.error("Correlation job: %s", e)


async def decay_confidence():
    """Паттерны без фидбека 30+ дней — decay confidence."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)
        async with async_session() as db:
            stale = (await db.execute(
                select(SanekPatternStats)
                .where(SanekPatternStats.updated_at < cutoff)
            )).scalars().all()
            for p in stale:
                p.correct_count = max(1, int(p.correct_count * 0.9))
                p.total_count = max(2, int(p.total_count * 0.9))
                p.updated_at = datetime.utcnow()
            await db.commit()
            logger.info("Decay: updated %d stale patterns", len(stale))
    except Exception as e:
        logger.error("Decay: %s", e)
