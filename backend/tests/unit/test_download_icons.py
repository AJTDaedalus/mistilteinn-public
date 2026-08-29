"""N.1 — what the icon script counts, and what it refuses to conflate.

The download itself needs the network and is not tested here. What *is* tested is the
reporting, because that is where this script can lie: a run that fetched nothing looking like
success, or an entity upstream has no art for looking like a failed fetch.
"""

from __future__ import annotations

import pytest

from scripts.download_icons import Report, portrait_name


def test_a_run_that_saw_nothing_is_not_success() -> None:
    """A run against an empty database downloads nothing and fails nothing.

    Reporting that as green is the green-by-absence shape this repo refuses everywhere —
    `tests/crossval` asserts its own coverage for the same reason.
    """
    assert not Report().ok


def test_a_complete_run_is_success() -> None:
    assert Report(downloaded=475).ok
    assert Report(already_present=475).ok


def test_an_entity_with_no_published_art_is_not_a_failure() -> None:
    """Three of the 475 are genuinely absent upstream — an unreleased weapon's placeholder and
    two artifact sets, all 404.

    Counting them as failures would make this script exit non-zero forever, and a check that
    can never pass is a check nobody runs.
    """
    assert Report(downloaded=472, absent_upstream=["a", "b", "c"]).ok


def test_a_real_fetch_failure_is_a_failure() -> None:
    """A timeout or a 5xx is worth retrying, and is exactly what the exit code is for."""
    assert not Report(downloaded=474, failed=["x: ReadTimeout"]).ok


def test_a_row_with_no_icon_name_does_not_fail_the_download() -> None:
    """That is a **seeding** gap, not a download one. Failing here would blame the fetch for
    something the importer did — and the summary names them either way."""
    assert Report(downloaded=475, missing_basename=["character Nobody"]).ok


def test_the_summary_names_every_bucket() -> None:
    """A number that moved silently is a number nobody re-checks."""
    summary = Report(
        downloaded=1, already_present=2,
        missing_basename=["a"], absent_upstream=["b", "c"], failed=["d"],
    ).summary()

    for expected in ("1 downloaded", "2 already present", "1 rows with no icon name",
                     "2 not published upstream", "1 failed"):
        assert expected in summary, summary


# ── how a response is classified ─────────────────────────────────────────────


async def _classify(
    status: int, *, body: bytes = b"webp", content_type: str = "image/webp",
) -> Report:
    """Run one fetch against a stub transport and return what it recorded.

    Stubbed rather than mocked at the function boundary: the classification lives in `_fetch`,
    and a test that replaced `_fetch` would assert nothing about it. This is the branch that
    decides whether an entity has no art or the network broke — the distinction the exit code
    rests on.
    """
    import asyncio
    import tempfile
    from pathlib import Path as _Path

    import httpx

    from scripts import download_icons

    report = Report()
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            status, content=body, headers={"content-type": content_type},
        ),
    )
    with tempfile.TemporaryDirectory() as tmp:
        original = download_icons.OUT
        download_icons.OUT = _Path(tmp)
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                await download_icons._fetch(
                    client, asyncio.Semaphore(1), "UI_Test", "weapon Test", report,
                    force=False,
                )
        finally:
            download_icons.OUT = original
    return report


@pytest.mark.asyncio
async def test_a_404_is_recorded_as_unpublished_not_failed() -> None:
    """The classification the exit code rests on.

    Three real entities 404 — an unreleased weapon's placeholder and two artifact sets — and
    calling that a failure would make this script exit non-zero forever.
    """
    report = await _classify(404)

    assert report.absent_upstream == ["UI_Test (weapon Test)"]
    assert report.failed == []


@pytest.mark.asyncio
async def test_a_server_error_is_a_failure() -> None:
    """A 5xx is worth retrying, and is what the exit code is for. Filed with the 404s it
    would be silently tolerated, and a run that fetched nothing would look complete."""
    report = await _classify(503)

    assert report.failed
    assert report.absent_upstream == []


@pytest.mark.asyncio
async def test_a_success_is_written_and_counted() -> None:
    report = await _classify(200)

    assert report.downloaded == 1
    assert report.failed == []


@pytest.mark.asyncio
async def test_a_200_that_is_not_an_image_is_a_failure_not_a_download() -> None:
    """**The check the status code cannot make.**

    Portrait basenames are derived by substitution rather than read from a payload, and this
    CDN answers `200 text/html` for a name it does not carry — the same shape as the SPA
    fallback that hid production's missing art for months. Without this, a wrong guess is
    written as `<name>.webp` holding an HTML body, counted as downloaded, committed by the
    art guard, and reported as vendored by `--check` forever after.
    """
    report = await _classify(200, body=b"<!doctype html>", content_type="text/html")

    assert report.downloaded == 0
    assert report.failed == ["UI_Test (weapon Test): served text/html, not an image"]


# ── portrait basenames ───────────────────────────────────────────────────────
#
# The portrait name is **derived by substitution**, not read from a payload — so unlike every
# other basename here it can be wrong in a way the catalogue cannot reveal. That is why
# `_fetch` checks the response's content type rather than its status: this CDN answers
# `200 text/html` for a name it does not have, the same shape as the SPA fallback that hid
# production's missing art for months.


def test_a_portrait_is_the_avatar_icon_with_the_gacha_prefix() -> None:
    assert portrait_name("UI_AvatarIcon_Ayaka") == "UI_Gacha_AvatarIcon_Ayaka"


def test_a_basename_in_another_shape_has_no_portrait() -> None:
    """Weapons and artifact sets have no gacha art, and guessing one would fetch nothing."""
    assert portrait_name("UI_EquipIcon_Sword_Blunt") is None
    assert portrait_name("UI_RelicIcon_15008_4") is None


def test_only_the_leading_prefix_is_replaced() -> None:
    """A basename that repeats the prefix must not be rewritten twice."""
    assert portrait_name("UI_AvatarIcon_UI_AvatarIcon_Odd") == (
        "UI_Gacha_AvatarIcon_UI_AvatarIcon_Odd"
    )
