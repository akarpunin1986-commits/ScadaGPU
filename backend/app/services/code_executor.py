"""
САНЁК v3 — CodeExecutor v2.
Pre-validation → Sandbox → Post-validation → Cross-check.
"""
from __future__ import annotations
import json, logging, re
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger("sanek.code_executor")

SANDBOX_URL = "http://sandbox:9999/execute"
SANDBOX_TIMEOUT = 65

# ═══════════ П4: ЗАПРЕЩЁННЫЕ ПАТТЕРНЫ В КОДЕ ═══════════

BLOCKED_PATTERNS = [
    # Прямые опасные вызовы
    (r'/api/commands', "Прямой Modbus запрещён. Используй propose_action tool."),
    (r'api/devices/.*/power-limit', "Управление мощностью — через propose_action."),
    (r'function_code\s*[:=]\s*[56]', "Modbus FC05/FC06 запрещён в sandbox."),
    # Системные
    (r'os\.system|subprocess|os\.popen', "Системные команды запрещены."),
    (r'__import__\s*\(', "Динамический импорт запрещён."),
    (r'eval\s*\(|exec\s*\(', "eval/exec запрещены."),
    # Запись в БД
    (r'INSERT\s+INTO|UPDATE\s+.*SET|DELETE\s+FROM|DROP\s+|ALTER\s+|CREATE\s+', "Запись в БД запрещена. Sandbox read-only."),
    (r'\.execute\s*\(\s*["\'](?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)', "Запись в БД запрещена."),
]

def _pre_validate(code: str) -> str | None:
    """Проверить код ДО отправки в sandbox. Возвращает ошибку или None."""
    for pattern, message in BLOCKED_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            return f"Код заблокирован: {message}"
    return None


# ═══════════ CONTEXT BUILDER ═══════════

def _build_context(extra_context: dict = None) -> dict:
    """Сформировать контекст для sandbox."""
    ctx = {
        "db_dsn": "postgresql://scada_readonly:readonly@postgres:5432/scada",
        "redis_url": "redis://redis:6379/0",
        "bitrix_webhook": "https://bricks-trade.bitrix24.ru/rest/102/a1452jp8xhqm1wu6",
        "bitrix_group_id": 46,
        "output_dir": "/output",
        "now_msk": (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
        "sites": {"МКЗ": 3, "ЯКЗ": 5},
        "devices": {
            "Двигатель 1 МКЗ": 1, "Двигатель 2 МКЗ": 2, "ШПР МКЗ": 3,
            "Двигатель 1 ЯКЗ": 4, "Двигатель 2 ЯКЗ": 5, "ШПР ЯКЗ": 6,
        },
    }
    if extra_context:
        ctx.update(extra_context)
    return ctx


# ═══════════ MAIN EXECUTE ═══════════

async def execute_code(code: str, extra_context: dict = None) -> dict:
    """
    Pre-validate → sandbox → post-process.
    Возвращает: {result, output, files[], error, blocked}
    """
    block_reason = _pre_validate(code)
    if block_reason:
        return {
            "error": block_reason,
            "blocked": True,
            "stdout": "",
            "files": [],
            "return_value": None,
        }

    context = _build_context(extra_context)

    try:
        async with httpx.AsyncClient(timeout=SANDBOX_TIMEOUT) as client:
            resp = await client.post(SANDBOX_URL, json={"code": code, "context": context})
            if resp.status_code != 200:
                return {"error": f"Sandbox HTTP {resp.status_code}", "stdout": "", "files": [], "return_value": None}
            raw = resp.json()
            logger.info("Sandbox response: error=%s, files=%d, return_value=%s",
                        raw.get("error", "none")[:100] if raw.get("error") else "none",
                        len(raw.get("files", [])),
                        str(raw.get("return_value", ""))[:100])
            if raw.get("error"):
                logger.warning("Sandbox code error: %s", raw["error"][:500])
    except httpx.TimeoutException:
        return {"error": "Sandbox timeout (65с). Код слишком долгий — упрости запрос.", "stdout": "", "files": [], "return_value": None}
    except httpx.ConnectError:
        return {"error": "Sandbox контейнер недоступен. docker compose up sandbox.", "stdout": "", "files": [], "return_value": None}
    except Exception as e:
        return {"error": f"CodeExecutor: {e}", "stdout": "", "files": [], "return_value": None}

    return raw


# ═══════════ П3: CROSS-CHECK ═══════════

async def cross_check_economics(sandbox_result: dict, site_id: int, last_days: int) -> dict | None:
    """
    Сравнить экономику из sandbox с данными get_economics_report.
    Возвращает предупреждение или None.
    """
    try:
        from services.sanek_v4.tools import execute_tool
        _site_names = {3: "mkz", 5: "yakz"}
        site_name = _site_names.get(site_id, "mkz")
        official = await execute_tool("get_economics_report", {"site": site_name, "last_days": last_days})
        if "error" in official:
            return None

        official_energy = official.get("totals", {}).get("energy_kwh", 0)
        sandbox_energy = None

        rv = sandbox_result.get("return_value") or {}
        if isinstance(rv, dict):
            for key in ("energy_kwh", "total_energy", "выработка", "summary"):
                if key in rv:
                    val = rv[key]
                    if isinstance(val, dict):
                        val = val.get("energy_kwh", val.get("total", 0))
                    if isinstance(val, (int, float)):
                        sandbox_energy = val
                        break

        if sandbox_energy is None or official_energy == 0:
            return None

        diff_pct = abs(sandbox_energy - official_energy) / official_energy * 100
        if diff_pct > 5:
            return {
                "warning": f"Расхождение данных: sandbox {sandbox_energy:.0f} кВт·ч vs БД {official_energy:.0f} кВт·ч ({diff_pct:.1f}%). Проверьте параметры расчёта.",
                "sandbox_value": sandbox_energy,
                "db_value": official_energy,
                "diff_pct": round(diff_pct, 1),
            }
    except Exception as e:
        logger.debug("Cross-check: %s", e)
    return None
