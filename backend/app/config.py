from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://scada:scada_dev_2026@postgres:5432/scada"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # App
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Modbus Poller
    POLL_INTERVAL: float = 2.0
    MODBUS_TIMEOUT: float = 2.0
    MODBUS_RETRY_DELAY: float = 5.0

    # Demo mode
    DEMO_MODE: bool = False

    # Maintenance scheduler
    MAINTENANCE_CHECK_INTERVAL: int = 30

    # AI Agent (Phase 5 — maintenance manual parsing via LLM)
    # Active provider: openai, claude, gemini, grok
    AI_PROVIDER: str = "openai"
    AI_TIMEOUT: int = 120

    # Provider API keys (set via .env or /api/ai/config)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GROK_API_KEY: str = ""
    GROK_MODEL: str = "grok-3-mini"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
