"""Application settings loaded from environment/`.env` via pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration: DB connection, CORS, and API prefix."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://mistilteinn:mistilteinn_dev@localhost:5432/mistilteinn"
    TESTING: bool = False
    LOG_LEVEL: str = "info"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:4200"]
    ENV: str = "local"  # "local" | "production"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached `Settings` instance."""
    return Settings()


settings = get_settings()
