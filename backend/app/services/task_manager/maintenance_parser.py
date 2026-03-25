"""Parse Word/PDF maintenance cards into structured MaintenanceCard records."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

import httpx

from config import settings
from models.task_manager import MaintenanceCard

logger = logging.getLogger("scada.task_manager")

SANDBOX_URL = "http://sandbox:9999/execute"
SANDBOX_TIMEOUT = 45

# ───────────────────────────────────────────────────────────
# LLM extraction prompt
# ───────────────────────────────────────────────────────────
_LLM_SYSTEM_PROMPT = (
    "Ты — парсер регламентов технического обслуживания "
    "газопоршневых установок (ГПУ). Извлеки из текста структурированные "
    "данные о карточках ТО. Верни ТОЛЬКО валидный JSON-массив."
)

_LLM_USER_PROMPT = """\
Извлеки карточки технического обслуживания из текста ниже.
Для каждой карточки верни JSON-объект:
{{
  "equipment_name": "название оборудования",
  "equipment_code": "код (если есть, иначе null)",
  "maintenance_type": "тип ТО (daily/weekly/monthly/quarterly/annual/overhaul)",
  "maintenance_name": "название работы",
  "interval_hours": число или null,
  "interval_days": число или null,
  "checklist_items": ["пункт 1", "пункт 2", ...]
}}

Верни JSON-массив карточек. Без комментариев, только JSON.

--- ТЕКСТ ---
{text}
"""


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════
async def parse_maintenance_file(
    file_path: str, redis
) -> list[MaintenanceCard]:
    """Parse a Word/PDF/Excel file into MaintenanceCard records.

    1. Extract text via sandbox container
    2. Parse structured tables or use LLM for unstructured text
    3. Build MaintenanceCard objects with source_hash
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix not in (".docx", ".pdf", ".xlsx"):
        raise ValueError(f"Unsupported file type: {suffix}")

    # Read file content
    content_bytes = path.read_bytes()
    content_b64 = base64.b64encode(content_bytes).decode()
    source_hash = _compute_hash(content_bytes)

    # Extract text via sandbox
    raw_text = await _extract_text_sandbox(content_b64, suffix)
    if not raw_text or len(raw_text.strip()) < 20:
        logger.warning("No meaningful text extracted from %s", file_path)
        return []

    # Decide: structured (tables detected) or LLM
    has_tables = _detect_tables(raw_text)
    if has_tables:
        parsed_items = _parse_structured_text(raw_text)
    else:
        parsed_items = await _parse_with_llm(raw_text, redis)

    if not parsed_items:
        logger.warning("No maintenance cards parsed from %s", file_path)
        return []

    # Build MaintenanceCard records
    cards: list[MaintenanceCard] = []
    for item in parsed_items:
        card = MaintenanceCard(
            equipment_code=item.get("equipment_code") or "unknown",
            equipment_name=item.get("equipment_name", "Неизвестно"),
            maintenance_type=item.get("maintenance_type", "unknown"),
            maintenance_name=item.get("maintenance_name"),
            interval_hours=item.get("interval_hours"),
            interval_days=item.get("interval_days"),
            checklist_items=item.get("checklist_items", []),
            source_file=str(file_path),
            source_hash=source_hash,
            is_active=True,
        )
        cards.append(card)

    logger.info(
        "Parsed %d maintenance cards from %s (hash=%s)",
        len(cards),
        path.name,
        source_hash[:12],
    )
    return cards


# ═══════════════════════════════════════════════════════════
# Sandbox text extraction
# ═══════════════════════════════════════════════════════════
async def _extract_text_sandbox(
    file_content_b64: str, file_type: str
) -> str:
    """POST to sandbox container to extract text from binary files."""

    if file_type == ".docx":
        code = _DOCX_EXTRACT_CODE
    elif file_type == ".pdf":
        code = _PDF_EXTRACT_CODE
    elif file_type == ".xlsx":
        code = _XLSX_EXTRACT_CODE
    else:
        return ""

    try:
        async with httpx.AsyncClient(timeout=SANDBOX_TIMEOUT) as client:
            resp = await client.post(
                SANDBOX_URL,
                json={
                    "code": code,
                    "context": {"file_b64": file_content_b64},
                },
            )
            if resp.status_code != 200:
                logger.error(
                    "Sandbox extraction HTTP %d for %s",
                    resp.status_code,
                    file_type,
                )
                return ""
            result = resp.json()
            return result.get("stdout", "") or str(result.get("return_value", ""))
    except httpx.TimeoutException:
        logger.error("Sandbox timeout during %s extraction", file_type)
        return ""
    except httpx.ConnectError:
        logger.error("Sandbox container unavailable for %s extraction", file_type)
        return ""
    except Exception:
        logger.exception("Sandbox extraction error for %s", file_type)
        return ""


# ═══════════════════════════════════════════════════════════
# LLM parsing for unstructured text
# ═══════════════════════════════════════════════════════════
async def _parse_with_llm(
    raw_text: str, redis
) -> list[dict]:
    """Use LLM to extract structured maintenance card data from text."""
    # Truncate if too long
    max_chars = 12000
    text = raw_text[:max_chars] if len(raw_text) > max_chars else raw_text

    prompt_text = _LLM_USER_PROMPT.format(text=text)

    try:
        if settings.OPENAI_API_KEY:
            result = await _call_openai(prompt_text)
        elif settings.CLAUDE_API_KEY:
            result = await _call_claude(prompt_text)
        else:
            logger.error("No LLM API key configured for maintenance parsing")
            return []

        # Parse JSON from LLM response
        return _extract_json_array(result)
    except Exception:
        logger.exception("LLM parsing failed")
        return []


async def _call_openai(prompt_text: str) -> str:
    """Call OpenAI API for structured extraction."""
    async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={
                "model": settings.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt_text},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _call_claude(prompt_text: str) -> str:
    """Call Anthropic Claude API for structured extraction."""
    async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.CLAUDE_MODEL,
                "max_tokens": 4096,
                "system": _LLM_SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": prompt_text},
                ],
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════
def _compute_hash(content: bytes) -> str:
    """SHA-256 hex digest of file content."""
    return hashlib.sha256(content).hexdigest()


def _detect_tables(text: str) -> bool:
    """Heuristic: text has table-like structure (pipe separators or tab-columns)."""
    lines = text.strip().split("\n")
    pipe_lines = sum(1 for l in lines if l.count("|") >= 2)
    tab_lines = sum(1 for l in lines if l.count("\t") >= 2)
    return pipe_lines > 3 or tab_lines > 3


def _parse_structured_text(text: str) -> list[dict]:
    """Parse table-formatted text into card dicts.

    Expects rows with columns: equipment_name, maintenance_type,
    interval_hours/days, checklist items.
    """
    cards: list[dict] = []
    lines = text.strip().split("\n")

    for line in lines:
        # Try pipe-separated
        if "|" in line:
            cols = [c.strip() for c in line.split("|") if c.strip()]
        elif "\t" in line:
            cols = [c.strip() for c in line.split("\t") if c.strip()]
        else:
            continue

        if len(cols) < 3:
            continue

        # Skip header-like rows
        if any(h in cols[0].lower() for h in ("оборудование", "equipment", "---", "===")):
            continue

        card = {
            "equipment_name": cols[0],
            "maintenance_type": cols[1] if len(cols) > 1 else "unknown",
            "maintenance_name": cols[2] if len(cols) > 2 else None,
            "interval_hours": _try_int(cols[3]) if len(cols) > 3 else None,
            "interval_days": _try_int(cols[4]) if len(cols) > 4 else None,
            "checklist_items": cols[5].split(";") if len(cols) > 5 else [],
        }
        cards.append(card)

    return cards


def _extract_json_array(text: str) -> list[dict]:
    """Extract a JSON array from LLM response text."""
    text = text.strip()
    # Try direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            # LLM might wrap in {"cards": [...]}
            for key in ("cards", "items", "maintenance_cards", "data"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
            return [parsed]
    except json.JSONDecodeError:
        pass

    # Try to find JSON array in text
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("Could not extract JSON array from LLM response")
    return []


def _try_int(value: str) -> int | None:
    """Try to parse a string as int, return None on failure."""
    try:
        return int(value.strip())
    except (ValueError, TypeError, AttributeError):
        return None


# ═══════════════════════════════════════════════════════════
# Sandbox extraction code templates
# ═══════════════════════════════════════════════════════════
_DOCX_EXTRACT_CODE = """
import base64, io
from docx import Document

data = base64.b64decode(context['file_b64'])
doc = Document(io.BytesIO(data))

lines = []
for para in doc.paragraphs:
    if para.text.strip():
        lines.append(para.text)

for table in doc.tables:
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        lines.append(" | ".join(cells))

print("\\n".join(lines))
"""

_PDF_EXTRACT_CODE = """
import base64, io
import pdfplumber

data = base64.b64decode(context['file_b64'])
pdf = pdfplumber.open(io.BytesIO(data))

lines = []
for page in pdf.pages:
    text = page.extract_text()
    if text:
        lines.append(text)
    for table in page.extract_tables():
        for row in table:
            cells = [str(c or '').strip() for c in row]
            lines.append(" | ".join(cells))

print("\\n".join(lines))
"""

_XLSX_EXTRACT_CODE = """
import base64, io
import openpyxl

data = base64.b64decode(context['file_b64'])
wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)

lines = []
for ws in wb.worksheets:
    lines.append(f"=== {ws.title} ===")
    for row in ws.iter_rows(values_only=True):
        cells = [str(c or '').strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells))

print("\\n".join(lines))
"""
