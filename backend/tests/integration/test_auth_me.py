"""Integration tests for GET /auth/me."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.models.enums import UserStatus
from app.models.session import Session
from app.models.user import User
from app.services.password import hash_password

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

_TEST_PASSWORD = "alpha-test-password-1234"  # noqa: S105
_SESSION_TTL_SECONDS = 30 * 24 * 3600


async def _create_user(
    db_session: AsyncSession,
    email: str,
    status: UserStatus,
) -> tuple[User, str]:
    user = User(
        email=email,
        label="Test User",
        password_hash=hash_password(_TEST_PASSWORD),
        status=status,
    )
    db_session.add(user)
    await db_session.flush()

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

    return user, raw_token


class TestGetMe:
    async def test_no_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer notarealtoken"},
        )
        assert resp.status_code == 401

    async def test_pending_user_returns_200_with_pending_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, raw_token = await _create_user(db_session, "pending@example.com", UserStatus.PENDING)
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["email"] == "pending@example.com"

    async def test_approved_user_returns_200_with_approved_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, raw_token = await _create_user(db_session, "approved@example.com", UserStatus.APPROVED)
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["email"] == "approved@example.com"

    async def test_disabled_user_returns_401(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, raw_token = await _create_user(db_session, "disabled@example.com", UserStatus.DISABLED)
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert resp.status_code == 401
