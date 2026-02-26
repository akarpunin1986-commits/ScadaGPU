"""Alarm Analytics API — REST endpoints for alarm events with analysis.

GET  /api/alarm-analytics/events          — list with filters
GET  /api/alarm-analytics/events/{id}     — single event with snapshot + analysis
GET  /api/alarm-analytics/active          — only active alarms
GET  /api/alarm-analytics/definitions     — alarm code lookup (for frontend fallback)
POST /api/alarm-analytics/explain         — LLM-powered alarm explanation (Sanek)
"""
from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_session
from alarm_analytics.models import AlarmAnalyticsEvent
from alarm_analytics.alarm_definitions import (
    ALARM_MAP_HGM9560, ALARM_MAP_HGM9520N, get_description_ru,
)

router = APIRouter(prefix="/api/alarm-analytics", tags=["alarm-analytics"])
logger = logging.getLogger("scada.alarm_analytics.router")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AlarmAnalyticsEventOut(BaseModel):
    id: int
    device_id: int
    device_type: str
    alarm_code: str
    alarm_name: str
    alarm_name_ru: str
    alarm_severity: str
    alarm_register: int
    alarm_bit: int
    occurred_at: datetime
    cleared_at: Optional[datetime] = None
    is_active: bool
    metrics_snapshot: Optional[dict] = None
    analysis_result: Optional[dict] = None

    model_config = {"from_attributes": True}


class AlarmAnalyticsEventBrief(BaseModel):
    id: int
    device_id: int
    device_type: str
    alarm_code: str
    alarm_name: str
    alarm_name_ru: str
    alarm_severity: str
    occurred_at: datetime
    cleared_at: Optional[datetime] = None
    is_active: bool

    model_config = {"from_attributes": True}


class AlarmDefinitionOut(BaseModel):
    code: str
    name: str
    name_ru: str
    severity: str
    register_field: str
    bit: int
    description_ru: str = ""


class AlarmExplainRequest(BaseModel):
    alarm_code: str
    device_id: int
    device_type: str = "generator"


class AlarmExplainResponse(BaseModel):
    success: bool
    explanation: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# ENDPOINTS
# ---------------------------------------------------------------------------

@router.get("/events", response_model=list[AlarmAnalyticsEventBrief])
async def list_events(
    device_id: Optional[int] = Query(None),
    device_ids: Optional[str] = Query(None, description="Comma-separated device IDs"),
    alarm_code: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    severity: Optional[str] = Query(None),
    last_hours: Optional[float] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_session),
) -> list[AlarmAnalyticsEventBrief]:
    """List alarm analytics events with filters and pagination."""
    stmt = select(AlarmAnalyticsEvent)
    conditions = []

    if device_ids is not None:
        ids = [int(x.strip()) for x in device_ids.split(",") if x.strip().isdigit()]
        if ids:
            conditions.append(AlarmAnalyticsEvent.device_id.in_(ids))
    elif device_id is not None:
        conditions.append(AlarmAnalyticsEvent.device_id == device_id)
    if alarm_code is not None:
        conditions.append(AlarmAnalyticsEvent.alarm_code == alarm_code)
    if is_active is not None:
        conditions.append(AlarmAnalyticsEvent.is_active == is_active)
    if severity is not None:
        conditions.append(AlarmAnalyticsEvent.alarm_severity == severity)
    if last_hours is not None:
        cutoff = datetime.utcnow() - timedelta(hours=last_hours)
        conditions.append(AlarmAnalyticsEvent.occurred_at >= cutoff)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(desc(AlarmAnalyticsEvent.occurred_at)).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/events/{event_id}", response_model=AlarmAnalyticsEventOut)
async def get_event(
    event_id: int,
    session: AsyncSession = Depends(get_session),
) -> AlarmAnalyticsEventOut:
    """Get single alarm analytics event with full snapshot and analysis."""
    stmt = select(AlarmAnalyticsEvent).where(AlarmAnalyticsEvent.id == event_id)
    result = await session.execute(stmt)
    event = result.scalar_one_or_none()
    if not event:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/active", response_model=list[AlarmAnalyticsEventBrief])
async def get_active(
    device_id: Optional[int] = Query(None),
    device_ids: Optional[str] = Query(None, description="Comma-separated device IDs"),
    session: AsyncSession = Depends(get_session),
) -> list[AlarmAnalyticsEventBrief]:
    """Return only currently active alarm analytics events."""
    stmt = select(AlarmAnalyticsEvent).where(
        AlarmAnalyticsEvent.is_active == True  # noqa: E712
    )
    if device_ids is not None:
        ids = [int(x.strip()) for x in device_ids.split(",") if x.strip().isdigit()]
        if ids:
            stmt = stmt.where(AlarmAnalyticsEvent.device_id.in_(ids))
    elif device_id is not None:
        stmt = stmt.where(AlarmAnalyticsEvent.device_id == device_id)
    stmt = stmt.order_by(desc(AlarmAnalyticsEvent.occurred_at))
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/definitions", response_model=list[AlarmDefinitionOut])
async def get_definitions(
    device_type: Optional[str] = Query(None, description="ats or generator"),
) -> list[AlarmDefinitionOut]:
    """Return alarm definitions for frontend lookup (no DB needed)."""
    result = []

    maps_to_query = []
    if device_type is None or device_type == "ats":
        maps_to_query.append(ALARM_MAP_HGM9560)
    if device_type is None or device_type == "generator":
        maps_to_query.append(ALARM_MAP_HGM9520N)

    for alarm_map in maps_to_query:
        for (field, bit), defn in alarm_map.items():
            result.append(AlarmDefinitionOut(
                code=defn["code"],
                name=defn["name"],
                name_ru=defn["name_ru"],
                severity=defn["severity"],
                register_field=field,
                bit=bit,
                description_ru=get_description_ru(defn),
            ))

    return result


# ---------------------------------------------------------------------------
# POST /explain — LLM-powered alarm explanation (Sanek)
# ---------------------------------------------------------------------------

def _find_alarm_def(alarm_code: str) -> dict | None:
    """Find alarm definition by code across both alarm maps."""
    for alarm_map in (ALARM_MAP_HGM9560, ALARM_MAP_HGM9520N):
        for (_field, _bit), defn in alarm_map.items():
            if defn["code"] == alarm_code:
                return {**defn, "register_field": _field, "bit": _bit}
    return None


# ---------------------------------------------------------------------------
# LRU cache for explain results (alarm_code -> (timestamp, response))
# ---------------------------------------------------------------------------
_EXPLAIN_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_CACHE_TTL = 600  # 10 minutes
_CACHE_MAX = 100  # max entries


def _cache_get(key: str) -> str | None:
    """Get cached explanation if exists and not expired."""
    if key in _EXPLAIN_CACHE:
        ts, text = _EXPLAIN_CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            _EXPLAIN_CACHE.move_to_end(key)
            return text
        else:
            del _EXPLAIN_CACHE[key]
    return None


def _cache_put(key: str, text: str) -> None:
    """Store explanation in cache."""
    _EXPLAIN_CACHE[key] = (time.time(), text)
    if len(_EXPLAIN_CACHE) > _CACHE_MAX:
        _EXPLAIN_CACHE.popitem(last=False)


async def _call_llm(provider: str, api_key: str, model: str, prompt: str) -> str:
    """Call active LLM provider with timing logs."""
    t0 = time.time()
    model_name = model or "(default)"
    logger.info("LLM call START: provider=%s model=%s prompt_len=%d", provider, model_name, len(prompt))

    try:
        if provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, timeout=30)
            resp = await client.chat.completions.create(
                model=model or "gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            result = resp.choices[0].message.content or ""

        elif provider == "claude":
            import httpx
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model or "claude-sonnet-4-20250514",
                        "max_tokens": 1024,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = data.get("content", [{}])[0].get("text", "")
                else:
                    err = resp.json().get("error", {}).get("message", resp.text)
                    raise RuntimeError(f"Claude API: {err}")

        elif provider == "gemini":
            import httpx
            mdl = model or "gemini-2.5-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={api_key}"
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 1024},
                })
                if resp.status_code == 200:
                    data = resp.json()
                    result = (data.get("candidates", [{}])[0]
                              .get("content", {}).get("parts", [{}])[0].get("text", ""))
                else:
                    err = resp.json().get("error", {}).get("message", resp.text)
                    raise RuntimeError(f"Gemini API: {err}")

        elif provider == "grok":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1", timeout=30)
            resp = await client.chat.completions.create(
                model=model or "grok-3-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            result = resp.choices[0].message.content or ""

        else:
            raise RuntimeError(f"Unknown provider: {provider}")

        elapsed = time.time() - t0
        logger.info("LLM call OK: provider=%s model=%s elapsed=%.1fs response_len=%d",
                     provider, model_name, elapsed, len(result))
        return result

    except Exception as e:
        elapsed = time.time() - t0
        logger.error("LLM call FAILED: provider=%s model=%s elapsed=%.1fs error=%s",
                      provider, model_name, elapsed, e)
        raise


@router.post("/explain", response_model=AlarmExplainResponse)
async def explain_alarm(
    req: AlarmExplainRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Use active LLM provider to explain an alarm in detail (Russian)."""
    t_total = time.time()
    logger.info("EXPLAIN START: code=%s device_id=%s device_type=%s",
                req.alarm_code, req.device_id, req.device_type)

    from api.ai_parser import _get_active_provider, _get_api_key, _get_model

    # 0. Check cache first
    cache_key = f"{req.alarm_code}:{req.device_id}:{req.device_type}"
    cached = _cache_get(cache_key)
    if cached:
        logger.info("EXPLAIN CACHE HIT: code=%s elapsed=%.3fs", req.alarm_code, time.time() - t_total)
        return AlarmExplainResponse(success=True, explanation=cached)

    # 1. Resolve LLM provider
    provider = _get_active_provider()
    api_key = _get_api_key(provider)
    model = _get_model(provider)
    logger.info("EXPLAIN provider=%s model=%s", provider, model or "(default)")

    if not api_key:
        return AlarmExplainResponse(
            success=False,
            error=f"API ключ для {provider} не настроен. Откройте настройки AI провайдера.",
        )

    # 2. Find alarm definition + description_ru
    alarm_def = _find_alarm_def(req.alarm_code)
    alarm_name_ru = alarm_def["name_ru"] if alarm_def else req.alarm_code
    alarm_severity = alarm_def["severity"] if alarm_def else "unknown"
    alarm_name_en = alarm_def["name"] if alarm_def else ""
    description_ru = get_description_ru(alarm_def) if alarm_def else ""

    # 3. Get current device metrics from Redis
    t_redis = time.time()
    metrics_snippet = "{}"
    try:
        redis = request.app.state.redis
        raw = await redis.get(f"device:{req.device_id}:metrics")
        if raw:
            mx = json.loads(raw)
            # Pick relevant fields for context (not all 200+ fields)
            relevant_keys = [
                "online", "engine_state", "gen_state",
                "rpm", "oil_pressure", "coolant_temp", "battery_voltage",
                "gen_voltage_ab", "gen_voltage_bc", "gen_voltage_ca",
                "gen_current_a", "gen_current_b", "gen_current_c",
                "gen_freq", "power_total", "power_factor",
                "mains_voltage_ab", "mains_voltage_bc", "mains_voltage_ca",
                "mains_freq", "busbar_voltage_ab", "busbar_freq",
                "fuel_level", "run_hours",
            ]
            metrics_snippet = json.dumps(
                {k: mx[k] for k in relevant_keys if k in mx},
                ensure_ascii=False,
            )
    except Exception as e:
        logger.warning("Could not fetch metrics for device %s: %s", req.device_id, e)
    logger.info("EXPLAIN redis fetch: %.3fs", time.time() - t_redis)

    # 4. Search knowledge base for relevant manual context
    t_kb = time.time()
    knowledge_context = ""
    try:
        from services.knowledge_base import search_knowledge
        search_query = f"{alarm_name_en} {alarm_name_ru}"
        kb_results = await search_knowledge(session, search_query, limit=3)
        if kb_results:
            snippets = []
            for r in kb_results:
                snippets.append(f"[{r['source_filename']}] {r['content'][:500]}")
            knowledge_context = "\n---\n".join(snippets)
    except Exception as e:
        logger.warning("Knowledge base search error: %s", e)
    logger.info("EXPLAIN KB search: %.3fs (found %d chars)", time.time() - t_kb, len(knowledge_context))

    # 5. Build prompt
    controller = "HGM9560 (ШПР/ATS)" if req.device_type == "ats" else "HGM9520N (генератор)"

    desc_block = ""
    if description_ru:
        desc_block = f"\nОписание аварии из документации:\n{description_ru}\n"

    kb_block = ""
    if knowledge_context:
        kb_block = f"\nКонтекст из мануала SmartGen:\n{knowledge_context}\n"

    prompt = (
        f"Ты — инженер-диагност SCADA-системы газопоршневых электростанций. "
        f"Контроллер: SmartGen {controller}.\n\n"
        f"Сработала авария:\n"
        f"- Код: {req.alarm_code}\n"
        f"- Название (EN): {alarm_name_en}\n"
        f"- Название (RU): {alarm_name_ru}\n"
        f"- Уровень: {alarm_severity}\n"
        f"{desc_block}\n"
        f"Текущие показания устройства (JSON):\n{metrics_snippet}\n"
        f"{kb_block}\n"
        f"Дай подробный анализ на русском языке:\n"
        f"1. Что означает эта авария (простым языком для оператора)\n"
        f"2. Возможные причины срабатывания\n"
        f"3. Что проверить в первую очередь\n"
        f"4. Рекомендации по устранению\n"
        f"5. Опасность: насколько критична ситуация\n\n"
        f"Отвечай кратко и структурированно, максимум 300 слов."
    )

    # 6. Call LLM
    try:
        explanation = await _call_llm(provider, api_key, model, prompt)
        result_text = explanation.strip()
        # Cache successful result
        _cache_put(cache_key, result_text)
        elapsed_total = time.time() - t_total
        logger.info("EXPLAIN DONE: code=%s total=%.1fs provider=%s", req.alarm_code, elapsed_total, provider)
        return AlarmExplainResponse(success=True, explanation=result_text)
    except Exception as e:
        elapsed_total = time.time() - t_total
        logger.error("EXPLAIN FAILED: code=%s total=%.1fs provider=%s error=%s",
                      req.alarm_code, elapsed_total, provider, e)
        from services.sanek import _format_llm_error
        friendly_err = _format_llm_error(provider, e)
        return AlarmExplainResponse(success=False, error=friendly_err)
