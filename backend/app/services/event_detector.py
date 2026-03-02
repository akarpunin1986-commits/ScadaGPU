"""EventDetector — detects state transitions and persists to scada_events.

Subscribes to Redis PubSub 'metrics:updates'. Tracks:
- GEN_STATUS:   gen_status (0-15) changes
- MODE_CHANGE:  mode_auto/manual/test/stop flag changes
- ATS_STATUS:   gen_ats_status / mains_ats_status changes
- MAINS:        mains_normal / mains_load flag changes
- SYSTEM:       online True↔False transitions
"""
import asyncio
import json
import logging
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.scada_event import ScadaEvent
from models.device import Device

logger = logging.getLogger("scada.event_detector")


# ---------------------------------------------------------------------------
# Human-readable labels
# ---------------------------------------------------------------------------

GEN_STATUS_LABELS = {
    0: "Стоп (Standby)",
    1: "Подготовка к запуску",
    2: "Подача топлива",
    3: "Прокрутка стартером",
    4: "Пауза стартера",
    5: "Контроль запуска",
    6: "Холостой ход",
    7: "Прогрев",
    8: "Ожидание нагрузки",
    9: "Работа под нагрузкой",
    10: "Охлаждение",
    11: "Остановка ХХ",
    12: "Аварийный стоп (ETS)",
    13: "Ожидание остановки",
    14: "Постостановка",
    15: "Ошибка остановки",
}

MODE_LABELS = {
    "auto": "AUTO",
    "manual": "MANUAL",
    "test": "TEST",
    "stop": "STOP",
}

ATS_STATUS_LABELS = {
    0: "Синхронизация",
    1: "Задержка вкл.",
    2: "Ожидание вкл.",
    3: "Включён (Closed)",
    4: "Разгрузка",
    5: "Задержка откл.",
    6: "Ожидание откл.",
    7: "Отключён (Opened)",
}

GEN_STATUS_ICONS = {
    0: "⏹", 1: "🔄", 2: "⛽", 3: "🔧", 4: "⏸", 5: "🔍",
    6: "💨", 7: "🔥", 8: "⏳", 9: "⚡", 10: "❄", 11: "🛑",
    12: "🚨", 13: "⏳", 14: "✅", 15: "❌",
}


class EventDetector:

    def __init__(
        self,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.redis = redis
        self.session_factory = session_factory
        self._running = False
        self._prev: dict[int, dict] = {}  # device_id → {gen_status, mode, gen_ats, mains_ats, mains_normal, mains_load, online}
        self._device_names: dict[int, str] = {}  # device_id → name cache
        self._initialized: set[int] = set()  # devices that have been initialized (skip first message)

    async def start(self) -> None:
        self._running = True
        await self._load_device_names()
        logger.info("EventDetector started (%d devices cached)", len(self._device_names))
        await self._subscribe()

    async def stop(self) -> None:
        self._running = False
        logger.info("EventDetector stopped")

    # ------------------------------------------------------------------
    async def _load_device_names(self) -> None:
        """Cache device names for human-readable messages."""
        try:
            async with self.session_factory() as session:
                result = await session.execute(select(Device))
                for dev in result.scalars().all():
                    self._device_names[dev.id] = dev.name or f"Устройство #{dev.id}"
        except Exception as exc:
            logger.warning("EventDetector: failed to load device names: %s", exc)

    def _dev_name(self, device_id: int) -> str:
        return self._device_names.get(device_id, f"Устройство #{device_id}")

    # ------------------------------------------------------------------
    async def _subscribe(self) -> None:
        while self._running:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe("metrics:updates")
                async for msg in pubsub.listen():
                    if not self._running:
                        break
                    if msg["type"] != "message":
                        continue
                    raw = msg["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    try:
                        await self._process(payload)
                    except Exception as exc:
                        logger.error("EventDetector process error: %s", exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("EventDetector subscribe error: %s", exc)
                await asyncio.sleep(2)
            finally:
                try:
                    await pubsub.unsubscribe("metrics:updates")
                    await pubsub.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    async def _process(self, payload: dict) -> None:
        device_id = payload.get("device_id")
        if device_id is None:
            return

        prev = self._prev.get(device_id, {})
        is_first = device_id not in self._initialized
        events: list[ScadaEvent] = []
        name = self._dev_name(device_id)
        device_type = payload.get("device_type", "generator")

        # === 1. GEN_STATUS (only for generators) ===
        cur_gs = payload.get("gen_status")
        if cur_gs is not None:
            prev_gs = prev.get("gen_status")
            if prev_gs is not None and cur_gs != prev_gs and not is_first:
                old_label = GEN_STATUS_LABELS.get(prev_gs, f"#{prev_gs}")
                new_label = GEN_STATUS_LABELS.get(cur_gs, f"#{cur_gs}")
                icon = GEN_STATUS_ICONS.get(cur_gs, "🔄")
                events.append(ScadaEvent(
                    device_id=device_id,
                    category="GEN_STATUS",
                    event_code=f"gs_{cur_gs}",
                    message=f"{icon} {name} → {new_label}",
                    old_value=str(prev_gs),
                    new_value=str(cur_gs),
                ))

        # === 2. MODE_CHANGE ===
        cur_mode = self._detect_mode(payload)
        if cur_mode:
            prev_mode = prev.get("mode")
            if prev_mode is not None and cur_mode != prev_mode and not is_first:
                events.append(ScadaEvent(
                    device_id=device_id,
                    category="MODE_CHANGE",
                    event_code=f"mode_{cur_mode}",
                    message=f"🎛 {name}: режим {MODE_LABELS.get(prev_mode, prev_mode)} → {MODE_LABELS.get(cur_mode, cur_mode)}",
                    old_value=prev_mode,
                    new_value=cur_mode,
                ))

        # === 3. ATS_STATUS ===
        for ats_field, ats_label in [("gen_ats_status", "АВР ген."), ("mains_ats_status", "АВР сети")]:
            cur_ats = payload.get(ats_field)
            if cur_ats is not None:
                prev_ats = prev.get(ats_field)
                if prev_ats is not None and cur_ats != prev_ats and not is_first:
                    old_label = ATS_STATUS_LABELS.get(prev_ats, f"#{prev_ats}")
                    new_label = ATS_STATUS_LABELS.get(cur_ats, f"#{cur_ats}")
                    icon = "🔌" if cur_ats == 3 else "⚡" if cur_ats == 7 else "🔄"
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="ATS_STATUS",
                        event_code=f"ats_{cur_ats}",
                        message=f"{icon} {name}: {ats_label} {old_label} → {new_label}",
                        old_value=str(prev_ats),
                        new_value=str(cur_ats),
                    ))

        # === 4. MAINS ===
        cur_mains_normal = payload.get("mains_normal")
        if cur_mains_normal is not None:
            prev_mn = prev.get("mains_normal")
            if prev_mn is not None and cur_mains_normal != prev_mn and not is_first:
                if cur_mains_normal:
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="MAINS",
                        event_code="mains_ok",
                        message=f"✅ {name}: Сеть в норме",
                        old_value="abnormal",
                        new_value="normal",
                    ))
                else:
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="MAINS",
                        event_code="mains_fail",
                        message=f"⚠ {name}: Пропадание сети!",
                        old_value="normal",
                        new_value="abnormal",
                    ))

        cur_mains_load = payload.get("mains_load")
        if cur_mains_load is not None:
            prev_ml = prev.get("mains_load")
            if prev_ml is not None and cur_mains_load != prev_ml and not is_first:
                if cur_mains_load:
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="MAINS",
                        event_code="mains_on_load",
                        message=f"⚡ {name}: Сеть на нагрузке",
                        old_value="off_load",
                        new_value="on_load",
                    ))
                else:
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="MAINS",
                        event_code="mains_off_load",
                        message=f"🔌 {name}: Сеть снята с нагрузки",
                        old_value="on_load",
                        new_value="off_load",
                    ))

        # === 5. SYSTEM: online True↔False ===
        online_now = payload.get("online")
        if online_now is not None:
            prev_online = prev.get("online")
            if prev_online is not None and online_now != prev_online and not is_first:
                if online_now:
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="SYSTEM",
                        event_code="online",
                        message=f"✅ {name}: связь восстановлена",
                        old_value="offline",
                        new_value="online",
                    ))
                else:
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="SYSTEM",
                        event_code="offline",
                        message=f"❌ {name}: нет связи!",
                        old_value="online",
                        new_value="offline",
                    ))

        # --- Persist events to DB + publish to Redis ---
        if events:
            try:
                async with self.session_factory() as session:
                    for ev in events:
                        session.add(ev)
                    await session.commit()
                    # Re-read to get generated id/created_at
                    for ev in events:
                        await session.refresh(ev)

                # Publish for frontend via WS bridge
                for ev in events:
                    try:
                        await self.redis.publish("events:new", json.dumps({
                            "id": ev.id,
                            "device_id": ev.device_id,
                            "device_name": name,
                            "category": ev.category,
                            "event_code": ev.event_code,
                            "message": ev.message,
                            "old_value": ev.old_value,
                            "new_value": ev.new_value,
                            "created_at": ev.created_at.isoformat() if ev.created_at else None,
                        }, default=str))
                    except Exception:
                        pass
                    logger.info("EVENT: device=%d cat=%s code=%s msg=%s",
                                device_id, ev.category, ev.event_code, ev.message)
            except Exception as exc:
                logger.error("EventDetector DB error: %s", exc)

        # --- Update prev state ---
        new_state = dict(prev)
        if cur_gs is not None:
            new_state["gen_status"] = cur_gs
        if cur_mode:
            new_state["mode"] = cur_mode
        for field in ("gen_ats_status", "mains_ats_status"):
            v = payload.get(field)
            if v is not None:
                new_state[field] = v
        if cur_mains_normal is not None:
            new_state["mains_normal"] = cur_mains_normal
        if cur_mains_load is not None:
            new_state["mains_load"] = cur_mains_load
        if online_now is not None:
            new_state["online"] = online_now
        self._prev[device_id] = new_state

        # Mark device as initialized (skip first message to avoid phantom events on restart)
        self._initialized.add(device_id)

    # ------------------------------------------------------------------
    @staticmethod
    def _detect_mode(payload: dict) -> str | None:
        """Determine controller mode from boolean flags."""
        if payload.get("mode_auto"):
            return "auto"
        if payload.get("mode_manual"):
            return "manual"
        if payload.get("mode_test"):
            return "test"
        if payload.get("mode_stop"):
            return "stop"
        return None
