from __future__ import annotations

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from app.config import Settings, get_settings
from app.database import get_db
from app.main import create_app
from app.models.base import Base
from app.models.enums import UserStatus
from app.models.session import Session
from app.models.user import User
from app.services.password import hash_password

_TEST_PASSWORD = "alpha-test-password-1234"  # noqa: S105
_SESSION_TTL_SECONDS = 30 * 24 * 3600

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://fairy:fairy_dev@localhost:5432/fairy_test",
)


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional session that rolls back after each test.

    Binds the session to an existing connection with an outer transaction,
    so all operations (including flushes) are contained and rolled back.
    """
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


def get_test_settings() -> Settings:
    return Settings(
        DATABASE_URL=TEST_DATABASE_URL,
        TESTING=True,
    )


@pytest.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    app.state.job_runner = MagicMock()
    app.dependency_overrides[get_settings] = get_test_settings

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


async def make_session_for(user: User, db_session: AsyncSession) -> str:
    """Mint a Session row for *user* and return the raw bearer token."""
    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(UTC)
    session = Session(
        user_id=str(user.id),
        token_hash=token_hash,
        expires_at=now + timedelta(seconds=_SESSION_TTL_SECONDS),
        last_used_at=now,
    )
    db_session.add(session)
    await db_session.flush()
    return raw_token


@pytest.fixture
async def authed_user(db_session: AsyncSession) -> tuple[User, str]:
    """Create an approved user with a session; return (user, raw_token).

    Use this when a test needs the user's ID alongside an authed client
    (e.g. to seed data directly via a repo with owner_id).
    """
    user = User(
        email=f"authed_{secrets.token_hex(4)}@test.example",
        label="Test User",
        password_hash=hash_password(_TEST_PASSWORD),
        status=UserStatus.APPROVED,
    )
    db_session.add(user)
    await db_session.flush()
    raw_token = await make_session_for(user, db_session)
    return user, raw_token


@pytest.fixture
async def authed_client(
    db_session: AsyncSession,
    authed_user: tuple[User, str],
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient pre-configured with a valid approved-user bearer token."""
    _, raw_token = authed_user

    app = create_app()
    app.state.job_runner = MagicMock()
    app.dependency_overrides[get_settings] = get_test_settings

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {raw_token}"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
