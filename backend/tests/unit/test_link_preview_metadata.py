"""`index.html` carries the tags a link scraper needs, and tells it not to index.

**There is no SSR here.** A crawler or an unfurler gets `frontend/src/index.html` and nothing
else: the per-route `<title>` is set by `PageTitle` at runtime, which no scraper executes. So
a mistilteinn URL pasted into Discord — where this project's bug-report workflow lives —
unfurled as a naked URL with no title, description or image.

This lives in the backend suite for the same reason `test_catalogue_art_is_not_committed.py`
does: the assertion is about a file the build ships and no component imports, and the
frontend's spec tsconfig deliberately carries only `vitest/globals`. Reading the file from
the Angular test build needs either `@types/node` or a `?raw` loader esbuild does not
configure for HTML — a whole dependency for two file reads is the wrong trade, and this
suite can already read the repository.

The failure being guarded is silent: deleting a meta tag changes nothing on screen, and no
screenshot, typecheck or unit test in the frontend would notice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
INDEX = REPO / "frontend" / "src" / "index.html"
ROBOTS = REPO / "frontend" / "public" / "robots.txt"


@pytest.fixture(scope="module")
def index_html() -> str:
    return INDEX.read_text(encoding="utf-8")


def _meta(html: str, attr: str, key: str) -> str | None:
    r"""The `content` of `<meta {attr}="{key}">`, or None.

    `\s+` between the attributes rather than a literal space: a long `content` sits on its
    own source line, and the first draft of this regex required them adjacent and reported
    two present tags as missing.
    """
    found = re.search(rf'<meta {attr}="{re.escape(key)}"\s+content="([^"]*)"', html)
    return found.group(1) if found else None


def test_the_login_wall_is_not_offered_to_a_search_index(index_html: str) -> None:
    """Every route sits behind `requireApproved`; the crawlable surface is one login card."""
    assert "noindex" in (_meta(index_html, "name", "robots") or "")


def test_robots_allows_the_fetch_that_lets_the_noindex_be_read() -> None:
    """`Disallow: /` would hide the `noindex`, not enforce it.

    A disallowed URL is never fetched, so the `noindex` is never read — and the bare URL can
    still be listed from inbound links alone. Allowing the fetch is what makes it effective.
    This asserts the two files do not contradict each other.
    """
    robots = ROBOTS.read_text(encoding="utf-8")
    assert not re.search(r"^\s*Disallow:\s*/\s*$", robots, re.M)
    assert re.search(r"^\s*Allow:\s*/", robots, re.M)


@pytest.mark.parametrize(
    ("attr", "key"),
    [
        ("property", "og:title"),
        ("property", "og:description"),
        ("property", "og:image"),
        ("property", "og:url"),
        ("property", "og:type"),
        ("name", "description"),
        ("name", "twitter:card"),
    ],
)
def test_the_tags_an_unfurler_reads_are_present(index_html: str, attr: str, key: str) -> None:
    assert _meta(index_html, attr, key)


def test_the_preview_image_is_absolute_and_committed(index_html: str) -> None:
    """A scraper resolves a relative URL against nothing, and every major unfurler needs one."""
    image = _meta(index_html, "property", "og:image")
    assert image
    assert image.startswith("https://")
    # …and the file it names is actually in the tree, which is the half a regex cannot check.
    assert (REPO / "frontend" / "public" / image.rsplit("/", 1)[-1]).is_file()


def test_metadata_content_stays_on_one_line(index_html: str) -> None:
    """An attribute value keeps its newlines and indentation verbatim.

    Only *rendered text* collapses whitespace. A description wrapped across source lines
    therefore ships with a run of spaces inside it, and no consumer is obliged to normalise
    it — this was written that way once and caught here.
    """
    assert not re.findall(r'content="[^"]*\n[^"]*"', index_html)
