"""
САНЁК v4 — Safety layer.

Rate limiting, input validation, and audit logging for all tool calls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

logger = logging.getLogger("sanek_v4.safety")


class ToolRateLimiter:
    """
    Rate limiter for tool calls.

    Limits:
    - send_modbus_command: 5/min, 10/session
    - create_bitrix_task:  3/min, 20/session
    - query_db:           20/min, 100/session
    - run_python_code:     5/min, 20/session
    - * (default):        30/min, 200/session
    """

    LIMITS = {
        "send_modbus_command": {"per_minute": 5, "per_session": 10},
        "create_bitrix_task":  {"per_minute": 3, "per_session": 20},
        "query_db":            {"per_minute": 20, "per_session": 100},
        "run_python_code":     {"per_minute": 5, "per_session": 20},
        "create_scada_task":   {"per_minute": 3, "per_session": 10},
        "escalate_task":       {"per_minute": 2, "per_session": 5},
        "upload_maintenance_card": {"per_minute": 2, "per_session": 5},
        "*":                   {"per_minute": 30, "per_session": 200},
    }

    def __init__(self):
        self._calls: dict[str, list[float]] = defaultdict(list)
        self._session_counts: dict[str, int] = defaultdict(int)

    def check(self, tool_name: str) -> tuple[bool, str | None]:
        """Check if tool call is allowed. Returns (allowed, error_message)."""
        limits = self.LIMITS.get(tool_name, self.LIMITS["*"])
        now = time.time()

        # Per-minute check
        recent = [t for t in self._calls[tool_name] if now - t < 60]
        self._calls[tool_name] = recent
        if len(recent) >= limits["per_minute"]:
            return False, (
                f"Rate limit: {tool_name} — максимум {limits['per_minute']} "
                f"вызовов в минуту. Подождите."
            )

        # Per-session check
        if self._session_counts[tool_name] >= limits["per_session"]:
            return False, (
                f"Session limit: {tool_name} — максимум {limits['per_session']} "
                f"вызовов за сессию."
            )

        return True, None

    def record(self, tool_name: str):
        """Record a tool call."""
        self._calls[tool_name].append(time.time())
        self._session_counts[tool_name] += 1

    def reset(self):
        """Reset for new session."""
        self._calls.clear()
        self._session_counts.clear()


class ToolAuditLog:
    """
    Audit logging for all tool calls.
    Writes to sanek_audit_log table (fire-and-forget).
    """

    async def log(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict,
        tool_output: Any,
        is_error: bool,
        execution_time_ms: int,
        user_message: str = "",
    ):
        """Log tool call to database. Non-blocking."""
        try:
            from sqlalchemy import text
            from models.base import async_session

            output_summary = str(tool_output)[:500] if tool_output else ""
            input_json = json.dumps(tool_input, ensure_ascii=False, default=str)[:2000]

            async with async_session() as db:
                await db.execute(
                    text("""
                        INSERT INTO sanek_audit_log
                            (session_id, tool_name, tool_input, tool_output_summary,
                             is_error, execution_time_ms, user_message_preview)
                        VALUES (:sid, :tn, :ti::jsonb, :tos, :ie, :etm, :ump)
                    """),
                    {
                        "sid": session_id[:64],
                        "tn": tool_name[:64],
                        "ti": input_json,
                        "tos": output_summary,
                        "ie": is_error,
                        "etm": execution_time_ms,
                        "ump": user_message[:200] if user_message else None,
                    },
                )
                await db.commit()
        except Exception as e:
            # Audit logging should never break the agent
            logger.debug("Audit log failed (non-critical): %s", e)


class SafetyValidator:
    """Input validation for tool calls."""

    VALID_DEVICES = {
        "mkz_gen1", "mkz_gen2", "yakz_gen1", "yakz_gen2",
        "mkz_panel", "yakz_panel",
        "mkz_all", "yakz_all", "all",
    }

    @staticmethod
    def validate_device_id(device_id: str) -> tuple[bool, str | None]:
        """Validate device_id exists."""
        if device_id not in SafetyValidator.VALID_DEVICES:
            return False, (
                f"Unknown device_id: '{device_id}'. "
                f"Available: {', '.join(sorted(SafetyValidator.VALID_DEVICES))}"
            )
        return True, None

    @staticmethod
    def validate_modbus_write(
        device_id: str, register: int, value: int, fc: str
    ) -> tuple[bool, str | None]:
        """Additional validation for Modbus write commands."""
        # FC 05: value must be 0xFF00 or 0x0000
        if fc == "05" and value not in (0xFF00, 0x0000):
            return False, (
                f"Function 05H (Write Coil): value must be 0xFF00 (65280) or 0x0000 (0). "
                f"Got: {value} (0x{value:04X})"
            )
        # FC 06: value must be uint16
        if fc == "06" and not (0 <= value <= 65535):
            return False, f"Function 06H: value must be 0-65535. Got: {value}"
        # Register address range check
        if register < 0 or register > 10000:
            return False, f"Register address out of range: {register}"
        return True, None

    @staticmethod
    def validate_sql(sql: str) -> tuple[bool, str | None]:
        """Validate SQL query is read-only."""
        import re

        sql_upper = sql.upper().strip()
        if not sql_upper.startswith("SELECT"):
            return False, "Только SELECT запросы разрешены."

        FORBIDDEN = [
            (r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE)\b',
             "модифицирующие операции"),
            (r'\b(EXECUTE|EXEC|CALL|DO)\b', "выполнение процедур"),
            (r';\s*\w', "множественные запросы"),
            (r'\bpg_\w+\s*\(', "системные функции"),
            (r'\bCOPY\b', "COPY"),
        ]
        for pattern, desc in FORBIDDEN:
            if re.search(pattern, sql, re.IGNORECASE):
                return False, f"Запрещённая конструкция SQL: {desc}"
        return True, None


# Singleton instances
rate_limiter = ToolRateLimiter()
audit_log = ToolAuditLog()
validator = SafetyValidator()
