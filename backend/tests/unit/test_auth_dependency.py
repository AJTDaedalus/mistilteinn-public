"""Unit tests for the get_current_user FastAPI dependency."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user
from app.models.enums import UserStatus
from app.models.user import User


def _make_user(status: UserStatus = UserStatus.APPROVED) -> User:
    user = MagicMock(spec=User)
    user.email = "test@example.com"
    user.status = status
    user.id = "some-uuid"
    return user


def _make_session(user_id: str = "some-uuid") -> MagicMock:
    s = MagicMock()
    s.user_id = user_id
    s.expires_at = datetime.now(UTC) + timedelta(hours=1)
    return s


def _make_protected_app() -> FastAPI:
    """Minimal app with one auth-protected route for testing."""
    app = FastAPI()

    @app.get("/protected", response_model=None)
    async def protected(user: User = Depends(get_current_user)):  # noqa: B008
        return {"email": user.email}

    return app


@pytest.fixture
def app():
    return _make_protected_app()


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _auth_header(raw_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


class TestGetCurrentUser:
    async def test_approved_user_returns_200(self, client: AsyncClient):
        """An approved user with a valid session token gets through."""
        approved = _make_user(UserStatus.APPROVED)
        mock_session = _make_session(user_id="some-uuid")

        with (
            patch("app.dependencies.SessionRepository") as mock_session_repo_cls,
            patch("app.dependencies.UserRepository") as mock_user_repo_cls,
        ):
            session_repo = AsyncMock()
            session_repo.get_by_token_hash.return_value = mock_session
            session_repo.touch = AsyncMock()
            mock_session_repo_cls.return_value = session_repo

            user_repo = AsyncMock()
            user_repo.get_by_id.return_value = approved
            mock_user_repo_cls.return_value = user_repo

            resp = await client.get("/protected", headers=_auth_header("a" * 64))

        assert resp.status_code == 200
        assert resp.json()["email"] == "test@example.com"

    async def test_absent_token_returns_401(self, client: AsyncClient):
        """No Authorization header → 401."""
        resp = await client.get("/protected")
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client: AsyncClient):
        """A token with no matching session → 401."""
        with patch("app.dependencies.SessionRepository") as mock_session_repo_cls:
            session_repo = AsyncMock()
            session_repo.get_by_token_hash.return_value = None
            mock_session_repo_cls.return_value = session_repo

            resp = await client.get("/protected", headers=_auth_header("deadbeef" * 8))

        assert resp.status_code == 401

    async def test_pending_user_returns_403(self, client: AsyncClient):
        """A pending (not yet approved) user is denied."""
        pending = _make_user(UserStatus.PENDING)
        mock_session = _make_session()

        with (
            patch("app.dependencies.SessionRepository") as mock_session_repo_cls,
            patch("app.dependencies.UserRepository") as mock_user_repo_cls,
        ):
            session_repo = AsyncMock()
            session_repo.get_by_token_hash.return_value = mock_session
            session_repo.touch = AsyncMock()
            mock_session_repo_cls.return_value = session_repo

            user_repo = AsyncMock()
            user_repo.get_by_id.return_value = pending
            mock_user_repo_cls.return_value = user_repo

            resp = await client.get("/protected", headers=_auth_header("anytoken"))

        assert resp.status_code == 403

    async def test_disabled_user_returns_403(self, client: AsyncClient):
        """A disabled user is denied even with a valid session token."""
        disabled = _make_user(UserStatus.DISABLED)
        mock_session = _make_session()

        with (
            patch("app.dependencies.SessionRepository") as mock_session_repo_cls,
            patch("app.dependencies.UserRepository") as mock_user_repo_cls,
        ):
            session_repo = AsyncMock()
            session_repo.get_by_token_hash.return_value = mock_session
            session_repo.touch = AsyncMock()
            mock_session_repo_cls.return_value = session_repo

            user_repo = AsyncMock()
            user_repo.get_by_id.return_value = disabled
            mock_user_repo_cls.return_value = user_repo

            resp = await client.get("/protected", headers=_auth_header("anytoken"))

        assert resp.status_code == 403

    async def test_token_is_hashed_before_lookup(self, client: AsyncClient):
        """The raw bearer token must never be compared directly — only its SHA-256."""
        raw_token = "rawtoken123"  # noqa: S105
        captured: dict = {}

        async def spy_get_by_token_hash(token_hash: str):
            captured["looked_up"] = token_hash

        with patch("app.dependencies.SessionRepository") as mock_session_repo_cls:
            session_repo = AsyncMock()
            session_repo.get_by_token_hash.side_effect = spy_get_by_token_hash
            mock_session_repo_cls.return_value = session_repo

            await client.get("/protected", headers=_auth_header(raw_token))

        expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        assert captured.get("looked_up") == expected_hash
        assert captured.get("looked_up") != raw_token
