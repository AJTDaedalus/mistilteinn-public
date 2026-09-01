"""The screenshot harness photographs the routes the app actually has.

**It drifted, and the drift was invisible.** `scripts/shoot.py` carried a hand-maintained tuple
whose comment claimed it was *"every route in `app.routes.ts`"*. It listed `/compare` months
after that route was removed, so the harness resolved it through the `**` catch-all,
photographed the **landing page**, and wrote it to `compare.png`. It also listed `/explain`,
now a redirect, and had never heard of `/calculate` or `/my-weapons` — both in the main nav.

Nothing failed. The sweep reported twelve routes shot and zero errors.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.shoot import APP_ROUTES, ROUTES

REPO = Path(__file__).resolve().parents[3]


def _declared() -> set[str]:
    """Every visitable path in the route table — no redirects, no catch-all."""
    text = APP_ROUTES.read_text()
    out = set()
    for path, body in re.findall(r"path:\s*'([^']*)'((?:(?!path:).)*)", text, re.S):
        if path == "**" or "redirectTo" in body:
            continue
        out.add("/" + path)
    return out


def test_the_route_table_is_where_this_test_thinks_it_is() -> None:
    """A moved file would make every assertion below pass by reading nothing."""
    assert APP_ROUTES.is_file(), f"{APP_ROUTES} does not exist"
    assert "path:" in APP_ROUTES.read_text()


def test_every_visitable_route_is_photographed() -> None:
    missing = sorted(_declared() - set(ROUTES))
    assert not missing, (
        f"these routes exist and are never screenshotted: {missing}. A page nobody renders is "
        f"a page nobody looks at, which is how this repo shipped a site with no art."
    )


def test_nothing_is_photographed_that_is_not_a_route() -> None:
    """The failure that started this: a removed route still on the list.

    It does not error — the catch-all redirects, so a picture of somewhere else arrives under
    the removed route's name.
    """
    extra = sorted(set(ROUTES) - _declared())
    assert not extra, (
        f"these are screenshotted and are not routes: {extra}. The catch-all will redirect "
        f"them, so the harness saves a picture of another page under this name."
    )


def test_redirects_are_not_photographed() -> None:
    """`/explain` redirects to `/calculate`; a shot of it is a duplicate under a stale name."""
    text = APP_ROUTES.read_text()
    redirects = {
        "/" + path
        for path, body in re.findall(r"path:\s*'([^']*)'((?:(?!path:).)*)", text, re.S)
        if "redirectTo" in body and path != "**"
    }
    assert redirects, "no redirects found — this test would pass vacuously"
    assert not (redirects & set(ROUTES)), (
        f"redirects are on the screenshot list: {sorted(redirects & set(ROUTES))}"
    )
