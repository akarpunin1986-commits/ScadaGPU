"""
САНЁК v3 — ProactiveMonitor.
Каждые 5 мин: L1 Python-проверки + Precursor-based predictions → Bitrix24 задача при critical.
"""
from __future__ import annotations
import asyncio, json, logging
from datetime import datetime, timedelta
from typing import Optional
from models.base import async_session
from models.device import Device
from models.device_type_registry import DeviceTypeRegistry
from sqlalchemy import select, and_

logger = logging.getLogger("sanek.proactive")

CHECK_INTERVAL = 300
COOLDOWN_SECONDS = 1800
LLM_COOLDOWN = 3600
BITRIX_WEBHOOK = "https://bricks-trade.bitrix24.ru/rest/102/a1452jp8xhqm1wu6"
BITRIX_GROUP_ID = 46
SITE_TO_SYSCODE = {3: "mkz_dgu1", 5: "yakz_dgu1"}


class ProactiveMonitor:
    def __init__(self):
        self._redis_cached = None

    async def _get_redis_client(self):
        if self._redis_cached is None:
            from services.redis_utils import _get_redis
            self._redis_cached = await _get_redis()
        return self._redis_cached

    async def run_forever(self):
        logger.info("ProactiveMonitor started, interval=%ds", CHECK_INTERVAL)
        await asyncio.sleep(60)
        while True:
            try:
                await self._check_all()
            except Exception as e:
                logger.error("ProactiveMonitor cycle: %s", e, exc_info=True)
            await asyncio.sleep(CHECK_INTERVAL)

    async def _check_all(self):
        redis = await self._get_redis_client()
        async with async_session() as db:
            devices = (await db.execute(select(Device).where(Device.is_active == True))).scalars().all()
            type_reg = {}
            for t in (await db.execute(select(DeviceTypeRegistry))).scalars().all():
                type_reg[t.type_code] = {"thresholds": t.thresholds or {}, "status_field": t.status_field, "running_status_code": t.running_status_code}

        problems = []
        for dev in devices:
            notes = getattr(dev, 'instance_notes', None) or ""
            if any(w in notes.lower() for w in ("ремонт", "плановый", "отключен")):
                continue
            dtype = dev.device_type.value
            ti = type_reg.get(dtype, {})
            raw = await redis.get(f"device:{dev.id}:metrics")
            if not raw:
                continue
            m = json.loads(raw)

            # Проверка 1: потеря связи
            if not m.get("online", False):
                problems.append({"device_id": dev.id, "device_name": dev.name, "site_id": dev.site_id, "severity": "warning", "type": "conn_lost", "message": f"Потеря связи: {dev.name}"})
                continue

            # Проверка 2: аварийный стоп
            sf = ti.get("status_field", "gen_status")
            if m.get(sf) == 12:
                problems.append({"device_id": dev.id, "device_name": dev.name, "site_id": dev.site_id, "severity": "critical", "type": "emergency_stop", "message": f"АВАРИЙНАЯ ОСТАНОВКА: {dev.name} (gen_status=12)"})

            # Проверка 3: пороги
            for mk, rules in ti.get("thresholds", {}).items():
                v = m.get(mk)
                if v is None:
                    continue
                viol = None
                if "critical" in rules and v >= rules["critical"]:
                    viol = ("critical", f"{mk}={v}>={rules['critical']}")
                elif "critical_low" in rules and v <= rules["critical_low"]:
                    viol = ("critical", f"{mk}={v}<={rules['critical_low']}")
                elif "warn" in rules and v >= rules["warn"]:
                    viol = ("warning", f"{mk}={v}>={rules['warn']}")
                elif "warn_low" in rules and v <= rules["warn_low"]:
                    viol = ("warning", f"{mk}={v}<={rules['warn_low']}")
                if viol:
                    problems.append({"device_id": dev.id, "device_name": dev.name, "site_id": dev.site_id, "severity": viol[0], "type": "threshold", "message": f"{dev.name}: {viol[1]}"})

            # ═══ SELF-LEARNING: Проверка 4 — Predictive Alerts ═══
            try:
                insights = await self._get_active_precursors()
                for insight in insights:
                    c = insight.content or {}
                    metric = c.get('precursor_metric')
                    trend = c.get('trend')
                    threshold = c.get('threshold_suggestion')
                    if not metric or not threshold:
                        continue
                    v = m.get(metric)
                    if v is None:
                        continue
                    triggered = (trend == 'rising' and v >= threshold) or \
                                (trend == 'falling' and v <= threshold)
                    if triggered and insight.confidence >= 0.7:
                        problems.append({
                            "device_id": dev.id,
                            "device_name": dev.name,
                            "site_id": dev.site_id,
                            "severity": "info",
                            "type": "predictive",
                            "message": f"⚡ ПРОГНОЗ: {dev.name} — {metric} {trend} "
                                       f"({v}), вероятен {insight.alarm_code} "
                                       f"в ближайшие 30 мин (confidence: {insight.confidence:.0%})"
                        })
            except Exception:
                pass  # learning_insights может не существовать ещё

        for p in problems:
            ck = f"sanek:proactive:cd:{p['device_id']}:{p['type']}"
            if await redis.exists(ck):
                continue
            await redis.set(ck, "1", ex=COOLDOWN_SECONDS)
            await self._notify(p, redis)
            if p["severity"] == "critical":
                await self._escalate_bitrix(p)

    async def _get_active_precursors(self):
        """Получить precursors из learning_insights."""
        try:
            from models.learning_insight import LearningInsight
            async with async_session() as db:
                return (await db.execute(
                    select(LearningInsight).where(and_(
                        LearningInsight.insight_type == "precursor",
                        LearningInsight.is_active == True,
                        LearningInsight.confidence >= 0.7
                    ))
                )).scalars().all()
        except Exception:
            return []

    async def _notify(self, problem, redis):
        try:
            await redis.publish("notifications", json.dumps({"type": "proactive_alert", "severity": problem["severity"], "device_id": problem["device_id"], "device_name": problem["device_name"], "message": problem["message"], "timestamp": datetime.utcnow().isoformat()}, ensure_ascii=False))
            logger.info("Proactive: %s", problem["message"])
        except Exception as e:
            logger.error("Notify: %s", e)

    async def _escalate_bitrix(self, problem):
        try:
            import httpx
            syscode = SITE_TO_SYSCODE.get(problem.get("site_id"))
            responsible_id = 102
            if syscode:
                try:
                    async with httpx.AsyncClient(timeout=10) as c:
                        resp = await c.get(f"{BITRIX_WEBHOOK}/lists.element.get", params={"IBLOCK_TYPE_ID": "lists", "IBLOCK_ID": 68, "FILTER[PROPERTY_338]": syscode})
                        data = resp.json().get("result", [])
                        if data:
                            pid = data[0].get("PROPERTY_340", {})
                            if isinstance(pid, dict):
                                responsible_id = int(list(pid.values())[0])
                            elif pid:
                                responsible_id = int(pid)
                except Exception:
                    pass

            async with httpx.AsyncClient(timeout=10) as c:
                check = await c.get(f"{BITRIX_WEBHOOK}/tasks.task.list", params={"filter[GROUP_ID]": BITRIX_GROUP_ID, "filter[TAG][]": f"device_{problem['device_id']}", "filter[!STATUS]": 5})
                existing = check.json().get("result", {}).get("tasks", [])
                if existing:
                    logger.info("Bitrix: task exists for device %d", problem["device_id"])
                    return

            async with httpx.AsyncClient(timeout=10) as c:
                result = await c.post(f"{BITRIX_WEBHOOK}/tasks.task.add", json={"fields": {
                    "TITLE": f"⚠️ АВАРИЯ: {problem['message'][:100]}",
                    "RESPONSIBLE_ID": responsible_id,
                    "GROUP_ID": BITRIX_GROUP_ID,
                    "PRIORITY": 2,
                    "DEADLINE": (datetime.utcnow() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S"),
                    "TAGS": ["АВАРИЯ", "SCADA", f"device_{problem['device_id']}"],
                    "DESCRIPTION": f"Автоматическое уведомление SCADA\n\nУстройство: {problem['device_name']} (ID: {problem['device_id']})\nТип: {problem['type']}\nВремя: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n\nПодробности в SCADA.",
                }})
                logger.info("Bitrix task created: %s", result.json())
        except Exception as e:
            logger.error("Bitrix escalation: %s", e)
