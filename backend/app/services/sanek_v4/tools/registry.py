"""
САНЁК v4 — Tool Registry.

Provides decorator-based tool registration and Anthropic-format definitions.
Anti-loop protection via call hash deduplication.
Safety integration: rate limiting, validation, audit logging.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Callable

logger = logging.getLogger("sanek_v4.tools")


class ToolRegistry:
    """Registry for v4 agent tools with safety layer."""

    def __init__(self):
        self._tools: dict[str, dict] = {}  # name → {func, definition}
        self._call_hashes: set[str] = set()
        self._session_id: str = ""

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
    ) -> Callable:
        """Decorator to register a tool function."""
        def decorator(func: Callable) -> Callable:
            self._tools[name] = {
                "func": func,
                "definition": {
                    "name": name,
                    "description": description,
                    "input_schema": input_schema,
                },
            }
            logger.info("Registered tool: %s", name)
            return func
        return decorator

    def get_definitions(self) -> list[dict]:
        """Get all tool definitions in Anthropic API format."""
        return [t["definition"] for t in self._tools.values()]

    async def execute(self, name: str, args: dict) -> dict:
        """Execute a tool by name with safety checks."""
        from services.sanek_v4.safety import rate_limiter, audit_log, validator

        if name not in self._tools:
            available = ", ".join(sorted(self._tools.keys()))
            return {"error": f"Tool '{name}' not found. Available: {available}"}

        # 1. Rate limit check
        allowed, error = rate_limiter.check(name)
        if not allowed:
            return {"status": "rate_limited", "message": error}

        # 2. Anti-loop: detect duplicate calls
        call_hash = hashlib.md5(
            f"{name}:{json.dumps(args, sort_keys=True, default=str)}".encode()
        ).hexdigest()

        if call_hash in self._call_hashes:
            return {"error": f"Duplicate call detected for {name}({args}). Use different parameters."}
        self._call_hashes.add(call_hash)

        # 3. Input validation
        if "device_id" in args and name not in ("get_topology",):
            ok, err = validator.validate_device_id(args["device_id"])
            if not ok:
                return {"status": "validation_error", "message": err}

        if name == "send_modbus_command":
            ok, err = validator.validate_modbus_write(
                args.get("device_id", ""),
                args.get("register_address", 0),
                args.get("value", 0),
                args.get("function_code", ""),
            )
            if not ok:
                return {"status": "validation_error", "message": err}

        if name == "query_db":
            ok, err = validator.validate_sql(args.get("sql", ""))
            if not ok:
                return {"status": "validation_error", "message": err}

        # 4. Execute
        start = time.time()
        is_error = False
        try:
            result = await self._tools[name]["func"](**args)
            if isinstance(result, dict) and "error" in result:
                is_error = True
        except Exception as e:
            logger.exception("Tool %s error: %s", name, e)
            result = {"error": f"{type(e).__name__}: {str(e)}"}
            is_error = True

        elapsed_ms = int((time.time() - start) * 1000)

        # 5. Record rate limit
        rate_limiter.record(name)

        # 6. Audit log (fire-and-forget)
        try:
            asyncio.create_task(audit_log.log(
                session_id=self._session_id,
                tool_name=name,
                tool_input=args,
                tool_output=result,
                is_error=is_error,
                execution_time_ms=elapsed_ms,
            ))
        except Exception:
            pass  # audit must never break agent

        return result

    def reset_call_hashes(self):
        """Reset anti-loop tracker (call at start of each conversation turn)."""
        self._call_hashes.clear()

    def set_session_id(self, session_id: str):
        """Set current session ID for audit logging."""
        self._session_id = session_id

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
