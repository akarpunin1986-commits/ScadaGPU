"""EquipmentSync — syncs equipment roles from Bitrix24 list to Redis cache.

Single source of truth for WHO gets assigned to tasks.
Loads from Bitrix24 "Оборудование предприятия" (IBLOCK_ID=68) every hour.
"""
import asyncio
import json
import logging
from datetime import datetime

from redis.asyncio import Redis

from config import settings
from services.bitrix24.client import Bitrix24Client
from services.bitrix24.config import (
    PROP_SYSTEM_CODE, PROP_RESPONSIBLE, PROP_ACCOMPLICES,
    PROP_AUDITORS, PROP_MODEL, PROP_EQUIPMENT_TYPE, PROP_ACTIVE,
    ACTIVE_YES_ID, REDIS_EQUIPMENT_PREFIX, REDIS_EQUIPMENT_INDEX,
    REDIS_USER_PREFIX, USER_CACHE_TTL,
)

logger = logging.getLogger("scada.bitrix24.equipment")


class EquipmentSync:

    def __init__(self, client: Bitrix24Client, redis: Redis):
        self.client = client
        self.redis = redis
        self.last_sync_time: str | None = None
        self.cached_count: int = 0

    async def initial_sync(self) -> None:
        """Run sync once at startup."""
        try:
            await self._sync()
        except Exception as exc:
            logger.error("EquipmentSync initial sync failed: %s", exc)

    async def run_periodic(self) -> None:
        """Run sync every BITRIX24_SYNC_INTERVAL seconds."""
        while True:
            await asyncio.sleep(settings.BITRIX24_SYNC_INTERVAL)
            try:
                await self._sync()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("EquipmentSync periodic sync error: %s", exc)

    async def _sync(self) -> None:
        """Fetch equipment from Bitrix24 list, cache roles in Redis."""
        logger.info("EquipmentSync: starting sync...")
        elements = await self.client.get_list_elements(
            settings.BITRIX24_IBLOCK_TYPE_ID,
            settings.BITRIX24_IBLOCK_ID,
        )

        system_codes: list[str] = []
        ttl = settings.BITRIX24_SYNC_INTERVAL * 2

        for elem in elements:
            system_code = self._extract_prop(elem, PROP_SYSTEM_CODE)
            if not system_code:
                continue

            # Check active status
            active_val = self._extract_prop(elem, PROP_ACTIVE)
            is_active = str(active_val) == ACTIVE_YES_ID if active_val else True

            if not is_active:
                await self.redis.delete(
                    f"{REDIS_EQUIPMENT_PREFIX}{system_code}"
                )
                continue

            # Extract roles
            responsible_id = self._extract_user_id(elem, PROP_RESPONSIBLE)
            accomplice_ids = self._extract_user_ids(elem, PROP_ACCOMPLICES)
            auditor_ids = self._extract_user_ids(elem, PROP_AUDITORS)

            # Get user names (cached)
            responsible_name = await self._get_user_name(responsible_id) if responsible_id else None
            accomplice_names = [
                await self._get_user_name(uid)
                for uid in accomplice_ids
            ]
            auditor_names = [
                await self._get_user_name(uid)
                for uid in auditor_ids
            ]

            data = {
                "system_code": system_code,
                "name": elem.get("NAME", ""),
                "model": self._extract_prop(elem, PROP_MODEL) or "",
                "equipment_type": self._extract_prop(elem, PROP_EQUIPMENT_TYPE) or "",
                "section": elem.get("SECTION_NAME", elem.get("IBLOCK_SECTION_ID", "")),
                "active": is_active,
                "responsible_id": responsible_id,
                "responsible_name": responsible_name,
                "accomplice_ids": accomplice_ids,
                "accomplice_names": accomplice_names,
                "auditor_ids": auditor_ids,
                "auditor_names": auditor_names,
                "last_synced": datetime.utcnow().isoformat(),
            }

            await self.redis.setex(
                f"{REDIS_EQUIPMENT_PREFIX}{system_code}",
                ttl,
                json.dumps(data, default=str),
            )
            system_codes.append(system_code)

        # Update index
        await self.redis.setex(
            REDIS_EQUIPMENT_INDEX, ttl,
            json.dumps(system_codes),
        )

        self.cached_count = len(system_codes)
        self.last_sync_time = datetime.utcnow().isoformat()
        logger.info("EquipmentSync: cached %d equipment items", len(system_codes))

    async def get_roles(self, system_code: str) -> dict | None:
        """Get cached roles for equipment by system_code."""
        raw = await self.redis.get(f"{REDIS_EQUIPMENT_PREFIX}{system_code}")
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        return None

    async def get_all_equipment(self) -> list[dict]:
        """Get all cached equipment for dashboard."""
        raw_index = await self.redis.get(REDIS_EQUIPMENT_INDEX)
        if not raw_index:
            return []
        if isinstance(raw_index, bytes):
            raw_index = raw_index.decode("utf-8")
        codes = json.loads(raw_index)
        result = []
        for code in codes:
            data = await self.get_roles(code)
            if data:
                result.append(data)
        return result

    async def _get_user_name(self, user_id: int) -> str:
        """Get user name from cache or Bitrix24 API."""
        if not user_id:
            return ""

        cache_key = f"{REDIS_USER_PREFIX}{user_id}"
        cached = await self.redis.get(cache_key)
        if cached:
            if isinstance(cached, bytes):
                cached = cached.decode("utf-8")
            return cached

        user = await self.client.get_user(user_id)
        if user:
            name = f"{user.get('LAST_NAME', '')} {user.get('NAME', '')}".strip()
        else:
            name = f"User #{user_id}"

        await self.redis.setex(cache_key, USER_CACHE_TTL, name)
        return name

    @staticmethod
    def _extract_prop(elem: dict, prop_key: str):
        """Extract property value from Bitrix24 list element."""
        props = elem.get(prop_key, {})
        if isinstance(props, dict):
            # Universal list format: {field_id: {n0: value}}
            for field_id, val_dict in props.items():
                if isinstance(val_dict, dict):
                    return list(val_dict.values())[0] if val_dict else None
                return val_dict
        return props if props else None

    @staticmethod
    def _extract_user_id(elem: dict, prop_key: str) -> int | None:
        """Extract single user ID from property."""
        val = EquipmentSync._extract_prop(elem, prop_key)
        if val:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _extract_user_ids(elem: dict, prop_key: str) -> list[int]:
        """Extract multiple user IDs from property (multiple=yes)."""
        props = elem.get(prop_key, {})
        ids: list[int] = []
        if isinstance(props, dict):
            for field_id, val_dict in props.items():
                if isinstance(val_dict, dict):
                    for val in val_dict.values():
                        try:
                            ids.append(int(val))
                        except (ValueError, TypeError):
                            pass
                else:
                    try:
                        ids.append(int(val_dict))
                    except (ValueError, TypeError):
                        pass
        return ids
