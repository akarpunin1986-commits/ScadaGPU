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

    # Phase 6 — Metrics persistence & disk management
    METRICS_WRITER_BATCH_SIZE: int = 50
    METRICS_WRITER_FLUSH_INTERVAL: float = 5.0
    DISK_CHECK_INTERVAL: int = 300          # seconds (5 min)
    DISK_MAX_DB_SIZE_MB: int = 10240        # 10 GB default
    DISK_CLEANUP_THRESHOLD_PCT: float = 80  # start FIFO at 80%
    DISK_CLEANUP_BATCH_SIZE: int = 10000

    # Bitrix24 integration module (Phase 7)
    BITRIX24_ENABLED: bool = False
    BITRIX24_WEBHOOK_URL: str = ""
    BITRIX24_GROUP_ID: int = 46
    BITRIX24_IBLOCK_ID: int = 68
    BITRIX24_IBLOCK_TYPE_ID: str = "lists"
    BITRIX24_RATE_LIMIT: float = 2.0            # requests per second
    BITRIX24_SYNC_INTERVAL: int = 3600          # equipment sync every 1 hour
    BITRIX24_TASK_CHECK_INTERVAL: int = 300     # check task status every 5 min
    BITRIX24_FALLBACK_RESPONSIBLE_ID: int = 102 # webhook user (Карпунин А.)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
