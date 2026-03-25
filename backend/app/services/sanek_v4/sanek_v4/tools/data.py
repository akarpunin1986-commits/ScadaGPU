"""
САНЁК v4 — Data tools.

get_current_metrics — real-time metrics from Redis
get_metrics_history — historical data from PostgreSQL metrics_data
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, and_

from config import settings
from models.base import async_session
from models.metrics_data import MetricsData
from services.sanek_v4.device_map import resolve_device, DEVICE_MAP
from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek_v4.tools.data")

# ── Redis client ──

_redis_client = None

async def _get_redis():
    global _redis_client
    if _redis_client is None:
        from redis.asyncio import Redis as AioRedis
        _redis_client = AioRedis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


# ═══════════════════════════════════════════════════════════════
# TOOL: get_current_metrics
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_current_metrics",
    description=(
        "Получить текущие (последние) показания устройства в реальном времени. "
        "Возвращает: мощность (кВт), напряжение, ток, частоту, температуру ОЖ, "
        "давление масла, моточасы, расход топлива, статус, активные аварии. "
        "Для всех устройств сайта передай 'mkz_all' или 'yakz_all'. "
        "Для одного устройства: 'mkz_gen1', 'mkz_gen2', 'mkz_panel', "
        "'yakz_gen1', 'yakz_gen2', 'yakz_panel'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": (
                    "Идентификатор устройства. "
                    "Примеры: 'mkz_gen1', 'mkz_gen2', 'mkz_panel', "
                    "'yakz_gen1', 'yakz_gen2', 'yakz_panel'. "
                    "Для всех устройств сайта: 'mkz_all' или 'yakz_all'. "
                    "Для всей системы: 'all'."
                ),
            },
        },
        "required": ["device_id"],
    },
)
async def get_current_metrics(device_id: str) -> dict | list[dict]:
    """Fetch latest metrics from Redis for one or multiple devices."""
    resolved = resolve_device(device_id)

    if isinstance(resolved, list):
        results = []
        for dev in resolved:
            m = await _fetch_device_metrics(dev)
            results.append(m)
        return results

    return await _fetch_device_metrics(resolved)


async def _fetch_device_metrics(dev: dict) -> dict:
    """Read one device's current metrics from Redis."""
    redis = await _get_redis()
    raw = await redis.get(f"device:{dev['device_id']}:metrics")

    if not raw:
        return {
            "device": _dev_key(dev),
            "device_name": dev["name"],
            "status": "offline",
            "error": "No data in Redis (device may be offline)",
        }

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"device": _dev_key(dev), "error": "Invalid metrics data in Redis"}

    ts_str = data.get("timestamp", "")
    age_seconds = None
    if ts_str:
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age_seconds = int((datetime.utcnow() - ts.replace(tzinfo=None)).total_seconds())
        except Exception:
            pass

    # Determine status from gen_status field
    gen_status = data.get("gen_status")
    status = _status_label(gen_status, dev["type"])

    # Build compact metrics dict (only non-null, relevant fields)
    metrics = {}
    _add(metrics, "active_power_kw", data.get("power_total"))
    _add(metrics, "reactive_power_kvar", data.get("reactive_total"))
    _add(metrics, "voltage_ab", data.get("gen_uab"))
    _add(metrics, "frequency_hz", data.get("gen_freq"))
    _add(metrics, "current_a", data.get("current_a"))
    _add(metrics, "coolant_temp_c", data.get("coolant_temp"))
    _add(metrics, "oil_pressure_kpa", data.get("oil_pressure"))
    _add(metrics, "engine_hours", data.get("run_hours"))
    _add(metrics, "engine_rpm", data.get("engine_speed"))
    _add(metrics, "fuel_consumption_lph", data.get("fuel_consumption"))
    _add(metrics, "battery_voltage", data.get("battery_volt"))
    _add(metrics, "load_pct", data.get("load_pct"))
    _add(metrics, "energy_kwh", data.get("energy_kwh"))

    # ATS/panel specific
    if dev["type"] == "ats":
        _add(metrics, "mains_power_kw", data.get("mains_total_p"))
        _add(metrics, "mains_voltage_ab", data.get("mains_uab"))
        _add(metrics, "mains_frequency_hz", data.get("mains_freq"))
        _add(metrics, "busbar_power_kw", data.get("busbar_p"))
        _add(metrics, "multiset_total_kw", data.get("multiset_total_p"))

    # Active alarms
    alarms = []
    for key in ("alarm_common", "alarm_shutdown", "alarm_warning", "alarm_block"):
        v = data.get(key)
        if v and v not in (0, "0", False):
            alarms.append(key)

    result = {
        "device": _dev_key(dev),
        "device_name": dev["name"],
        "type": dev["type"],
        "controller": dev["controller"],
        "rated_kw": dev["rated_kw"],
        "status": status,
        "timestamp": ts_str,
        "age_seconds": age_seconds,
        "metrics": metrics,
    }
    if alarms:
        result["alarms_active"] = alarms
    return result


# ═══════════════════════════════════════════════════════════════
# TOOL: get_metrics_history
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_metrics_history",
    description=(
        "Получить историю метрик устройства за период. "
        "Возвращает агрегированные значения (avg, min, max) с автоматическим шагом. "
        "Используй для анализа трендов, поиска аномалий, сравнения периодов. "
        "Максимальный период — 90 дней."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "description": "Устройство (mkz_gen1, yakz_gen2 и т.д.)",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Список метрик. Примеры: ['power_total'], ['coolant_temp', 'oil_pressure']. "
                    "Доступные: power_total, reactive_total, gen_freq, current_a, "
                    "coolant_temp, oil_pressure, battery_volt, run_hours, engine_speed, "
                    "fuel_consumption, load_pct, energy_kwh, mains_total_p. "
                    "Пустой массив = power_total по умолчанию."
                ),
            },
            "period": {
                "type": "string",
                "description": (
                    "Период: '1h', '6h', '24h', '7d', '30d', '90d'. "
                    "Или конкретные даты: '2026-03-10..2026-03-18'."
                ),
            },
        },
        "required": ["device_id", "period"],
    },
)
async def get_metrics_history(
    device_id: str,
    period: str,
    metrics: list[str] | None = None,
) -> dict:
    """Query historical metrics from PostgreSQL with auto-aggregation."""
    dev = resolve_device(device_id)
    if isinstance(dev, list):
        return {"error": "Use specific device_id for history, not '_all'"}

    db_device_id = dev["device_id"]

    # Parse period
    now = datetime.utcnow()
    if ".." in period:
        parts = period.split("..")
        start = datetime.fromisoformat(parts[0])
        end = datetime.fromisoformat(parts[1]) if len(parts) > 1 else now
    else:
        delta_map = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
            "90d": timedelta(days=90),
        }
        delta = delta_map.get(period)
        if not delta:
            return {"error": f"Invalid period '{period}'. Use: 1h, 6h, 24h, 7d, 30d, 90d"}
        start = now - delta
        end = now

    # Determine aggregation step
    total_hours = (end - start).total_seconds() / 3600
    if total_hours <= 1:
        step_minutes = 1
    elif total_hours <= 6:
        step_minutes = 5
    elif total_hours <= 24:
        step_minutes = 15
    elif total_hours <= 24 * 7:
        step_minutes = 60
    else:
        step_minutes = 60 * 24  # daily

    # Default metrics
    if not metrics:
        metrics = ["power_total"]

    # Validate metric names against MetricsData columns
    valid_columns = {c.name for c in MetricsData.__table__.columns}
    for m in metrics:
        if m not in valid_columns:
            return {"error": f"Unknown metric '{m}'. Available: power_total, coolant_temp, oil_pressure, gen_freq, current_a, fuel_consumption, load_pct, energy_kwh, mains_total_p, etc."}

    # Build SQL with time-bucket aggregation
    step_interval = timedelta(minutes=step_minutes)
    result_data = {}

    async with async_session() as db:
        for metric_name in metrics:
            col = getattr(MetricsData, metric_name)

            # Get aggregated values per time bucket
            bucket_expr = func.date_trunc(
                'minute' if step_minutes < 60 else ('hour' if step_minutes < 1440 else 'day'),
                MetricsData.timestamp,
            )

            query = (
                select(
                    bucket_expr.label("bucket"),
                    func.avg(col).label("avg_val"),
                    func.min(col).label("min_val"),
                    func.max(col).label("max_val"),
                )
                .where(
                    and_(
                        MetricsData.device_id == db_device_id,
                        MetricsData.timestamp >= start,
                        MetricsData.timestamp <= end,
                        col.isnot(None),
                    )
                )
                .group_by("bucket")
                .order_by("bucket")
                .limit(500)
            )

            rows = (await db.execute(query)).all()

            if not rows:
                result_data[metric_name] = {"values": [], "min": None, "max": None, "avg": None, "trend": "no_data"}
                continue

            values = [round(float(r.avg_val), 2) if r.avg_val is not None else None for r in rows]
            timestamps = [r.bucket.strftime("%H:%M" if total_hours <= 48 else "%m-%d") for r in rows]
            all_mins = [float(r.min_val) for r in rows if r.min_val is not None]
            all_maxs = [float(r.max_val) for r in rows if r.max_val is not None]
            all_avgs = [float(r.avg_val) for r in rows if r.avg_val is not None]

            # Simple trend calculation (linear regression slope)
            trend = _calc_trend(all_avgs)

            result_data[metric_name] = {
                "values": values,
                "timestamps": timestamps,
                "min": round(min(all_mins), 2) if all_mins else None,
                "max": round(max(all_maxs), 2) if all_maxs else None,
                "avg": round(sum(all_avgs) / len(all_avgs), 2) if all_avgs else None,
                "trend": trend,
                "points": len(values),
            }

    step_label = f"{step_minutes}min" if step_minutes < 60 else f"{step_minutes // 60}h" if step_minutes < 1440 else "1d"

    return {
        "device": _dev_key(dev),
        "device_name": dev["name"],
        "period": f"{start.isoformat()}..{end.isoformat()}",
        "step": step_label,
        "data": result_data,
    }


# ── Helpers ──

def _dev_key(dev: dict) -> str:
    """Get the string key for a device dict."""
    for k, v in DEVICE_MAP.items():
        if v["device_id"] == dev["device_id"]:
            return k
    return f"device_{dev['device_id']}"


def _add(d: dict, key: str, val) -> None:
    """Add non-None value to dict, round floats."""
    if val is not None:
        try:
            d[key] = round(float(val), 2)
        except (TypeError, ValueError):
            d[key] = val


def _status_label(gen_status, device_type: str) -> str:
    """Convert gen_status code to human label."""
    if gen_status is None:
        return "unknown"
    try:
        code = int(gen_status)
    except (TypeError, ValueError):
        return str(gen_status)

    if device_type == "ats":
        return {0: "idle", 1: "active", 2: "switching"}.get(code, f"status_{code}")

    # HGM9520N gen_status codes
    labels = {
        0: "stopped", 1: "pre_heating", 2: "pre_oil", 3: "cranking",
        4: "safety_on", 5: "warming_up", 6: "running",
        7: "cooling_down", 8: "emergency_stop", 9: "post_lubrication",
        10: "stopped_fault", 11: "manual", 12: "derating",
        13: "idle_standby", 14: "auto_standby", 15: "test",
    }
    return labels.get(code, f"status_{code}")


def _calc_trend(values: list[float]) -> str:
    """Simple linear trend detection."""
    if len(values) < 3:
        return "insufficient_data"

    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n

    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return "stable"

    slope = numerator / denominator
    # Normalize slope relative to mean
    if y_mean == 0:
        return "stable"

    relative_change = abs(slope * n / y_mean)

    if relative_change < 0.03:
        return "stable"
    elif slope > 0:
        return "rising"
    else:
        return "falling"


# ═══════════════════════════════════════════════════════════════
# TOOL: get_economics_report
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_economics_report",
    description=(
        "Получить экономический отчёт площадки: газ, выработка, ПОЛНАЯ себестоимость "
        "(газ + постоянные затраты), тариф сети, экономия/убыток. "
        "ИСПОЛЬЗУЙ ЭТОТ TOOL для любых вопросов об экономике, себестоимости, расходах! "
        "Он даёт ТОЧНЫЕ цифры из раздела Экономика (включая плановые затраты: масло, "
        "запчасти, зарплата, лизинг и др.). НЕ считай себестоимость вручную — "
        "get_economics_report всегда точнее."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "site": {
                "type": "string",
                "enum": ["mkz", "yakz"],
                "description": "Площадка: 'mkz' (МКЗ, site_id=3) или 'yakz' (ЯКЗ, site_id=5).",
            },
            "last_days": {
                "type": "integer",
                "description": "Количество дней для отчёта (1-90). По умолчанию 7.",
            },
        },
        "required": ["site"],
    },
)
async def get_economics_report(site: str, last_days: int = 7) -> dict:
    """Fetch economics report from the existing SCADA economics API."""
    import httpx
    from services.sanek_v4.device_map import SITE_MAP

    site_info = SITE_MAP.get(site)
    if not site_info:
        return {"error": f"Unknown site '{site}'. Use 'mkz' or 'yakz'."}

    site_id = site_info["site_id"]
    last_days = max(1, min(90, last_days))

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"http://localhost:8000/api/economics/report/{site_id}",
                params={"last_days": last_days},
            )
            if resp.status_code != 200:
                return {"error": f"Economics API returned {resp.status_code}"}

            data = resp.json()
    except Exception as e:
        return {"error": f"Economics API error: {str(e)}"}

    days = data.get("days", [])
    totals = data.get("totals", {})

    # Build compact daily breakdown
    daily = []
    for d in days:
        daily.append({
            "date": d.get("date", ""),
            "energy_kwh": round(d.get("energy_kwh", 0), 1),
            "gas_m3": round(d.get("gas_m3", 0), 1),
            "gas_cost_rub": round(d.get("cost_rub", 0) or 0, 0),
            "gas_cost_per_kwh": d.get("cost_per_kwh", 0),
            "planned_costs_rub": round(d.get("planned_costs_rub", 0) or 0, 0),
            "full_cost_per_kwh": d.get("full_cost_per_kwh", 0),
            "grid_price_per_kwh": d.get("grid_price_per_kwh", 0),
            "devices": d.get("devices", []),
        })

    te = totals.get("energy_kwh", 0)
    tg = totals.get("gas_m3", 0)
    tc_gas = totals.get("total_cost", 0) or 0
    avg_gas_cost = totals.get("avg_cost_per_kwh", 0) or 0
    tc_planned = totals.get("planned_costs", 0) or 0
    tc_full = totals.get("full_cost", 0) or 0
    avg_full_cost = totals.get("avg_full_cost_per_kwh", 0) or 0
    avg_planned_cost = totals.get("avg_planned_cost_per_kwh", 0) or 0
    grid_price = totals.get("avg_grid_price_per_kwh", 0)
    if grid_price is None:
        grid_price = 8.0

    # Calculate savings vs grid using FULL cost
    cost_for_savings = avg_full_cost or avg_gas_cost
    savings = round(te * (grid_price - cost_for_savings), 0) if cost_for_savings and te else 0
    effect = "ЭКОНОМИЯ" if savings >= 0 else "УБЫТОК"

    return {
        "site": site,
        "site_name": site_info["name"],
        "period_days": last_days,
        "daily": daily,
        "totals": {
            "energy_kwh": round(te, 1),
            "gas_m3": round(tg, 1),
            "gas_cost_rub": round(tc_gas, 0),
            "avg_gas_cost_per_kwh": round(avg_gas_cost, 2),
            "planned_costs_rub": round(tc_planned, 0),
            "avg_planned_cost_per_kwh": round(avg_planned_cost, 2),
            "full_cost_rub": round(tc_full, 0),
            "avg_full_cost_per_kwh": round(avg_full_cost, 2),
            "grid_price_per_kwh": round(grid_price, 2),
            "savings_vs_grid_rub": savings,
            "effect": effect,
        },
    }
