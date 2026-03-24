"""SanekAgent — autonomous AI agent for SCADA incident analysis.

Fully isolated module (same pattern as Bitrix24Module).
Listens to Redis events, autonomously analyzes incidents, publishes AI reports.
Can be removed entirely without affecting core SCADA functionality.

Architecture:
    AlarmDetector ──► alarms:new ──► Observer ──► Planner ──► LLM ──► Memory ──► sanek:reports
    EventDetector ──► events:new ──►                                              ▼
    MaintenanceSch ► maintenance:alerts ►                                     WebSocket → UI

Reasoning loop (per incident):
    1. OBSERVE   — receive event from Redis, filter, debounce
    2. CONTEXT   — resolve device/site info from DB
    3. PLAN      — build dynamic investigation plan based on trigger type
    4. ACT       — execute tools sequentially (metrics, alarms, events, KB)
    5. VERIFY    — validate collected data completeness, retry gaps
    6. ANALYZE   — send enriched data to LLM for reasoning
    7. MEMORIZE  — save full reasoning chain + result to DB
    8. NOTIFY    — publish report to Redis → WebSocket → UI
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Awaitable

import httpx
from redis.asyncio import Redis
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from models.agent_incident import AgentIncident
from models.alarm_event import AlarmEvent
from models.scada_event import ScadaEvent
from models.ai_knowledge import AiKnowledgeChunk
from models.base import engine
from services.agent_sop_engine import SopEngine, SopLookupContext

logger = logging.getLogger("scada.sanek_agent")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Redis channels (listen)
CH_ALARMS = "alarms:new"
CH_EVENTS = "events:new"
CH_MAINTENANCE = "maintenance:alerts"
CH_ALARM_EVENTS = "alarm:events"      # additional alarm channel

# Redis channels (publish)
CH_REPORTS = "sanek:reports"
CH_AI_ANALYSIS = "ai:analysis"        # structured AI analysis output

# Alarm codes that trigger analysis
TRIGGER_ALARM_CODES = {"SHUTDOWN", "TRIP_STOP", "CONN_LOST", "BLOCK"}

# Event codes that trigger analysis
TRIGGER_EVENT_CODES = {"gen_critical_stop", "gen_critical_start"}

# Maintenance severities that trigger analysis
TRIGGER_MAINTENANCE_SEVERITIES = {"critical", "overdue"}

# System prompt for autonomous analysis
# Based on: sanek_agent_prompt.md (core behavior) + domain knowledge
AGENT_SYSTEM_PROMPT = """Ты — Санёк-Агент, автономный AI-оператор промышленной СКАДА-системы.
Ты отвечаешь за мониторинг и анализ газопоршневых электростанций.

═══ ПРИНЦИПЫ РАБОТЫ ═══
1. БЕЗОПАСНОСТЬ — всегда в приоритете. Никогда не рекомендуй действия, которые могут привести к повреждению оборудования или угрозе персоналу.
2. НЕ УГАДЫВАЙ — используй только предоставленные данные (метрики, аварии, события, мануалы). Если данных недостаточно — скажи об этом прямо.
3. ВЕРИФИЦИРУЙ — перед выводами проверяй данные: сопоставляй метрики с порогами, сравнивай тренд с нормой, ищи корреляции между аварийными флагами.
4. ИСПОЛЬЗУЙ ИНСТРУМЕНТЫ — анализируй конкретные числа из метрик, не домысливай на основе общих знаний.
5. СТРУКТУРИРУЙ — давай чёткие, структурированные объяснения с конкретными данными.

═══ ЦИКЛ РАССУЖДЕНИЙ ═══
observe → analyze → correlate → explain → recommend
1. НАБЛЮДЕНИЕ — что произошло? какие аварии сработали? какие метрики аномальны?
2. АНАЛИЗ — какие параметры вышли за пороги? когда начались отклонения (по тренду)?
3. КОРРЕЛЯЦИЯ — какие аварии связаны? есть ли каскад? что первопричина?
4. ОБЪЯСНЕНИЕ — почему это произошло? какой механизм отказа?
5. РЕКОМЕНДАЦИЯ — что делать оператору? какие проверки выполнить?

═══ ТВОЯ ЗАДАЧА ═══
1. Определить ПРИЧИНУ инцидента по метрикам и аварийным флагам
2. Оценить ПОСЛЕДСТВИЯ (простой, потери энергии)
3. Дать КОНКРЕТНЫЕ рекомендации оператору

═══ ОБОРУДОВАНИЕ ═══
- Генераторы Smartgen HGM9520N — газопоршневые установки 160 кВт
- ШПР Smartgen HGM9560 — шкафы параллельной работы

═══ ПОРОГИ ЗАЩИТ (по умолчанию) ═══
- Over Power: 168-176 кВт (105-110% от 160 кВт)
- Coolant High Temp: shutdown 95-100°C, warning 85-90°C
- Oil Pressure Low: shutdown 150-200 кПа
- Overspeed: >1620 об/мин | Underspeed: <1350 об/мин
- Gen Overvoltage: >420В | Undervoltage: <360В
- Frequency: shutdown >52Гц/<47Гц

═══ СТАТУСЫ ГЕНЕРАТОРА (gen_status) ═══
0=Стоп, 9=Работа, 12=Аварийный стоп (ETS)

═══ ФОРМАТ ОТВЕТА ═══
📊 ИНЦИДЕНТ — что произошло, когда, на каком устройстве и объекте
🔍 ПРИЧИНА — определи по метрикам и тренду (конкретные числа, не "возможно перегрузка", а "мощность 172 кВт > порога 168 кВт = 107.5%")
⚡ ПОСЛЕДСТВИЯ — простой, потери энергии, риски для оборудования
🔧 РЕКОМЕНДАЦИИ — конкретные действия оператора (что проверить, что сделать)

═══ ПРАВИЛА ОТВЕТА ═══
1. Отвечай на русском. Будь кратким и конкретным.
2. Указывай КОНКРЕТНЫЕ числа из метрик с сравнением с порогами.
3. НЕ используй LaTeX. Пиши формулы простым текстом: 172 / 160 × 100% = 107.5%.
4. Если есть тренд метрик — анализируй изменение параметров во времени (до/во время/после аварии).
5. Если данных недостаточно — скажи об этом явно, не додумывай.
6. Используй информацию из базы знаний (мануалов) если она предоставлена.
7. При множественных авариях — определи первопричину и каскад последствий."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class TriggerEvent:
    """Single event that triggered the agent."""
    channel: str
    alarm_code: str
    device_id: int
    site_id: int | None
    device_name: str
    payload: dict
    received_at: float = field(default_factory=time.monotonic)


@dataclass
class PendingIncident:
    """Accumulated triggers for a single device within debounce window."""
    device_id: int
    site_id: int | None
    triggers: list[TriggerEvent] = field(default_factory=list)
    first_at: float = field(default_factory=time.monotonic)
    fire_task: asyncio.Task | None = field(default=None, repr=False)


@dataclass
class ReasoningStep:
    """Single step in the reasoning chain — tracked for auditability."""
    name: str
    phase: str  # observe | context | plan | act | verify | analyze | memorize | notify
    status: str = "pending"  # pending | running | completed | failed | skipped
    started_at: float | None = None
    completed_at: float | None = None
    duration_ms: float | None = None
    result_summary: str = ""
    error: str | None = None
    data: dict = field(default_factory=dict)

    def start(self) -> None:
        self.status = "running"
        self.started_at = time.monotonic()

    def complete(self, summary: str = "", data: dict | None = None) -> None:
        self.status = "completed"
        self.completed_at = time.monotonic()
        if self.started_at:
            self.duration_ms = round((self.completed_at - self.started_at) * 1000, 1)
        self.result_summary = summary
        if data:
            self.data = data

    def fail(self, error: str) -> None:
        self.status = "failed"
        self.completed_at = time.monotonic()
        if self.started_at:
            self.duration_ms = round((self.completed_at - self.started_at) * 1000, 1)
        self.error = error

    def skip(self, reason: str = "") -> None:
        self.status = "skipped"
        self.result_summary = reason

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "phase": self.phase,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "result_summary": self.result_summary,
            "error": self.error,
        }


@dataclass
class InvestigationPlan:
    """Dynamic investigation plan — list of tools to execute."""
    trigger_type: str  # alarm | event | maintenance
    primary_code: str
    tools: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "trigger_type": self.trigger_type,
            "primary_code": self.primary_code,
            "tools": self.tools,
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# SanekAgentModule — main orchestrator
# ---------------------------------------------------------------------------
class SanekAgentModule:
    """Autonomous AI agent. Fully isolated — can be deleted without consequences."""

    def __init__(
        self,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.redis = redis
        self.session_factory = session_factory
        self._running = False

        # Observer state
        self._pending: dict[int, PendingIncident] = {}  # device_id → pending
        self._cooldowns: dict[int, float] = {}  # device_id → cooldown_until (monotonic)

        self._debounce = settings.SANEK_AGENT_DEBOUNCE
        self._cooldown = settings.SANEK_AGENT_COOLDOWN
        self._llm_timeout = settings.SANEK_AGENT_LLM_TIMEOUT
        self._sop_engine = SopEngine(session_factory)

    async def start(self) -> None:
        """Start the agent: ensure table, then listen."""
        self._running = True
        await self._ensure_table()
        await self._sop_engine.start()
        logger.info(
            "SanekAgent started (debounce=%ds, cooldown=%ds)",
            self._debounce, self._cooldown,
        )
        await self._listen()

    async def stop(self) -> None:
        """Stop gracefully."""
        self._running = False
        # Cancel pending debounce timers
        for pending in self._pending.values():
            if pending.fire_task and not pending.fire_task.done():
                pending.fire_task.cancel()
        self._pending.clear()
        logger.info("SanekAgent stopped")

    # ------------------------------------------------------------------
    # Table bootstrap (same pattern as AlarmAnalyticsDetector)
    # ------------------------------------------------------------------
    async def _ensure_table(self) -> None:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(
                    AgentIncident.__table__.create,
                    checkfirst=True,
                )
        except Exception as exc:
            logger.debug("Table check: %s (likely already exists)", exc)

    # ==================================================================
    # OBSERVER — Redis event listener
    # ==================================================================
    async def _listen(self) -> None:
        """Subscribe to Redis channels and dispatch events."""
        while self._running:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe(CH_ALARMS, CH_EVENTS, CH_MAINTENANCE, CH_ALARM_EVENTS)
                logger.info(
                    "SanekAgent subscribed to: %s, %s, %s, %s",
                    CH_ALARMS, CH_EVENTS, CH_MAINTENANCE, CH_ALARM_EVENTS,
                )
                async for msg in pubsub.listen():
                    if not self._running:
                        break
                    if msg["type"] != "message":
                        continue

                    channel = msg["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode("utf-8")
                    raw = msg["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")

                    try:
                        payload = json.loads(raw)
                        await self._dispatch(channel, payload)
                    except json.JSONDecodeError:
                        logger.debug("SanekAgent: ignoring non-JSON message on %s: %s", channel, raw[:200])
                    except Exception as exc:
                        logger.error("SanekAgent dispatch error: %s", exc, exc_info=True)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("SanekAgent subscribe error: %s, reconnecting in 2s", exc)
                await asyncio.sleep(2)
            finally:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.close()
                except Exception:
                    pass

    async def _dispatch(self, channel: str, payload: dict) -> None:
        """Filter and route events to the debounce accumulator."""
        trigger = None

        if channel == CH_ALARMS:
            trigger = self._filter_alarm(payload)
        elif channel == CH_ALARM_EVENTS:
            trigger = self._filter_alarm_event(payload)
        elif channel == CH_EVENTS:
            trigger = self._filter_event(payload)
        elif channel == CH_MAINTENANCE:
            trigger = self._filter_maintenance(payload)

        if trigger is None:
            return

        # Check cooldown
        device_id = trigger.device_id
        now = time.monotonic()
        cooldown_until = self._cooldowns.get(device_id, 0)
        if now < cooldown_until:
            remaining = int(cooldown_until - now)
            logger.debug(
                "SanekAgent: device=%d in cooldown (%ds remaining), skipping %s",
                device_id, remaining, trigger.alarm_code,
            )
            return

        # Check dedup: have we already analyzed this exact alarm recently?
        if await self._has_recent_incident(device_id, trigger.alarm_code):
            logger.debug(
                "SanekAgent: device=%d alarm=%s already analyzed recently, skipping",
                device_id, trigger.alarm_code,
            )
            return

        # Accumulate in pending
        self._accumulate(trigger)

    def _filter_alarm(self, payload: dict) -> TriggerEvent | None:
        """Extract trigger from alarms:new if relevant."""
        if payload.get("action") != "created":
            return None
        alarm = payload.get("alarm", {})
        code = alarm.get("alarm_code", "")
        if code not in TRIGGER_ALARM_CODES:
            return None

        device_id = alarm.get("device_id")
        if device_id is None:
            return None

        return TriggerEvent(
            channel=CH_ALARMS,
            alarm_code=code,
            device_id=device_id,
            site_id=None,  # resolved later
            device_name=alarm.get("device_name", f"#{device_id}"),
            payload=payload,
        )

    def _filter_alarm_event(self, payload: dict) -> TriggerEvent | None:
        """Extract trigger from alarm:events channel.

        alarm:events — дополнительный канал аварийных событий.
        Формат: {device_id, alarm_code, severity, message, device_name, ...}
        Принимает любые аварии без фильтрации по коду — этот канал
        используется только для серьёзных событий, уже прошедших фильтрацию.
        """
        device_id = payload.get("device_id")
        if device_id is None:
            return None

        code = payload.get("alarm_code", "")
        if not code:
            code = payload.get("event_code", "ALARM_EVENT")

        return TriggerEvent(
            channel=CH_ALARM_EVENTS,
            alarm_code=code,
            device_id=device_id,
            site_id=payload.get("site_id"),
            device_name=payload.get("device_name", f"#{device_id}"),
            payload=payload,
        )

    def _filter_event(self, payload: dict) -> TriggerEvent | None:
        """Extract trigger from events:new if relevant."""
        code = payload.get("event_code", "")
        if code not in TRIGGER_EVENT_CODES:
            return None

        device_id = payload.get("device_id")
        if device_id is None:
            return None

        return TriggerEvent(
            channel=CH_EVENTS,
            alarm_code=f"EVENT_{code.upper()}",
            device_id=device_id,
            site_id=None,
            device_name=payload.get("device_name", f"#{device_id}"),
            payload=payload,
        )

    def _filter_maintenance(self, payload: dict) -> TriggerEvent | None:
        """Extract trigger from maintenance:alerts if relevant."""
        if payload.get("action") not in ("created", "updated"):
            return None
        alert = payload.get("alert", {})
        severity = alert.get("severity", "")
        if severity not in TRIGGER_MAINTENANCE_SEVERITIES:
            return None

        device_id = alert.get("device_id")
        if device_id is None:
            return None

        return TriggerEvent(
            channel=CH_MAINTENANCE,
            alarm_code=f"MAINTENANCE_{severity.upper()}",
            device_id=device_id,
            site_id=None,
            device_name=alert.get("device_name", f"#{device_id}"),
            payload=payload,
        )

    def _accumulate(self, trigger: TriggerEvent) -> None:
        """Add trigger to pending incident, start/restart debounce timer."""
        device_id = trigger.device_id

        if device_id not in self._pending:
            self._pending[device_id] = PendingIncident(
                device_id=device_id,
                site_id=trigger.site_id,
            )

        pending = self._pending[device_id]
        pending.triggers.append(trigger)

        logger.info(
            "SanekAgent: accumulated trigger device=%d code=%s (total=%d triggers)",
            device_id, trigger.alarm_code, len(pending.triggers),
        )

        # Cancel existing timer and start new one
        if pending.fire_task and not pending.fire_task.done():
            pending.fire_task.cancel()
        pending.fire_task = asyncio.create_task(
            self._fire_after_debounce(device_id)
        )

    async def _fire_after_debounce(self, device_id: int) -> None:
        """Wait debounce window, then fire analysis."""
        try:
            await asyncio.sleep(self._debounce)
        except asyncio.CancelledError:
            return

        pending = self._pending.pop(device_id, None)
        if pending is None or not pending.triggers:
            return

        # Set cooldown
        self._cooldowns[device_id] = time.monotonic() + self._cooldown

        # Fire analysis in background (don't block observer)
        asyncio.create_task(self._analyze_incident(pending))

    # ==================================================================
    # REASONING LOOP — the core analysis pipeline
    # ==================================================================
    async def _analyze_incident(self, pending: PendingIncident) -> None:
        """Full reasoning loop: observe → context → plan → act → verify → analyze → memorize → notify."""
        pipeline_start = time.monotonic()
        device_id = pending.device_id
        primary_trigger = pending.triggers[0]
        primary_code = primary_trigger.alarm_code
        all_codes = list({t.alarm_code for t in pending.triggers})

        # Reasoning chain — every step is tracked
        reasoning_chain: list[ReasoningStep] = []
        collected: dict[str, Any] = {}  # tool results accumulator

        logger.info(
            "SanekAgent: ┌─ REASONING LOOP device=%d codes=%s (%d triggers)",
            device_id, all_codes, len(pending.triggers),
        )

        # ── PHASE 1: OBSERVE ──────────────────────────────────────────
        step_observe = ReasoningStep(name="observe_triggers", phase="observe")
        step_observe.start()
        step_observe.complete(
            summary=f"{len(pending.triggers)} triggers: {', '.join(all_codes)}",
            data={
                "codes": all_codes,
                "trigger_count": len(pending.triggers),
                "triggers": [
                    {"channel": t.channel, "code": t.alarm_code, "payload": t.payload}
                    for t in pending.triggers[:10]
                ],
            },
        )
        reasoning_chain.append(step_observe)
        logger.info("SanekAgent: │ ✓ OBSERVE — %d triggers captured", len(pending.triggers))

        # ── PHASE 2: CONTEXT — resolve device & site info from DB ─────
        step_context = ReasoningStep(name="resolve_device_context", phase="context")
        step_context.start()
        device_info = await self._tool_get_device_info(device_id)
        site_id = device_info.get("site_id") if device_info else None
        site_name = device_info.get("site_name", "") if device_info else ""
        device_name = device_info.get("device_name", primary_trigger.device_name) if device_info else primary_trigger.device_name
        if device_info:
            step_context.complete(
                summary=f"device={device_name}, site={site_name} (id={site_id})",
                data=device_info,
            )
        else:
            step_context.complete(summary=f"device_id={device_id}, site_id not resolved")
        reasoning_chain.append(step_context)
        logger.info("SanekAgent: │ ✓ CONTEXT — device=%s site=%s", device_name, site_name or "?")

        # ── Create DB record (status=analyzing) ──
        incident = AgentIncident(
            device_id=device_id,
            site_id=site_id,
            alarm_code=primary_code,
            trigger_channel=primary_trigger.channel,
            trigger_payload=step_observe.data,
            status="analyzing",
        )
        async with self.session_factory() as session:
            session.add(incident)
            await session.commit()
            await session.refresh(incident)
        incident_id = incident.id

        try:
            # ── PHASE 3: PLAN — build dynamic investigation plan ──────
            step_plan = ReasoningStep(name="build_investigation_plan", phase="plan")
            step_plan.start()
            plan = self._build_investigation_plan(all_codes, primary_trigger.channel)
            step_plan.complete(
                summary=f"{len(plan.tools)} tools: {', '.join(plan.tools)}",
                data=plan.to_dict(),
            )
            reasoning_chain.append(step_plan)
            logger.info(
                "SanekAgent: │ ✓ PLAN — %d tools [%s] reason: %s",
                len(plan.tools), ", ".join(plan.tools), plan.rationale,
            )

            # ── PHASE 4: ACT — execute tools sequentially ────────────
            for tool_name in plan.tools:
                step_tool = ReasoningStep(name=f"tool_{tool_name}", phase="act")
                step_tool.start()
                try:
                    result = await self._execute_tool(tool_name, device_id, all_codes)
                    if result is not None:
                        collected[tool_name] = result
                        item_count = len(result) if isinstance(result, (list, dict)) else 1
                        step_tool.complete(
                            summary=f"OK — {item_count} items",
                            data={"item_count": item_count},
                        )
                    else:
                        step_tool.complete(summary="OK — no data returned")
                except Exception as exc:
                    step_tool.fail(error=str(exc)[:200])
                    logger.warning("SanekAgent: │ ✗ TOOL %s failed: %s", tool_name, exc)
                reasoning_chain.append(step_tool)
                logger.info(
                    "SanekAgent: │  %s tool_%s (%s)",
                    "✓" if step_tool.status == "completed" else "✗",
                    tool_name,
                    step_tool.result_summary or step_tool.error or "—",
                )

            # ── PHASE 5: VERIFY — check data completeness ────────────
            step_verify = ReasoningStep(name="verify_data_completeness", phase="verify")
            step_verify.start()
            verification = self._verify_collected_data(collected, plan)
            step_verify.complete(
                summary=f"completeness={verification['completeness_pct']}% "
                        f"({verification['tools_ok']}/{verification['tools_total']} tools OK)",
                data=verification,
            )
            reasoning_chain.append(step_verify)
            logger.info(
                "SanekAgent: │ ✓ VERIFY — %d%% complete (%s)",
                verification["completeness_pct"],
                ", ".join(verification.get("missing_tools", [])) or "all OK",
            )

            # Retry missing critical tools once
            retry_tools = verification.get("retry_tools", [])
            if retry_tools:
                logger.info("SanekAgent: │   retrying %d tools: %s", len(retry_tools), retry_tools)
                for tool_name in retry_tools:
                    step_retry = ReasoningStep(name=f"retry_{tool_name}", phase="verify")
                    step_retry.start()
                    try:
                        result = await self._execute_tool(tool_name, device_id, all_codes)
                        if result is not None:
                            collected[tool_name] = result
                            step_retry.complete(summary="retry OK")
                        else:
                            step_retry.complete(summary="retry OK — no data")
                    except Exception as exc:
                        step_retry.fail(error=str(exc)[:200])
                    reasoning_chain.append(step_retry)

            # ── PHASE 6: ANALYZE — send enriched data to LLM ─────────
            step_analyze = ReasoningStep(name="llm_analysis", phase="analyze")
            step_analyze.start()

            user_message = self._build_analysis_prompt(
                device_id=device_id,
                device_name=device_name,
                site_name=site_name,
                all_codes=all_codes,
                triggers=pending.triggers,
                collected=collected,
                device_info=device_info,
            )

            llm_result = await self._call_llm(user_message)
            step_analyze.complete(
                summary=f"provider={llm_result.get('provider')}, "
                        f"model={llm_result.get('model')}, "
                        f"tokens={llm_result.get('tokens')}",
                data={
                    "provider": llm_result.get("provider"),
                    "model": llm_result.get("model"),
                    "tokens": llm_result.get("tokens"),
                },
            )
            reasoning_chain.append(step_analyze)
            logger.info(
                "SanekAgent: │ ✓ ANALYZE — %s/%s (%s tokens)",
                llm_result.get("provider"), llm_result.get("model"),
                llm_result.get("tokens"),
            )

            # Parse structured sections from LLM response (before SOP phase)
            llm_text = llm_result.get("text", "")
            parsed_sections = self._parse_llm_sections(llm_text)

            # ── PHASE 7: SOP — resolve standard operating procedure ──
            step_sop = ReasoningStep(name="sop_lookup", phase="sop")
            step_sop.start()

            action_plan = None
            try:
                sop_ctx = SopLookupContext(
                    incident_id=incident_id,
                    alarm_code=primary_code,
                    device_type=device_info.get("device_type", "") if device_info else "",
                    device_name=device_name,
                    severity=pending.triggers[0].payload.get("severity", "") if pending.triggers else "",
                    cause=parsed_sections.get("cause", ""),
                    llm_caller=self._call_llm,
                )
                action_plan = await self._sop_engine.resolve(sop_ctx)
                step_sop.complete(
                    summary=f"source={action_plan.source}, confidence={action_plan.confidence:.2f}, "
                            f"sop_id={action_plan.sop_id}, steps={len(action_plan.actions)}",
                    data={
                        "source": action_plan.source,
                        "confidence": action_plan.confidence,
                        "sop_id": action_plan.sop_id,
                        "sop_version": action_plan.sop_version,
                        "steps_count": len(action_plan.actions),
                    },
                )
                logger.info(
                    "SanekAgent: │ ✓ SOP — source=%s confidence=%.2f sop_id=%s steps=%d",
                    action_plan.source, action_plan.confidence,
                    action_plan.sop_id, len(action_plan.actions),
                )
            except Exception as sop_exc:
                step_sop.complete(summary=f"error: {sop_exc}", data={"error": str(sop_exc)[:200]})
                logger.warning("SanekAgent: │ ✗ SOP — error: %s", sop_exc)

            reasoning_chain.append(step_sop)

            # ── PHASE 8: MEMORIZE — save full reasoning chain to DB ──
            step_memorize = ReasoningStep(name="save_to_db", phase="memorize")
            step_memorize.start()

            pipeline_duration_ms = round((time.monotonic() - pipeline_start) * 1000, 1)
            analysis_data = {
                "version": 3,  # reasoning loop version (v3 = with SOP)
                "pipeline_duration_ms": pipeline_duration_ms,
                "reasoning_chain": [s.to_dict() for s in reasoning_chain],
                "investigation_plan": plan.to_dict(),
                "verification": verification,
                "collected_data": {
                    "metrics_snapshot": collected.get("get_metrics_snapshot"),
                    "metrics_history": self._summarize_history(collected.get("get_metrics_history")),
                    "alarm_count": len(collected.get("get_alarm_history", [])),
                    "event_count": len(collected.get("get_events", [])),
                    "alarm_bits_count": len(collected.get("get_alarm_bits", [])),
                    "knowledge_chunks": len(collected.get("search_knowledge", [])),
                },
            }

            async with self.session_factory() as session:
                stmt = select(AgentIncident).where(AgentIncident.id == incident_id)
                result = await session.execute(stmt)
                incident = result.scalar_one()
                incident.analysis = analysis_data
                incident.cause = parsed_sections.get("cause", "") or None
                incident.recommendation = llm_text
                incident.llm_provider = llm_result.get("provider")
                incident.llm_model = llm_result.get("model")
                incident.llm_tokens_used = llm_result.get("tokens")
                incident.sop_actions = action_plan.to_dict() if action_plan else None
                incident.status = "completed"
                incident.completed_at = datetime.utcnow()
                await session.commit()

            step_memorize.complete(summary=f"incident_id={incident_id}, cause_parsed={'yes' if parsed_sections.get('cause') else 'no'}")
            reasoning_chain.append(step_memorize)
            logger.info("SanekAgent: │ ✓ MEMORIZE — saved incident=%d", incident_id)

            # ── PHASE 9: NOTIFY — publish report to Redis ────────────
            step_notify = ReasoningStep(name="publish_report", phase="notify")
            step_notify.start()

            await self._publish_report(
                incident_id=incident_id,
                device_id=device_id,
                device_name=device_name,
                site_id=site_id,
                alarm_code=primary_code,
                recommendation=llm_text,
                cause=parsed_sections.get("cause", ""),
                parsed_recommendation=parsed_sections.get("recommendation", ""),
                analysis_data=analysis_data,
                actions=action_plan.to_dict() if action_plan else None,
            )
            step_notify.complete(summary=f"published to {CH_REPORTS}")
            reasoning_chain.append(step_notify)

            logger.info(
                "SanekAgent: └─ DONE device=%d incident=%d (%.1fs total)",
                device_id, incident_id, pipeline_duration_ms / 1000,
            )

        except Exception as exc:
            logger.error(
                "SanekAgent: └─ FAILED device=%d incident=%d: %s",
                device_id, incident_id, exc, exc_info=True,
            )
            # Save error to DB
            try:
                async with self.session_factory() as session:
                    stmt = select(AgentIncident).where(AgentIncident.id == incident_id)
                    result = await session.execute(stmt)
                    incident = result.scalar_one()
                    incident.status = "failed"
                    incident.error_message = str(exc)[:500]
                    incident.completed_at = datetime.utcnow()
                    incident.analysis = {
                        "version": 2,
                        "reasoning_chain": [s.to_dict() for s in reasoning_chain],
                        "error": str(exc)[:500],
                    }
                    await session.commit()
            except Exception as save_exc:
                logger.error("SanekAgent: failed to save error status for incident=%d: %s", incident_id, save_exc)

    # ==================================================================
    # PLANNER — dynamic investigation plan builder
    # ==================================================================
    def _build_investigation_plan(
        self,
        alarm_codes: list[str],
        trigger_channel: str,
    ) -> InvestigationPlan:
        """Build investigation plan based on trigger type and alarm codes.

        Different incidents require different tool sets:
        - SHUTDOWN/TRIP_STOP → full investigation (metrics history + alarms + events + KB)
        - CONN_LOST → focus on connectivity, skip metrics history (device offline)
        - MAINTENANCE → focus on run hours and events, less urgency
        - EVENTS → standard investigation
        """
        # Determine trigger type
        if trigger_channel in (CH_ALARMS, CH_ALARM_EVENTS):
            trigger_type = "alarm"
        elif trigger_channel == CH_EVENTS:
            trigger_type = "event"
        elif trigger_channel == CH_MAINTENANCE:
            trigger_type = "maintenance"
        else:
            trigger_type = "event"  # safe fallback

        primary_code = alarm_codes[0] if alarm_codes else "UNKNOWN"

        # Base tools — always executed
        tools = ["get_metrics_snapshot", "get_past_incidents"]
        rationale_parts = ["снимок текущих метрик", "память: прошлые инциденты на устройстве"]

        # SHUTDOWN / TRIP_STOP — полное расследование
        if any(c in ("SHUTDOWN", "TRIP_STOP") for c in alarm_codes):
            tools.append("get_metrics_history")
            rationale_parts.append("история метрик ±5 мин (тренд до аварии)")
            tools.append("get_alarm_history")
            rationale_parts.append("аварии за 2ч (каскад аварий)")
            tools.append("get_alarm_bits")
            rationale_parts.append("побитовые аварии (детальные флаги)")
            tools.append("get_events")
            rationale_parts.append("журнал событий")
            tools.append("search_knowledge")
            rationale_parts.append("мануалы по кодам аварий")

        # CONN_LOST — фокус на связи
        elif any("CONN_LOST" in c for c in alarm_codes):
            tools.append("get_alarm_history")
            rationale_parts.append("аварии за 2ч (повторные обрывы)")
            tools.append("get_events")
            rationale_parts.append("события потери связи")
            tools.append("search_knowledge")
            rationale_parts.append("документация по коммуникации")
            # Don't fetch metrics_history — device is offline, no new data

        # BLOCK — блокировка запуска
        elif any("BLOCK" in c for c in alarm_codes):
            tools.append("get_metrics_history")
            rationale_parts.append("история метрик (условия до блокировки)")
            tools.append("get_alarm_history")
            rationale_parts.append("аварии (причина блокировки)")
            tools.append("get_alarm_bits")
            rationale_parts.append("побитовые флаги")
            tools.append("get_events")
            rationale_parts.append("журнал событий")
            tools.append("search_knowledge")
            rationale_parts.append("мануал по блокировкам")

        # MAINTENANCE — плановое ТО
        elif trigger_type == "maintenance":
            tools.append("get_alarm_history")
            rationale_parts.append("были ли аварии на этом устройстве")
            tools.append("get_events")
            rationale_parts.append("журнал событий")
            # Metrics history less critical for maintenance

        # EVENT — стандартное расследование
        else:
            tools.append("get_metrics_history")
            rationale_parts.append("история метрик ±5 мин")
            tools.append("get_alarm_history")
            rationale_parts.append("аварии за 2ч")
            tools.append("get_events")
            rationale_parts.append("журнал событий")
            tools.append("search_knowledge")
            rationale_parts.append("база знаний")

        plan = InvestigationPlan(
            trigger_type=trigger_type,
            primary_code=primary_code,
            tools=tools,
            rationale="; ".join(rationale_parts),
        )
        return plan

    # ==================================================================
    # TOOL REGISTRY — execute tools by name
    # ==================================================================
    async def _execute_tool(
        self,
        tool_name: str,
        device_id: int,
        alarm_codes: list[str],
    ) -> Any:
        """Dispatch tool execution by name. Returns tool result or None."""
        tool_map: dict[str, Callable[..., Awaitable]] = {
            "get_metrics_snapshot": lambda: self._tool_get_metrics_snapshot(device_id),
            "get_metrics_history": lambda: self._tool_get_metrics_history(device_id),
            "get_alarm_history": lambda: self._tool_get_alarm_history(device_id),
            "get_alarm_bits": lambda: self._tool_get_alarm_bits(device_id),
            "get_events": lambda: self._tool_get_events(device_id),
            "search_knowledge": lambda: self._tool_search_knowledge(alarm_codes),
            "get_past_incidents": lambda: self._tool_get_past_incidents(device_id, alarm_codes),
        }

        handler = tool_map.get(tool_name)
        if handler is None:
            logger.warning("SanekAgent: unknown tool '%s'", tool_name)
            return None
        return await handler()

    # ------------------------------------------------------------------
    # Tool: get_metrics_snapshot — current Redis snapshot
    # ------------------------------------------------------------------
    async def _tool_get_metrics_snapshot(self, device_id: int) -> dict | None:
        """Get current device metrics from Redis (instant, <1ms)."""
        raw = await self.redis.get(f"device:{device_id}:metrics")
        if raw:
            return json.loads(raw)
        return None

    # ------------------------------------------------------------------
    # Tool: get_metrics_history — ±5 min trend from MetricsData table
    # ------------------------------------------------------------------
    async def _tool_get_metrics_history(self, device_id: int) -> list[dict] | None:
        """Get metrics history ±5 min around current time from DB.

        Returns sampled data points (every 30s) with key parameters
        to show the trend leading up to the incident.
        """
        from models.metrics_data import MetricsData

        now = datetime.utcnow()
        time_from = now - timedelta(minutes=5)
        time_to = now + timedelta(minutes=1)  # small buffer for clock drift

        async with self.session_factory() as session:
            stmt = (
                select(MetricsData)
                .where(MetricsData.device_id == device_id)
                .where(MetricsData.timestamp >= time_from)
                .where(MetricsData.timestamp <= time_to)
                .order_by(MetricsData.timestamp)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        if not rows:
            return None

        # Sample every ~30s to reduce volume (poller writes ~2s intervals)
        sampled: list[dict] = []
        last_ts: datetime | None = None

        for row in rows:
            if last_ts and row.timestamp and (row.timestamp - last_ts).total_seconds() < 25:
                continue
            last_ts = row.timestamp

            point: dict[str, Any] = {
                "ts": row.timestamp.isoformat() if row.timestamp else None,
            }
            # Include key fields based on device type
            if row.device_type == "generator":
                point.update({
                    "power_total": row.power_total,
                    "gen_freq": row.gen_freq,
                    "gen_uab": row.gen_uab,
                    "engine_speed": row.engine_speed,
                    "coolant_temp": row.coolant_temp,
                    "oil_pressure": row.oil_pressure,
                    "oil_temp": row.oil_temp,
                    "current_a": row.current_a,
                    "load_pct": row.load_pct,
                    "gen_status": row.gen_status,
                    "battery_volt": row.battery_volt,
                })
            else:
                point.update({
                    "mains_total_p": row.mains_total_p,
                    "mains_freq": row.mains_freq,
                    "mains_uab": row.mains_uab,
                    "busbar_p": row.busbar_p,
                    "busbar_freq": row.busbar_freq,
                })
            sampled.append(point)

        return sampled

    # ------------------------------------------------------------------
    # Tool: get_alarm_history — recent alarms from DB
    # ------------------------------------------------------------------
    async def _tool_get_alarm_history(self, device_id: int) -> list[dict]:
        """Get alarm events for this device in the last 2 hours."""
        async with self.session_factory() as session:
            cutoff = datetime.utcnow() - timedelta(hours=2)
            stmt = (
                select(AlarmEvent)
                .where(AlarmEvent.device_id == device_id)
                .where(AlarmEvent.occurred_at >= cutoff)
                .order_by(desc(AlarmEvent.occurred_at))
                .limit(20)
            )
            result = await session.execute(stmt)
            alarms = result.scalars().all()
            return [
                {
                    "alarm_code": a.alarm_code,
                    "severity": a.severity,
                    "message": a.message,
                    "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
                    "cleared_at": a.cleared_at.isoformat() if a.cleared_at else None,
                    "is_active": a.is_active,
                }
                for a in alarms
            ]

    # ------------------------------------------------------------------
    # Tool: get_alarm_bits — active bit-level alarms from alarm_analytics
    # ------------------------------------------------------------------
    async def _tool_get_alarm_bits(self, device_id: int) -> list[dict]:
        """Get active bit-level alarms from alarm_analytics module."""
        from alarm_analytics.models import AlarmAnalyticsEvent

        async with self.session_factory() as session:
            stmt = (
                select(AlarmAnalyticsEvent)
                .where(AlarmAnalyticsEvent.device_id == device_id)
                .where(AlarmAnalyticsEvent.is_active == True)  # noqa: E712
                .limit(20)
            )
            result = await session.execute(stmt)
            events = result.scalars().all()
            return [
                {
                    "alarm_name": e.alarm_name,
                    "alarm_severity": e.alarm_severity,
                    "description_ru": (
                        (e.analysis_result or {}).get("manual_description", "")
                        or e.alarm_name_ru
                        or ""
                    ),
                    "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                }
                for e in events
            ]

    # ------------------------------------------------------------------
    # Tool: get_events — recent SCADA events from DB
    # ------------------------------------------------------------------
    async def _tool_get_events(self, device_id: int) -> list[dict]:
        """Get SCADA event journal entries for this device in the last 2 hours."""
        async with self.session_factory() as session:
            cutoff = datetime.utcnow() - timedelta(hours=2)
            stmt = (
                select(ScadaEvent)
                .where(ScadaEvent.device_id == device_id)
                .where(ScadaEvent.created_at >= cutoff)
                .order_by(desc(ScadaEvent.created_at))
                .limit(30)
            )
            result = await session.execute(stmt)
            events = result.scalars().all()
            return [
                {
                    "category": e.category,
                    "event_code": e.event_code,
                    "message": e.message,
                    "old_value": e.old_value,
                    "new_value": e.new_value,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ]

    # ------------------------------------------------------------------
    # Tool: search_knowledge — KB search for relevant documentation
    # ------------------------------------------------------------------
    async def _tool_search_knowledge(self, alarm_codes: list[str]) -> list[dict]:
        """Search knowledge base for relevant documentation chunks."""
        query_map = {
            "SHUTDOWN": "alarm shutdown trip over power coolant oil pressure",
            "TRIP_STOP": "emergency stop trip safety protection",
            "CONN_LOST": "communication modbus connection lost troubleshooting",
            "BLOCK": "alarm block interlock start failure",
            "WARNING": "warning alarm maintenance service",
        }

        results: list[dict] = []
        seen_ids: set[int] = set()

        for code in alarm_codes:
            base_code = code.replace("EVENT_", "").replace("MAINTENANCE_", "")
            query = query_map.get(base_code, f"{base_code} alarm protection troubleshooting")

            async with self.session_factory() as session:
                keywords = query.split()[:5]
                stmt = select(AiKnowledgeChunk).limit(50)
                result = await session.execute(stmt)
                chunks = result.scalars().all()

                for chunk in chunks:
                    if chunk.id in seen_ids:
                        continue
                    content_lower = (chunk.content or "").lower()
                    title_lower = (chunk.title or "").lower()
                    score = sum(
                        1 for kw in keywords
                        if kw.lower() in content_lower or kw.lower() in title_lower
                    )
                    if score >= 2:
                        seen_ids.add(chunk.id)
                        results.append({
                            "title": chunk.title or "",
                            "content": (chunk.content or "")[:800],
                            "source": chunk.source_filename or "",
                            "score": score,
                        })

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:5]

    # ------------------------------------------------------------------
    # Tool: get_device_info — resolve device & site from DB (no HTTP)
    # ------------------------------------------------------------------
    async def _tool_get_device_info(self, device_id: int) -> dict | None:
        """Resolve device name, type, site_id, site_name directly from DB."""
        from models.device import Device
        from models.site import Site

        try:
            async with self.session_factory() as session:
                stmt = (
                    select(Device, Site)
                    .outerjoin(Site, Device.site_id == Site.id)
                    .where(Device.id == device_id)
                )
                result = await session.execute(stmt)
                row = result.first()
                if row is None:
                    return None

                device, site = row
                return {
                    "device_id": device.id,
                    "device_name": device.name,
                    "device_type": device.device_type.value if device.device_type else "generator",
                    "ip_address": device.ip_address,
                    "site_id": device.site_id,
                    "site_name": site.name if site else "",
                    "site_code": site.code if site else "",
                    "run_hours_note": "see metrics for run_hours",
                }
        except Exception as exc:
            logger.warning("SanekAgent: get_device_info failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Tool: get_past_incidents — agent memory (past analyses for device)
    # ------------------------------------------------------------------
    async def _tool_get_past_incidents(
        self, device_id: int, alarm_codes: list[str] | None = None,
    ) -> list[dict]:
        """Query past completed incidents for the same device.

        Returns up to 5 most recent completed analyses with:
        - alarm_code, cause, recommendation summary, timestamp.
        Used as "memory" so the agent can reference past diagnoses,
        detect recurring problems, and avoid repeating analysis.
        """
        try:
            async with self.session_factory() as session:
                stmt = (
                    select(AgentIncident)
                    .where(AgentIncident.device_id == device_id)
                    .where(AgentIncident.status == "completed")
                    .order_by(desc(AgentIncident.completed_at))
                    .limit(5)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

                if not rows:
                    return []

                incidents: list[dict] = []
                for row in rows:
                    incidents.append({
                        "id": row.id,
                        "alarm_code": row.alarm_code,
                        "cause": (row.cause or "")[:300],
                        "recommendation": (row.recommendation or "")[:300],
                        "created_at": row.created_at.isoformat() if row.created_at else "",
                        "completed_at": row.completed_at.isoformat() if row.completed_at else "",
                        "llm_provider": row.llm_provider,
                    })
                return incidents
        except Exception as exc:
            logger.warning("SanekAgent: get_past_incidents failed: %s", exc)
            return []

    # ==================================================================
    # VERIFY — check collected data completeness
    # ==================================================================
    def _verify_collected_data(
        self,
        collected: dict[str, Any],
        plan: InvestigationPlan,
    ) -> dict:
        """Verify that all planned tools returned data. Returns verification report."""
        tools_total = len(plan.tools)
        tools_ok = 0
        tools_empty = 0
        missing_tools: list[str] = []
        retry_tools: list[str] = []

        # Critical tools that should be retried if missing
        critical_tools = {"get_metrics_snapshot", "get_alarm_history"}

        for tool_name in plan.tools:
            result = collected.get(tool_name)
            if result is None:
                missing_tools.append(tool_name)
                if tool_name in critical_tools:
                    retry_tools.append(tool_name)
            elif isinstance(result, (list, dict)) and len(result) == 0:
                tools_empty += 1
                tools_ok += 1  # empty is OK (no data != error)
            else:
                tools_ok += 1

        completeness_pct = round((tools_ok / tools_total) * 100) if tools_total > 0 else 0

        return {
            "tools_total": tools_total,
            "tools_ok": tools_ok,
            "tools_empty": tools_empty,
            "missing_tools": missing_tools,
            "retry_tools": retry_tools,
            "completeness_pct": completeness_pct,
            "data_sufficient": completeness_pct >= 50,
        }

    @staticmethod
    def _summarize_history(history: list[dict] | None) -> dict | None:
        """Compact summary of metrics history for storage in analysis JSONB."""
        if not history:
            return None
        return {
            "data_points": len(history),
            "time_range": {
                "from": history[0].get("ts") if history else None,
                "to": history[-1].get("ts") if history else None,
            },
            # Store first and last point for quick view
            "first_point": history[0] if history else None,
            "last_point": history[-1] if history else None,
        }

    # ==================================================================
    # LLM CALL — multi-provider support
    # ==================================================================
    async def _call_llm(self, user_message: str) -> dict:
        """Call LLM using the configured provider (same as sanek.py chat)."""
        provider, api_key, model = self._get_llm_config()

        if not api_key:
            logger.warning("SanekAgent: no LLM API key configured")
            return {
                "text": "⚠ AI-анализ недоступен: не настроен API-ключ LLM провайдера.",
                "provider": None,
                "model": None,
                "tokens": None,
            }

        try:
            if provider in ("openai", "grok"):
                return await self._call_openai(api_key, model, user_message, provider)
            elif provider == "claude":
                return await self._call_claude(api_key, model, user_message)
            elif provider == "gemini":
                return await self._call_gemini(api_key, model, user_message)
            else:
                return await self._call_openai(api_key, model, user_message, provider)
        except Exception as exc:
            logger.error("SanekAgent LLM call failed (%s): %s", provider, exc)
            return {
                "text": f"⚠ Ошибка AI-анализа ({provider}): {str(exc)[:200]}",
                "provider": provider,
                "model": model,
                "tokens": None,
            }

    def _get_llm_config(self) -> tuple[str, str, str]:
        """Get LLM provider, key, model from the same cache as ai_parser."""
        try:
            from api.ai_parser import _get_active_provider, _get_api_key, _get_model
            provider = _get_active_provider()
            api_key = _get_api_key(provider)
            model = _get_model(provider)
            return provider, api_key, model
        except Exception:
            provider = settings.AI_PROVIDER
            key_map = {
                "openai": settings.OPENAI_API_KEY,
                "claude": settings.CLAUDE_API_KEY,
                "gemini": settings.GEMINI_API_KEY,
                "grok": settings.GROK_API_KEY,
            }
            model_map = {
                "openai": settings.OPENAI_MODEL,
                "claude": settings.CLAUDE_MODEL,
                "gemini": settings.GEMINI_MODEL,
                "grok": settings.GROK_MODEL,
            }
            return provider, key_map.get(provider, ""), model_map.get(provider, "")

    async def _call_openai(self, api_key: str, model: str, message: str, provider: str = "openai") -> dict:
        """Call OpenAI/Grok API (no tool calling, simple completion)."""
        from openai import AsyncOpenAI

        base_url = "https://api.x.ai/v1" if provider == "grok" else None
        client = AsyncOpenAI(api_key=api_key, timeout=self._llm_timeout, base_url=base_url)

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0.3,
            max_completion_tokens=2048,
        )

        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else None
        return {"text": text, "provider": provider, "model": model, "tokens": tokens}

    async def _call_claude(self, api_key: str, model: str, message: str) -> dict:
        """Call Claude API via httpx (same pattern as sanek.py)."""
        async with httpx.AsyncClient(timeout=self._llm_timeout) as http:
            resp = await http.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_completion_tokens": 2048,
                    "system": AGENT_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": message}],
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        tokens = None
        usage = data.get("usage", {})
        if usage:
            tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return {"text": text, "provider": "claude", "model": model, "tokens": tokens}

    async def _call_gemini(self, api_key: str, model: str, message: str) -> dict:
        """Call Gemini API via httpx."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        async with httpx.AsyncClient(timeout=self._llm_timeout) as http:
            resp = await http.post(
                url,
                json={
                    "system_instruction": {"parts": [{"text": AGENT_SYSTEM_PROMPT}]},
                    "contents": [{"role": "user", "parts": [{"text": message}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text += part.get("text", "")

        tokens = None
        usage = data.get("usageMetadata", {})
        if usage:
            tokens = usage.get("totalTokenCount")
        return {"text": text, "provider": "gemini", "model": model, "tokens": tokens}

    # ==================================================================
    # PROMPT BUILDER — enriched with reasoning data
    # ==================================================================
    def _build_analysis_prompt(
        self,
        device_id: int,
        device_name: str,
        site_name: str,
        all_codes: list[str],
        triggers: list[TriggerEvent],
        collected: dict[str, Any],
        device_info: dict | None,
    ) -> str:
        """Build the enriched user message for LLM analysis."""
        parts: list[str] = []

        # Header
        now_msk = (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M MSK")
        parts.append(f"📅 Время анализа: {now_msk}")
        parts.append(f"🔧 Устройство: {device_name} (device_id={device_id})")
        if site_name:
            parts.append(f"🏭 Объект: {site_name}")
        if device_info:
            parts.append(f"📋 Тип: {device_info.get('device_type', '?')}, IP: {device_info.get('ip_address', '?')}")
        parts.append(f"🚨 Коды аварий: {', '.join(all_codes)}")
        parts.append(f"📊 Количество триггеров за {self._debounce}с: {len(triggers)}")
        parts.append("")

        # Trigger details
        parts.append("═══ ТРИГГЕРЫ ═══")
        for i, t in enumerate(triggers[:5], 1):
            parts.append(f"{i}. [{t.channel}] {t.alarm_code}")
            if t.channel == CH_ALARMS:
                alarm = t.payload.get("alarm", {})
                parts.append(f"   Сообщение: {alarm.get('message', '—')}")
                parts.append(f"   Severity: {alarm.get('severity', '—')}")
            elif t.channel == CH_EVENTS:
                parts.append(f"   Событие: {t.payload.get('message', '—')}")
                parts.append(f"   old={t.payload.get('old_value', '—')} → new={t.payload.get('new_value', '—')}")
        parts.append("")

        # Current metrics snapshot
        metrics = collected.get("get_metrics_snapshot", {})
        if metrics:
            parts.append("═══ ТЕКУЩИЕ МЕТРИКИ ═══")
            device_type = metrics.get("device_type", "generator")
            if device_type == "generator":
                fields = [
                    ("Статус (gen_status)", metrics.get("gen_status")),
                    ("Online", metrics.get("online")),
                    ("Мощность (кВт)", metrics.get("power_total")),
                    ("Напряжение UAB (В)", metrics.get("gen_uab")),
                    ("Ток фаза A (А)", metrics.get("current_a")),
                    ("Частота (Гц)", metrics.get("gen_freq")),
                    ("Обороты (об/мин)", metrics.get("engine_speed")),
                    ("Температура ОЖ (°C)", metrics.get("coolant_temp")),
                    ("Давление масла (кПа)", metrics.get("oil_pressure")),
                    ("Температура масла (°C)", metrics.get("oil_temp")),
                    ("Уровень топлива (%)", metrics.get("fuel_level")),
                    ("Нагрузка (%)", metrics.get("load_pct")),
                    ("Наработка (ч)", metrics.get("run_hours")),
                    ("Энергия (кВт·ч)", metrics.get("energy_kwh")),
                    ("Напряжение АКБ (В)", metrics.get("battery_volt")),
                ]
            else:
                fields = [
                    ("Online", metrics.get("online")),
                    ("Мощность сети (кВт)", metrics.get("mains_total_p")),
                    ("Мощность шины (кВт)", metrics.get("busbar_p")),
                    ("Напряжение сети UAB (В)", metrics.get("mains_uab")),
                    ("Частота сети (Гц)", metrics.get("mains_freq")),
                ]
            for label, val in fields:
                if val is not None:
                    parts.append(f"  {label}: {val}")
            parts.append("")

        # Metrics history (trend ±5 min)
        history = collected.get("get_metrics_history")
        if history and isinstance(history, list) and len(history) > 0:
            parts.append(f"═══ ТРЕНД МЕТРИК (±5 мин, {len(history)} точек) ═══")
            # Show key trend: power, temp, oil pressure over time
            for point in history:
                ts_short = (point.get("ts") or "?")[-8:]  # HH:MM:SS
                power = point.get("power_total", "")
                temp = point.get("coolant_temp", "")
                oil = point.get("oil_pressure", "")
                speed = point.get("engine_speed", "")
                status = point.get("gen_status", "")
                parts.append(
                    f"  {ts_short} | pwr={power} | temp={temp} | oil={oil} "
                    f"| rpm={speed} | status={status}"
                )
            parts.append("")

        # Recent alarms
        alarms = collected.get("get_alarm_history", [])
        if alarms:
            parts.append("═══ АВАРИИ ЗА 2 ЧАСА ═══")
            for a in alarms[:10]:
                status = "⚠️ АКТИВНА" if a.get("is_active") else "✅ снята"
                parts.append(
                    f"  [{a.get('occurred_at', '?')}] {a.get('alarm_code')} "
                    f"({a.get('severity')}) — {a.get('message')} [{status}]"
                )
            parts.append("")

        # Alarm bits (detailed)
        alarm_bits = collected.get("get_alarm_bits", [])
        if alarm_bits:
            parts.append("═══ ПОБИТОВЫЕ АВАРИИ (активные) ═══")
            for ab in alarm_bits[:10]:
                parts.append(
                    f"  {ab.get('alarm_name')} ({ab.get('alarm_severity')}) "
                    f"— {ab.get('description_ru', '—')} [с {ab.get('occurred_at', '?')}]"
                )
            parts.append("")

        # SCADA events
        events = collected.get("get_events", [])
        if events:
            parts.append("═══ СОБЫТИЯ SCADA ЗА 2 ЧАСА ═══")
            for e in events[:15]:
                parts.append(
                    f"  [{e.get('created_at', '?')}] {e.get('category')}/{e.get('event_code')} "
                    f"— {e.get('message')}"
                )
            parts.append("")

        # Knowledge base context
        kb_context = collected.get("search_knowledge", [])
        if kb_context:
            parts.append("═══ ИЗ БАЗЫ ЗНАНИЙ (МАНУАЛЫ) ═══")
            for kb in kb_context[:3]:
                parts.append(f"📖 {kb.get('title')} (источник: {kb.get('source')})")
                parts.append(f"   {kb.get('content', '')[:500]}")
                parts.append("")

        # Past incidents (agent memory)
        past_incidents = collected.get("get_past_incidents", [])
        if past_incidents:
            parts.append(f"═══ ПАМЯТЬ: ПРОШЛЫЕ ИНЦИДЕНТЫ НА УСТРОЙСТВЕ ({len(past_incidents)} шт) ═══")
            for pi in past_incidents[:5]:
                ts = pi.get("completed_at") or pi.get("created_at") or "?"
                parts.append(f"  [{ts}] Авария: {pi.get('alarm_code', '?')}")
                cause_text = pi.get("cause", "")
                if cause_text:
                    parts.append(f"    Причина: {cause_text[:200]}")
                rec_text = pi.get("recommendation", "")
                if rec_text:
                    parts.append(f"    Рекомендация: {rec_text[:200]}")
                parts.append("")
            parts.append(
                "⚠ Учти прошлые инциденты: если проблема ПОВТОРЯЕТСЯ — укажи это! "
                "Если причина та же — рекомендуй системное решение, а не повторный ремонт."
            )
            parts.append("")

        # Instructions
        parts.append("═══ ЗАДАНИЕ ═══")
        parts.append("Проанализируй данные выше и дай отчёт по структуре:")
        parts.append("📊 ИНЦИДЕНТ — что произошло, когда, на каком устройстве")
        parts.append("🔍 ПРИЧИНА — определи по метрикам и тренду (конкретные числа!)")
        parts.append("⚡ ПОСЛЕДСТВИЯ — простой, потери энергии")
        parts.append("🔧 РЕКОМЕНДАЦИИ — конкретные действия оператора")
        if history:
            parts.append("💡 ТРЕНД — проанализируй изменение параметров во времени (до/во время/после аварии)")

        return "\n".join(parts)

    # ==================================================================
    # MEMORY — dedup and helpers
    # ==================================================================
    async def _has_recent_incident(self, device_id: int, alarm_code: str) -> bool:
        """Check if we already analyzed this alarm code for this device recently."""
        try:
            async with self.session_factory() as session:
                cutoff = datetime.utcnow() - timedelta(minutes=10)
                stmt = (
                    select(func.count())
                    .select_from(AgentIncident)
                    .where(AgentIncident.device_id == device_id)
                    .where(AgentIncident.alarm_code == alarm_code)
                    .where(AgentIncident.created_at >= cutoff)
                )
                result = await session.execute(stmt)
                count = result.scalar() or 0
                return count > 0
        except Exception:
            return False

    async def _resolve_site_id(self, device_id: int) -> int | None:
        """Resolve site_id from device_id (legacy, use _tool_get_device_info instead)."""
        info = await self._tool_get_device_info(device_id)
        return info.get("site_id") if info else None

    # ==================================================================
    # PARSE — extract structured sections from LLM response
    # ==================================================================
    @staticmethod
    def _parse_llm_sections(llm_text: str) -> dict[str, str]:
        """Parse structured LLM response into named sections.

        Expected sections in LLM output (from AGENT_SYSTEM_PROMPT):
            📊 ИНЦИДЕНТ — incident summary
            🔍 ПРИЧИНА  — root cause analysis
            ⚡ ПОСЛЕДСТВИЯ — consequences
            🔧 РЕКОМЕНДАЦИИ — recommendations
            💡 ТРЕНД — trend analysis (optional)

        Returns dict with keys: incident, cause, consequences, recommendation, trend.
        Each value is the text content of that section (stripped).
        If a section is not found, its value is an empty string.
        """
        sections: dict[str, str] = {
            "incident": "",
            "cause": "",
            "consequences": "",
            "recommendation": "",
            "trend": "",
        }

        # Map emoji markers → section keys
        marker_patterns = [
            (r"📊\s*ИНЦИДЕНТ", "incident"),
            (r"🔍\s*ПРИЧИНА", "cause"),
            (r"⚡\s*ПОСЛЕДСТВИЯ", "consequences"),
            (r"🔧\s*РЕКОМЕНДАЦИИ", "recommendation"),
            (r"💡\s*ТРЕНД", "trend"),
        ]

        # Build ordered list of (match_start, match_end, key) for found markers
        found: list[tuple[int, int, str]] = []
        for pattern, key in marker_patterns:
            m = re.search(pattern, llm_text)
            if m:
                found.append((m.start(), m.end(), key))

        # Sort by position in text
        found.sort(key=lambda x: x[0])

        # Extract text between consecutive markers
        for i, (start, end, key) in enumerate(found):
            if i + 1 < len(found):
                next_start = found[i + 1][0]
                section_text = llm_text[end:next_start]
            else:
                # Last section — take everything until end
                section_text = llm_text[end:]
            sections[key] = section_text.strip().strip("—").strip()

        # Fallback: if parsing yielded nothing, use full text as recommendation
        if not any(sections.values()):
            sections["recommendation"] = llm_text.strip()

        return sections

    # ==================================================================
    # NOTIFY — publish report to Redis for WebSocket bridge
    # ==================================================================
    async def _publish_report(
        self,
        incident_id: int,
        device_id: int,
        device_name: str,
        site_id: int | None,
        alarm_code: str,
        recommendation: str,
        cause: str = "",
        parsed_recommendation: str = "",
        analysis_data: dict | None = None,
        actions: dict | None = None,
    ) -> None:
        """Publish completed report to Redis channels.

        Publishes to two channels:
        - sanek:reports — legacy, for SanekAgent WebSocket bridge (UI notifications)
        - ai:analysis   — structured AI analysis for WebSocket → frontend

        The ai:analysis channel sends a clean message with:
            type = "ai_analysis"
            data = {device_id, alarm, cause, recommendation, ...}
        """
        now_iso = datetime.utcnow().isoformat()

        report_data = {
            "id": incident_id,
            "device_id": device_id,
            "device_name": device_name,
            "site_id": site_id,
            "alarm_code": alarm_code,
            "recommendation": recommendation[:500],  # truncate for WS
            "status": "completed",
            "created_at": now_iso,
            "reasoning_summary": {
                "version": analysis_data.get("version") if analysis_data else None,
                "pipeline_duration_ms": analysis_data.get("pipeline_duration_ms") if analysis_data else None,
                "tools_used": len(analysis_data.get("investigation_plan", {}).get("tools", [])) if analysis_data else 0,
                "completeness_pct": analysis_data.get("verification", {}).get("completeness_pct") if analysis_data else None,
            } if analysis_data else None,
        }

        # 1. Publish to sanek:reports (legacy — WS bridge → UI)
        sanek_report = {"type": "sanek_report", "data": report_data}
        try:
            await self.redis.publish(CH_REPORTS, json.dumps(sanek_report, default=str))
            logger.info("SanekAgent: published report incident=%d to %s", incident_id, CH_REPORTS)
        except Exception as exc:
            logger.warning("SanekAgent: failed to publish to %s: %s", CH_REPORTS, exc)

        # 2. Publish to ai:analysis — structured format for frontend WebSocket
        #    Frontend expects: type="ai_analysis", data={device_id, alarm, cause, recommendation}
        ai_analysis_data = {
            "id": incident_id,
            "device_id": device_id,
            "device_name": device_name,
            "site_id": site_id,
            "alarm": alarm_code,
            "cause": cause[:500] if cause else "",
            "recommendation": parsed_recommendation[:500] if parsed_recommendation else recommendation[:500],
            "status": "completed",
            "created_at": now_iso,
        }
        if actions:
            ai_analysis_data["actions"] = actions
        ai_analysis = {"type": "ai_analysis", "data": ai_analysis_data}
        try:
            await self.redis.publish(CH_AI_ANALYSIS, json.dumps(ai_analysis, default=str))
            logger.info("SanekAgent: published analysis incident=%d to %s", incident_id, CH_AI_ANALYSIS)
        except Exception as exc:
            logger.warning("SanekAgent: failed to publish to %s: %s", CH_AI_ANALYSIS, exc)
