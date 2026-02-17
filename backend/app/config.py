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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
