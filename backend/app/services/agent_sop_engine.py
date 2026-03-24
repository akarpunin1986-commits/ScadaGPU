"""SOP Engine — Standard Operating Procedures lookup and action plan generation.

Stateless module that maps (alarm_code, device_type, root_cause) to a concrete
operator action plan.  Falls back to LLM-generated procedures when no SOP
is found in the database.

4-tier lookup priority:
    1. Exact match (alarm + device_type + root_cause)  → confidence 0.95
    2. Alarm + device_type (root_cause IS NULL)         → confidence 0.70
    3. Alarm + device_type='any'                        → confidence 0.50
    4. LLM fallback                                     → confidence 0.40
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.sop_procedure import SopProcedure

logger = logging.getLogger("scada.sop_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_CACHE_TTL_S = 120          # TTL for SOP lookup cache (seconds)
_LLM_RAW_LIMIT = 4000      # Max chars from LLM response before regex parse
_MAX_ACTIONS = 20           # Max steps in a single action plan
_MAX_INSTRUCTION_LEN = 500  # Max length of a single instruction string
_MAX_PLAN_JSON_SIZE = 10240  # 10 KB limit for serialized action plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize_alarm_code(val: str | None) -> str:
    """Normalize alarm code to uppercase, stripped."""
    if not val:
        return "UNKNOWN"
    return val.strip().upper()


def normalize_device_type(val: str | None) -> str:
    """Normalize device_type: lowercase, only [a-z0-9_]."""
    if not val:
        return "unknown"
    return re.sub(r"[^a-z0-9_]", "", val.lower().strip()) or "unknown"


def normalize_root_cause(val: str | None) -> str:
    """Normalize root_cause: uppercase, stripped. Returns 'UNKNOWN' if empty."""
    if not val:
        return "UNKNOWN"
    result = val.strip().upper()
    return result if result else "UNKNOWN"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class SopLookupContext:
    """Input context for SOP resolution."""
    incident_id: int
    alarm_code: str
    device_type: str
    device_name: str = ""
    severity: str = ""
    cause: str = ""
    llm_caller: Callable[[str], Awaitable[dict]] | None = None


@dataclass
class ActionPlan:
    """Output action plan for an incident."""
    incident_id: int
    device: str
    alarm: str
    cause: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    source: str = "db"          # "db" | "llm" | "error"
    confidence: float = 0.0
    sop_id: int | None = None
    sop_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "incident_id": self.incident_id,
            "device": self.device,
            "alarm": self.alarm,
            "cause": self.cause,
            "actions": self.actions,
            "source": self.source,
            "confidence": self.confidence,
            "sop_id": self.sop_id,
            "sop_version": self.sop_version,
        }
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        if len(serialized) > _MAX_PLAN_JSON_SIZE:
            result["actions"] = result["actions"][:5]
            result["_truncated"] = True
            logger.warning(
                "SOP Engine: action plan truncated, size exceeded %d bytes, incident=%d",
                _MAX_PLAN_JSON_SIZE, self.incident_id,
            )
        return result


# ---------------------------------------------------------------------------
# SOP Engine
# ---------------------------------------------------------------------------
class SopEngine:
    """Stateless SOP lookup + action plan builder.

    Uses a dict-based TTL cache with asyncio.Lock for thread safety.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._cache: dict[str, tuple[float, SopProcedure | None]] = {}
        self._cache_lock = asyncio.Lock()
        self._started = False

    # ── Public API ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """One-time startup check: verify sop_procedures table is accessible."""
        if self._started:
            return
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(SopProcedure.id).limit(1)
                )
                count = 1 if result.scalar() else 0
                logger.info("SOP Engine: startup check OK, table accessible, has_data=%s", count > 0)
                self._started = True
        except Exception as exc:
            logger.error("SOP Engine: startup check FAILED — %s", exc)

    async def resolve(self, ctx: SopLookupContext) -> ActionPlan:
        """Main entry point: resolve incident → action plan."""
        alarm = normalize_alarm_code(ctx.alarm_code)
        device_type = normalize_device_type(ctx.device_type)
        cause = normalize_root_cause(ctx.cause)

        # Tier 1–3: database lookup
        sop = await self._lookup(alarm, device_type, cause)
        if sop:
            plan = self._build_plan_from_db(ctx, sop, device_type, cause)
            logger.info(
                "SOP Engine: DB hit for incident=%d alarm=%s device=%s, sop_id=%d confidence=%.2f",
                ctx.incident_id, alarm, device_type, sop.id, plan.confidence,
            )
            return plan

        # Tier 4: LLM fallback
        if ctx.llm_caller:
            plan = await self._build_plan_from_llm(ctx, alarm, device_type)
            logger.info(
                "SOP Engine: LLM fallback for incident=%d alarm=%s, confidence=%.2f",
                ctx.incident_id, alarm, plan.confidence,
            )
            return plan

        # No SOP, no LLM — safe fallback
        logger.warning(
            "SOP Engine: no SOP and no LLM for incident=%d alarm=%s",
            ctx.incident_id, alarm,
        )
        return self._safe_fallback(ctx, alarm)

    def invalidate_cache(self) -> None:
        """Clear the SOP lookup cache (e.g. after SOP table update)."""
        self._cache.clear()
        logger.info("SOP Engine: cache invalidated")

    # ── Database lookup (3-tier) ───────────────────────────────────────

    async def _lookup(
        self, alarm: str, device_type: str, cause: str,
    ) -> SopProcedure | None:
        """4-tier priority lookup with TTL cache and double-checked locking."""

        cache_key = f"{alarm}:{device_type}:{cause}"
        now = time.monotonic()

        # Fast path: check cache without lock
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL_S:
            return cached[1]

        # Slow path: acquire lock, double-check, then query DB
        async with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                return cached[1]

            sop = await self._query_db(alarm, device_type, cause)
            self._cache[cache_key] = (time.monotonic(), sop)
            return sop

    async def _query_db(
        self, alarm: str, device_type: str, cause: str,
    ) -> SopProcedure | None:
        """Execute 3-tier DB query. Returns best match or None."""
        async with self._session_factory() as session:
            # Tier 1: exact match (alarm + device_type + root_cause)
            stmt = select(SopProcedure).where(
                and_(
                    SopProcedure.alarm_code == alarm,
                    SopProcedure.device_type == device_type,
                    SopProcedure.root_cause == cause,
                )
            ).limit(1)
            result = await session.execute(stmt)
            sop = result.scalar_one_or_none()
            if sop:
                return sop

            # Tier 2: alarm + device_type, root_cause IS NULL
            stmt = select(SopProcedure).where(
                and_(
                    SopProcedure.alarm_code == alarm,
                    SopProcedure.device_type == device_type,
                    SopProcedure.root_cause.is_(None),
                )
            ).limit(1)
            result = await session.execute(stmt)
            sop = result.scalar_one_or_none()
            if sop:
                return sop

            # Tier 3: alarm + device_type='any'
            stmt = select(SopProcedure).where(
                and_(
                    SopProcedure.alarm_code == alarm,
                    SopProcedure.device_type == "any",
                )
            ).limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    # ── Plan builders ──────────────────────────────────────────────────

    def _build_plan_from_db(
        self, ctx: SopLookupContext, sop: SopProcedure,
        device_type: str, cause: str,
    ) -> ActionPlan:
        """Build action plan from a database SOP record."""
        raw_actions = sop.actions_json or []

        # Determine confidence by tier
        if sop.root_cause and sop.device_type != "any":
            confidence = 0.95
        elif sop.device_type != "any":
            confidence = 0.70
        else:
            confidence = 0.50

        actions = []
        for i, action in enumerate(raw_actions[:_MAX_ACTIONS]):
            if not isinstance(action, dict):
                continue
            step = {
                "step": action.get("step", i + 1),
                "instruction": str(action.get("instruction", ""))[:_MAX_INSTRUCTION_LEN],
            }
            # Optional fields
            for opt_key in ("ui_control", "expected_state", "verification", "safety_note"):
                val = action.get(opt_key)
                if val is not None:
                    step[opt_key] = str(val)[:_MAX_INSTRUCTION_LEN]
            actions.append(step)

        return ActionPlan(
            incident_id=ctx.incident_id,
            device=ctx.device_name or device_type,
            alarm=ctx.alarm_code,
            cause=ctx.cause or cause,
            actions=actions,
            source="db",
            confidence=confidence,
            sop_id=sop.id,
            sop_version=sop.version,
        )

    async def _build_plan_from_llm(
        self, ctx: SopLookupContext, alarm: str, device_type: str,
    ) -> ActionPlan:
        """Build action plan using LLM fallback."""
        prompt = self._build_fallback_prompt(alarm, device_type, ctx.cause, ctx.device_name)

        try:
            llm_result = await ctx.llm_caller(prompt)
            raw_text = llm_result.get("text", "")
            actions = self._parse_llm_actions(raw_text)

            if not actions:
                logger.warning(
                    "SOP Engine: LLM returned no parseable actions for incident=%d",
                    ctx.incident_id,
                )
                return self._safe_fallback(ctx, alarm)

            return ActionPlan(
                incident_id=ctx.incident_id,
                device=ctx.device_name or device_type,
                alarm=ctx.alarm_code,
                cause=ctx.cause,
                actions=actions,
                source="llm",
                confidence=0.40,
            )
        except Exception as exc:
            logger.error(
                "SOP Engine: LLM fallback failed for incident=%d — %s",
                ctx.incident_id, exc,
            )
            return self._safe_fallback(ctx, alarm)

    # ── LLM prompt & parsing ──────────────────────────────────────────

    @staticmethod
    def _build_fallback_prompt(
        alarm: str, device_type: str, cause: str, device_name: str,
    ) -> str:
        return (
            f"You are an industrial power systems engineer.\n"
            f"Device: {device_name or device_type}\n"
            f"Alarm: {alarm}\n"
            f"Cause: {cause}\n\n"
            f"Generate a JSON array of operator action steps.\n"
            f"Each step must have: step (int), instruction (string).\n"
            f"Optional fields: ui_control, expected_state, verification, safety_note.\n"
            f"Return ONLY a JSON array, no markdown, no explanation.\n"
            f"Maximum 10 steps. Each instruction under 200 characters.\n"
            'Example: [{"step": 1, "instruction": "Check relay status"}]'
        )

    @staticmethod
    def _parse_llm_actions(raw: str) -> list[dict[str, Any]]:
        """Parse JSON array of actions from LLM response.

        Strips markdown fences, uses non-greedy regex, limits input size.
        """
        if not raw:
            return []

        truncated = raw[:_LLM_RAW_LIMIT]

        # Strip markdown code fences
        truncated = re.sub(r"```(?:json)?\s*", "", truncated)
        truncated = truncated.replace("```", "")

        # Find JSON array with non-greedy regex
        match = re.search(r"\[.*?\]", truncated, re.S)
        if not match:
            return []

        try:
            parsed = json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            return []

        if not isinstance(parsed, list):
            return []

        actions = []
        for i, item in enumerate(parsed[:_MAX_ACTIONS]):
            if not isinstance(item, dict):
                continue
            instruction = item.get("instruction", "")
            if not isinstance(instruction, str) or not instruction.strip():
                continue
            step = {
                "step": item.get("step", i + 1),
                "instruction": instruction[:_MAX_INSTRUCTION_LEN],
            }
            for opt_key in ("ui_control", "expected_state", "verification", "safety_note"):
                val = item.get(opt_key)
                if val is not None and isinstance(val, str):
                    step[opt_key] = val[:_MAX_INSTRUCTION_LEN]
            actions.append(step)

        return actions

    # ── Fallback ───────────────────────────────────────────────────────

    @staticmethod
    def _safe_fallback(ctx: SopLookupContext, alarm: str) -> ActionPlan:
        """Return a minimal safe action plan when nothing else works."""
        logger.warning(
            "SOP Engine: safe fallback for incident=%d alarm=%s",
            ctx.incident_id, alarm,
        )
        return ActionPlan(
            incident_id=ctx.incident_id,
            device=ctx.device_name or "unknown",
            alarm=alarm,
            cause=ctx.cause or "",
            actions=[{
                "step": 1,
                "instruction": "SOP not found. Escalate to shift engineer.",
            }],
            source="error",
            confidence=0.0,
        )
