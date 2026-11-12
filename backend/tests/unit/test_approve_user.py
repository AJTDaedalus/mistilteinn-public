"""Unit tests for scripts/approve_user.py."""

from __future__ import annotations

import datetime
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import UserStatus
from app.models.user import User


def _make_user(
    email: str, status: UserStatus = UserStatus.PENDING, *, verified: bool = True
) -> User:
    user = MagicMock(spec=User)
    user.email = email
    user.status = status
    user.approved_at = None
    user.email_verified_at = datetime.datetime.now(datetime.UTC) if verified else None
    return user


def _patched(repo):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session, (
        patch("scripts.approve_user.create_async_engine", return_value=AsyncMock()),
        patch(
            "scripts.approve_user.async_sessionmaker",
            return_value=MagicMock(return_value=mock_session),
        ),
        patch("scripts.approve_user.UserRepository", return_value=repo),
    )


class TestApproveRefusesAnUnverifiedAddress:
    """Security audit F1: approving an unverified account approves whoever registered first."""

    async def test_unverified_user_is_refused(self, capsys):
        user = _make_user("u@example.com", verified=False)
        repo = AsyncMock()
        repo.get_by_email.return_value = user
        session, patches = _patched(repo)

        with patches[0], patches[1], patches[2]:
            from scripts.approve_user import approve_user

            with pytest.raises(SystemExit) as exc_info:
                await approve_user("u@example.com")

        assert exc_info.value.code == 1
        assert user.status == UserStatus.PENDING
        session.commit.assert_not_awaited()
        assert "not verified" in capsys.readouterr().err

    async def test_the_flag_approves_an_unverified_user_anyway(self):
        user = _make_user("u@example.com", verified=False)
        repo = AsyncMock()
        repo.get_by_email.return_value = user
        session, patches = _patched(repo)

        with patches[0], patches[1], patches[2]:
            from scripts.approve_user import approve_user

            await approve_user("u@example.com", allow_unverified=True)

        assert user.status == UserStatus.APPROVED
        session.commit.assert_awaited_once()

    def test_main_passes_the_flag(self):
        with (
            patch.object(sys, "argv", ["approve_user", "u@example.com", "--allow-unverified"]),
            patch("scripts.approve_user.approve_user", new=MagicMock()) as fake,
            patch("scripts.approve_user.asyncio.run"),
        ):
            from scripts.approve_user import main

            main()

        fake.assert_called_once_with("u@example.com", allow_unverified=True)


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
