"""Common LLM utilities extracted from legacy sanek.py v2."""

PROVIDER_LABELS = {"openai": "OpenAI", "claude": "Claude", "gemini": "Gemini", "grok": "Grok"}


def format_llm_error(provider: str, error, status_code: int = 0) -> str:
    """Format LLM provider errors into human-readable Russian messages."""
    label = PROVIDER_LABELS.get(provider, provider)
    err_str = str(error).lower()

    if status_code in (401, 403) or any(kw in err_str for kw in (
        "401", "403", "unauthorized", "authentication", "invalid api key",
        "incorrect api key", "invalid x-api-key", "permission denied",
    )):
        return (
            f"🔑 Ошибка авторизации: API ключ провайдера {label} недействителен."
        )

    if status_code == 429 or any(kw in err_str for kw in ("429", "rate limit", "too many requests", "quota")):
        return f"⚡ Лимит запросов: провайдер {label} ограничил частоту."

    if any(kw in err_str for kw in ("timeout", "timed out", "timeouterror")):
        return f"⏱ Превышено время ожидания: {label} не ответил."

    if any(kw in err_str for kw in ("connecterror", "connectionerror", "connection refused", "unreachable")):
        return f"🌐 Нет связи с {label} API."

    if status_code >= 500 or any(kw in err_str for kw in ("500", "502", "503", "504", "internal server error")):
        return f"🔧 Сервер {label} временно недоступен."

    if any(kw in err_str for kw in ("model not found", "model_not_found", "does not exist")):
        return f"📋 Модель не найдена у {label}."

    short_err = str(error)[:200]
    return f"❌ Ошибка {label}: {short_err}"


def format_http_error(provider: str, status_code: int, error_body: str) -> str:
    """Format HTTP status errors."""
    return format_llm_error(provider, error_body, status_code=status_code)
