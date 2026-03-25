"""
САНЁК v4 — Agent Loop with Token Rate Limiter.

Tracks input token usage per minute and auto-waits before hitting 30K limit.
Uses Anthropic streaming API + smart tool selection.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from anthropic import AsyncAnthropic, APIError, APITimeoutError, RateLimitError

from config import settings
from services.sanek_v4.prompt import build_system_prompt
from services.sanek_v4.tools import execute_tool, get_tool_definitions, registry

logger = logging.getLogger("sanek_v4.loop")

_RETRY_WAITS = [5, 10, 20, 30, 45]
_MAX_RETRIES = 5

# ══════════════════════════════════════════════════════════
# Token Rate Limiter — prevents 429 by pre-checking budget
# ══════════════════════════════════════════════════════════
_TOKEN_LIMIT_PER_MIN = 30_000  # org limit from Anthropic
_token_log: list[tuple[float, int]] = []  # [(timestamp, tokens_used), ...]


def _tokens_used_last_minute() -> int:
    """Count input tokens used in the last 60 seconds."""
    cutoff = time.time() - 60
    total = 0
    for ts, tok in _token_log:
        if ts >= cutoff:
            total += tok
    return total


def _record_tokens(tokens: int):
    """Record token usage and cleanup old entries."""
    now = time.time()
    _token_log.append((now, tokens))
    # Cleanup entries older than 2 minutes
    cutoff = now - 120
    while _token_log and _token_log[0][0] < cutoff:
        _token_log.pop(0)


async def _wait_for_budget(estimated_tokens: int, event_callback=None):
    """Wait until we have enough token budget. Returns wait time in seconds."""
    total_waited = 0
    while True:
        used = _tokens_used_last_minute()
        available = _TOKEN_LIMIT_PER_MIN - used
        if available >= estimated_tokens:
            return total_waited

        # Need to wait — find when oldest entry expires
        if _token_log:
            oldest_ts = _token_log[0][0]
            wait = max(1, int(oldest_ts + 61 - time.time()))
        else:
            wait = 5

        wait = min(wait, 30)  # cap at 30s per wait

        if event_callback:
            await event_callback({
                "type": "thinking", "step": "forming_answer",
                "detail": f"⏳ Жду бюджет токенов ({used}/{_TOKEN_LIMIT_PER_MIN} за мин, нужно ~{estimated_tokens})... {wait}с",
            })

        logger.info("Token budget wait: used=%d, need=%d, wait=%ds", used, estimated_tokens, wait)
        await asyncio.sleep(wait)
        total_waited += wait

        if total_waited > 90:  # max 90s total wait
            logger.warning("Token budget wait exceeded 90s, proceeding anyway")
            return total_waited


# ── Singleton Anthropic client (persistent TCP/TLS through VPN) ──
_anthropic_client: AsyncAnthropic | None = None


def _get_anthropic_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(
            api_key=settings.CLAUDE_API_KEY,
            timeout=settings.AI_TIMEOUT,
            max_retries=0,
        )
    return _anthropic_client


class AgentLoop:
    def __init__(self, model=None, max_iterations=25, max_tokens=4096):
        self.model = model or settings.CLAUDE_MODEL
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.client = _get_anthropic_client()

    async def run(self, user_message, conversation_history=None, site_context=None) -> AsyncIterator[dict]:
        # Load memories for cross-session context
        try:
            from services.sanek_v4.prompt import _get_memories
            memories = await _get_memories()
        except Exception:
            memories = []
        # Extract user_context and source from site_context dict if present
        _uc = None
        _src = None
        _sc = site_context
        if isinstance(site_context, dict) and "user_context" in site_context:
            _uc = site_context.get("user_context")
            _src = site_context.get("source")
            _sc = None
        system = build_system_prompt(_sc, memories=memories, user_context=_uc, source=_src)
        all_tools = get_tool_definitions()
        from services.sanek_v4.tool_selector import select_tools
        tools = select_tools(all_tools, user_message)
        logger.info("Tools %d/%d for: %s", len(tools), len(all_tools), user_message[:60])

        registry.reset_call_hashes()

        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": user_message})
        messages = self._trim_context(messages, system, tools)

        tools_used = []
        total_in = 0
        total_out = 0
        _event_queue = []  # for streaming events from nested contexts

        # Helper to collect events that can't be yielded from nested contexts
        async def _emit(ev):
            _event_queue.append(ev)

        yield {"type": "mode", "mode": "deep"}
        yield {"type": "thinking", "step": "analyzing_query", "detail": user_message[:80]}

        for iteration in range(self.max_iterations):
            # ── Pre-flight: check token budget ──
            estimated = self._estimate_tokens(messages, system, tools)
            waited = await _wait_for_budget(estimated, _emit)
            # Flush queued events
            for ev in _event_queue:
                yield ev
            _event_queue.clear()

            if waited > 0:
                logger.info("Waited %ds for token budget before iteration %d", waited, iteration + 1)

            # ── Stream LLM response ──
            collected_content = []
            stop_reason = None
            last_error = None
            text_buffer = ""
            usage_in = usage_out = 0

            for attempt in range(_MAX_RETRIES):
                try:
                    collected_content = []
                    text_buffer = ""
                    stop_reason = None

                    async with self.client.messages.stream(
                        model=self.model,
                        max_tokens=self.max_tokens,
                        system=system,
                        messages=messages,
                        tools=tools,
                    ) as stream:
                        async for event in stream:
                            if event.type == "content_block_delta":
                                delta = event.delta
                                if hasattr(delta, "text") and delta.text:
                                    text_buffer += delta.text

                        response = await stream.get_final_message()
                        collected_content = response.content
                        stop_reason = response.stop_reason
                        if hasattr(response, "usage"):
                            usage_in = getattr(response.usage, "input_tokens", 0)
                            usage_out = getattr(response.usage, "output_tokens", 0)

                    # Record actual token usage
                    _record_tokens(usage_in)
                    break

                except RateLimitError as e:
                    last_error = e
                    # Parse retry-after header if available
                    retry_after = None
                    err_str = str(e)
                    if hasattr(e, 'response') and e.response:
                        retry_after = e.response.headers.get('retry-after')
                    wait = int(retry_after) if retry_after else _RETRY_WAITS[min(attempt, len(_RETRY_WAITS)-1)]
                    wait = min(wait, 60)

                    logger.warning("Rate limit (attempt %d/%d), retry-after=%s, wait=%ds: %s",
                        attempt + 1, _MAX_RETRIES, retry_after, wait, err_str[:150])

                    # Record estimated tokens to prevent immediate retry overload
                    _record_tokens(estimated)

                    if attempt < _MAX_RETRIES - 1:
                        yield {"type": "thinking", "step": "forming_answer",
                               "detail": f"⏳ Лимит API, жду {wait}с ({attempt+1}/{_MAX_RETRIES})..."}
                        await asyncio.sleep(wait)
                        continue
                    break

                except (APIError, APITimeoutError) as e:
                    last_error = e
                    err_str = str(e).lower()
                    etype = type(e).__name__.lower()
                    is_retryable = "overloaded" in err_str or "529" in err_str or "timeout" in etype
                    logger.warning("Claude API error (%d/%d): %s: %s",
                        attempt + 1, _MAX_RETRIES, type(e).__name__, str(e)[:200])
                    if is_retryable and attempt < _MAX_RETRIES - 1:
                        wait = _RETRY_WAITS[attempt]
                        yield {"type": "thinking", "step": "forming_answer",
                               "detail": f"API ошибка, повтор {wait}с ({attempt+1}/{_MAX_RETRIES})..."}
                        await asyncio.sleep(wait)
                        continue
                    break

                except Exception as e:
                    last_error = e
                    logger.exception("LLM error: %s", e)
                    break

            if not collected_content and not stop_reason:
                yield {"type": "error",
                       "message": f"⏱ Claude не ответил: {type(last_error).__name__}: {str(last_error)[:200]}"}
                return

            total_in += usage_in
            total_out += usage_out
            messages.append({"role": "assistant", "content": collected_content})

            # ── end_turn ──
            if stop_reason == "end_turn":
                full_text = self._extract_text(collected_content)
                if full_text:
                    chunk_size = 200
                    for i in range(0, len(full_text), chunk_size):
                        yield {"type": "text_delta", "text": full_text[i:i+chunk_size]}
                        await asyncio.sleep(0.02)
                yield {"type": "done", "message": full_text,
                       "tools_used": tools_used, "iterations": iteration + 1,
                       "tokens": {"input": total_in, "output": total_out}}
                return

            # ── tool_use ──
            if stop_reason == "tool_use":
                tool_results = []
                for block in collected_content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input
                    tool_use_id = block.id

                    yield {"type": "step", "tool": tool_name, "status": "running",
                           "description": _tool_description(tool_name, tool_input),
                           "iteration": iteration + 1}

                    if tool_name not in {t["name"] for t in tools}:
                        tools = all_tools

                    try:
                        result = await asyncio.wait_for(
                            execute_tool(tool_name, tool_input), timeout=120.0)
                        is_error = "error" in result if isinstance(result, dict) else False
                    except asyncio.TimeoutError:
                        result = {"error": f"Timeout {tool_name} (120s)"}
                        is_error = True
                    except Exception as e:
                        result = {"error": f"{type(e).__name__}: {str(e)}"}
                        is_error = True

                    tools_used.append({"tool": tool_name, "input": tool_input,
                                       "error": is_error, "iteration": iteration + 1})
                    yield {"type": "step", "tool": tool_name, "status": "done"}

                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    if len(result_str) > 15000:
                        result_str = result_str[:14000] + "\n...[truncated]"

                    tool_results.append({"type": "tool_result", "tool_use_id": tool_use_id,
                                         "content": result_str, "is_error": is_error})

                messages.append({"role": "user", "content": tool_results})
                messages = self._trim_context(messages, system, tools)
                continue

            # Unexpected
            text = self._extract_text(collected_content)
            if text:
                yield {"type": "done", "message": text, "tools_used": tools_used, "iterations": iteration + 1}
            else:
                yield {"type": "error", "message": f"Unexpected stop_reason={stop_reason}"}
            return

        yield {"type": "error", "message": f"⚠ Лимит итераций ({self.max_iterations})."}

    def _extract_text(self, content):
        parts = []
        if isinstance(content, list):
            for block in content:
                if hasattr(block, "text"):
                    parts.append(block.text)
        elif isinstance(content, str):
            return content
        return "\n".join(parts)

    def _trim_context(self, messages, system, tools):
        estimated = self._estimate_tokens(messages, system, tools)
        if estimated <= 180000:
            return messages
        if len(messages) <= 8:
            return messages
        trimmed = [messages[0]]
        for m in messages[1:-6]:
            content = m.get("content")
            if isinstance(content, list):
                new_blocks = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        c = block.get("content", "")
                        if isinstance(c, str) and len(c) > 2000:
                            new_blocks.append({**block, "content": c[:1500] + "\n...[trimmed]"})
                        else:
                            new_blocks.append(block)
                    else:
                        new_blocks.append(block)
                trimmed.append({**m, "content": new_blocks})
            elif isinstance(content, str) and len(content) > 3000:
                trimmed.append({**m, "content": content[:2000] + "\n...[trimmed]"})
            else:
                trimmed.append(m)
        trimmed.extend(messages[-6:])
        return trimmed

    def _estimate_tokens(self, messages, system, tools):
        total = len(system) // 4 + len(json.dumps(tools, default=str)) // 4
        for m in messages:
            c = m.get("content", "")
            if isinstance(c, str):
                total += len(c) // 4
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict):
                        total += len(json.dumps(b, default=str)) // 4
                    elif hasattr(b, "text"):
                        total += len(b.text) // 4
            total += 4
        return total


def _tool_description(tool_name, tool_input):
    d = tool_input.get("device_id", "")
    p = tool_input.get("period", "")
    q = tool_input.get("query", "")
    s = tool_input.get("site", "")
    return {
        "get_current_metrics": f"📡 Метрики {d}", "get_metrics_history": f"📈 История {d} {p}",
        "get_economics_report": f"💰 Экономика {s}", "get_alarms": f"⚠️ Аварии {d}" if d else "⚠️ Аварии",
        "get_topology": "🏭 Топология", "search_knowledge": f"📚 {q[:30]}" if q else "📚 База знаний",
        "get_alarm_reference": f"📋 Аларм {tool_input.get('alarm_code','')}",
        "get_bitrix_tasks": "📝 Задачи", "create_bitrix_task": "📝 Создаю задачу",
        "read_modbus_register": f"🔧 Регистр {tool_input.get('register_address','')}",
        "send_modbus_command": f"⚡ Команда {tool_input.get('action','')}",
        "run_python_code": "🐍 Python", "query_db": "🔍 SQL", "get_db_schema": "📊 Схема БД",
        "save_sop_entry": "💾 Сохраняю SOP",
    }.get(tool_name, tool_name)
