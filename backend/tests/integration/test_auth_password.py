"""Integration tests: register / login / logout endpoints (password auth flow)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from app.models.enums import UserStatus
from app.models.session import Session
from app.models.user import User
from app.services.password import hash_password

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


# ── helpers ────────────────────────────────────────────────────────────────────

_DEFAULT_PASSWORD = "valid-test-password-1234"  # noqa: S105


async def _make_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    status: UserStatus = UserStatus.PENDING,
    password: str = _DEFAULT_PASSWORD,
) -> User:
    email = email or f"user_{secrets.token_hex(4)}@example.com"
    user = User(
        email=email,
        label="Test",
        password_hash=hash_password(password),
        status=status,
    )
    db.add(user)
    await db.flush()
    return user


async def _mint_session(db: AsyncSession, user: User) -> tuple[Session, str]:
    """Create a real session row and return (session, raw_token)."""
    from app.repositories.session import SessionRepository

    raw_token = secrets.token_hex(32)
    session_repo = SessionRepository(db)
    session = await session_repo.create_for_user(
        str(user.id), raw_token, ttl_seconds=30 * 24 * 3600
    )
    return session, raw_token


# ── POST /auth/register ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_happy_path(client: AsyncClient, db_session: AsyncSession) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "newuser@example.com", "password": _DEFAULT_PASSWORD},
        headers={"CF-Connecting-IP": "203.0.113.172"},
    )
    # 202, not 201: nothing is created synchronously any more — the row and the verification
    # email are both written behind the response.
    assert resp.status_code == 202
    assert resp.json() == {"status": "verification_sent"}

    # Verify user exists in DB with password_hash set and status PENDING
    from sqlalchemy import select

    result = await db_session.execute(select(User).where(User.email == "newuser@example.com"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.password_hash is not None
    assert user.status == UserStatus.PENDING


@pytest.mark.asyncio
async def test_register_does_not_disclose_that_an_email_is_known(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """**This test used to assert the opposite**, and the opposite was an oracle.

    Answering `409 "Email already registered."` let anyone with the URL test whether an
    address has an account here. That was acceptable while a human approved every signup;
    open registration makes it a free membership-checking API
    (`DESIGN_open_registration.md` §2). The duplicate path now returns the same 202 and the
    same body as a new address, and the account holder is told by email instead.

    Renamed rather than deleted: a reader looking for "why doesn't this 409?" should land on
    the answer, not on an absence.
    """
    await _make_user(db_session, email="dup@example.com")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": _DEFAULT_PASSWORD},
        headers={"CF-Connecting-IP": "203.0.113.171"},
    )
    assert resp.status_code == 202
    assert resp.json() == {"status": "verification_sent"}


@pytest.mark.asyncio
async def test_register_weak_password_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_password_equals_email_returns_422(client: AsyncClient) -> None:
    email = "sameaspassword@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": email},
    )
    assert resp.status_code == 422


# ── POST /auth/login ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_approved_user_returns_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, status=UserStatus.APPROVED)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": _DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "expires_at" in data
    assert len(data["token"]) == 64  # secrets.token_hex(32) = 64 hex chars

    # Verify session row exists in DB
    from sqlalchemy import select

    from app.models.session import Session as SessionModel

    result = await db_session.execute(
        select(SessionModel).where(SessionModel.user_id == str(user.id))
    )
    sessions = result.scalars().all()
    assert len(sessions) == 1


@pytest.mark.asyncio
async def test_login_pending_user_returns_403(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, status=UserStatus.PENDING)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": _DEFAULT_PASSWORD},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["status"] == "pending"


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, status=UserStatus.APPROVED)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrong-password-9999"},
    )
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_missing_email_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": _DEFAULT_PASSWORD},
    )
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_disabled_user_returns_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, status=UserStatus.DISABLED)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": _DEFAULT_PASSWORD},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_rate_limit_triggers_after_ten_attempts(
    client: AsyncClient,
) -> None:
    """Per-email limiter (10/hour) blocks the 11th request for the same email."""
    email = f"ratelimit_{secrets.token_hex(8)}@example.com"
    payload = {"email": email, "password": "wrong-password-5555"}
    hit_429 = False
    for _ in range(12):
        resp = await client.post("/api/v1/auth/login", json=payload)
        if resp.status_code == 429:
            hit_429 = True
            break
    assert hit_429, "Expected 429 after 10 failed login attempts for the same email"


# ── POST /auth/logout ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_deletes_session_and_subsequent_me_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, status=UserStatus.APPROVED)
    _, raw_token = await _mint_session(db_session, user)
    auth = {"Authorization": f"Bearer {raw_token}"}

    # me works before logout
    resp = await client.get("/api/v1/auth/me", headers=auth)
    assert resp.status_code == 200

    # logout
    resp = await client.post("/api/v1/auth/logout", headers=auth)
    assert resp.status_code == 204

    # me fails after logout
    resp = await client.get("/api/v1/auth/me", headers=auth)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401


# ── GET /auth/me with expired session ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_with_expired_session_returns_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, status=UserStatus.APPROVED)
    raw_token = secrets.token_hex(32)

    import hashlib

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expired_session = Session(
        user_id=str(user.id),
        token_hash=token_hash,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        last_used_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db_session.add(expired_session)
    await db_session.flush()

    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert resp.status_code == 401
