"""
САНЁК v4 — Dynamic Device Map.

Loads device/site topology from DB, caches in Redis.
Module-level DEVICE_MAP and SITE_MAP are updated in-place
so all existing imports continue to work.

Fallback: static hardcoded values if DB unavailable.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("sanek.device_map")

CACHE_KEY = "sanek:device_map"
CACHE_TTL = 300  # 5 min

# ── Static fallback (used until first DB load) ──
DEVICE_MAP: dict[str, dict] = {
    "mkz_gen1":  {"device_id": 1, "site_id": 3, "site_code": "mkz", "name": "МКЗ Генератор 1", "type": "generator", "controller": "HGM9520N", "rated_kw": 160},
    "mkz_gen2":  {"device_id": 2, "site_id": 3, "site_code": "mkz", "name": "МКЗ Генератор 2", "type": "generator", "controller": "HGM9520N", "rated_kw": 160},
    "mkz_panel": {"device_id": 3, "site_id": 3, "site_code": "mkz", "name": "МКЗ ШПР (HGM9560)", "type": "ats", "controller": "HGM9560", "rated_kw": 0},
    "yakz_gen1":  {"device_id": 4, "site_id": 5, "site_code": "yakz", "name": "ЯКЗ Генератор 1", "type": "generator", "controller": "HGM9520N", "rated_kw": 160},
    "yakz_gen2":  {"device_id": 5, "site_id": 5, "site_code": "yakz", "name": "ЯКЗ Генератор 2", "type": "generator", "controller": "HGM9520N", "rated_kw": 160},
    "yakz_panel": {"device_id": 6, "site_id": 5, "site_code": "yakz", "name": "ЯКЗ ШПР (HGM9560)", "type": "ats", "controller": "HGM9560", "rated_kw": 0},
}

SITE_MAP: dict[str, dict] = {
    "mkz": {"site_id": 3, "name": "МКЗ (Моргаушский завод)", "rated_power_kw": 320},
    "yakz": {"site_id": 5, "name": "ЯКЗ (Ядринский завод)", "rated_power_kw": 320},
}

_loaded = False


# ── Public API ──

async def refresh_device_map() -> None:
    """Load device_map from DB (or Redis cache) and update module-level dicts in-place."""
    global _loaded
    try:
        # Try Redis cache first
        from services.redis_utils import get_redis
        redis = await get_redis()
        cached = await redis.get(CACHE_KEY)
        if cached:
            data = json.loads(cached)
            _apply(data)
            _loaded = True
            return

        # Load from DB
        data = await _load_from_db()
        if data["devices"]:
            _apply(data)
            _loaded = True
            # Cache in Redis
            await redis.set(CACHE_KEY, json.dumps(data, ensure_ascii=False), ex=CACHE_TTL)
            logger.info("Device map refreshed from DB: %d devices, %d sites",
                        len(data["devices"]), len(data["sites"]))
        else:
            logger.warning("DB returned 0 devices, keeping static fallback")
    except Exception as e:
        logger.warning("Failed to refresh device_map from DB: %s — using static fallback", e)


async def invalidate_cache() -> None:
    """Clear Redis cache — call after device/site CRUD."""
    try:
        from services.redis_utils import get_redis
        redis = await get_redis()
        await redis.delete(CACHE_KEY)
        # Also refresh in-memory maps immediately
        await refresh_device_map()
    except Exception as e:
        logger.warning("Failed to invalidate device_map cache: %s", e)


# ── Resolve helpers (unchanged API) ──

def resolve_device(device_id_str: str) -> dict | list[dict]:
    """
    Resolve string device ID to device info dict(s).

    mkz_gen1  -> single device dict
    mkz_all   -> list of all MKZ devices
    all       -> list of all devices
    """
    if device_id_str == "all":
        return list(DEVICE_MAP.values())

    if device_id_str.endswith("_all"):
        site_code = device_id_str.replace("_all", "")
        return [d for d in DEVICE_MAP.values() if d["site_code"] == site_code]

    dev = DEVICE_MAP.get(device_id_str)
    if not dev:
        available = ", ".join(sorted(DEVICE_MAP.keys()))
        raise ValueError(
            f"Device {device_id_str} not found. "
            f"Available: {available}"
        )
    return dev


def get_device_id(device_id_str: str) -> int:
    """Get numeric DB device_id from string ID."""
    dev = resolve_device(device_id_str)
    if isinstance(dev, list):
        raise ValueError(f"{device_id_str} resolves to multiple devices, use specific ID")
    return dev["device_id"]


# ── Internal ──

def _apply(data: dict) -> None:
    """Update module-level dicts in-place."""
    DEVICE_MAP.clear()
    DEVICE_MAP.update(data["devices"])
    SITE_MAP.clear()
    SITE_MAP.update(data["sites"])


async def _load_from_db() -> dict:
    """Load topology from PostgreSQL."""
    from sqlalchemy import select
    from models.base import async_session
    from models.device import Device
    from models.site import Site

    async with async_session() as db:
        sites = (await db.execute(select(Site).where(Site.is_active == True))).scalars().all()
        devices = (await db.execute(select(Device).where(Device.is_active == True))).scalars().all()

    # Build site_map: code -> info
    site_map = {}
    site_id_to_code = {}
    for s in sites:
        code = s.code.lower()
        site_id_to_code[s.id] = code
        # Sum rated_kw from generators
        rated = sum(160 for d in devices if d.site_id == s.id and d.device_type.value == "generator")
        site_map[code] = {
            "site_id": s.id,
            "name": s.name,
            "rated_power_kw": rated,
        }

    # Build device_map: string_key -> info
    device_map = {}
    device_counter: dict[str, int] = {}  # site_code -> gen counter
    for d in devices:
        site_code = site_id_to_code.get(d.site_id, f"site{d.site_id}")
        dtype = d.device_type.value if d.device_type else "unknown"

        if dtype == "generator":
            device_counter[site_code] = device_counter.get(site_code, 0) + 1
            key = f"{site_code}_gen{device_counter[site_code]}"
        elif dtype == "ats":
            key = f"{site_code}_panel"
        else:
            key = f"{site_code}_{dtype}_{d.id}"

        device_map[key] = {
            "device_id": d.id,
            "site_id": d.site_id,
            "site_code": site_code,
            "name": d.name,
            "type": dtype,
            "controller": _guess_controller(d),
            "rated_kw": 160 if dtype == "generator" else 0,
        }

    return {"devices": device_map, "sites": site_map}


def _guess_controller(device) -> str:
    """Guess controller type from device attributes."""
    if device.device_type and device.device_type.value == "ats":
        return "HGM9560"
    return "HGM9520N"
