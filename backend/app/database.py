"""Async SQLAlchemy engine, session factory, and the `get_db` FastAPI dependency."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session, committing on success and rolling back on error."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# asyncpg raises the socket error *raw* when the server refuses the connection or the
# host does not resolve — SQLAlchemy only wraps errors that reach it through the DBAPI,
# and a failed TCP connect never gets that far. Verified 2026-08-21 against a bad port:
# a plain ConnectionRefusedError escaped a `except SQLAlchemyError` clause, which would
# have defeated the whole retry. OSError covers ConnectionRefusedError, socket.gaierror,
# and TimeoutError alike.
_RETRYABLE = (SQLAlchemyError, OSError)


class DatabaseUnavailableError(RuntimeError):
    """The database was still unreachable after the whole boot-connect budget."""


async def wait_for_db(
    target: AsyncEngine | None = None,
    *,
    attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Block until the database answers `SELECT 1`; raise once the budget is spent.

    mistilteinn shares the fairy stack's Postgres and therefore has no `depends_on: db`
    to order startup for it (DESIGN §A3). Boot can legitimately race the database, so the
    first connect retries with exponential backoff — but a database that never arrives is
    a hard failure, never a degraded start. Raising here aborts the FastAPI lifespan, so
    the process exits instead of serving requests it cannot answer.

    Returns the attempt number that succeeded (1 when the first try worked).
    """
    eng = engine if target is None else target
    attempts = settings.DB_CONNECT_ATTEMPTS if attempts is None else attempts
    base_delay = settings.DB_CONNECT_BASE_DELAY if base_delay is None else base_delay
    max_delay = settings.DB_CONNECT_MAX_DELAY if max_delay is None else max_delay
    if attempts < 1:
        raise ValueError(f"attempts must be at least 1, got {attempts}")

    delay = base_delay
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with eng.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except _RETRYABLE as exc:
            last_error = exc
            if attempt == attempts:
                break
            logger.warning(
                "Database unreachable (attempt %d/%d): %s — retrying in %.1fs",
                attempt,
                attempts,
                exc.__class__.__name__,
                delay,
            )
            await sleep(delay)
            delay = min(delay * 2, max_delay)
        else:
            if attempt > 1:
                logger.info("Database reachable after %d attempts", attempt)
            return attempt

    raise DatabaseUnavailableError(
        f"Database unreachable after {attempts} attempts; giving up rather than "
        f"starting without it. Check that the shared Postgres is up and that "
        f"DATABASE_URL points at it.",
    ) from last_error
