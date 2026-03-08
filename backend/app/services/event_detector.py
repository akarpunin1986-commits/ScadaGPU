"""EventDetector — detects state transitions and persists to scada_events.

Subscribes to Redis PubSub 'metrics:updates'. Tracks:
- GEN_STATUS:   gen_status (HGM9520N) / genset_status (HGM9560) changes
- GEN_CRITICAL: consolidated STOP/START events with root cause
- MODE_CHANGE:  mode_auto/manual/test/stop flag changes (both types)
- ATS_STATUS:   gen_ats_status/mains_ats_status (HGM9520N) /
                busbar_switch/mains_switch (HGM9560) changes
- MAINS:        mains_normal/mains_load (HGM9520N) /
                mains_status (HGM9560) changes
- SYSTEM:       online True↔False transitions (both types)
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

# HGM9520N generator gen_status (0-15)
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

# HGM9560 ATS panel genset_status (0-14)
GENSET_STATUS_9560_LABELS = {
    0: "Стоп (Standby)",
    1: "Прогрев свечей",
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
    14: "Ошибка остановки",
}

MODE_LABELS = {
    "auto": "AUTO",
    "manual": "MANUAL",
    "test": "TEST",
    "stop": "STOP",
}

# HGM9520N: gen_ats_status / mains_ats_status (0-7)
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

# HGM9560: busbar_switch / mains_switch (same codes 0-7)
SWITCH_STATUS_LABELS = ATS_STATUS_LABELS  # same encoding

# HGM9560: mains_status (0-3)
MAINS_STATUS_LABELS = {
    0: "Норма",
    1: "Норма (задержка)",
    2: "Авария сети",
    3: "Авария сети (задержка)",
}

GEN_STATUS_ICONS = {
    0: "⏹", 1: "🔄", 2: "⛽", 3: "🔧", 4: "⏸", 5: "🔍",
    6: "💨", 7: "🔥", 8: "⏳", 9: "⚡", 10: "❄", 11: "🛑",
    12: "🚨", 13: "⏳", 14: "✅", 15: "❌",
}

# States where generator is "running" (producing or about to produce power)
GEN_RUNNING_STATES = {6, 7, 8, 9}  # idle, warmup, wait_load, working
# States where generator is "stopping/stopped"
GEN_STOP_STATES = {0, 10, 11, 12, 13, 14, 15}
# States where generator is "starting"
GEN_START_STATES = {1, 2, 3, 4, 5}

# Root cause mapping based on the stop state entered
STOP_CAUSE = {
    0: "штатная остановка",
    10: "охлаждение → останов",
    11: "остановка ХХ",
    12: "АВАРИЙНЫЙ СТОП (ETS)",
    13: "ожидание остановки",
    14: "постостановка",
    15: "ОШИБКА ОСТАНОВКИ",
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
        self._prev: dict[int, dict] = {}  # device_id → tracked state
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

        # =============================================================
        # 1. GEN_STATUS
        #    - HGM9520N generators: field "gen_status" (0-15)
        #    - HGM9560 ATS panel:   field "genset_status" (0-14)
        # =============================================================
        if device_type == "ats":
            cur_gs = payload.get("genset_status")
            gs_labels = GENSET_STATUS_9560_LABELS
            gs_prev_key = "genset_status"
        else:
            cur_gs = payload.get("gen_status")
            gs_labels = GEN_STATUS_LABELS
            gs_prev_key = "gen_status"

        if cur_gs is not None:
            prev_gs = prev.get(gs_prev_key)
            if prev_gs is not None and cur_gs != prev_gs and not is_first:
                old_label = gs_labels.get(prev_gs, f"#{prev_gs}")
                new_label = gs_labels.get(cur_gs, f"#{cur_gs}")
                icon = GEN_STATUS_ICONS.get(cur_gs, "🔄")
                events.append(ScadaEvent(
                    device_id=device_id,
                    category="GEN_STATUS",
                    event_code=f"gs_{cur_gs}",
                    message=f"{icon} {name} → {new_label}",
                    old_value=str(prev_gs),
                    new_value=str(cur_gs),
                ))

                # --- GEN_CRITICAL: consolidated stop/start events ---
                # STOP: running (6-9) → any stop state (0, 10-15)
                if prev_gs in GEN_RUNNING_STATES and cur_gs in GEN_STOP_STATES:
                    cause = STOP_CAUSE.get(cur_gs, f"статус {cur_gs}")
                    # Determine mode context for root cause
                    cur_mode = self._detect_mode(payload)
                    mode_ctx = ""
                    if cur_mode == "stop":
                        mode_ctx = " (ручной стоп оператором)"
                    elif cur_mode == "auto":
                        mode_ctx = " (авто)"
                    elif cur_mode == "manual":
                        mode_ctx = " (ручной режим)"
                    # ETS is always critical regardless of mode
                    if cur_gs == 12:
                        msg = f"🚨 ОСТАНОВКА {name}: {cause}{mode_ctx}"
                    elif cur_gs == 15:
                        msg = f"❌ ОСТАНОВКА {name}: {cause}{mode_ctx}"
                    else:
                        msg = f"🛑 ОСТАНОВКА {name}: {cause}{mode_ctx}"
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="GEN_CRITICAL",
                        event_code="gen_critical_stop",
                        message=msg,
                        old_value=old_label,
                        new_value=new_label,
                    ))
                    logger.warning("CRITICAL STOP: device=%d %s → %s cause=%s%s",
                                   device_id, old_label, new_label, cause, mode_ctx)

                # START: stopped/standby (0, 10-15) → starting (1-5) or running (6-9)
                elif prev_gs in GEN_STOP_STATES and cur_gs in (GEN_START_STATES | GEN_RUNNING_STATES):
                    cur_mode = self._detect_mode(payload)
                    mode_ctx = ""
                    if cur_mode == "auto":
                        mode_ctx = " (авто)"
                    elif cur_mode == "manual":
                        mode_ctx = " (ручной)"
                    elif cur_mode == "test":
                        mode_ctx = " (тест)"
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="GEN_CRITICAL",
                        event_code="gen_critical_start",
                        message=f"🟢 ЗАПУСК {name}: {new_label}{mode_ctx}",
                        old_value=old_label,
                        new_value=new_label,
                    ))
                    logger.info("CRITICAL START: device=%d %s → %s%s",
                                device_id, old_label, new_label, mode_ctx)

        # =============================================================
        # 2. MODE_CHANGE (same flags for both device types)
        # =============================================================
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

        # =============================================================
        # 3. ATS_STATUS
        #    - HGM9520N generators: gen_ats_status, mains_ats_status (0-7)
        #    - HGM9560 ATS panel:   busbar_switch, mains_switch (0-7)
        # =============================================================
        if device_type == "ats":
            ats_fields = [
                ("busbar_switch", "Шинный ввод", SWITCH_STATUS_LABELS),
                ("mains_switch", "Сетевой ввод", SWITCH_STATUS_LABELS),
            ]
        else:
            ats_fields = [
                ("gen_ats_status", "АВР ген.", ATS_STATUS_LABELS),
                ("mains_ats_status", "АВР сети", ATS_STATUS_LABELS),
            ]

        for ats_field, ats_label, labels in ats_fields:
            cur_ats = payload.get(ats_field)
            if cur_ats is not None:
                prev_ats = prev.get(ats_field)
                if prev_ats is not None and cur_ats != prev_ats and not is_first:
                    old_label = labels.get(prev_ats, f"#{prev_ats}")
                    new_label = labels.get(cur_ats, f"#{cur_ats}")
                    icon = "🔌" if cur_ats == 3 else "⚡" if cur_ats == 7 else "🔄"
                    events.append(ScadaEvent(
                        device_id=device_id,
                        category="ATS_STATUS",
                        event_code=f"ats_{cur_ats}",
                        message=f"{icon} {name}: {ats_label} {old_label} → {new_label}",
                        old_value=str(prev_ats),
                        new_value=str(cur_ats),
                    ))

        # =============================================================
        # 4. MAINS
        #    - HGM9520N generators: mains_normal (bool), mains_load (bool)
        #    - HGM9560 ATS panel:   mains_status (0=normal,1=normal_delay,
        #                           2=abnormal,3=abnormal_delay)
        # =============================================================
        if device_type == "ats":
            # HGM9560: track mains_status transitions
            cur_ms = payload.get("mains_status")
            if cur_ms is not None:
                prev_ms = prev.get("mains_status")
                if prev_ms is not None and cur_ms != prev_ms and not is_first:
                    # Determine if transition is normal↔abnormal
                    was_normal = prev_ms in (0, 1)
                    is_normal = cur_ms in (0, 1)
                    old_label = MAINS_STATUS_LABELS.get(prev_ms, f"#{prev_ms}")
                    new_label = MAINS_STATUS_LABELS.get(cur_ms, f"#{cur_ms}")
                    if was_normal and not is_normal:
                        events.append(ScadaEvent(
                            device_id=device_id,
                            category="MAINS",
                            event_code="mains_fail",
                            message=f"⚠ {name}: {new_label}!",
                            old_value=old_label,
                            new_value=new_label,
                        ))
                    elif not was_normal and is_normal:
                        events.append(ScadaEvent(
                            device_id=device_id,
                            category="MAINS",
                            event_code="mains_ok",
                            message=f"✅ {name}: Сеть восстановлена",
                            old_value=old_label,
                            new_value=new_label,
                        ))
                    elif cur_ms != prev_ms:
                        # Transition within same group (e.g. 0→1 or 2→3)
                        events.append(ScadaEvent(
                            device_id=device_id,
                            category="MAINS",
                            event_code=f"mains_status_{cur_ms}",
                            message=f"🔌 {name}: Сеть {old_label} → {new_label}",
                            old_value=old_label,
                            new_value=new_label,
                        ))
        else:
            # HGM9520N: track mains_normal and mains_load booleans
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

        # =============================================================
        # 5. SYSTEM: online True↔False (both device types)
        # =============================================================
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
        # GEN_STATUS
        if cur_gs is not None:
            new_state[gs_prev_key] = cur_gs
        # MODE_CHANGE
        if cur_mode:
            new_state["mode"] = cur_mode
        # ATS_STATUS
        for ats_field, _, _ in ats_fields:
            v = payload.get(ats_field)
            if v is not None:
                new_state[ats_field] = v
        # MAINS
        if device_type == "ats":
            cur_ms_val = payload.get("mains_status")
            if cur_ms_val is not None:
                new_state["mains_status"] = cur_ms_val
        else:
            mn = payload.get("mains_normal")
            if mn is not None:
                new_state["mains_normal"] = mn
            ml = payload.get("mains_load")
            if ml is not None:
                new_state["mains_load"] = ml
        # SYSTEM
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
