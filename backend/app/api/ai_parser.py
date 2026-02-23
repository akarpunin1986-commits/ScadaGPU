"""
Phase 5.1+5.2 — AI agent API with persistent multi-provider configuration
and Sanek AI assistant chat.

API keys stored in PostgreSQL (ai_provider_configs table).
Supports multiple LLM providers simultaneously: OpenAI, Claude, Gemini, Grok.
One provider is "active" — used by default for AI operations.
Sanek assistant: full SCADA access via tool calling + persistent chat history.
"""
import json
import logging
import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel
import sqlalchemy as sa
from sqlalchemy import select, update

from config import settings
from models.base import async_session
from models.ai_provider import AiProviderConfig
from models.ai_chat import AiChatMessage

router = APIRouter(prefix="/api/ai", tags=["ai-agent"])
logger = logging.getLogger("scada.ai_parser")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_PROVIDERS = ("openai", "claude", "gemini", "grok")

DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "claude": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.5-flash",
    "grok": "grok-3-mini",
}

# ---------------------------------------------------------------------------
# In-memory cache (populated from DB on startup, updated on save)
# ---------------------------------------------------------------------------
_cache: dict = {
    "provider": "",   # active provider name
    "keys": {},       # {provider: api_key}
    "models": {},     # {provider: model}
}


def mask_key(key: str) -> str:
    """Mask API key for safe display: 'sk-proj-abc...xyz4'."""
    if not key:
        return ""
    if len(key) <= 8:
        return key[:2] + "..." + key[-2:]
    return key[:6] + "..." + key[-4:]


async def load_ai_configs_from_db():
    """Load all provider configs from DB into memory cache. Called on startup."""
    global _cache
    try:
        async with async_session() as session:
            result = await session.execute(select(AiProviderConfig))
            rows = result.scalars().all()

        for row in rows:
            if row.is_configured and row.api_key:
                _cache["keys"][row.provider] = row.api_key
            if row.model:
                _cache["models"][row.provider] = row.model
            if row.is_active:
                _cache["provider"] = row.provider

        configured = [p for p in _cache["keys"]]
        logger.info(
            "AI configs loaded from DB: %d providers configured, active=%s",
            len(configured),
            _cache["provider"] or "none",
        )
    except Exception as e:
        logger.warning("Could not load AI configs from DB (table may not exist yet): %s", e)


def _get_active_provider() -> str:
    """Get active provider: cache (from DB) → .env fallback."""
    if _cache.get("provider"):
        return _cache["provider"]
    return settings.AI_PROVIDER


def _get_api_key(provider: str) -> str:
    """Get API key: cache (from DB) → .env fallback."""
    cached = _cache.get("keys", {}).get(provider)
    if cached:
        return cached
    return {
        "openai": settings.OPENAI_API_KEY,
        "claude": settings.CLAUDE_API_KEY,
        "gemini": settings.GEMINI_API_KEY,
        "grok": settings.GROK_API_KEY,
    }.get(provider, "")


def _get_model(provider: str) -> str:
    """Get model: cache (from DB) → .env fallback → default."""
    cached = _cache.get("models", {}).get(provider)
    if cached:
        return cached
    env_model = {
        "openai": settings.OPENAI_MODEL,
        "claude": settings.CLAUDE_MODEL,
        "gemini": settings.GEMINI_MODEL,
        "grok": settings.GROK_MODEL,
    }.get(provider, "")
    return env_model or DEFAULT_MODELS.get(provider, "")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class ParseRequest(BaseModel):
    webhook_url: str
    file_id: int
    filename: str = ""


class ParsedTask(BaseModel):
    text: str
    is_critical: bool = False
    sort_order: int = 0


class ParsedInterval(BaseModel):
    code: str
    name: str
    hours: int
    sort_order: int = 0
    tasks: list[ParsedTask] = []


class ParseResponse(BaseModel):
    success: bool
    template_name: str = ""
    description: str = ""
    intervals: list[ParsedInterval] = []
    raw_text_preview: str = ""
    error: str | None = None


class HealthResponse(BaseModel):
    available: bool
    provider: str = ""
    model: str = ""


class ConfigRequest(BaseModel):
    provider: str
    api_key: str
    model: str = ""


class ConfigResponse(BaseModel):
    success: bool
    message: str = ""


class TestRequest(BaseModel):
    provider: str
    api_key: str
    model: str = ""


class TestResponse(BaseModel):
    success: bool
    message: str = ""
    error: str | None = None


# --- New multi-provider schemas ---
class ProviderInfo(BaseModel):
    provider: str
    is_configured: bool = False
    is_active: bool = False
    model: str = ""
    api_key_masked: str = ""


class ProvidersListResponse(BaseModel):
    providers: list[ProviderInfo] = []
    active_provider: str = ""


class ProviderSaveRequest(BaseModel):
    provider: str
    api_key: str
    model: str = ""


class ProviderSaveResponse(BaseModel):
    success: bool
    message: str = ""


class ProviderActivateRequest(BaseModel):
    provider: str


class ProviderActivateResponse(BaseModel):
    success: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Multi-provider endpoints (new)
# ---------------------------------------------------------------------------
@router.get("/providers", response_model=ProvidersListResponse)
async def list_providers():
    """List all 4 providers with their status, masked keys, active flag."""
    # Fetch from DB
    db_rows = {}
    try:
        async with async_session() as session:
            result = await session.execute(select(AiProviderConfig))
            for row in result.scalars().all():
                db_rows[row.provider] = row
    except Exception as e:
        logger.warning("Could not read AI configs from DB: %s", e)

    providers = []
    active = ""

    for p in VALID_PROVIDERS:
        db_row = db_rows.get(p)
        if db_row and db_row.is_configured and db_row.api_key:
            # From DB
            info = ProviderInfo(
                provider=p,
                is_configured=True,
                is_active=db_row.is_active,
                model=db_row.model or DEFAULT_MODELS.get(p, ""),
                api_key_masked=mask_key(db_row.api_key),
            )
            if db_row.is_active:
                active = p
        else:
            # Check .env fallback
            env_key = _get_api_key(p)
            if env_key and p not in _cache.get("keys", {}):
                info = ProviderInfo(
                    provider=p,
                    is_configured=True,
                    is_active=(_get_active_provider() == p and not active),
                    model=_get_model(p),
                    api_key_masked=mask_key(env_key),
                )
                if info.is_active:
                    active = p
            else:
                info = ProviderInfo(
                    provider=p,
                    is_configured=False,
                    is_active=False,
                    model=DEFAULT_MODELS.get(p, ""),
                )
        providers.append(info)

    return ProvidersListResponse(providers=providers, active_provider=active)


@router.post("/provider/save", response_model=ProviderSaveResponse)
async def save_provider(req: ProviderSaveRequest):
    """Save (upsert) API key + model for a provider to DB."""
    if req.provider not in VALID_PROVIDERS:
        return ProviderSaveResponse(
            success=False,
            message=f"Неизвестный провайдер: {req.provider}",
        )

    if not req.api_key.strip():
        return ProviderSaveResponse(success=False, message="API ключ не указан")

    model = req.model or DEFAULT_MODELS.get(req.provider, "")

    try:
        async with async_session() as session:
            result = await session.execute(
                select(AiProviderConfig).where(AiProviderConfig.provider == req.provider)
            )
            row = result.scalar_one_or_none()

            if row:
                row.api_key = req.api_key.strip()
                row.model = model
                row.is_configured = True
            else:
                row = AiProviderConfig(
                    provider=req.provider,
                    api_key=req.api_key.strip(),
                    model=model,
                    is_configured=True,
                    is_active=False,
                )
                session.add(row)

            await session.commit()

        # Update cache
        _cache["keys"][req.provider] = req.api_key.strip()
        _cache["models"][req.provider] = model

        logger.info(
            "AI provider saved: %s, model=%s, key=%s",
            req.provider, model, mask_key(req.api_key),
        )
        return ProviderSaveResponse(
            success=True,
            message=f"✅ {req.provider} сохранён в БД, модель: {model}",
        )
    except Exception as e:
        logger.error("Error saving AI provider %s: %s", req.provider, e)
        return ProviderSaveResponse(success=False, message=f"Ошибка: {e}")


@router.post("/provider/activate", response_model=ProviderActivateResponse)
async def activate_provider(req: ProviderActivateRequest):
    """Set one provider as active (deactivate all others)."""
    if req.provider not in VALID_PROVIDERS:
        return ProviderActivateResponse(
            success=False,
            message=f"Неизвестный провайдер: {req.provider}",
        )

    # Check if provider has a key
    key = _get_api_key(req.provider)
    if not key:
        return ProviderActivateResponse(
            success=False,
            message=f"⚠ {req.provider} не настроен — сначала сохраните API ключ",
        )

    try:
        async with async_session() as session:
            # Deactivate all
            await session.execute(
                update(AiProviderConfig).values(is_active=False)
            )
            # Activate requested
            result = await session.execute(
                select(AiProviderConfig).where(AiProviderConfig.provider == req.provider)
            )
            row = result.scalar_one_or_none()
            if row:
                row.is_active = True
            else:
                # Provider configured via .env only, create DB row
                row = AiProviderConfig(
                    provider=req.provider,
                    api_key=key,
                    model=_get_model(req.provider),
                    is_configured=True,
                    is_active=True,
                )
                session.add(row)

            await session.commit()

        # Update cache
        _cache["provider"] = req.provider

        logger.info("AI active provider set to: %s", req.provider)
        return ProviderActivateResponse(
            success=True,
            message=f"★ {req.provider} активирован",
        )
    except Exception as e:
        logger.error("Error activating AI provider %s: %s", req.provider, e)
        return ProviderActivateResponse(success=False, message=f"Ошибка: {e}")


@router.delete("/provider/{provider}")
async def delete_provider(provider: str):
    """Remove a provider's API key from DB."""
    if provider not in VALID_PROVIDERS:
        return {"success": False, "message": f"Неизвестный провайдер: {provider}"}

    try:
        async with async_session() as session:
            result = await session.execute(
                select(AiProviderConfig).where(AiProviderConfig.provider == provider)
            )
            row = result.scalar_one_or_none()
            if row:
                row.api_key = ""
                row.is_configured = False
                if row.is_active:
                    row.is_active = False
                    _cache["provider"] = ""
                await session.commit()

        # Remove from cache
        _cache["keys"].pop(provider, None)

        logger.info("AI provider removed: %s", provider)
        return {"success": True, "message": f"{provider} удалён"}
    except Exception as e:
        logger.error("Error deleting AI provider %s: %s", provider, e)
        return {"success": False, "message": f"Ошибка: {e}"}


# ---------------------------------------------------------------------------
# Existing endpoints (backward compatible)
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthResponse)
async def ai_health():
    """Check if AI agent is configured and available."""
    provider = _get_active_provider()
    api_key = _get_api_key(provider)
    available = bool(api_key)
    return HealthResponse(
        available=available,
        provider=provider if available else "",
        model=_get_model(provider) if available else "",
    )


@router.post("/config", response_model=ConfigResponse)
async def set_ai_config(req: ConfigRequest):
    """
    Legacy endpoint — saves config to DB (backward compatible).
    Called by old frontend versions.
    """
    if req.provider not in VALID_PROVIDERS:
        return ConfigResponse(
            success=False,
            message=f"Неизвестный провайдер: {req.provider}",
        )

    # Save to DB via new logic
    save_result = await save_provider(ProviderSaveRequest(
        provider=req.provider,
        api_key=req.api_key,
        model=req.model,
    ))

    if save_result.success:
        # Also activate this provider
        await activate_provider(ProviderActivateRequest(provider=req.provider))

    return ConfigResponse(
        success=save_result.success,
        message=save_result.message,
    )


@router.post("/test", response_model=TestResponse)
async def test_ai_provider(req: TestRequest):
    """Test connection to an LLM provider with a simple request."""
    provider = req.provider
    api_key = req.api_key
    model = req.model

    if not api_key:
        return TestResponse(success=False, error="API ключ не указан")

    try:
        if provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, timeout=15)
            resp = await client.chat.completions.create(
                model=model or "gpt-4o",
                messages=[{"role": "user", "content": "Ответь одним словом: работает"}],
                max_tokens=10,
            )
            text = resp.choices[0].message.content or ""
            return TestResponse(
                success=True,
                message=f"✅ OpenAI ({model or 'gpt-4o'}): {text.strip()}",
            )

        elif provider == "claude":
            import httpx
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model or "claude-sonnet-4-20250514",
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "Ответь одним словом: работает"}],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get("content", [{}])[0].get("text", "")
                    return TestResponse(
                        success=True,
                        message=f"✅ Claude ({model or 'claude-sonnet-4-20250514'}): {text.strip()}",
                    )
                else:
                    err = resp.json().get("error", {}).get("message", resp.text)
                    return TestResponse(success=False, error=f"Claude API: {err}")

        elif provider == "gemini":
            import httpx
            mdl = model or "gemini-2.5-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={api_key}"
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.post(
                    url,
                    json={
                        "contents": [{"parts": [{"text": "Ответь одним словом: работает"}]}],
                        "generationConfig": {"maxOutputTokens": 10},
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    return TestResponse(
                        success=True,
                        message=f"✅ Gemini ({mdl}): {text.strip()}",
                    )
                else:
                    err = resp.json().get("error", {}).get("message", resp.text)
                    return TestResponse(success=False, error=f"Gemini API: {err}")

        elif provider == "grok":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.x.ai/v1",
                timeout=15,
            )
            resp = await client.chat.completions.create(
                model=model or "grok-3-mini",
                messages=[{"role": "user", "content": "Ответь одним словом: работает"}],
                max_tokens=10,
            )
            text = resp.choices[0].message.content or ""
            return TestResponse(
                success=True,
                message=f"✅ Grok ({model or 'grok-3-mini'}): {text.strip()}",
            )

        else:
            return TestResponse(success=False, error=f"Неизвестный провайдер: {provider}")

    except Exception as e:
        logger.warning("AI test error (%s): %s", provider, str(e))
        return TestResponse(success=False, error=str(e))


@router.post("/parse", response_model=ParseResponse)
async def parse_maintenance_file(req: ParseRequest):
    """
    Download file from Bitrix24 Disk, extract text, parse with LLM.
    Returns structured maintenance intervals + tasks.
    """
    from services.ai_agent import MaintenanceDocumentParser, AIAgentError

    provider = _get_active_provider()
    api_key = _get_api_key(provider)
    model = _get_model(provider)

    if not api_key:
        return ParseResponse(
            success=False,
            error=f"API ключ для {provider} не настроен. Откройте 🤖 AI Провайдер.",
        )

    try:
        parser = MaintenanceDocumentParser(
            provider=provider,
            api_key=api_key,
            model=model,
        )
        result = await parser.parse_bitrix_file(
            webhook_url=req.webhook_url,
            file_id=req.file_id,
            filename=req.filename or None,
        )

        # Convert raw dict to typed response
        intervals = []
        for iv_data in result.get("intervals", []):
            tasks = []
            for t_data in iv_data.get("tasks", []):
                tasks.append(ParsedTask(
                    text=t_data.get("text", ""),
                    is_critical=t_data.get("is_critical", False),
                    sort_order=t_data.get("sort_order", 0),
                ))
            intervals.append(ParsedInterval(
                code=iv_data.get("code", f"to{len(intervals)+1}"),
                name=iv_data.get("name", f"ТО-{len(intervals)+1}"),
                hours=iv_data.get("hours", 0),
                sort_order=iv_data.get("sort_order", len(intervals)),
                tasks=tasks,
            ))

        logger.info(
            "Successfully parsed %d intervals from file_id=%d via %s",
            len(intervals), req.file_id, provider,
        )

        return ParseResponse(
            success=True,
            template_name=result.get("name", "Регламент ТО"),
            description=result.get("description", ""),
            intervals=intervals,
            raw_text_preview=result.get("raw_text_preview", "")[:500],
        )

    except AIAgentError as e:
        logger.warning("AI agent error: %s", str(e))
        return ParseResponse(success=False, error=str(e))
    except Exception as e:
        logger.error("Unexpected error in AI parse: %s", str(e), exc_info=True)
        return ParseResponse(
            success=False,
            error=f"Непредвиденная ошибка: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Sanek Chat — AI assistant endpoints
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    session_id: str = ""
    message: str


class ChatAction(BaseModel):
    tool: str = ""
    args: dict = {}
    result: dict | None = None


class PendingAction(BaseModel):
    tool: str = ""
    args: dict = {}
    description: str = ""


class ChatResponse(BaseModel):
    session_id: str = ""
    message: str = ""
    actions: list[ChatAction] = []
    pending_action: PendingAction | None = None


class ChatHistoryMessage(BaseModel):
    role: str
    content: str
    tool_calls: str | None = None
    tool_name: str | None = None
    created_at: str


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatHistoryMessage] = []


# In-memory pending actions per session
_pending_actions: dict[str, dict] = {}


@router.post("/chat", response_model=ChatResponse)
async def sanek_chat(req: ChatRequest):
    """
    Chat with Sanek AI assistant.
    Supports tool calling to interact with SCADA system.
    Dangerous commands require operator confirmation.
    """
    from services.sanek import SanekAssistant

    # Resolve provider
    provider = _get_active_provider()

    if not provider or provider not in VALID_PROVIDERS:
        return ChatResponse(
            message="⚠ AI провайдер не выбран.\n\n"
                    "Откройте «🤖 AI Провайдер» в боковом меню слева, "
                    "добавьте API ключ и активируйте провайдера.",
        )

    api_key = _get_api_key(provider)
    model = _get_model(provider)
    label = {"openai": "OpenAI", "claude": "Claude", "gemini": "Gemini", "grok": "Grok"}.get(provider, provider)

    if not api_key:
        return ChatResponse(
            message=f"🔑 API ключ для {label} не настроен.\n\n"
                    f"Откройте «🤖 AI Провайдер» в боковом меню, "
                    f"введите ключ для {label} и нажмите «Сохранить».",
        )

    # Session management
    session_id = req.session_id or str(uuid.uuid4())[:8]

    # Save user message to DB
    try:
        async with async_session() as session:
            session.add(AiChatMessage(
                session_id=session_id,
                role="user",
                content=req.message,
            ))
            await session.commit()
    except Exception as e:
        logger.warning("Could not save user message: %s", e)

    # Load conversation history from DB
    messages = []
    try:
        async with async_session() as session:
            result = await session.execute(
                select(AiChatMessage)
                .where(AiChatMessage.session_id == session_id)
                .order_by(AiChatMessage.created_at)
                .limit(50)
            )
            rows = result.scalars().all()
            for row in rows:
                if row.role in ("user", "assistant"):
                    messages.append({"role": row.role, "content": row.content})
    except Exception as e:
        logger.warning("Could not load chat history: %s", e)
        messages = [{"role": "user", "content": req.message}]

    # Check for pending action
    pending = _pending_actions.pop(session_id, None)

    try:
        assistant = SanekAssistant(
            provider=provider,
            api_key=api_key,
            model=model,
        )
        result = await assistant.chat(messages=messages, pending_action=pending)
    except Exception as e:
        logger.error("Sanek chat error: %s", e, exc_info=True)
        return ChatResponse(
            session_id=session_id,
            message=f"Ошибка: {str(e)}",
        )

    # Save assistant reply to DB
    assistant_msg = result.get("message", "")
    pending_action = result.get("pending_action")

    try:
        async with async_session() as session:
            session.add(AiChatMessage(
                session_id=session_id,
                role="assistant",
                content=assistant_msg,
                tool_calls=json.dumps(result.get("actions", []), ensure_ascii=False, default=str) if result.get("actions") else None,
            ))
            await session.commit()
    except Exception as e:
        logger.warning("Could not save assistant message: %s", e)

    # Store pending action for next turn
    if pending_action:
        _pending_actions[session_id] = pending_action

    return ChatResponse(
        session_id=session_id,
        message=assistant_msg,
        actions=[ChatAction(**a) for a in result.get("actions", [])],
        pending_action=PendingAction(**pending_action) if pending_action else None,
    )


@router.get("/chat/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str = Query(..., description="Chat session ID"),
    limit: int = Query(50, ge=1, le=200),
):
    """Get chat history for a session."""
    try:
        async with async_session() as session:
            result = await session.execute(
                select(AiChatMessage)
                .where(AiChatMessage.session_id == session_id)
                .order_by(AiChatMessage.created_at)
                .limit(limit)
            )
            rows = result.scalars().all()
    except Exception as e:
        logger.error("Error loading chat history: %s", e)
        return ChatHistoryResponse(session_id=session_id)

    messages = [
        ChatHistoryMessage(
            role=row.role,
            content=row.content,
            tool_calls=row.tool_calls,
            tool_name=row.tool_name,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]

    return ChatHistoryResponse(session_id=session_id, messages=messages)


@router.get("/chat/sessions")
async def list_chat_sessions(limit: int = Query(20, ge=1, le=100)):
    """List recent chat sessions."""
    from sqlalchemy import distinct, desc
    try:
        async with async_session() as session:
            # Get distinct session_ids ordered by latest message
            result = await session.execute(
                select(
                    AiChatMessage.session_id,
                    sa.func.max(AiChatMessage.created_at).label("last_at"),
                    sa.func.count(AiChatMessage.id).label("msg_count"),
                )
                .group_by(AiChatMessage.session_id)
                .order_by(desc("last_at"))
                .limit(limit)
            )
            rows = result.all()
    except Exception as e:
        logger.error("Error listing chat sessions: %s", e)
        return {"sessions": []}

    sessions = [
        {
            "session_id": row.session_id,
            "last_at": row.last_at.isoformat() if row.last_at else "",
            "message_count": row.msg_count,
        }
        for row in rows
    ]
    return {"sessions": sessions}
