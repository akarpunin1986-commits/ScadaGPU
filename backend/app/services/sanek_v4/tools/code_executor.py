"""
САНЁК v4 — Code execution tools.

run_python_code — execute Python in Docker sandbox
query_db — execute read-only SQL SELECT queries
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime

import httpx
from sqlalchemy import text

from config import settings
from models.base import async_session
from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek_v4.tools.code_executor")

SANDBOX_URL = "http://sandbox:9999/execute"
SANDBOX_TIMEOUT = 30
MAX_SQL_ROWS = 100
SQL_TIMEOUT = 10


# ═══════════════════════════════════════════════════════════════
# TOOL: run_python_code
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="run_python_code",
    description=(
        "Выполнить Python код в изолированном Docker контейнере для сложных вычислений. "
        "Используй когда стандартные tools недостаточны: статистический анализ, "
        "корреляции, расчёт трендов, форматирование отчётов, генерация Excel/PDF.\n\n"
        "Доступные библиотеки: pandas, numpy, openpyxl, matplotlib, datetime, json, math.\n"
        "Код НЕ имеет доступа к сети — данные передавай через параметр 'context'.\n"
        "Для доступа к БД в коде доступна переменная DB_DSN.\n"
        "Timeout: 30 секунд. Лимит памяти: 256MB.\n\n"
        "Паттерн использования:\n"
        "1. Получи данные через tools (get_metrics_history, query_db)\n"
        "2. Передай в context\n"
        "3. Вычисли/сгенерируй файл в коде\n"
        "4. Результат — в переменной 'result' (dict или str)\n\n"
        "ФАЙЛЫ (Excel/PDF):\n"
        "Для файлов пиши в /output/ → скачивание по /reports/{filename}.\n"
        "Пример: df.to_excel('/output/report.xlsx'); result={'download_url':'/reports/report.xlsx'}\n\n"
        "ПРЯМОЙ ДОСТУП К БД:\n"
        "В sandbox доступна переменная DB_DSN (PostgreSQL). Используй psycopg2:\n"
        "import psycopg2; conn=psycopg2.connect(DB_DSN); df=pd.read_sql(sql, conn)\n"
        "ЭТО ЛУЧШЕ чем передавать данные через context (нет лимита размера).\n"
        "Таблицы: metrics_data(device_id,timestamp,power_total,mains_total_p,...), "
        "devices(id,site_id,name), sites, alarm_events, gas_prices, grid_prices, planned_costs.\n"
        "МКЗ: gen1=device_id 1, gen2=2, panel=3. ЯКЗ: gen1=4, gen2=5, panel=6."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python код. Переменная 'context' содержит данные. "
                    "Итоговый результат — в переменную 'result'. "
                    "Доступны: pandas, numpy, openpyxl, matplotlib, json, math, datetime."
                ),
            },
            "context": {
                "type": "object",
                "description": "Данные для передачи в скрипт. Доступны как переменная 'context'.",
            },
        },
        "required": ["code"],
    },
)
async def run_python_code(
    code: str,
    context: dict | None = None,
) -> dict:
    """Execute Python code in Docker sandbox."""
    # Pre-validation
    forbidden = _validate_code(code)
    if forbidden:
        return {
            "status": "error",
            "error_type": "ValidationError",
            "message": f"Запрещённая конструкция: {forbidden}. "
                       "Sandbox не имеет доступа к сети и файловой системе.",
        }

    # Send code directly to sandbox — sandbox_runner.py v2 handles:
    # - DB_DSN injection via context.db_dsn
    # - result variable extraction
    # - /output/ file scanning
    # - timeout (60s) and security
    from config import settings as _settings
    db_dsn = _settings.DATABASE_URL.replace("+asyncpg", "") if hasattr(_settings, 'DATABASE_URL') else "postgresql://scada:scada_dev_2026@postgres:5432/scada"
    sandbox_context = {"db_dsn": db_dsn}
    if context:
        sandbox_context.update(context)

    logger.info("run_python_code: code_len=%d, first_100=%s", len(code), code[:100].replace('\n',' '))

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=SANDBOX_TIMEOUT + 5) as client:
            resp = await client.post(
                SANDBOX_URL,
                json={"code": code, "context": sandbox_context},
            )

        elapsed_ms = int((time.time() - start) * 1000)
        data = resp.json()

        logger.info("Sandbox: error=%s files=%d rv=%s time=%dms",
                     str(data.get("error", ""))[:100] if data.get("error") else "none",
                     len(data.get("files", [])),
                     str(data.get("return_value", ""))[:100],
                     elapsed_ms)

        # Sandbox v2 response: {stdout, files, error, return_value}
        if data.get("error"):
            return {
                "status": "error",
                "error_type": "SandboxError",
                "message": data["error"][:500],
                "stdout": data.get("stdout", "")[:500] or None,
                "execution_time_ms": elapsed_ms,
            }

        # Success — build response
        files = []
        for f in (data.get("files") or []):
            files.append({
                "filename": f.get("name", ""),
                "download_url": f.get("path", "/reports/" + f.get("name", "")),
                "size_kb": f.get("size_kb", 0),
            })

        # Also check local reports dir (fallback)
        if not files:
            files = _check_output_files()

        resp_data = {
            "status": "success",
            "result": data.get("return_value") or ({"files": [f["filename"] for f in files]} if files else "OK"),
            "execution_time_ms": elapsed_ms,
        }
        if files:
            resp_data["files"] = files
        if data.get("stdout"):
            resp_data["stdout"] = data["stdout"][:500]
        return resp_data

    except httpx.TimeoutException:
        return {
            "status": "error",
            "error_type": "TimeoutError",
            "message": f"Код не завершился за {SANDBOX_TIMEOUT} секунд.",
        }
    except Exception as e:
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": str(e)[:300],
        }


def _check_output_files() -> list[dict]:
    """Check for newly created files in /opt/scada/reports/ (= sandbox /output/)."""
    import os
    reports_dir = "/opt/scada/reports" if os.path.exists("/opt/scada/reports") else "/app/reports"
    files = []
    try:
        if os.path.isdir(reports_dir):
            for f in os.listdir(reports_dir):
                path = os.path.join(reports_dir, f)
                if os.path.isfile(path):
                    size_kb = round(os.path.getsize(path) / 1024, 1)
                    # Only include recent files (last 60 seconds)
                    import time
                    if time.time() - os.path.getmtime(path) < 60:
                        files.append({
                            "filename": f,
                            "download_url": f"/reports/{f}",
                            "size_kb": size_kb,
                        })
    except Exception:
        pass
    return files


def _validate_code(code: str) -> str | None:
    """Validate code for forbidden constructs."""
    FORBIDDEN = [
        (r'\bimport\s+(os|subprocess|sys|socket|http|urllib|requests|shutil)\b',
         "import os/subprocess/sys/socket/http"),
        (r'\b__import__\b', "__import__()"),
        # open() for write allowed ONLY to /output/ (sandbox volume)
        (r'\bopen\s*\([^)]*["\']w[^)]*\)(?!.*\/output)', "open() write вне /output/"),
        (r'\bexec\s*\(', "exec()"),
        (r'\bcompile\s*\(', "compile()"),
        (r'/api/commands', "прямые Modbus вызовы"),
    ]
    for pattern, desc in FORBIDDEN:
        if re.search(pattern, code):
            return desc
    return None


# ═══════════════════════════════════════════════════════════════
# TOOL: query_db
# ═══════════════════════════════════════════════════════════════

FORBIDDEN_SQL_PATTERNS = [
    r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE)\b',
    r'\b(EXECUTE|EXEC|CALL|DO)\b',
    r';\s*\w',        # multiple statements
    r'\bpg_\w+\s*\(', # pg_ system functions
    r'\bCOPY\b',
]

@registry.tool(
    name="query_db",
    description=(
        "Выполнить произвольный SQL SELECT к PostgreSQL базе ScadaGPU. "
        "Используй когда стандартные tools (get_current_metrics, get_metrics_history) "
        "не подходят: сложные JOIN, нестандартные агрегации, поиск корреляций.\n\n"
        "ТОЛЬКО SELECT. INSERT/UPDATE/DELETE запрещены.\n"
        "Максимум 100 строк, timeout 10 секунд.\n\n"
        "Основные таблицы:\n"
        "- metrics_data: device_id, timestamp, power_total, coolant_temp, oil_pressure, "
        "gen_freq, fuel_consumption, load_pct, energy_kwh, mains_total_p, run_hours\n"
        "- devices: id, site_id, name, device_type, ip_address\n"
        "- sites: id, name, code (МКЗ=MKZ, ЯКЗ=YKZ)\n"
        "- alarm_events: device_id, alarm_code, severity, message, occurred_at, cleared_at, is_active\n"
        "- gas_prices: site_id, effective_from, price_per_m3\n"
        "- grid_prices: site_id, effective_from, price_per_kwh\n"
        "- planned_costs: site_id, year, month, category, amount\n"
        "- maintenance_logs: device_id, interval_id, performed_at, engine_hours"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "SQL SELECT запрос. Используй LIMIT. "
                    "Пример: SELECT device_id, AVG(power_total) as avg_power "
                    "FROM metrics_data WHERE timestamp > NOW() - INTERVAL '1 day' "
                    "GROUP BY device_id LIMIT 10"
                ),
            },
            "explain": {
                "type": "string",
                "description": "Краткое описание цели запроса (для аудита).",
            },
        },
        "required": ["sql", "explain"],
    },
)
async def query_db(sql: str, explain: str = "") -> dict:
    """Execute read-only SQL query."""
    # Validate SQL
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT"):
        return {"status": "error", "message": "Только SELECT запросы разрешены."}

    for pattern in FORBIDDEN_SQL_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE):
            return {"status": "error", "message": f"Запрещённая конструкция в SQL"}

    # Auto-add LIMIT
    if "LIMIT" not in sql_upper:
        sql = sql.rstrip(";") + f" LIMIT {MAX_SQL_ROWS}"

    # Execute with timeout
    start = time.time()
    try:
        async with async_session() as db:
            result = await asyncio.wait_for(
                db.execute(text(sql)),
                timeout=SQL_TIMEOUT,
            )
            rows_raw = result.fetchall()
            columns = list(result.keys()) if result.keys() else []

    except asyncio.TimeoutError:
        return {
            "status": "error",
            "message": f"Запрос не выполнился за {SQL_TIMEOUT} секунд. Добавь WHERE или уменьши период.",
        }
    except Exception as e:
        return {"status": "error", "message": f"SQL error: {type(e).__name__}: {str(e)[:200]}"}

    elapsed_ms = int((time.time() - start) * 1000)

    # Convert rows to serializable format
    rows = []
    for row in rows_raw[:MAX_SQL_ROWS]:
        rows.append([
            str(v) if isinstance(v, datetime) else
            round(float(v), 4) if isinstance(v, float) else
            v
            for v in row
        ])

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "execution_time_ms": elapsed_ms,
        "truncated": len(rows_raw) >= MAX_SQL_ROWS,
        "explain": explain,
    }
