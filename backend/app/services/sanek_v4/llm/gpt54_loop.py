"""
САНЁК v4 — GPT-5.4 Native Agent Loop with TRUE STREAMING.

Key performance features:
- stream=True → text appears character-by-character (no waiting for full response)
- parallel_tool_calls=True → GPT calls 2-3 tools simultaneously
- 120s timeout (longer for streaming)
- Parallel tool execution via asyncio.gather
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

import openai

from config import settings
from services.sanek_v4.prompt import build_system_prompt
from services.sanek_v4.tools import execute_tool, get_tool_definitions, registry
from services.sanek_v4.llm.gpt54_tools import convert_tools_to_openai

logger = logging.getLogger("sanek_v4.gpt54")

_RETRY_WAITS = [3, 6, 12, 20, 30]
_MAX_RETRIES = 5

# ── OpenAI client factory (fresh connections for VPN reliability) ──

def _get_openai_client() -> openai.AsyncOpenAI:
    """Create OpenAI client. No connection pooling — each iteration gets fresh TCP."""
    return openai.AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=300.0,      # 5min total timeout (GPT-5.4 can think 60-90s)
        max_retries=0,
    )


class GPT54AgentLoop:
    def __init__(self, model=None, max_iterations=25, max_tokens=4096, stream=True):
        self.model = model or settings.OPENAI_MODEL or "gpt-5.4"
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.stream = stream
        self.client = _get_openai_client()

    async def run(self, user_message, conversation_history=None, site_context=None) -> AsyncIterator[dict]:
        # Build prompt + memories
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
            _sc = None  # Don't pass user_context dict as site_context
        system_prompt = build_system_prompt(_sc, memories=memories, user_context=_uc, source=_src)

        # Smart tool selection: core + relevant extras (max ~18)
        all_tools = get_tool_definitions()
        from services.sanek_v4.tool_selector import select_tools
        selected_tools = select_tools(all_tools, user_message)
        # GPT-5.4: ensure at least 15 tools for flexibility
        if len(selected_tools) < 15:
            extra_names = {t["name"] for t in selected_tools}
            for t in all_tools:
                if t["name"] not in extra_names:
                    selected_tools.append(t)
                if len(selected_tools) >= 18:
                    break
        tools_openai = convert_tools_to_openai(selected_tools)
        logger.info("GPT-5.4 tools %d/%d: %s", len(tools_openai), len(all_tools), user_message[:60])

        registry.reset_call_hashes()

        # Build OpenAI messages
        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            for m in conversation_history:
                if m.get("role") in ("user", "assistant"):
                    messages.append({"role": m["role"], "content": m.get("content", "")})
        messages.append({"role": "user", "content": user_message})

        tools_used = []
        total_in = total_out = 0

        yield {"type": "mode", "mode": "deep"}
        yield {"type": "thinking", "step": "analyzing_query", "detail": user_message[:80]}

        for iteration in range(self.max_iterations):
            start = time.time()

            # ── Stream GPT-5.4 response ──
            streamed_text = ""
            tool_calls_acc = {}  # id → {name, arguments}
            finish_reason = None
            last_error = None

            for attempt in range(_MAX_RETRIES):
                try:
                    streamed_text = ""
                    tool_calls_acc = {}
                    finish_reason = None

                    kwargs = {
                        "model": self.model,
                        "max_completion_tokens": self.max_tokens,
                        "messages": messages,
                        "temperature": 0.2,
                    }
                    if tools_openai:
                        kwargs["tools"] = tools_openai
                        kwargs["parallel_tool_calls"] = True

                    if not self.stream:
                        # Non-streaming mode (stable through VPN)
                        response = await self.client.chat.completions.create(**kwargs)
                        if response.choices:
                            choice = response.choices[0]
                            streamed_text = choice.message.content or ""
                            finish_reason = choice.finish_reason
                            if choice.message.tool_calls:
                                for tc in choice.message.tool_calls:
                                    tool_calls_acc[tc.index if hasattr(tc, 'index') else len(tool_calls_acc)] = {
                                        "id": tc.id,
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    }
                        if response.usage:
                            total_in += response.usage.prompt_tokens or 0
                            total_out += response.usage.completion_tokens or 0
                        if streamed_text:
                            yield {"type": "text_delta", "text": streamed_text}
                        break  # success

                    # Streaming mode
                    kwargs["stream"] = True
                    kwargs["stream_options"] = {"include_usage": True}

                    stream = await self.client.chat.completions.create(**kwargs)

                    async for chunk in stream:
                        if not chunk.choices:
                            # Usage chunk (last one)
                            if chunk.usage:
                                total_in += chunk.usage.prompt_tokens or 0
                                total_out += chunk.usage.completion_tokens or 0
                            continue

                        delta = chunk.choices[0].delta
                        fr = chunk.choices[0].finish_reason

                        # Text delta → stream immediately to frontend
                        if delta and delta.content:
                            streamed_text += delta.content
                            yield {"type": "text_delta", "text": delta.content}

                        # Tool call deltas → accumulate
                        if delta and delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index
                                if idx not in tool_calls_acc:
                                    tool_calls_acc[idx] = {
                                        "id": tc.id or "",
                                        "name": tc.function.name if tc.function and tc.function.name else "",
                                        "arguments": "",
                                    }
                                if tc.id:
                                    tool_calls_acc[idx]["id"] = tc.id
                                if tc.function:
                                    if tc.function.name:
                                        tool_calls_acc[idx]["name"] = tc.function.name
                                    if tc.function.arguments:
                                        tool_calls_acc[idx]["arguments"] += tc.function.arguments

                        if fr:
                            finish_reason = fr

                    break  # success

                except openai.RateLimitError as e:
                    last_error = e
                    wait = _RETRY_WAITS[min(attempt, len(_RETRY_WAITS) - 1)]
                    logger.warning("GPT rate limit (%d/%d), wait %ds", attempt + 1, _MAX_RETRIES, wait)
                    if attempt < _MAX_RETRIES - 1:
                        yield {"type": "thinking", "step": "forming_answer",
                               "detail": f"⏳ Лимит, жду {wait}с ({attempt+1}/{_MAX_RETRIES})..."}
                        await asyncio.sleep(wait)
                        continue
                    break

                except (openai.APIError, openai.APITimeoutError, openai.APIConnectionError) as e:
                    last_error = e
                    err_str = str(e).lower()
                    is_retryable = "timeout" in err_str or "server" in err_str or "overloaded" in err_str
                    logger.warning("GPT API error (%d/%d): %s: %s",
                                   attempt + 1, _MAX_RETRIES, type(e).__name__, str(e)[:200])
                    if is_retryable and attempt < _MAX_RETRIES - 1:
                        wait = _RETRY_WAITS[attempt]
                        yield {"type": "thinking", "step": "forming_answer",
                               "detail": f"Ошибка, повтор {wait}с..."}
                        await asyncio.sleep(wait)
                        continue
                    break

                except Exception as e:
                    last_error = e
                    logger.exception("GPT error: %s", e)
                    break

            if finish_reason is None and not streamed_text and not tool_calls_acc:
                yield {"type": "error",
                       "message": f"⏱ GPT-5.4: {type(last_error).__name__}: {str(last_error)[:200]}"}
                return

            latency = int((time.time() - start) * 1000)
            yield {"type": "provider_info", "provider": "gpt54",
                   "model": self.model, "latency_ms": latency, "iteration": iteration + 1}

            # ── CASE 1: stop → text response done ──
            if finish_reason == "stop":
                yield {"type": "done", "message": streamed_text,
                       "tools_used": tools_used, "iterations": iteration + 1,
                       "tokens": {"input": total_in, "output": total_out},
                       "provider": "gpt54"}
                return

            # ── CASE 2: tool_calls → execute tools ──
            if finish_reason == "tool_calls" and tool_calls_acc:
                # Build assistant message for history
                tc_list = []
                for idx in sorted(tool_calls_acc.keys()):
                    tc = tool_calls_acc[idx]
                    tc_list.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    })

                assistant_msg = {"role": "assistant", "content": streamed_text or None, "tool_calls": tc_list}
                messages.append(assistant_msg)

                # Preamble (GPT can include text before tool calls)
                if streamed_text:
                    yield {"type": "preamble", "text": streamed_text}

                # Execute ALL tools in PARALLEL
                async_tasks = []
                for tc in tc_list:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        args = {}

                    yield {"type": "step", "tool": name, "status": "running",
                           "description": _tool_desc(name, args), "iteration": iteration + 1}

                    # If tool not in selected set, unlock all
                    if name not in {t["function"]["name"] for t in tools_openai}:
                        tools_openai = convert_tools_to_openai(all_tools)

                    async_tasks.append((tc["id"], name, args,
                                        asyncio.create_task(execute_tool(name, args))))

                # Collect results
                for tc_id, name, args, task in async_tasks:
                    try:
                        result = await asyncio.wait_for(task, timeout=30.0)
                        is_error = "error" in result if isinstance(result, dict) else False
                    except asyncio.TimeoutError:
                        result = {"error": f"Timeout {name} (30s)"}
                        is_error = True
                    except Exception as e:
                        result = {"error": f"{type(e).__name__}: {str(e)}"}
                        is_error = True

                    tools_used.append({"tool": name, "input": args,
                                       "error": is_error, "iteration": iteration + 1})
                    yield {"type": "step", "tool": name, "status": "done"}

                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    if len(result_str) > 15000:
                        result_str = result_str[:14000] + "\n...[truncated]"

                    messages.append({"role": "tool", "tool_call_id": tc_id, "content": result_str})

                continue

            # ── CASE 3: length ──
            if finish_reason == "length":
                text = streamed_text + "\n[обрезано]"
                yield {"type": "done", "message": text,
                       "tools_used": tools_used, "iterations": iteration + 1, "provider": "gpt54"}
                return

            # ── Unexpected ──
            if streamed_text:
                yield {"type": "done", "message": streamed_text,
                       "tools_used": tools_used, "iterations": iteration + 1}
            else:
                yield {"type": "error", "message": f"Unexpected finish_reason={finish_reason}"}
            return

        yield {"type": "error", "message": f"⚠ Лимит итераций ({self.max_iterations})."}

    async def _execute_safe(self, name, args):
        return await execute_tool(name, args)


def _tool_desc(tool_name, tool_input):
    d = tool_input.get("device_id", "")
    p = tool_input.get("period", "")
    q = tool_input.get("query", "")
    s = tool_input.get("site", "")
    return {
        "get_current_metrics": f"📡 Метрики {d}",
        "get_metrics_history": f"📈 История {d} {p}",
        "get_economics_report": f"💰 Экономика {s}",
        "get_alarms": f"⚠️ Аварии {d}" if d else "⚠️ Аварии",
        "get_topology": "🏭 Топология",
        "search_knowledge": f"📚 {q[:30]}" if q else "📚 База знаний",
        "get_alarm_reference": f"📋 Аларм {tool_input.get('alarm_code', '')}",
        "get_bitrix_tasks": "📝 Задачи", "create_bitrix_task": "📝 Создаю задачу",
        "read_modbus_register": f"🔧 Регистр {tool_input.get('register_address', '')}",
        "send_modbus_command": f"⚡ Команда {tool_input.get('action', '')}",
        "run_python_code": "🐍 Python", "query_db": "🔍 SQL",
        "get_db_schema": "📊 Схема", "save_sop_entry": "💾 SOP",
    }.get(tool_name, tool_name)
