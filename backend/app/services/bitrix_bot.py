"""Bitrix24 Chat-Bot service — Phase 3.

Handles incoming messages from B24 chat-bot, routes them through Sanek v4,
converts responses to B24 format, manages progress tracking and file uploads.

Architecture:
  B24 Event -> handle_bot_message() -> Sanek v4 AgentLoop -> B24 response
  Progress:  B24ProgressTracker updates chat message in real-time
  Files:     upload_file_to_b24_disk() -> send_file_in_chat()
  Format:    convert_markdown_to_b24() for bbcode output
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from pathlib import Path

import aiofiles
import httpx

from config import settings
from models.base import async_session

logger = logging.getLogger("scada.bitrix_bot")

# ═══════════════════════════════════════════════════════════════════════
# 1. Bot REST API calls (imbot.* methods via bot access_token)
# ═══════════════════════════════════════════════════════════════════════

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


async def _get_bot_access_token(redis) -> str:
    """Get bot access token from Redis cache or fall back to config."""
    try:
        cached = await redis.get("bitrix:bot:access_token")
        if cached:
            return cached.decode() if isinstance(cached, bytes) else cached
    except Exception as e:
        logger.debug("Redis token read failed: %s", e)
    return settings.BITRIX24_BOT_ACCESS_TOKEN


async def _refresh_bot_token(redis) -> str | None:
    """Refresh app OAuth token via oauth.bitrix.info using client credentials."""
    try:
        rt = await redis.get("bitrix:bot:refresh_token")
        if not rt:
            logger.error("No refresh_token in Redis — reinstall app in Б24")
            return None
        refresh_token = rt.decode() if isinstance(rt, bytes) else rt
    except Exception:
        logger.error("Redis refresh_token read failed")
        return None

    if not settings.BITRIX24_OAUTH_CLIENT_ID:
        logger.error("BITRIX24_OAUTH_CLIENT_ID not set")
        return None

    try:
        client = _get_http_client()
        resp = await client.post(
            "https://oauth.bitrix.info/oauth/token/",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.BITRIX24_OAUTH_CLIENT_ID,
                "client_secret": settings.BITRIX24_OAUTH_CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
        )
        data = resp.json()
        new_token = data.get("access_token")
        new_refresh = data.get("refresh_token")

        if new_token:
            await redis.set("bitrix:bot:access_token", new_token, ex=3500)
            if new_refresh:
                await redis.set("bitrix:bot:refresh_token", new_refresh, ex=2592000)
                logger.info("Bot token refreshed, new refresh_token saved")
            return new_token
        else:
            logger.warning("Token refresh response has no access_token: %s", data)
            return None
    except Exception as e:
        logger.warning("Bot token refresh failed (webhook bot may have persistent token): %s", e)
        return None


async def imbot_api_call(method: str, params: dict, redis=None) -> dict:
    """Call Bitrix24 REST API using bot access_token.

    Retries 3 times with exponential backoff on 429/5xx.
    On 401 attempts token refresh once.
    """
    token = await _get_bot_access_token(redis) if redis else settings.BITRIX24_BOT_ACCESS_TOKEN
    url = f"https://{settings.BITRIX24_PORTAL}/rest/{method}"
    client = _get_http_client()
    last_exc: Exception | None = None
    refreshed = False

    for attempt in range(3):
        call_params = {**params, "auth": token}

        try:
            resp = await client.post(url, json=call_params)
            data = resp.json()

            # B24 error handling
            if "error" in data:
                error_code = data.get("error", "")

                # Rate limit
                if error_code == "QUERY_LIMIT_EXCEEDED" or resp.status_code == 429:
                    backoff = 2 ** attempt
                    logger.warning("Bot API rate limit, retry %d/3 in %ds", attempt + 1, backoff)
                    await asyncio.sleep(backoff)
                    continue

                # Auth error — try refresh once
                if error_code in ("INVALID_TOKEN", "NO_AUTH_FOUND", "expired_token") or resp.status_code == 401:
                    if not refreshed and redis:
                        refreshed = True
                        new_token = await _refresh_bot_token(redis)
                        if new_token:
                            token = new_token
                            continue
                    raise RuntimeError(f"Bot auth failed: [{error_code}] {data.get('error_description', '')}")

                # Other B24 errors — don't retry
                logger.error("Bot API error: %s %s", error_code, data.get("error_description", ""))
                return data

            return data

        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code >= 500:
                backoff = 2 ** attempt
                logger.warning("Bot API HTTP %d, retry %d/3 in %ds",
                               exc.response.status_code, attempt + 1, backoff)
                await asyncio.sleep(backoff)
                continue
            raise

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
            backoff = 2 ** attempt
            logger.warning("Bot API connection error: %s, retry %d/3 in %ds",
                           exc, attempt + 1, backoff)
            await asyncio.sleep(backoff)
            continue

        except RuntimeError:
            raise

        except Exception as exc:
            last_exc = exc
            logger.exception("Bot API unexpected error on %s", method)
            break

    raise last_exc or RuntimeError(f"Bot API call {method} failed after 3 retries")


# Unified B24 REST API call — alias for backward compatibility
b24_app_call = imbot_api_call


# ═══════════════════════════════════════════════════════════════════════
# 4. Tool progress messages
# ═══════════════════════════════════════════════════════════════════════

TOOL_PROGRESS_MAP: dict[str, str] = {
    "get_current_metrics":   "⏳ Получаю метрики...",
    "get_metrics_history":   "⏳ Загружаю историю метрик...",
    "get_economics_report":  "⏳ Считаю экономику...",
    "get_alarms":            "⏳ Проверяю аварии...",
    "get_topology":          "⏳ Получаю топологию...",
    "search_knowledge":      "⏳ Ищу в базе знаний...",
    "get_alarm_reference":   "⏳ Ищу справку по аварии...",
    "get_bitrix_tasks":      "⏳ Получаю задачи...",
    "create_bitrix_task":    "⏳ Создаю задачу в Битрикс...",
    "read_modbus_register":  "⏳ Читаю Modbus регистр...",
    "send_modbus_command":   "⏳ Выполняю команду...",
    "run_python_code":       "⏳ Выполняю Python код...",
    "query_db":              "⏳ Выполняю SQL запрос...",
    "get_db_schema":         "⏳ Получаю схему БД...",
    "save_sop_entry":        "⏳ Сохраняю SOP...",
}


# ═══════════════════════════════════════════════════════════════════════
# 5. B24ProgressTracker — live progress in B24 chat
# ═══════════════════════════════════════════════════════════════════════

class B24ProgressTracker:
    """Tracks Sanek v4 tool execution progress in a B24 chat message.

    Sends an initial "accepted" message, then updates it as tools run.
    Rate-limited to 1 update per 2 seconds to avoid B24 API throttling.
    """

    def __init__(self, bot_id: int, dialog_id: str, redis):
        self.bot_id = bot_id
        self.dialog_id = dialog_id
        self.redis = redis
        self._message_id: int | None = None
        self._last_update: float = 0.0
        self._steps_done: list[str] = []
        self._current_step: str = ""
        self._typing_active = False
        self._typing_task = None

    async def _send_typing(self) -> None:
        try:
            await imbot_api_call("imbot.chat.sendTyping", {
                "BOT_ID": self.bot_id, "DIALOG_ID": self.dialog_id,
            }, redis=self.redis)
        except Exception:
            pass

    async def _typing_loop(self) -> None:
        while self._typing_active:
            await self._send_typing()
            await asyncio.sleep(4)

    def _build_progress_text(self) -> str:
        lines = ["🧠 [b]Анализирую запрос...[/b]\n"]
        for s in self._steps_done:
            lines.append(f"✅ {s}")
        if self._current_step:
            lines.append(f"⏳ {self._current_step}")
        return "\n".join(lines)

    async def start(self) -> None:
        self._typing_active = True
        self._typing_task = asyncio.create_task(self._typing_loop())
        try:
            result = await imbot_api_call("imbot.message.add", {
                "BOT_ID": self.bot_id, "DIALOG_ID": self.dialog_id,
                "MESSAGE": "🧠 [b]Принял запрос, анализирую...[/b]",
            }, redis=self.redis)
            self._message_id = result.get("result")
            self._last_update = time.monotonic()
        except Exception as e:
            logger.error("Failed to send progress start: %s", e)

    async def on_tool_start(self, tool_name: str) -> None:
        if not self._message_id:
            return
        # Mark previous step as done
        if self._current_step:
            self._steps_done.append(self._current_step)
        # Set new current step
        self._current_step = TOOL_PROGRESS_MAP.get(tool_name, tool_name).replace("⏳ ", "")
        # Always update (no rate limit — B24 allows ~2 req/sec)
        try:
            await imbot_api_call("imbot.message.update", {
                "BOT_ID": self.bot_id, "MESSAGE_ID": self._message_id,
                "MESSAGE": self._build_progress_text(),
            }, redis=self.redis)
            self._last_update = time.monotonic()
        except Exception as e:
            logger.debug("Progress update failed: %s", e)

    async def finish(self, final_text: str, keyboard: list | None = None, attach: list | None = None) -> None:
        # Stop typing
        self._typing_active = False
        if self._typing_task:
            self._typing_task.cancel()
            try:
                await self._typing_task
            except (asyncio.CancelledError, Exception):
                pass
        if not self._message_id:
            params: dict = {
                "BOT_ID": self.bot_id,
                "DIALOG_ID": self.dialog_id,
                "MESSAGE": final_text,
            }
            if keyboard:
                params["KEYBOARD"] = keyboard
            if attach:
                params["ATTACH"] = attach
            try:
                await imbot_api_call("imbot.message.add", params, redis=self.redis)
            except Exception as e:
                logger.error("Failed to send final message: %s", e)
            return

        params = {
            "BOT_ID": self.bot_id,
            "MESSAGE_ID": self._message_id,
            "MESSAGE": final_text,
        }
        if keyboard:
            params["KEYBOARD"] = keyboard
        if attach:
            params["ATTACH"] = attach

        try:
            await imbot_api_call("imbot.message.update", params, redis=self.redis)
        except Exception as e:
            logger.error("Failed to update final message: %s", e)


# ═══════════════════════════════════════════════════════════════════════
# 6. Suggestions → B24 Keyboard
# ═══════════════════════════════════════════════════════════════════════

_COLOR_MAP: dict[str, str] = {
    "метрик":    "#29619b",   # blue
    "авари":     "#c75050",   # red
    "стату":     "#29619b",   # blue
    "эконом":    "#2e8b57",   # green
    "генератор": "#29619b",   # blue
    "помощ":     "#808080",   # gray
    "отчёт":     "#2e8b57",   # green
    "отчет":     "#2e8b57",   # green
    "задач":     "#9b6429",   # orange
    "default":   "#535c69",   # dark gray
}


def _get_icon(text: str) -> str:
    """Select emoji icon based on suggestion text content."""
    text_lower = text.lower()
    if any(w in text_lower for w in ("метрик", "данные", "показ")):
        return "📡"
    if any(w in text_lower for w in ("авари", "alarm", "ошибк")):
        return "⚠️"
    if any(w in text_lower for w in ("эконом", "стоимост", "расход")):
        return "💰"
    if any(w in text_lower for w in ("стату", "состоян")):
        return "📊"
    if any(w in text_lower for w in ("задач", "битрикс")):
        return "📝"
    if any(w in text_lower for w in ("отчёт", "отчет", "excel", "pdf")):
        return "📄"
    if any(w in text_lower for w in ("помощ", "помоги", "что умеешь")):
        return "💡"
    return "▶️"


def suggestions_to_keyboard(sanek_response: str) -> tuple[str, list | None]:
    """Parse suggestions from Sanek response and convert to B24 KEYBOARD.

    Supports two formats:
    1. XML: <suggestions>- option1\n- option2</suggestions>
    2. Text pattern: "Уточните ...:\n- option1\n- option2\n- option3"
       Also matches numbered lists: "1. option1\n2. option2"

    Returns:
        (cleaned_text, keyboard_list_or_None)
    """
    # 1. Try XML format first
    match = re.search(r"<suggestions>(.*?)</suggestions>", sanek_response, re.DOTALL)
    if match:
        cleaned = sanek_response[:match.start()] + sanek_response[match.end():]
        cleaned = cleaned.strip()
        raw = match.group(1).strip()
        lines = [line.strip().lstrip("- ").strip() for line in raw.splitlines() if line.strip()]
        if lines:
            return cleaned, _build_keyboard(lines)

    # 2. Try text pattern: "Уточните/Выберите/Что именно...:\n* opt1\n* opt2"
    #    Handles markdown bold (**Уточните:**) and various list markers (*, -, •, numbered)
    #    Also handles "за X дней" style without explicit question keyword
    keywords = (
        r"(?:\*\*)?(?:Уточните|Выберите|Что именно|Какой|Какую|Какое|Какие"
        r"|Пожалуйста,?\s*уточните|Уточните,?\s*пожалуйста"
        r"|Варианты|Период|Формат)(?:\*\*)?"
    )
    pattern = re.compile(
        r"(" + keywords + r"[^\n]*?:?\s*\*?\*?\s*\n)"
        r"((?:\s*(?:[-•·]|\*(?!\*)|\d+[.)]\s)\s*[^\n]+\n?){2,})",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(sanek_response)
    if match:
        question_line = match.group(1).strip().replace("**", "")
        items_block = match.group(2)
        # Extract list items: handle *, -, •, numbered
        items = re.findall(r"(?:[-•·]|\*(?!\*)|\d+[.)]\s)\s*(.+)", items_block)
        items = [item.strip().lstrip("*").strip() for item in items if item.strip()]
        if len(items) >= 2:
            # Remove the entire block from text, keep question as context
            cleaned = sanek_response[:match.start()] + question_line
            cleaned = cleaned.strip()
            return cleaned, _build_keyboard(items)

    return sanek_response, None


def _build_keyboard(lines: list[str]) -> list[dict]:
    """Build B24 keyboard from a list of option strings."""
    keyboard: list[dict] = []
    for line in lines[:6]:  # max 6 buttons
        line_lower = line.lower()
        bg_color = _COLOR_MAP["default"]
        for keyword, color in _COLOR_MAP.items():
            if keyword != "default" and keyword in line_lower:
                bg_color = color
                break

        icon = _get_icon(line)
        keyboard.append({
            "TEXT": f"{icon} {line}",
            "ACTION": "SEND",
            "ACTION_VALUE": line,
            "BG_COLOR": bg_color,
            "TEXT_COLOR": "#ffffff",
            "DISPLAY": "LINE",
        })
    return keyboard


# ═══════════════════════════════════════════════════════════════════════
# 7. Markdown → B24 BBCode conversion
# ═══════════════════════════════════════════════════════════════════════

def _convert_md_tables(text: str) -> str:
    """Convert markdown tables to plain-text aligned rows."""
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        # Skip separator rows like |---|---|
        if stripped and re.match(r"^\|[\s\-:|]+\|$", stripped):
            continue
        # Convert table rows: | A | B | → A | B
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            result.append("  ".join(cells))
        else:
            result.append(line)
    return "\n".join(result)


def convert_markdown_to_b24(text: str) -> str:
    """Convert markdown formatting to Bitrix24 bbcode.

    Conversion order matters to avoid double-processing:
    1. Code blocks (``` ```) → plain text
    2. Inline code (`code`) → plain text
    3. Headers (## H) → [b]H[/b]
    4. Bold (**text**) → [b]text[/b]
    5. Italic (*text*) → [i]text[/i]
    6. Links [text](url) → [url=url]text[/url]
    7. Tables
    """
    if not text:
        return ""

    # 1. Code blocks → plain text (remove ``` markers)
    text = re.sub(r"```[\w]*\n(.*?)```", r"\1", text, flags=re.DOTALL)

    # 2. Inline code → plain text
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # 3. Headers → bold
    text = re.sub(r"^#{1,4}\s+(.+)$", r"[b]\1[/b]", text, flags=re.MULTILINE)

    # 4. Bold **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", text)
    text = re.sub(r"__(.+?)__", r"[b]\1[/b]", text)

    # 5. Italic *text* or _text_ (but not inside [b] tags or URLs)
    text = re.sub(r"(?<!\[b\])(?<!\w)\*([^*]+?)\*(?!\w)", r"[i]\1[/i]", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"[i]\1[/i]", text)

    # 6. Links [text](url) → [url=url]text[/url]
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"[url=\2]\1[/url]", text)

    # 7. Tables
    text = _convert_md_tables(text)

    # 8. Clean stray HTML/XML tags that LLM may produce
    text = re.sub(r"</?(?:item|div|span|br|p|ul|ol|li|hr|img)[^>]*>", "", text, flags=re.IGNORECASE)

    return text


# ═══════════════════════════════════════════════════════════════════════
# 8. Upload file to B24 Disk
# ═══════════════════════════════════════════════════════════════════════

_B24_REPORTS_FOLDER_NAME = "ScadaGPU Reports"
_REDIS_FOLDER_ID_KEY = "bitrix:bot:reports_folder_id"


async def upload_file_to_b24_disk(file_name: str, redis) -> str | None:
    """Upload a file from REPORTS_DIR to Bitrix24 Disk.

    Creates "ScadaGPU Reports" folder if it doesn't exist (caches folder_id in Redis).
    Uses Sanek webhook URL for disk operations.
    Returns download_url or None on failure.
    """
    file_path = Path(settings.REPORTS_DIR) / file_name
    if not file_path.exists():
        logger.error("File not found for B24 upload: %s", file_path)
        return None

    # Get or create reports folder
    folder_id = await _get_or_create_reports_folder(redis)
    if not folder_id:
        logger.error("Failed to get/create B24 reports folder")
        return None

    try:
        import base64

        # Read file content
        async with aiofiles.open(file_path, "rb") as f:
            content = await f.read()

        # Add full timestamp to avoid DISK_OBJ_22000 (duplicate name)
        name_base, name_ext = os.path.splitext(file_name)
        ts_suffix = time.strftime("%Y%m%d_%H%M%S")
        upload_name = f"{name_base}_{ts_suffix}{name_ext}"

        # Upload via b24_app_call with base64 encoding
        data = await imbot_api_call("disk.folder.uploadFile", {
            "id": folder_id,
            "data": {"NAME": upload_name},
            "fileContent": [upload_name, base64.b64encode(content).decode()],
        }, redis=redis)

        if "error" in data:
            logger.error("B24 disk upload error: %s", data)
            return None

        file_data = data.get("result", {})
        logger.info("B24 disk upload result keys: %s", list(file_data.keys()) if isinstance(file_data, dict) else type(file_data))
        download_url = (
            file_data.get("DOWNLOAD_URL")
            or file_data.get("downloadUrl")
            or file_data.get("DETAIL_URL")
            or file_data.get("detailUrl")
        )
        file_id = file_data.get("ID") or file_data.get("id") or file_data.get("FILE_ID")

        if download_url:
            logger.info("File uploaded to B24 Disk: %s -> %s (id=%s)", file_name, download_url, file_id)
        elif file_id:
            # No download_url but have file_id — construct URL
            download_url = f"https://{settings.BITRIX24_PORTAL}/disk/downloadFile/{file_id}/"
            logger.info("File uploaded, constructed URL: %s (id=%s)", download_url, file_id)
        else:
            logger.warning("File uploaded but no URL or ID: %s", file_data)

        return download_url

    except Exception as e:
        logger.exception("Failed to upload file to B24 Disk: %s", e)
        return None


async def _get_or_create_reports_folder(redis) -> int | None:
    """Get existing reports folder ID from Redis cache, or create new one."""
    # Check cache
    try:
        cached = await redis.get(_REDIS_FOLDER_ID_KEY)
        if cached:
            return int(cached.decode() if isinstance(cached, bytes) else cached)
    except Exception:
        pass

    # Redis lock to prevent concurrent duplicate folder creation
    lock_acquired = await redis.set("bitrix:reports_folder_lock", "1", ex=30, nx=True)
    if not lock_acquired:
        await asyncio.sleep(2)
        cached = await redis.get(_REDIS_FOLDER_ID_KEY)
        return int(cached.decode() if isinstance(cached, bytes) else cached) if cached else None

    try:
        # Get common storage via app access_token
        data = await imbot_api_call("disk.storage.getlist", {}, redis=redis)
        storages = data.get("result", [])

        # Find common storage (shared), fallback to first
        storage_id = None
        for s in storages:
            if s.get("ENTITY_TYPE") == "common":
                storage_id = s.get("ID")
                break
        if not storage_id and storages:
            storage_id = storages[0].get("ID")

        if not storage_id:
            logger.error("No B24 disk storage found")
            return None

        # List folders in storage root
        data = await imbot_api_call("disk.storage.getchildren", {"id": storage_id}, redis=redis)
        children = data.get("result", [])

        for child in children:
            if child.get("NAME") == _B24_REPORTS_FOLDER_NAME and child.get("TYPE") == "folder":
                folder_id = int(child["ID"])
                await redis.set(_REDIS_FOLDER_ID_KEY, str(folder_id), ex=86400)
                return folder_id

        # Create folder
        data = await imbot_api_call("disk.storage.addfolder", {
            "id": storage_id, "data": {"NAME": _B24_REPORTS_FOLDER_NAME},
        }, redis=redis)
        folder_data = data.get("result", {})
        folder_id = folder_data.get("ID")
        if folder_id:
            folder_id = int(folder_id)
            await redis.set(_REDIS_FOLDER_ID_KEY, str(folder_id), ex=86400)
            logger.info("Created B24 reports folder: id=%d", folder_id)
            return folder_id

        logger.error("Failed to create B24 reports folder: %s", data)
        return None

    except Exception as e:
        logger.exception("Failed to get/create B24 reports folder: %s", e)
        return None
    finally:
        await redis.delete("bitrix:reports_folder_lock")


# ═══════════════════════════════════════════════════════════════════════
# 9. Send file in chat via ATTACH
# ═══════════════════════════════════════════════════════════════════════

async def send_file_in_chat(
    dialog_id: str,
    bot_id: int,
    file_name: str,
    file_url: str,
    description: str,
    redis,
) -> None:
    """Send a file link in B24 chat as an ATTACH message."""
    attach = [
        {"MESSAGE": f"📎 {description}"},
        {
            "LINK": {
                "NAME": file_name,
                "LINK": file_url,
                "DESC": description,
            }
        },
    ]

    try:
        result = await imbot_api_call("imbot.message.add", {
            "BOT_ID": bot_id,
            "DIALOG_ID": dialog_id,
            "MESSAGE": f"📎 {file_name}",
            "ATTACH": attach,
        }, redis=redis)
        logger.info("send_file_in_chat result: %s", result)
    except Exception as e:
        logger.error("Failed to send file in chat: %s", e)
        # Fallback: send as plain text link
        try:
            await imbot_api_call("imbot.message.add", {
                "BOT_ID": bot_id,
                "DIALOG_ID": dialog_id,
                "MESSAGE": f"📎 [url={file_url}]{file_name}[/url]",
            }, redis=redis)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 10. Main handler — incoming B24 bot messages
# ═══════════════════════════════════════════════════════════════════════

# RBAC: viewers get a reduced tool set
_VIEWER_ALLOWED_TOOLS = {
    "get_current_metrics", "get_metrics_history", "get_economics_report",
    "get_alarms", "get_topology", "search_knowledge", "get_alarm_reference",
}


# _sanek_v4_complete removed — using services.sanek_v4.sanek_v4_complete instead

async def _handle_incident_response(from_user_id: int, dialog_id: str,
                                     command_params: str, redis) -> None:
    """Handle executor's response to incident inquiry (keyboard button click)."""
    from urllib.parse import parse_qs
    from models.base import async_session as _async_session
    from models.task_manager import TaskCommunication, ScadaTask

    parsed = parse_qs(command_params)
    task_id = int(parsed.get("task", [0])[0])
    status = parsed.get("status", ["unknown"])[0]

    if not task_id:
        return

    bot_id = settings.BITRIX24_BOT_ID

    async with _async_session() as session:
        task = await session.get(ScadaTask, task_id)
        if not task:
            return

        # Log inbound communication
        status_text = {"onsite": "Уже на месте", "need_help": "Нужна помощь"}.get(status, status)
        comm = TaskCommunication(
            task_id=task_id,
            channel="b24_chat",
            direction="inbound",
            sender=str(from_user_id),
            recipient_user_id=from_user_id,
            recipient_name=task.responsible_name or "",
            recipient_role="executor",
            message_type="incident_response",
            message_text=status_text,
        )
        session.add(comm)

        # Update task status
        if task.status == "created":
            task.status = "in_progress"

        await session.commit()

    # Acknowledge
    if status == "need_help":
        reply = f"🆘 Принято! Задача #{task_id} — запрос помощи отправлен руководителю."
    else:
        reply = f"✅ Принято! Задача #{task_id} — вы на месте. Опишите ситуацию когда разберётесь."

    await imbot_api_call("imbot.message.add", {
        "BOT_ID": bot_id,
        "DIALOG_ID": dialog_id,
        "MESSAGE": reply,
    }, redis=redis)

    logger.info("Incident response from user %d: task=%d status=%s", from_user_id, task_id, status)


# Semaphore: max 3 concurrent bot handlers (queue for multi-user)
_B24_SEMAPHORE = asyncio.Semaphore(3)



# ────────────────────────────────────────────────────────────
# Task Manager: free-text response binding
# ────────────────────────────────────────────────────────────
SANEK_PREFIXES = ("санёк", "санек", "sanek", "вопрос:", "/reset", "сброс")

def _is_sanek_command(text: str) -> bool:
    """Check if message is explicitly addressed to Sanek (not a task response)."""
    return any(text.lower().strip().startswith(p) for p in SANEK_PREFIXES)


async def _find_pending_tasks_for_user(bitrix_user_id: int) -> list:
    """Find tasks where user is executor and task awaits response (escalation >= 1)."""
    from sqlalchemy import select
    from models.base import async_session as _async_session
    from models.task_manager import ScadaTask

    async with _async_session() as db:
        result = await db.execute(
            select(ScadaTask).where(
                ScadaTask.responsible_user_id == bitrix_user_id,
                ScadaTask.status.in_(["created", "in_progress", "overdue"]),
                ScadaTask.escalation_level >= 1,
            ).order_by(ScadaTask.deadline.asc()).limit(5)
        )
        return result.scalars().all()


async def _handle_task_free_text(task, from_user_id: int, dialog_id: str, text: str, redis) -> None:
    """Record free-text response, analyze quality, decide next action."""
    from models.base import async_session as _async_session
    from models.task_manager import TaskCommunication, ScadaTask

    bot_id = settings.BITRIX24_BOT_ID

    # 1. Save response to task_communications
    async with _async_session() as db:
        comm = TaskCommunication(
            task_id=task.id,
            channel="b24_chat",
            direction="inbound",
            sender=str(from_user_id),
            recipient_user_id=from_user_id,
            recipient_name=task.responsible_name or "",
            recipient_role="executor",
            message_type="executor_free_text",
            message_text=text,
        )
        db.add(comm)
        await db.commit()

    # 2. Analyze response quality
    analysis = await _analyze_response_quality(task.title, text)

    # 3. Decision based on analysis
    if analysis.get("is_substantial"):
        # Good response -> move task to in_progress
        async with _async_session() as db:
            task_obj = await db.get(ScadaTask, task.id)
            if task_obj and task_obj.status in ("created", "overdue"):
                task_obj.status = "in_progress"
                await db.commit()
        try:
            await imbot_api_call("imbot.message.add", {
                "BOT_ID": bot_id,
                "DIALOG_ID": dialog_id,
                "MESSAGE": f"Ответ принят по задаче #{task.id} «{task.title}». Спасибо.",
            }, redis=redis)
        except Exception as e:
            logger.warning("Failed to send confirmation: %s", e)
    else:
        # Not substantial -> ask for details, log system analysis
        missing = analysis.get('missing', 'Ukazhite kogda vypolnite i kakie raboty nuzhny')
        async with _async_session() as db:
            sys_comm = TaskCommunication(
                task_id=task.id,
                channel="internal",
                direction="outbound",
                sender="system",
                recipient_user_id=from_user_id,
                recipient_name=task.responsible_name or "",
                recipient_role="executor",
                message_type="system_analysis",
                message_text=f"Analiz: {analysis.get('summary', '?')}. Trebujetsja: {missing}",
            )
            db.add(sys_comm)
            await db.commit()
        try:
            await imbot_api_call("imbot.message.add", {
                "BOT_ID": bot_id,
                "DIALOG_ID": dialog_id,
                "MESSAGE": f"Ответ получен по задаче #{task.id}, но не хватает конкретики. {missing}. Уточните, пожалуйста.",
            }, redis=redis)
        except Exception as e:
            logger.warning("Failed to send clarification request: %s", e)

    logger.info("Task free-text: user=%d task=%d substantial=%s text=%s",
                from_user_id, task.id, analysis.get("is_substantial"), text[:100])




async def _analyze_response_quality(task_title: str, response_text: str) -> dict:
    """Evaluate executor response quality. LLM only for medium-length replies."""
    text_len = len(response_text.strip())

    # Short -> not substantial
    if text_len < 30:
        return {"score": 0.2, "is_substantial": False,
                "summary": "Slishkom korotkij otvet",
                "missing": "Ukazhite kogda vypolnite, kakie raboty i materialy nuzhny"}

    # Long -> treat as substantial
    if text_len > 200:
        return {"score": 0.9, "is_substantial": True,
                "summary": "Razvyornutyj otvet", "missing": ""}

    # Medium -> LLM analysis
    try:
        import openai as _oai
        from config import settings as _s
        client = _oai.AsyncOpenAI(api_key=_s.OPENAI_API_KEY, timeout=30)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    "Otseni otvet ispolnitelya na zadachu TO. "
                    f"Zadacha: {task_title}\n"
                    f"Otvet: \"{response_text}\"\n\n"
                    "Otvet TOLKO JSON (bez markdown):\n"
                    '{"score": 0.0-1.0, "is_substantial": true/false, '
                    '"summary": "vyvod", "missing": "chego ne hvataet"}'
                )
            }],
            max_tokens=200,
            temperature=0,
        )
        import json as _json
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code block if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return _json.loads(raw)
    except Exception as e:
        logger.warning("LLM response analysis failed: %s, treating as substantial", e)
        return {"score": 0.5, "is_substantial": True,
                "summary": "Analiz nedostupen", "missing": ""}

async def handle_bot_message(event_data: dict, redis) -> None:
    """Main handler — wraps with semaphore for concurrent user queue."""
    async with _B24_SEMAPHORE:
        await _handle_bot_message_inner(event_data, redis)


async def _handle_bot_message_inner(event_data: dict, redis) -> None:
    """Process a B24 bot message through Sanek v4."""
    try:
        # Determine event type
        event_type = event_data.get("event", "")
        data = event_data.get("data", {}) or event_data.get("data[PARAMS]", {})

        # Normalize: ONIMBOTMESSAGEADD vs ONIMCOMMANDADD
        if event_type == "ONIMCOMMANDADD":
            # Command event: extract from COMMAND fields
            params = data.get("PARAMS", data)
            message_text = params.get("COMMAND_PARAMS", "").strip()
            command = params.get("COMMAND", "").strip()
            from_user_id = int(params.get("FROM_USER_ID", 0))
            dialog_id = str(params.get("DIALOG_ID", ""))

            # /reset command
            if command == "reset" or message_text.lower() in ("/reset", "reset"):
                message_text = ""  # will be handled below as reset
        else:
            # Regular message
            params = data.get("PARAMS", data)
            message_text = params.get("MESSAGE", "").strip()
            from_user_id = int(params.get("FROM_USER_ID", 0))
            dialog_id = str(params.get("DIALOG_ID", ""))
            command = ""

        if not from_user_id or not dialog_id:
            logger.warning("Bot message missing FROM_USER_ID or DIALOG_ID: %s", event_data)
            return

        bot_id = settings.BITRIX24_BOT_ID

        # ── Handle /reset command ──
        if command == "reset" or message_text.lower() in ("/reset", "сброс"):
            session_key = f"b24bot:session:{from_user_id}"
            last_key = f"b24bot:last_msg:{from_user_id}"
            await redis.delete(session_key)
            await redis.delete(last_key)
            new_session = f"b24_{from_user_id}_{int(time.time())}"
            await redis.set(session_key, new_session, ex=7200)
            await imbot_api_call("imbot.message.add", {
                "BOT_ID": bot_id,
                "DIALOG_ID": dialog_id,
                "MESSAGE": "✅ Контекст сброшен. Начнём с чистого листа.",
            }, redis=redis)
            return

        # ── Handle incident_response command from keyboard buttons ──
        if command == "incident_response":
            await _handle_incident_response(from_user_id, dialog_id, message_text, redis)
            return

        if not message_text:
            return

        # ── Find or create ScadaUser by bitrix_id ──
        from sqlalchemy import select
        from models.scada_user import ScadaUser, UserRole

        user: ScadaUser | None = None
        async with async_session() as db:
            result = await db.execute(
                select(ScadaUser).where(ScadaUser.bitrix_id == from_user_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                # Auto-create user with viewer role
                user = ScadaUser(
                    bitrix_id=from_user_id,
                    name=f"B24 User #{from_user_id}",
                    role=UserRole.viewer.value,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                logger.info("Auto-created ScadaUser for bitrix_id=%d", from_user_id)

        # ── Check is_active ──
        if not user.is_active:
            await imbot_api_call("imbot.message.add", {
                "BOT_ID": bot_id,
                "DIALOG_ID": dialog_id,
                "MESSAGE": "🚫 Ваш доступ деактивирован. Обратитесь к администратору.",
            }, redis=redis)
            return

        # ── RBAC: restrict viewer tools ──
        is_viewer = user.role == UserRole.viewer.value

        # ── Session management: auto-reset after 15min idle ──
        IDLE_TIMEOUT = 900  # 15 min silence = new topic
        session_key = f"b24bot:session:{from_user_id}"
        last_key = f"b24bot:last_msg:{from_user_id}"
        now = time.time()

        last_msg_time = await redis.get(last_key)
        raw_session = await redis.get(session_key)
        need_new = not raw_session or (
            last_msg_time and (now - float(last_msg_time)) > IDLE_TIMEOUT
        )

        if need_new:
            session_id = f"b24_{from_user_id}_{int(now)}"
            await redis.set(session_key, session_id, ex=7200)
        else:
            session_id = raw_session.decode() if isinstance(raw_session, bytes) else raw_session

        await redis.set(last_key, str(now), ex=7200)

        # ── Mark message as read (via im.dialog.read, not imbot) ──
        msg_id = params.get("MESSAGE_ID")
        if msg_id:
            try:
                await imbot_api_call("im.dialog.read", {
                    "BOT_ID": bot_id,
                    "DIALOG_ID": dialog_id,
                    "MESSAGE_ID": msg_id,
                }, redis=redis)
            except Exception:
                pass

        # ── Task Manager: check if user has pending tasks ──
        if not _is_sanek_command(message_text):
            pending_tasks = await _find_pending_tasks_for_user(from_user_id)
            if pending_tasks:
                # Bind response to most urgent task
                await _handle_task_free_text(pending_tasks[0], from_user_id, dialog_id, message_text, redis)
                if len(pending_tasks) > 1:
                    other_titles = ", ".join(f"#{t.id}" for t in pending_tasks[1:3])
                    try:
                        await imbot_api_call("imbot.message.add", {
                            "BOT_ID": bot_id,
                            "DIALOG_ID": dialog_id,
                            "MESSAGE": f"Также ожидают ответа: {other_titles}",
                        }, redis=redis)
                    except Exception:
                        pass
                return

        # ── Create progress tracker ──
        tracker = B24ProgressTracker(bot_id=bot_id, dialog_id=dialog_id, redis=redis)
        await tracker.start()

        # ── Run Sanek v4 (with RBAC) ──
        from services.sanek_v4 import sanek_v4_complete
        from services.sanek_v4.prompt import build_user_context
        excluded_tools = ["send_modbus_command"]
        allowed_tools = list(_VIEWER_ALLOWED_TOOLS) if is_viewer else None
        user_context = build_user_context(user, source="bitrix_chat")

        try:
            response_text, generated_files = await asyncio.wait_for(
                sanek_v4_complete(
                    message=message_text,
                    user_id=user.id,
                    session_id=session_id,
                    source="bitrix_chat",
                    user_context=user_context,
                    excluded_tools=excluded_tools,
                    allowed_tools=allowed_tools,
                    on_tool_start=tracker.on_tool_start,
                ),
                timeout=180,
            )
        except asyncio.TimeoutError:
            response_text = "⏱ Превышено время обработки запроса (180с). Попробуйте упростить вопрос."
            generated_files = []
        except Exception as e:
            logger.exception("Sanek v4 error for bitrix_id=%d: %s", from_user_id, e)
            response_text = f"❌ Ошибка обработки: {type(e).__name__}: {str(e)[:200]}"
            generated_files = []

        # ── Handle generated files (from sandbox) ──
        logger.info("DEBUG FILES: from sanek=%d, response_len=%d, response_preview=%s",
                     len(generated_files), len(response_text), response_text[:100])

        # ── ALWAYS scan reports dir for recent files (created in last 120s) ──
        rdir = settings.REPORTS_DIR
        if os.path.exists(rdir):
            now_ts = time.time()
            for fn in os.listdir(rdir):
                fp = os.path.join(rdir, fn)
                if os.path.isfile(fp) and fn.endswith(('.xlsx', '.pdf', '.csv', '.png')):
                    age = now_ts - os.path.getmtime(fp)
                    if age < 120 and not any(gf.get("filename") == fn for gf in generated_files):
                        generated_files.append({"filename": fn, "name": fn})
                        logger.info("Found recent file: %s (age=%.0fs)", fn, age)

        # Upload files to B24 Disk and collect ATTACHes for final message
        file_attaches = []
        for gf in generated_files:
            fname = gf.get("filename") or gf.get("name", "")
            if not fname:
                continue
            logger.info("Uploading %s to B24 Disk", fname)
            file_url = await upload_file_to_b24_disk(fname, redis)
            if file_url:
                file_attaches.append({
                    "FILE": {"NAME": f"📎 {fname}", "LINK": file_url}
                })
                response_text = response_text.replace(f"/reports/{fname}", "")

        # Remove ALL empty/broken markdown links like [📥 Скачать Excel]() or [text]()
        response_text = re.sub(r"\[([^\]]*(?:Скачать|скачать|Excel|excel|xlsx|Файл|файл)[^\]]*)\]\(\s*\)", "", response_text)
        # Remove leftover /reports/ references
        response_text = re.sub(r"\[([^\]]*)\]\(/reports/[^)]*\)", r"\1", response_text)

        # ── Extract suggestions → keyboard BEFORE markdown conversion ──
        # (markdown conversion destroys * list markers needed for button parsing)
        response_text, keyboard = suggestions_to_keyboard(response_text)

        # ── Convert markdown → B24 bbcode ──
        b24_text = convert_markdown_to_b24(response_text)

        # ── If files — ensure text is not empty ──
        if not b24_text.strip() and generated_files:
            b24_text = "✅ Файл сформирован"
        elif not b24_text.strip():
            b24_text = "✅ Запрос обработан."

        # ── Truncate if too long (B24 message limit ~10000 chars) ──
        if len(b24_text) > 9500:
            b24_text = b24_text[:9500] + "\n\n[i]...сообщение обрезано[/i]"

        # ── Send final response ──
        await tracker.finish(b24_text, keyboard, attach=file_attaches or None)

        # ── Log activity ──
        try:
            from services.activity_logger import log_activity
            await log_activity(user.id, "chat_message_b24", source="bitrix_chat",
                             details={"message": message_text[:200]})
        except Exception:
            pass

        logger.info(
            "B24 bot: user=%d (%s), msg=%s, tools=%d, response_len=%d",
            from_user_id, user.name,
            message_text[:60], len(generated_files), len(b24_text),
        )

    except Exception as e:
        logger.exception("handle_bot_message fatal error: %s", e)
        # Try to notify user
        try:
            await imbot_api_call("imbot.message.add", {
                "BOT_ID": settings.BITRIX24_BOT_ID,
                "DIALOG_ID": event_data.get("data", {}).get("PARAMS", {}).get("DIALOG_ID", ""),
                "MESSAGE": "❌ Внутренняя ошибка бота. Попробуйте позже.",
            }, redis=redis)
        except Exception:
            pass


def _extract_generated_files(response_text: str) -> list[dict]:
    """Extract generated file references from Sanek response.

    Looks for patterns like: 📎 filename.xlsx or [file: filename.pdf]
    """
    files = []
    reports_dir = Path(settings.REPORTS_DIR)

    # Pattern: 📎 filename.ext
    for match in re.finditer(r"📎\s*(\S+\.(?:xlsx|pdf|csv|png|jpg))", response_text):
        name = match.group(1)
        if (reports_dir / name).exists():
            files.append({"name": name, "description": name})

    # Pattern: [file: filename.ext] or файл: filename.ext
    for match in re.finditer(r"(?:\[file:\s*|файл:\s*)(\S+\.(?:xlsx|pdf|csv|png|jpg))", response_text, re.IGNORECASE):
        name = match.group(1)
        if (reports_dir / name).exists() and not any(f["name"] == name for f in files):
            files.append({"name": name, "description": name})

    # Pattern: /reports/filename.ext (markdown links or plain text)
    for match in re.finditer(r"/reports/(\S+\.(?:xlsx|pdf|csv|png|jpg))", response_text, re.IGNORECASE):
        name = match.group(1)
        if (reports_dir / name).exists() and not any(f["name"] == name for f in files):
            files.append({"name": name, "description": name})

    # Pattern: download_url in tool result
    for match in re.finditer(r'"download_url":\s*"/reports/(\S+?)"', response_text):
        name = match.group(1)
        if (reports_dir / name).exists() and not any(f["name"] == name for f in files):
            files.append({"name": name, "description": name})

    return files


# ═══════════════════════════════════════════════════════════════════════
# 11. Bot registration (one-time)
# ═══════════════════════════════════════════════════════════════════════

async def register_bot(redis) -> dict:
    """Register the bot in Bitrix24 via imbot.register.

    Uses the Sanek admin webhook. Should be called once during initial setup.
    """
    webhook_url = settings.BITRIX24_SANEK_WEBHOOK_URL.rstrip("/")
    client = _get_http_client()

    bot_params = {
        "CODE": "scada_sanek",
        "TYPE": "B",  # Bot type
        "EVENT_MESSAGE_ADD": settings.BITRIX24_BOT_HANDLER_URL + "/api/bitrix/bot/message",
        "EVENT_WELCOME_MESSAGE": "👋 Привет! Я Санёк — AI-ассистент СКАДА.\n"
                                 "Спрашивай о метриках, авариях, экономике ГПУ.\n"
                                 "Команда /reset — сбросить контекст.",
        "EVENT_BOT_DELETE": settings.BITRIX24_BOT_HANDLER_URL + "/api/bitrix/bot/event",
        "PROPERTIES": {
            "NAME": "Санёк",
            "LAST_NAME": "СКАДА",
            "COLOR": "GREEN",
            "WORK_POSITION": "AI-ассистент газопоршневых электростанций",
            "PERSONAL_PHOTO": "",  # Can be set to avatar URL later
        },
        "COMMANDS": [
            {
                "COMMAND": "reset",
                "TITLE": "Сброс контекста",
                "PARAMS": "N",
                "HIDDEN": "N",
                "EXTRANET_SUPPORT": "N",
            },
            {
                "COMMAND": "sanek",
                "TITLE": "Спросить Санька",
                "PARAMS": "Y",
                "HIDDEN": "Y",
                "EXTRANET_SUPPORT": "N",
            },
        ],
    }

    try:
        resp = await client.post(
            f"{webhook_url}/imbot.register",
            json=bot_params,
            timeout=30.0,
        )
        data = resp.json()

        if "error" in data:
            logger.error("Bot registration failed: %s", data)
            return {"success": False, "error": data.get("error_description", str(data))}

        bot_id = data.get("result")
        logger.info("Bot registered successfully, bot_id=%s", bot_id)

        return {
            "success": True,
            "bot_id": bot_id,
            "message": f"Bot registered with id={bot_id}. "
                       f"Set BITRIX24_BOT_ID={bot_id} in .env",
        }

    except Exception as e:
        logger.exception("Bot registration error: %s", e)
        return {"success": False, "error": str(e)}


async def update_bot_profile(redis=None) -> dict:
    """Update bot name, description and avatar in Bitrix24.

    Uses ``imbot.update`` via app access_token.
    Call once after deploy or when avatar changes.
    """
    import base64 as b64_module

    avatar_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "static", "sanek_avatar_white_512.jpg")
    )

    fields: dict = {
        "NAME": "Робот Санёк",
        "WORK_POSITION": "AI-ассистент пром. оборудования",
        "COLOR": "GREEN",
    }

    if os.path.exists(avatar_path):
        with open(avatar_path, "rb") as f:
            fields["PERSONAL_PHOTO"] = b64_module.b64encode(f.read()).decode()
        logger.info("Avatar loaded: %s (%d bytes)", avatar_path, os.path.getsize(avatar_path))
    else:
        logger.warning("Avatar not found: %s, updating without photo", avatar_path)

    # imbot.update is buggy in B24 — workaround: unregister + re-register
    # with correct PROPERTIES (name, avatar, description)
    bot_id = settings.BITRIX24_BOT_ID

    # Step 1: Unregister old bot
    try:
        unreg = await b24_app_call("imbot.unregister", {"BOT_ID": bot_id}, redis=redis)
        logger.info("Unregistered bot %d: %s", bot_id, unreg.get("result", unreg.get("error")))
    except Exception as e:
        logger.warning("Unregister failed (may not exist): %s", e)

    # Step 2: Register with new PROPERTIES
    props = {
        "NAME": fields.get("NAME", "Робот Санёк"),
        "WORK_POSITION": fields.get("WORK_POSITION", "AI-ассистент пром. оборудования"),
        "COLOR": fields.get("COLOR", "GREEN"),
    }
    if "PERSONAL_PHOTO" in fields:
        props["PERSONAL_PHOTO"] = fields["PERSONAL_PHOTO"]

    reg_params = {
        "CODE": "sanek_scada_v2",
        "TYPE": "B",
        "EVENT_MESSAGE_ADD": settings.BITRIX24_BOT_HANDLER_URL + "/api/bitrix/bot/message",
        "EVENT_WELCOME_MESSAGE": settings.BITRIX24_BOT_HANDLER_URL + "/api/bitrix/bot/message",
        "EVENT_BOT_DELETE": settings.BITRIX24_BOT_HANDLER_URL + "/api/bitrix/bot/event",
        "PROPERTIES": props,
    }

    try:
        result = await b24_app_call("imbot.register", reg_params, redis=redis)
        new_id = result.get("result")
        if new_id:
            logger.info("Bot re-registered: id=%s, name=%s", new_id, props["NAME"])
            return {"result": True, "new_bot_id": new_id,
                    "message": f"Bot updated. New BOT_ID={new_id} — update BITRIX24_BOT_ID in config!"}
        else:
            logger.error("Bot re-register failed: %s", result)
            return result
    except Exception as e:
        logger.exception("Bot re-register error: %s", e)
        return {"error": str(e)}
