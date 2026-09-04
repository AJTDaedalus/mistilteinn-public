from __future__ import annotations

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

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
from app.dependencies import get_email_sender_dep, get_turnstile
from app.main import create_app
from app.models.base import Base
from app.models.enums import UserStatus
from app.models.session import Session
from app.models.user import User
from app.services.email.recording import RecordingEmailSender
from app.services.password import hash_password

_TEST_PASSWORD = "alpha-test-password-1234"  # noqa: S105
_SESSION_TTL_SECONDS = 30 * 24 * 3600

# Default deliberately names mistilteinn_test, not fairy_test. The two projects
# share one Postgres server (DESIGN §A3), and these fixtures create and drop
# tables — pointed at fairy_test they would rewrite the *other* repo's schema.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://mistilteinn:mistilteinn_dev@localhost:5432/mistilteinn_test",
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
    app.dependency_overrides[get_settings] = get_test_settings

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def signup_client(db_session):
    """A client with overridable settings and a mail sender that records instead of sending.

    Returns `(make, mailbox)`. `make(**overrides)` builds a client whose app sees
    `Settings(**overrides)`, so a test can flip `AUTO_APPROVE_ON_VERIFY` or
    `REGISTRATION_OPEN` without touching the process environment — which is the only way to
    test a flag whose whole purpose is being flipped under pressure.

    Every message the app would have sent lands in `mailbox.sent`. **No network**: the unit
    lane blocks `socket.connect` outright, and this keeps the integration lane honest too.

    Pass `email_sender=` or `turnstile=` to substitute a different fake for one client. With
    no `turnstile=`, the real verifier runs with an empty secret and therefore passes — the
    same no-key path a fresh clone takes.
    """
    mailbox = RecordingEmailSender()
    stack: list = []

    def make(email_sender=None, turnstile=None, **settings_overrides) -> AsyncClient:
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: Settings(
            DATABASE_URL=TEST_DATABASE_URL, TESTING=True, **settings_overrides,
        )
        app.dependency_overrides[get_email_sender_dep] = lambda: email_sender or mailbox
        if turnstile is not None:
            app.dependency_overrides[get_turnstile] = lambda: turnstile

        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        stack.append(client)
        return client

    yield make, mailbox

    for client in stack:
        await client.aclose()


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
