"""
Phase 5 — AI agent API for parsing maintenance documents from Bitrix24 Disk.

Isolated module: separate router, no SCADA core dependencies.
Supports multiple LLM providers: OpenAI, Claude, Gemini, Grok.
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from config import settings

router = APIRouter(prefix="/api/ai", tags=["ai-agent"])
logger = logging.getLogger("scada.ai_parser")

# Runtime config overrides (set from frontend, not persisted to .env)
_runtime_config: dict = {}


def _get_active_provider() -> str:
    """Get active provider from runtime config or settings."""
    return _runtime_config.get("provider", settings.AI_PROVIDER)


def _get_api_key(provider: str) -> str:
    """Get API key for provider from runtime config or settings."""
    rt_keys = _runtime_config.get("keys", {})
    if provider in rt_keys:
        return rt_keys[provider]
    return {
        "openai": settings.OPENAI_API_KEY,
        "claude": settings.CLAUDE_API_KEY,
        "gemini": settings.GEMINI_API_KEY,
        "grok": settings.GROK_API_KEY,
    }.get(provider, "")


def _get_model(provider: str) -> str:
    """Get model for provider from runtime config or settings."""
    rt_models = _runtime_config.get("models", {})
    if provider in rt_models:
        return rt_models[provider]
    return {
        "openai": settings.OPENAI_MODEL,
        "claude": settings.CLAUDE_MODEL,
        "gemini": settings.GEMINI_MODEL,
        "grok": settings.GROK_MODEL,
    }.get(provider, "")


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


# ---------------------------------------------------------------------------
# Endpoints
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
    Set AI provider configuration at runtime.
    Saves API key and model for the specified provider.
    """
    global _runtime_config

    if req.provider not in ("openai", "claude", "gemini", "grok"):
        return ConfigResponse(
            success=False,
            message=f"Неизвестный провайдер: {req.provider}",
        )

    _runtime_config["provider"] = req.provider
    if "keys" not in _runtime_config:
        _runtime_config["keys"] = {}
    if "models" not in _runtime_config:
        _runtime_config["models"] = {}

    _runtime_config["keys"][req.provider] = req.api_key
    if req.model:
        _runtime_config["models"][req.provider] = req.model

    logger.info(
        "AI config updated: provider=%s, model=%s, key=%s...%s",
        req.provider,
        req.model or _get_model(req.provider),
        req.api_key[:8],
        req.api_key[-4:] if len(req.api_key) > 12 else "***",
    )
    return ConfigResponse(
        success=True,
        message=f"{req.provider} настроен, модель: {req.model or _get_model(req.provider)}",
    )


@router.post("/test", response_model=TestResponse)
async def test_ai_provider(req: TestRequest):
    """
    Test connection to an LLM provider with a simple request.
    """
    provider = req.provider
    api_key = req.api_key
    model = req.model

    if not api_key:
        return TestResponse(success=False, error="API ключ не указан")

    try:
        if provider == "openai":
            from openai import AsyncOpenAI, APIError
            client = AsyncOpenAI(api_key=api_key, timeout=15)
            resp = await client.chat.completions.create(
                model=model or "gpt-4o",
                messages=[{"role": "user", "content": "Ответь одним словом: работает"}],
                max_tokens=10,
            )
            text = resp.choices[0].message.content or ""
            return TestResponse(
                success=True,
                message=f"✅ OpenAI ({model}): {text.strip()}",
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
                        message=f"✅ Claude ({model}): {text.strip()}",
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
            # Grok uses OpenAI-compatible API at api.x.ai
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
                message=f"✅ Grok ({model}): {text.strip()}",
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
