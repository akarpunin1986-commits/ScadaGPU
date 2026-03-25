"""
САНЁК v4 — LLM Provider Factory.

Creates the appropriate AgentLoop based on AI_PROVIDER config.
GPT-5.4 primary, Claude Sonnet 4 fallback.
"""
from __future__ import annotations

import logging

from config import settings

logger = logging.getLogger("sanek_v4.llm")


def create_agent_loop(stream=True):
    """Create AgentLoop for the configured provider."""
    provider = settings.AI_PROVIDER.lower()

    if provider == "openai" and settings.OPENAI_API_KEY:
        logger.info("Using GPT-5.4 (%s) stream=%s", settings.OPENAI_MODEL, stream)
        from services.sanek_v4.llm.gpt54_loop import GPT54AgentLoop
        return GPT54AgentLoop(model=settings.OPENAI_MODEL, stream=stream)

    if provider == "claude" and settings.CLAUDE_API_KEY:
        logger.info("Using Claude (%s)", settings.CLAUDE_MODEL)
        from services.sanek_v4.loop import AgentLoop
        return AgentLoop(model=settings.CLAUDE_MODEL)

    # Auto-detect: try GPT first, then Claude
    if settings.OPENAI_API_KEY:
        logger.info("Auto-detected OpenAI key, using GPT-5.4")
        from services.sanek_v4.llm.gpt54_loop import GPT54AgentLoop
        return GPT54AgentLoop()

    if settings.CLAUDE_API_KEY:
        logger.info("Auto-detected Claude key, using Claude Sonnet")
        from services.sanek_v4.loop import AgentLoop
        return AgentLoop()

    raise RuntimeError("No LLM API key configured (OPENAI_API_KEY or CLAUDE_API_KEY)")


async def run_with_failover(user_message: str, **kwargs):
    """Run with automatic failover: GPT → Claude."""
    providers = []

    if settings.OPENAI_API_KEY:
        providers.append(("openai", settings.OPENAI_MODEL))
    if settings.CLAUDE_API_KEY:
        providers.append(("claude", settings.CLAUDE_MODEL))

    if not providers:
        yield {"type": "error", "message": "Нет настроенных LLM провайдеров"}
        return

    for i, (prov, model) in enumerate(providers):
        try:
            if prov == "openai":
                from services.sanek_v4.llm.gpt54_loop import GPT54AgentLoop
                loop = GPT54AgentLoop(model=model)
            else:
                from services.sanek_v4.loop import AgentLoop
                loop = AgentLoop(model=model)

            failed = False
            async for event in loop.run(user_message, **kwargs):
                if event.get("type") == "error" and i < len(providers) - 1:
                    # Try next provider
                    logger.warning("Provider %s failed, trying fallback", prov)
                    yield {"type": "thinking", "step": "forming_answer",
                           "detail": f"Переключаюсь на {providers[i + 1][0]}..."}
                    failed = True
                    break
                yield event

            if not failed:
                return  # Success

        except Exception as e:
            logger.warning("Provider %s error: %s", prov, e)
            if i < len(providers) - 1:
                yield {"type": "thinking", "step": "forming_answer",
                       "detail": f"Ошибка {prov}, переключаюсь на {providers[i + 1][0]}..."}
                continue
            yield {"type": "error",
                   "message": f"Все LLM провайдеры недоступны: {type(e).__name__}: {str(e)[:200]}"}
