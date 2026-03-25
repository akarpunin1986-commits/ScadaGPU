"""
САНЁК v4 — Agentic Architecture.

Entry point: chat_stream_v4() — SSE streaming endpoint wrapper.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import AsyncIterator

from sqlalchemy import select, desc, func

from models.base import async_session

logger = logging.getLogger("sanek_v4")


async def chat_stream_v4(
    body: dict,
    user_id: int | None = None,
    user_context: str | None = None,
    source: str | None = None,
) -> AsyncIterator[str]:
    """
    SSE streaming wrapper for v4 AgentLoop.

    Receives request body from /api/ai/chat/stream,
    loads history, runs agent loop, saves messages, streams events.

    Yields SSE-formatted strings: "data: {json}\n\n"
    """
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id") or str(uuid.uuid4())
    context = body.get("context")  # {site, site_name, view}
    # user_id from body (set by ai_parser) or from function parameter
    _user_id = body.get("user_id") or user_id
    _user_name = body.get("user_name")

    if not user_message:
        yield _sse({"type": "error", "message": "Пустое сообщение"})
        return

    # ── Load conversation history from DB ──
    history = await _load_history(session_id, limit=20)

    # ── Save user message to DB ──
    await _save_message(session_id, "user", user_message, user_id=_user_id, source=source or "scada")

    # ── Build site context ──
    site_context = None
    if context:
        site_context = {
            "site": context.get("site"),
            "site_name": context.get("site_name", ""),
            "view": context.get("view", ""),
        }

    # ── Run agent loop (GPT-5.4 primary, Claude fallback) ──
    from services.sanek_v4.tools import registry as _reg
    _reg.set_session_id(session_id)

    from services.sanek_v4.llm.factory import create_agent_loop
    agent = create_agent_loop()
    full_text = ""
    tools_used = []
    iterations = 0

    try:
        _ctx = dict(site_context or {})
        if user_context:
            _ctx["user_context"] = user_context
        if source:
            _ctx["source"] = source

        async for event in agent.run(
            user_message=user_message,
            conversation_history=history,
            site_context=_ctx,
        ):
            event_type = event.get("type")

            if event_type == "done":
                full_text = event.get("message", "")
                tools_used = event.get("tools_used", [])
                iterations = event.get("iterations", 0)

                # Add session_id to done event
                event["session_id"] = session_id

            yield _sse(event)

    except Exception as e:
        logger.exception("Agent loop error: %s", e)
        yield _sse({
            "type": "error",
            "message": f"❌ Ошибка агента: {type(e).__name__}: {str(e)[:200]}",
            "session_id": session_id,
        })
        return

    # ── Save assistant response to DB ──
    if full_text:
        tool_info = json.dumps(tools_used, ensure_ascii=False, default=str) if tools_used else None
        await _save_message(
            session_id, "assistant", full_text,
            tool_calls=tool_info,
            extra={"iterations": iterations, "version": "v4"},
            user_id=_user_id,
            source=source or "scada",
        )

        # ── Auto session summary (self-learning) ──
        try:
            from services.sanek_v4.learning.session_memory import save_session_summary
            await save_session_summary(
                session_id=session_id,
                user_message=user_message,
                assistant_response=full_text,
                tools_used=tools_used,
                iterations=iterations,
            )
        except Exception as e:
            logger.debug("Session memory save skipped: %s", e)


async def sanek_v4_complete(
    message: str,
    user_id: int | None = None,
    session_id: str | None = None,
    source: str = "bitrix_chat",
    user_context: str | None = None,
    excluded_tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    on_tool_start=None,
) -> tuple[str, list[dict]]:
    """Non-streaming Sanek v4 for Bitrix24 chat.

    Returns (response_text, files_generated).
    """
    session_id = session_id or str(uuid.uuid4())

    # ── Load conversation history from DB ──
    history = await _load_history(session_id, limit=20)

    # ── Save user message to DB ──
    await _save_message(session_id, "user", message, user_id=user_id, source=source or "bitrix_chat")

    # ── Configure tool registry ──
    from services.sanek_v4.tools import registry as _reg
    _reg.set_session_id(session_id)

    # ── Create agent loop (non-streaming for B24 bot — stable through VPN) ──
    from services.sanek_v4.llm.factory import create_agent_loop
    agent = create_agent_loop(stream=True)  # streaming stable after VPN route fix

    full_text = ""
    tools_used = []
    iterations = 0
    files_generated: list[dict] = []

    try:
        # Build site_context with user info for agent loop
        _site_ctx = None
        if user_context or source:
            _site_ctx = {"user_context": user_context or "", "source": source or "scada"}

        async for event in agent.run(
            user_message=message,
            conversation_history=history,
            site_context=_site_ctx,
        ):
            event_type = event.get("type")

            if event_type == "step":
                status = event.get("status")
                tool_name = event.get("tool")
                if status == "running" and on_tool_start and tool_name:
                    try:
                        await on_tool_start(tool_name)
                    except TypeError:
                        try:
                            await on_tool_start(tool_name, event.get("input", {}))
                        except Exception:
                            pass
                    except Exception:
                        pass
                # Extract files from run_python_code results
                if status == "done" and tool_name == "run_python_code":
                    result = event.get("result", {})
                    if isinstance(result, dict):
                        url = result.get("download_url")
                        if url:
                            files_generated.append({
                                "download_url": url,
                                "filename": url.rsplit("/", 1)[-1] if "/" in url else url,
                                "size_kb": result.get("size_kb"),
                            })

            elif event_type == "text_delta":
                full_text += event.get("text", event.get("delta", ""))

            elif event_type == "done":
                full_text = event.get("message", full_text)
                tools_used = event.get("tools_used", [])
                iterations = event.get("iterations", 0)

    except Exception as e:
        logger.exception("sanek_v4_complete error: %s", e)
        return f"❌ Ошибка агента: {type(e).__name__}: {str(e)[:200]}", []

    # ── Save assistant response to DB ──
    if full_text:
        tool_info = json.dumps(tools_used, ensure_ascii=False, default=str) if tools_used else None
        await _save_message(
            session_id, "assistant", full_text,
            tool_calls=tool_info,
            extra={"iterations": iterations, "version": "v4", "source": source},
            user_id=user_id,
            source=source or "bitrix_chat",
        )

        # ── Auto session summary ──
        try:
            from services.sanek_v4.learning.session_memory import save_session_summary
            await save_session_summary(
                session_id=session_id,
                user_message=message,
                assistant_response=full_text,
                tools_used=tools_used,
                iterations=iterations,
            )
        except Exception as e:
            logger.debug("Session memory save skipped: %s", e)

    # Fallback: extract files from response text or check reports dir
    if not files_generated:
        import re, os
        # Pattern: /reports/filename.ext in text
        for m in re.finditer(r"/reports/(\S+\.(?:xlsx|pdf|csv|png))", full_text, re.IGNORECASE):
            fname = m.group(1)
            fpath = f"/opt/scada/reports/{fname}" if os.path.exists("/opt/scada/reports") else f"/app/reports/{fname}"
            if os.path.exists(fpath):
                files_generated.append({"filename": fname, "download_url": f"/reports/{fname}"})
        # Also check recently created files in reports dir (last 120 sec)
        if not files_generated:
            import time as _time
            rdir = "/opt/scada/reports" if os.path.exists("/opt/scada/reports") else "/app/reports"
            if os.path.exists(rdir):
                now = _time.time()
                for fn in os.listdir(rdir):
                    fp = os.path.join(rdir, fn)
                    if os.path.isfile(fp) and fn.endswith(('.xlsx','.pdf','.csv','.png')) and (now - os.path.getmtime(fp)) < 120:
                        files_generated.append({"filename": fn, "download_url": f"/reports/{fn}"})

    return full_text, files_generated


def _sse(data: dict) -> str:
    """Format dict as SSE event string."""
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _load_history(session_id: str, limit: int = 20) -> list[dict]:
    """Load conversation history from ai_chat_messages table."""
    try:
        from models.ai_chat import AiChatMessage
    except ImportError:
        logger.warning("AiChatMessage model not available, no history")
        return []

    try:
        async with async_session() as db:
            query = (
                select(AiChatMessage)
                .where(AiChatMessage.session_id == session_id)
                .order_by(desc(AiChatMessage.created_at))
                .limit(limit)
            )
            rows = (await db.execute(query)).scalars().all()

        # Reverse to chronological order
        rows = list(reversed(rows))

        # Filter out auth codes and system messages from context
        AUTH_CODE_MARKER = "[auth-code]"
        messages = []
        for row in rows:
            content = row.content or ""
            if AUTH_CODE_MARKER in content:
                continue
            if "Контекст сброшен" in content:
                continue
            messages.append({
                "role": row.role,
                "content": content,
            })
        return messages
    except Exception as e:
        logger.warning("Failed to load history: %s", e)
        return []


async def _save_message(
    session_id: str,
    role: str,
    content: str,
    tool_calls: str | None = None,
    extra: dict | None = None,
    user_id: int | None = None,
    source: str | None = None,
) -> None:
    """Save a message to ai_chat_messages table."""
    try:
        from models.ai_chat import AiChatMessage
    except ImportError:
        return

    try:
        async with async_session() as db:
            msg = AiChatMessage(
                session_id=session_id,
                role=role,
                content=content,
                tool_calls=tool_calls,
                user_id=user_id,
                source=source or "scada",
            )
            db.add(msg)
            await db.commit()
    except Exception as e:
        logger.warning("Failed to save message: %s", e)
