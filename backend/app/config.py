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

    # ── Open registration ────────────────────────────────────────────────────────
    # `DESIGN_open_registration.md`. **Every one of these must also appear in
    # `docker-compose.yml` and `docker-compose.prod.yml`**: the backend service enumerates its
    # environment and has no `env_file:`, so a setting that is not listed there is invisible to
    # the running app no matter what `.env` says — and invisible *silently*. That was the first
    # finding of fairy's pre-merge review, and
    # `tests/unit/test_settings_reach_the_container.py` is what stops it recurring here.

    #: `"console"` prints the mail (and the verification URL) to stdout; `"resend"` sends it.
    #: Console is the default so a fresh clone can run the whole signup flow with no API key
    #: and no network, which is also what every test uses.
    EMAIL_PROVIDER: str = "console"
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "Mistilteinn <noreply@mistilteinn.aetherus.dev>"

    #: Where the emailed link points. **Wrong here means every verification link in every
    #: message points at localhost**, which is exactly how this fails silently in production.
    PUBLIC_BASE_URL: str = "http://localhost:4201"

    #: The two flags, and the reason they are two rather than one (DESIGN §2, D-OR2).
    #:
    #: A bot wave still *creating* accounts is stopped by closing registration. A wave that has
    #: *already* created verified accounts is stopped by turning off auto-approval while real
    #: humans keep signing up and queueing. One switch forces a choice between over- and
    #: under-reacting.
    REGISTRATION_OPEN: bool = True
    AUTO_APPROVE_ON_VERIFY: bool = False

    #: 24h. OWASP says "as short as tolerable"; under a few hours produces real support load
    #: from overnight mail.
    EMAIL_VERIFY_TTL_SECONDS: int = 24 * 3600

    #: Empty secret disables Turnstile entirely, so local dev and tests need no key and no
    #: network. `EXPECTED_HOSTNAME` empty skips the hostname check — set it in production, or
    #: a token minted on any other site using this widget is accepted.
    TURNSTILE_SECRET_KEY: str = ""
    TURNSTILE_EXPECTED_HOSTNAME: str = ""

    #: Per-account caps (DESIGN §3.3), sized against the owner's real inventory — 2,369
    #: artifacts and 75 builds — rather than against fairy's disc numbers.
    MAX_ARTIFACTS_PER_USER: int = 10_000
    MAX_BUILDS_PER_USER: int = 500
    MAX_TEAMS_PER_USER: int = 200
    MAX_ROTATIONS_PER_USER: int = 500

    #: **Somebody else's servers.** `POST /rotations/import/link` is the only request-time
    #: outbound fetch in `app/`; open registration would make it a free proxy pointed at
    #: gcsim. Owner, 2026-09-02: *"I don't want to push our compute load to them."*
    MAX_GCSIM_IMPORTS_PER_DAY: int = 20

    #: A search writes a corpus row, so this bounds writes rather than compute — the search
    #: itself runs in the user's browser.
    MAX_SIM_RUNS_PER_DAY: int = 200

    #: Unverified PENDING accounts older than this are swept at startup, so bots that never
    #: click do not accumulate forever.
    UNVERIFIED_REAP_DAYS: int = 30


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached `Settings` instance."""
    return Settings()


settings = get_settings()
