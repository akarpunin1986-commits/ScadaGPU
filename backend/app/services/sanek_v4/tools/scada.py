"""
САНЁК v4 — SCADA tools.

get_alarms — active and historical alarm events
get_topology — system structure (sites, devices, statuses)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, and_, desc

from models.base import async_session
from models.alarm_event import AlarmEvent
from models.device import Device
from models.site import Site
from config import settings
from services.sanek_v4.device_map import resolve_device, DEVICE_MAP, SITE_MAP
from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek_v4.tools.scada")


# Lazy Redis
_redis_client = None

async def _get_redis():
    global _redis_client
    if _redis_client is None:
        from redis.asyncio import Redis as AioRedis
        _redis_client = AioRedis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


# ═══════════════════════════════════════════════════════════════
# TOOL: get_alarms
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_alarms",
    description=(
        "Получить аварии (алармы). "
        "Без параметров — все текущие активные аварии по всем устройствам. "
        "С device_id — только для конкретного устройства. "
        "С period — история аварий за период ('1h', '24h', '7d', '30d'). "
        "Используй для диагностики проблем и анализа надёжности."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": (
                    "Фильтр по устройству. Опционально. "
                    "Без него — аварии всех устройств. "
                    "Примеры: 'mkz_gen1', 'yakz_gen2', 'mkz_all'."
                ),
            },
            "period": {
                "type": "string",
                "description": (
                    "Период истории: '1h', '24h', '7d', '30d'. "
                    "Без этого — только текущие активные аварии."
                ),
            },
            "severity": {
                "type": "string",
                "enum": ["all", "error", "warning"],
                "description": "Фильтр по severity. По умолчанию 'all'.",
            },
        },
    },
)
async def get_alarms(
    device_id: str | None = None,
    period: str | None = None,
    severity: str = "all",
) -> dict:
    """Fetch active or historical alarms."""

    # Resolve device IDs
    db_device_ids = None
    if device_id:
        resolved = resolve_device(device_id)
        if isinstance(resolved, list):
            db_device_ids = [d["device_id"] for d in resolved]
        else:
            db_device_ids = [resolved["device_id"]]

    async with async_session() as db:
        if period:
            # Historical alarms
            delta_map = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}
            hours = delta_map.get(period)
            if not hours:
                return {"error": f"Invalid period '{period}'. Use: 1h, 24h, 7d, 30d"}

            cutoff = datetime.utcnow() - timedelta(hours=hours)
            conditions = [AlarmEvent.occurred_at >= cutoff]
        else:
            # Active alarms only
            conditions = [AlarmEvent.is_active.is_(True)]

        if db_device_ids:
            conditions.append(AlarmEvent.device_id.in_(db_device_ids))

        if severity != "all":
            conditions.append(AlarmEvent.severity == severity)

        query = (
            select(AlarmEvent)
            .where(and_(*conditions))
            .order_by(desc(AlarmEvent.occurred_at))
            .limit(50)
        )

        rows = (await db.execute(query)).scalars().all()

    # Build reverse device map (db_id → string key)
    id_to_key = {v["device_id"]: k for k, v in DEVICE_MAP.items()}

    alarms = []
    for a in rows:
        duration = None
        if a.cleared_at and a.occurred_at:
            duration = int((a.cleared_at - a.occurred_at).total_seconds())

        alarms.append({
            "device": id_to_key.get(a.device_id, f"device_{a.device_id}"),
            "alarm_code": a.alarm_code,
            "severity": a.severity,
            "message": a.message,
            "is_active": a.is_active,
            "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
            "cleared_at": a.cleared_at.isoformat() if a.cleared_at else None,
            "duration_seconds": duration,
        })

    # Also fetch detailed alarms from alarm_analytics_events
    detailed_alarms = []
    try:
        from alarm_analytics.models import AlarmAnalyticsEvent
        async with async_session() as db2:
            aa_conditions = []
            if period:
                aa_conditions.append(AlarmAnalyticsEvent.occurred_at >= cutoff)
            else:
                aa_conditions.append(AlarmAnalyticsEvent.is_active.is_(True))
            if db_device_ids:
                aa_conditions.append(AlarmAnalyticsEvent.device_id.in_(db_device_ids))

            aa_query = (
                select(AlarmAnalyticsEvent)
                .where(and_(*aa_conditions))
                .order_by(desc(AlarmAnalyticsEvent.occurred_at))
                .limit(50)
            )
            aa_rows = (await db2.execute(aa_query)).scalars().all()

            for aa in aa_rows:
                duration = None
                if aa.cleared_at and aa.occurred_at:
                    duration = int((aa.cleared_at - aa.occurred_at).total_seconds())
                detailed_alarms.append({
                    "device": id_to_key.get(aa.device_id, f"device_{aa.device_id}"),
                    "alarm_code": aa.alarm_code,
                    "alarm_name": aa.alarm_name,
                    "alarm_name_ru": aa.alarm_name_ru,
                    "severity": aa.alarm_severity,
                    "is_active": aa.is_active,
                    "occurred_at": aa.occurred_at.isoformat() if aa.occurred_at else None,
                    "cleared_at": aa.cleared_at.isoformat() if aa.cleared_at else None,
                    "duration_seconds": duration,
                    "analysis": aa.analysis_result,
                })
    except Exception as e:
        logger.warning("Failed to load alarm_analytics: %s", e)

    return {
        "mode": "active" if not period else f"history_{period}",
        "count": len(alarms),
        "alarms": alarms,
        "detailed_alarms_count": len(detailed_alarms),
        "detailed_alarms": detailed_alarms,
    }


# ═══════════════════════════════════════════════════════════════
# TOOL: get_topology
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_topology",
    description=(
        "Получить информацию об ОБОРУДОВАНИИ и площадках СКАДЫ: генераторы, контроллеры, "
        "устройства, сайты МКЗ/ЯКЗ, статусы, мощности. "
        "Вызывай когда юзер спрашивает про ОБОРУДОВАНИЕ: "
        "'какие генераторы', 'что на МКЗ', 'устройства ЯКЗ', 'топология', "
        "'структура СКАДЫ' (если про оборудование, не людей). "
        "НЕ вызывай для вопросов про сотрудников, отделы, должности — это get_company_info."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "site_id": {
                "type": "string",
                "description": "Фильтр по сайту: 'mkz' или 'yakz'. Без параметра — вся система.",
            },
        },
    },
)
async def get_topology(site_id: str | None = None) -> dict:
    """Get system topology with live status from Redis."""
    redis = await _get_redis()

    sites = []
    site_codes = [site_id] if site_id else ["mkz", "yakz"]

    for code in site_codes:
        site_info = SITE_MAP.get(code)
        if not site_info:
            continue

        devices = []
        for dev_key, dev in DEVICE_MAP.items():
            if dev["site_code"] != code:
                continue

            # Get live status from Redis
            raw = await redis.get(f"device:{dev['device_id']}:metrics")
            connection = "offline"
            status = "unknown"
            power = None

            if raw:
                try:
                    data = json.loads(raw)
                    connection = "online"
                    ts_str = data.get("timestamp", "")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        age = (datetime.utcnow() - ts.replace(tzinfo=None)).total_seconds()
                        if age > 30:
                            connection = "stale"

                    gen_status = data.get("gen_status")
                    if gen_status is not None:
                        status = "running" if int(gen_status) == 6 else "stopped" if int(gen_status) == 0 else f"status_{gen_status}"

                    power = data.get("power_total")
                    if power is not None:
                        power = round(float(power), 1)
                except Exception:
                    pass

            devices.append({
                "device_id": dev_key,
                "name": dev["name"],
                "type": dev["type"],
                "controller": dev["controller"],
                "rated_kw": dev["rated_kw"],
                "connection": connection,
                "status": status,
                "current_power_kw": power,
            })

        sites.append({
            "code": code,
            "name": site_info["name"],
            "rated_power_kw": site_info["rated_power_kw"],
            "devices": devices,
        })

    total_online = sum(
        1 for s in sites for d in s["devices"] if d["connection"] == "online"
    )
    total_devices = sum(len(s["devices"]) for s in sites)

    return {
        "sites": sites,
        "total_rated_power_kw": 640,
        "devices_online": total_online,
        "devices_total": total_devices,
    }
