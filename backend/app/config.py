from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://scada:scada_dev_2026@postgres:5432/scada"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    CHROMADB_URL: str = "http://chromadb:8000"
    CHROMADB_COLLECTION: str = "knowledge_base"
    SANEK_RAG_ENABLED: bool = True
    SANEK_RAG_TOP_K: int = 5
    SANEK_RAG_MIN_SCORE: float = 0.3

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

    # Sanek AI version
    SANEK_VERSION: str = "v4"

    # SanekAgent — autonomous AI incident analysis
    SANEK_AGENT_ENABLED: bool = False
    SANEK_AGENT_DEBOUNCE: int = 60          # seconds to wait before analysis (collect related events)
    SANEK_AGENT_COOLDOWN: int = 300         # seconds cooldown per device after analysis
    SANEK_AGENT_LLM_TIMEOUT: int = 60      # LLM request timeout

    # Auth / JWT
    JWT_SECRET_KEY: str = "change-me"
    JWT_EXPIRE_HOURS: int = 0               # 0 = never expire
    JWT_ALGORITHM: str = "HS256"

    # Bitrix24 OAuth (user login via Б24)
    BITRIX24_PORTAL: str = "bricks-trade.bitrix24.ru"
    BITRIX24_OAUTH_CLIENT_ID: str = "local.69bd49b8e01a24.49645433"
    BITRIX24_OAUTH_CLIENT_SECRET: str = ""
    BITRIX24_OAUTH_REDIRECT_URI: str = "http://192.168.30.130/api/auth/oauth/callback"
    BITRIX24_QR_OAUTH_REDIRECT_URI: str = "http://192.168.30.130/api/auth/qr/oauth-callback"
    BITRIX24_BOT_ID: int = 0

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

    # Auth code settings
    AUTH_CODE_TTL_SECONDS: int = 300
    AUTH_CODE_RATE_LIMIT_SECONDS: int = 60
    AUTH_MAX_ATTEMPTS: int = 5

    # Bitrix24 bot
    BITRIX24_BOT_ACCESS_TOKEN: str = ""
    BITRIX24_BOT_HANDLER_URL: str = ""
    BITRIX24_SANEK_WEBHOOK_URL: str = ""

    # Task manager
    TM_DEDUP_WINDOW_DAYS: int = 7
    TM_ESCALATION_COOLDOWN_HOURS: int = 24
    TM_HOURS_MONITOR_INTERVAL: int = 300
    TM_LEARNING_INTERVAL: int = 3600
    TM_OFFLINE_DRAIN_INTERVAL: int = 60
    TM_SCHEDULE_MONITOR_INTERVAL: int = 300
    TM_SUPERVISOR_INTERVAL: int = 60

    # Maintenance
    MAINT_ALERT_COOLDOWN_HOURS: int = 24
    MAINT_ALERT_INTERVAL: int = 300
    MAINT_DAYS_TASK: int = 7
    MAINT_DAYS_WARN: int = 14
    MAINT_HOURS_TASK: int = 50
    MAINT_HOURS_WARN: int = 100
    MAINT_VALUE_POLL_INTERVAL: int = 60

    # Deadline / escalation
    DEADLINE_CRITICAL_HOURS: int = 4
    DEADLINE_HIGH_HOURS: int = 24
    DEADLINE_NORMAL_DAYS: int = 7
    ESCALATION_SOFT_REMINDER_HOURS: int = 12
    ESCALATION_HARD_HOURS: int = 48

    # Reports
    REPORTS_DIR: str = "/opt/scada/reports"

    # Quality
    QUALITY_METRICS_SNAPSHOT_DELAY_HOURS: int = 1
    QUALITY_VISION_ENABLED: bool = False

    # Equipment
    EQUIPMENT_DEVICE_MAP: str = "{}"

    # Offline
    OFFLINE_EXTERNAL_TIMEOUT: int = 300

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
