"""Boot-time database connect retry (A.7).

mistilteinn does not own its Postgres container any more (DESIGN §A3), so there is no
`depends_on: db` to enforce startup ordering. The app must therefore tolerate a database
that is not up *yet*, and must still fail loudly rather than serve traffic without one.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from app.database import DatabaseUnavailableError, wait_for_db


def _failing_engine(failures: int, error: Exception | None = None) -> MagicMock:
    """An engine whose `connect()` raises `error` `failures` times, then succeeds."""
    calls = {"n": 0}
    error = error or OperationalError("SELECT 1", {}, Exception("connection refused"))

    def connect() -> MagicMock:
        calls["n"] += 1
        cm = MagicMock()
        if calls["n"] <= failures:
            cm.__aenter__ = AsyncMock(side_effect=error)
        else:
            conn = MagicMock()
            conn.execute = AsyncMock(return_value=None)
            cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    engine = MagicMock()
    engine.connect = connect
    engine.attempts_made = calls
    return engine


class _Sleeps:
    """Records the delays it was asked to wait, without waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


async def test_connects_first_try_without_sleeping():
    sleeps = _Sleeps()
    engine = _failing_engine(failures=0)

    attempts = await wait_for_db(engine, attempts=5, base_delay=0.5, max_delay=8.0, sleep=sleeps)

    assert attempts == 1
    assert sleeps.delays == []


async def test_retries_until_the_database_answers():
    sleeps = _Sleeps()
    engine = _failing_engine(failures=3)

    attempts = await wait_for_db(engine, attempts=10, base_delay=0.5, max_delay=8.0, sleep=sleeps)

    assert attempts == 4
    assert sleeps.delays == [0.5, 1.0, 2.0]


async def test_backoff_is_capped_at_max_delay():
    sleeps = _Sleeps()
    engine = _failing_engine(failures=5)

    await wait_for_db(engine, attempts=10, base_delay=1.0, max_delay=4.0, sleep=sleeps)

    assert sleeps.delays == [1.0, 2.0, 4.0, 4.0, 4.0]


async def test_exhausting_the_budget_raises_rather_than_returning():
    """The whole point: never fall through to a half-started app."""
    sleeps = _Sleeps()
    engine = _failing_engine(failures=99)

    with pytest.raises(DatabaseUnavailableError) as excinfo:
        await wait_for_db(engine, attempts=3, base_delay=0.5, max_delay=8.0, sleep=sleeps)

    # Budget exhausted means 3 attempts and only 2 waits — no pointless final sleep.
    assert engine.attempts_made["n"] == 3
    assert sleeps.delays == [0.5, 1.0]
    # The cause survives, so the log says *why* the database was unreachable.
    assert isinstance(excinfo.value.__cause__, OperationalError)


async def test_rejects_a_nonsensical_budget():
    with pytest.raises(ValueError, match="attempts"):
        await wait_for_db(_failing_engine(failures=0), attempts=0)


async def test_retries_a_raw_socket_error_too():
    """asyncpg raises ConnectionRefusedError unwrapped — SQLAlchemy never sees a refused TCP
    connect, so a `SQLAlchemyError`-only clause would let it escape and skip every retry.
    Caught in the wild on 2026-08-21 while verifying A.7 against a bad port.
    """
    sleeps = _Sleeps()
    engine = _failing_engine(failures=2, error=ConnectionRefusedError(111, "Connect call failed"))

    attempts = await wait_for_db(engine, attempts=5, base_delay=0.5, max_delay=8.0, sleep=sleeps)

    assert attempts == 3
    assert sleeps.delays == [0.5, 1.0]


async def test_dns_failure_is_retryable():
    import socket

    sleeps = _Sleeps()
    engine = _failing_engine(failures=1, error=socket.gaierror("Name or service not known"))

    assert await wait_for_db(engine, attempts=3, base_delay=0.25, max_delay=8.0, sleep=sleeps) == 2
