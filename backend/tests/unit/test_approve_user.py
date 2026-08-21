"""Unit tests for scripts/approve_user.py."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import UserStatus
from app.models.user import User


def _make_user(email: str, status: UserStatus = UserStatus.PENDING) -> User:
    user = MagicMock(spec=User)
    user.email = email
    user.status = status
    user.approved_at = None
    return user


class TestApproveUser:
    async def test_approves_pending_user(self):
        user = _make_user("a@example.com", UserStatus.PENDING)

        mock_repo = AsyncMock()
        mock_repo.get_by_email.return_value = user

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_maker = MagicMock(return_value=mock_session)
        mock_engine = AsyncMock()

        with (
            patch("scripts.approve_user.create_async_engine", return_value=mock_engine),
            patch("scripts.approve_user.async_sessionmaker", return_value=mock_session_maker),
            patch("scripts.approve_user.UserRepository", return_value=mock_repo),
        ):
            from scripts.approve_user import approve_user

            await approve_user("a@example.com")

        assert user.status == UserStatus.APPROVED
        assert user.approved_at is not None
        mock_session.commit.assert_awaited_once()

    async def test_already_approved_is_idempotent(self, capsys):
        user = _make_user("b@example.com", UserStatus.APPROVED)

        mock_repo = AsyncMock()
        mock_repo.get_by_email.return_value = user

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_maker = MagicMock(return_value=mock_session)
        mock_engine = AsyncMock()

        with (
            patch("scripts.approve_user.create_async_engine", return_value=mock_engine),
            patch("scripts.approve_user.async_sessionmaker", return_value=mock_session_maker),
            patch("scripts.approve_user.UserRepository", return_value=mock_repo),
        ):
            from scripts.approve_user import approve_user

            await approve_user("b@example.com")

        mock_session.commit.assert_not_awaited()
        out = capsys.readouterr().out
        assert "already approved" in out

    async def test_unknown_email_exits_with_error(self, capsys):
        mock_repo = AsyncMock()
        mock_repo.get_by_email.return_value = None

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_maker = MagicMock(return_value=mock_session)
        mock_engine = AsyncMock()

        with (
            patch("scripts.approve_user.create_async_engine", return_value=mock_engine),
            patch("scripts.approve_user.async_sessionmaker", return_value=mock_session_maker),
            patch("scripts.approve_user.UserRepository", return_value=mock_repo),
        ):
            from scripts.approve_user import approve_user

            with pytest.raises(SystemExit) as exc_info:
                await approve_user("nobody@example.com")

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "nobody@example.com" in err

    def test_main_exits_on_missing_arg(self, capsys):
        with patch.object(sys, "argv", ["approve_user"]):
            from scripts.approve_user import main

            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
