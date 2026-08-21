"""Unit tests for the icons-directory guard in scripts/download_icons.py (issue #115).

Pure logic against a tmp_path, matching this directory's convention — no DB, no network.

The bug: `download_all_icons` called `os.makedirs` unguarded as its very first statement.
In a prod container the dev `/frontend_icons` bind mount does not exist, so `get_icons_dir`
falls back to `/frontend/public/icons`, `/` is not writable, and the `PermissionError`
took the whole seed down *after* the data had already committed. A correct seed then looks
exactly like a failed one.

These pin the degrade-to-warning contract: an unusable icons directory makes
`download_all_icons` a logged no-op that never reaches the database.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest

from scripts.download_icons import download_all_icons, ensure_icons_dir_writable


class TestEnsureIconsDirWritable:
    """The guard itself: True only when the directory exists and can be written to."""

    def test_creates_a_missing_directory(self, tmp_path) -> None:
        target = tmp_path / "icons"

        assert ensure_icons_dir_writable(str(target)) is True
        assert target.is_dir()

    def test_accepts_an_existing_writable_directory(self, tmp_path) -> None:
        assert ensure_icons_dir_writable(str(tmp_path)) is True

    def test_returns_false_when_the_directory_cannot_be_created(self, tmp_path, caplog) -> None:
        target = str(tmp_path / "icons")

        denied = PermissionError(13, "Permission denied")
        with patch("scripts.download_icons.os.makedirs", side_effect=denied):
            result = ensure_icons_dir_writable(target)

        assert result is False
        assert target in caplog.text

    def test_returns_false_on_any_oserror_not_just_permission(self, tmp_path, caplog) -> None:
        """`/frontend` is the observed case, but a read-only mount raises OSError too."""
        target = str(tmp_path / "icons")

        with patch("scripts.download_icons.os.makedirs", side_effect=OSError(30, "read-only")):
            assert ensure_icons_dir_writable(target) is False
        assert target in caplog.text

    @pytest.mark.skipif(os.getuid() == 0, reason="root ignores the write bit")
    def test_returns_false_when_the_directory_exists_but_is_not_writable(
        self, tmp_path, caplog
    ) -> None:
        target = tmp_path / "icons"
        target.mkdir()
        target.chmod(0o500)
        try:
            assert ensure_icons_dir_writable(str(target)) is False
        finally:
            target.chmod(0o700)
        assert str(target) in caplog.text


class TestDownloadAllIconsDegradesInsteadOfCrashing:
    """The seed must survive an unwritable icons dir — that is the whole point of #115."""

    @pytest.mark.asyncio
    async def test_returns_without_raising_and_never_touches_the_db(self) -> None:
        with (
            patch("scripts.download_icons.get_icons_dir", return_value="/frontend/public/icons"),
            patch("scripts.download_icons.ensure_icons_dir_writable", return_value=False),
            patch("scripts.download_icons.create_async_engine") as mock_engine,
        ):
            await download_all_icons()

        mock_engine.assert_not_called()


class TestPerFileFailuresDoNotEscape:
    """The dir guard is not enough on its own: the *write* must not raise either.

    `seed_db` imports and awaits `download_all_icons` directly -- it does not go
    through `run_download_icons`, which is the only place with a blanket
    `except Exception`. So anything that escapes a per-icon task propagates out
    of `_finish` and fails a seed whose data has already committed, which is the
    exact failure #115 is about.
    """

    @pytest.mark.asyncio
    async def test_write_oserror_is_logged_and_counted_as_a_miss(self, tmp_path, caplog) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from scripts.download_icons import download_one_icon

        resp = MagicMock(status_code=200, content=b"webp-bytes")
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)

        with patch("scripts.download_icons.open", side_effect=OSError(28, "No space left")):
            result = await download_one_icon(
                client, "UI_Icon_Probe", str(tmp_path), asyncio.Semaphore(1)
            )

        assert result is False
        assert "UI_Icon_Probe" in caplog.text

    @pytest.mark.asyncio
    async def test_a_raising_task_does_not_propagate_out_of_download_all_icons(
        self, tmp_path, caplog
    ) -> None:
        """`asyncio.gather(..., return_exceptions=True)` is what makes this hold."""
        with (
            patch("scripts.download_icons.get_icons_dir", return_value=str(tmp_path)),
            patch("scripts.download_icons._icon_basenames_from_db", return_value={"Boom"}),
            patch(
                "scripts.download_icons.download_one_icon",
                side_effect=RuntimeError("kaboom"),
            ),
        ):
            await download_all_icons()  # must not raise

        assert "Boom" in caplog.text
