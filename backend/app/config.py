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
    # Two dev origins, because there are two supported ways to reach the SPA:
    # 4201 is the compose-published port (host 4201 -> container 4200, remapped off
    # fairy's 4200 so both stacks can run at once), and 4200 is what a bare
    # `npm start` on the host still serves. Production overrides this via env.
    CORS_ORIGINS: list[str] = ["http://localhost:4201", "http://localhost:4200"]
    ENV: str = "local"  # "local" | "production"

    # Boot-time database connect retry (A.7). There is no `depends_on: db` any more —
    # the Postgres server belongs to the fairy compose stack (DESIGN §A3) — so the app
    # may legitimately start before the database is reachable. Defaults spend roughly
    # 47s (0.5, 1, 2, 4, then 8s ceilings) before failing loudly.
    DB_CONNECT_ATTEMPTS: int = 10
    DB_CONNECT_BASE_DELAY: float = 0.5
    DB_CONNECT_MAX_DELAY: float = 8.0


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached `Settings` instance."""
    return Settings()


settings = get_settings()
