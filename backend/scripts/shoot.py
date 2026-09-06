"""Walk the app in a headless browser and screenshot every page. Dev only.

    cd backend && python -m scripts.shoot                # every route
    cd backend && python -m scripts.shoot --route /builds --route /inventory
    cd backend && python -m scripts.shoot --seed         # also import references/*.json

## Why this exists

Every visual defect this project has shipped was invisible to a green suite. Production served
no art for months; a delete button rendered outside its own card; the login form sat above 700
pixels of nothing. 1300 backend tests and 400 frontend tests passed through all of it, because
none of them look at a page.

This does not *judge* a page — nothing automated here decides whether a layout is good. It
removes the friction from looking, which is the part that was actually stopping anyone.

## The account

A dedicated, approved, dev-only login (`SERVICE_EMAIL`). It is created if absent and reused
after that, so screenshots are comparable between runs. **It is not a fixture and holds no
secrets** — the password is a constant in this file, which is safe precisely because this
script refuses to run against anything but a local backend.

`--seed` fills it from a GOOD export in `references/` — the owner's real inventory, which is
the only way to see the pages as they actually render. That directory is gitignored, so this
is a no-op on a machine that has none.

## Why `add_init_script` rather than a login form

The session token lives in `localStorage`, and Playwright can seed it *before the page's own
scripts run*. Driving the login form instead would make every screenshot depend on the login
form working, which is the one page that cannot then be screenshotted independently.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:  # pragma: no cover — playwright is an optional dependency, see `shoot`
    from playwright.async_api import Browser, Page

import httpx

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "screenshots"
REFERENCES = REPO / "references"

#: The dev frontend and backend. Both are refused if they are not local — see `_refuse_remote`.
FRONTEND = "http://localhost:4201"
BACKEND = "http://localhost:8001"

SERVICE_EMAIL = "screenshots@example.com"

#: The first status code that is a failure. Named because ruff refuses the bare literal,
#: and because "400 and up" is the actual rule rather than an arbitrary threshold.
_HTTP_ERROR = 400
SERVICE_PASSWORD = "ScreenshotsAreLocal123!"  # noqa: S105 — local-only, see the docstring
SERVICE_LABEL = "Screenshots"

#: Where localStorage keeps the session. Must match `api/auth.service.ts`.
TOKEN_KEY = "mistilteinn.token"  # noqa: S105 — a storage key, not a credential

#: Where the SPA declares its routes. Read, never copied — see `_routes`.
APP_ROUTES = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "app" / "app.routes.ts"
)

#: The order the product intends, for the routes that have one. Anything the route table
#: carries and this does not is appended rather than dropped, so a new page cannot go
#: unphotographed just because nobody added it here.
PREFERRED = (
    "/", "/inventory", "/my-weapons", "/builds", "/teams", "/rotations", "/optimize",
    "/calculate", "/teapot", "/characters", "/weapons", "/artifact-sets", "/enemies",
)


def _routes() -> tuple[str, ...]:
    """Every visitable route, read off `app.routes.ts`.

    **This was a hand-maintained tuple and it drifted.** It still listed `/compare`, which the
    owner had removed — so the harness resolved it through the `**` catch-all, photographed the
    **landing page**, and filed it as `compare.png`. It also listed `/explain`, now a redirect,
    and it had never been told about `/calculate` or `/my-weapons`, both of which are in the
    main nav.

    A visual harness that silently photographs the wrong page is worse than one that errors,
    and this is the repo whose standing lesson is that rendering a page and looking at it is
    the check nothing else performs. So the list is derived.

    Redirects and the catch-all are excluded: they are not pages, and following one produces a
    picture of somewhere else under the wrong name — which is the whole defect.
    """
    text = APP_ROUTES.read_text()
    # Each entry is `path: '...'`, optionally followed by `redirectTo:` before the next path.
    entries = re.findall(r"path:\s*'([^']*)'((?:(?!path:).)*)", text, re.S)
    found = []
    for path, body in entries:
        if path == "**" or "redirectTo" in body:
            continue
        found.append("/" + path)
    seen = set(found)
    ordered = [r for r in PREFERRED if r in seen]
    ordered += [r for r in found if r not in set(ordered)]
    return tuple(ordered)


ROUTES = _routes()

#: Routes whose guards bounce an *authenticated* caller somewhere else.
#:
#: `login.png` and `pending.png` were byte-identical photographs of `/inventory`, because the
#: harness signs in and these three redirect for a signed-in session. That is precisely the
#: fault `_routes()` above exists to prevent — "a visual harness that silently photographs the
#: wrong page is worse than one that errors" — reported by an audit and left standing.
#:
#: These are shot in a second browser context with no token, which is the only state in which
#: they are the page they are named after.
SIGNED_OUT = ("/login", "/verify", "/pending")

VIEWPORT = {"width": 1440, "height": 1000}


def _refuse_remote() -> None:
    """This creates an account and imports data. It may only ever do that locally."""
    for url in (FRONTEND, BACKEND):
        if not url.startswith(("http://localhost", "http://127.0.0.1")):
            msg = (
                f"{url} is not local; this script creates accounts and imports data, "
                f"and refuses to do either remotely"
            )
            raise SystemExit(msg)


#: Where the last good token is kept between runs.
#:
#: `/auth/login` is rate limited, and a harness whose whole purpose is being run repeatedly
#: hits that limit on its own — which then reads as the app being broken. The cached token is
#: tried first and the file is discarded the moment it stops working.
_TOKEN_CACHE = REPO / ".shoot-token"


async def _cached_token(client: httpx.AsyncClient) -> str | None:
    """The stored token, if it still authenticates."""
    if not _TOKEN_CACHE.exists():
        return None
    token = _TOKEN_CACHE.read_text().strip()
    me = await client.get(
        f"{BACKEND}/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"},
    )
    if me.status_code == httpx.codes.OK:
        return token
    _TOKEN_CACHE.unlink(missing_ok=True)
    return None


async def _token(client: httpx.AsyncClient) -> str:
    """Sign the service account in, creating and approving it the first time."""
    cached = await _cached_token(client)
    if cached:
        return cached

    body = {"email": SERVICE_EMAIL, "password": SERVICE_PASSWORD}
    signed_in = await client.post(f"{BACKEND}/api/v1/auth/login", json=body)
    if signed_in.status_code == httpx.codes.OK:
        return _remember(str(signed_in.json()["token"]))

    # **Only a rejected sign-in means "no such account".** Treating *any* failure as one sent
    # a rate-limited run (429, easy to hit when shooting repeatedly) down the register path,
    # where it re-approved an existing account and then failed on a second login — reporting
    # the retry's error rather than the real one.
    if signed_in.status_code not in {httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN}:
        detail = (
            "Rate limited — wait a minute and re-run."
            if signed_in.status_code == httpx.codes.TOO_MANY_REQUESTS
            else signed_in.text[:200]
        )
        msg = f"could not sign in as {SERVICE_EMAIL}: HTTP {signed_in.status_code}. {detail}"
        raise SystemExit(msg)

    await client.post(
        f"{BACKEND}/api/v1/auth/register", json={**body, "label": SERVICE_LABEL},
    )
    # Approval is a database state with no self-service endpoint, which is correct — an
    # account that could approve itself would not be an approval.
    from scripts.approve_user import approve_user  # noqa: PLC0415 — needs the DB, not the API

    await approve_user(SERVICE_EMAIL)
    signed_in = await client.post(f"{BACKEND}/api/v1/auth/login", json=body)
    signed_in.raise_for_status()
    return _remember(str(signed_in.json()["token"]))


def _remember(token: str) -> str:
    """Store the token for the next run, and hand it back."""
    _TOKEN_CACHE.write_text(token)
    _TOKEN_CACHE.chmod(0o600)
    return token


async def _seed(client: httpx.AsyncClient, token: str) -> None:
    """Import a GOOD export from `references/`, so the pages have something real to draw."""
    # **Picked by format, not by filename.** This took the last file alphabetically, and
    # `references/` also holds an *HSR* relic export — `hsr_relic_export-…` sorts after
    # `genshin_export_…`, so every seeded run posted Star Rail relics to a Genshin importer
    # and got a 400. The directory is gitignored, so what is in it varies per machine and a
    # positional guess is never safe.
    good = []
    for candidate in sorted(REFERENCES.glob("*.json")):
        try:
            parsed = json.loads(candidate.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict) and parsed.get("format") == "GOOD":
            good.append((candidate, parsed))
    if not good:
        print("no GOOD export in references/ — pages will render their empty states")
        return
    export, payload = good[-1]
    result = await client.post(
        f"{BACKEND}/api/v1/artifacts/import/good",
        # Builds too: a screenshot of `/builds` showing "you have no builds yet" is a
        # screenshot of the empty state, and the empty state is not what needs looking at.
        json={"mode": "replace", "payload": payload, "rebuild_builds": True},
        headers={"Authorization": f"Bearer {token}"},
        timeout=180.0,
    )
    result.raise_for_status()
    body = result.json()
    built = (body.get("builds") or {}).get("created", 0)
    print(f"seeded from {export.name}: {body['inserted']} artifacts, {built} builds")


def _watch(page: Page, errors: list[str]) -> None:
    """Collect page errors, failed responses and console errors into `errors`.

    Registered **once per page**, appending into a list the caller clears per route.
    Registering inside the route loop bound `errors` late, so every listener wrote into
    whichever list the last iteration had made, and route three reported route one's errors.
    """
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    # A bare "Failed to load resource: 404" names nothing, and on a 150-card grid the
    # question is always *which* one. The console message genuinely does not carry the
    # URL, so it is taken from the response instead.
    page.on(
        "response",
        lambda r: errors.append(f"HTTP {r.status} {r.url}") if r.status >= _HTTP_ERROR else None,
    )
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)


async def _shoot_signed_out(
    browser: Browser, routes: tuple[str, ...], *, full_page: bool,
) -> int:
    """Shoot the auth screens in a context with no token. Returns the console-error count.

    Everything else in this harness runs signed in, and these routes redirect for an
    authenticated session — which is how `login.png` and `pending.png` came to be two
    byte-identical photographs of `/inventory`, filed under the names of pages nobody had
    looked at. Signed out is the only state in which they are the page they are named after.
    """
    wanted = [r for r in routes if r in SIGNED_OUT]
    if not wanted:
        return 0

    broken = 0
    context = await browser.new_context(viewport=VIEWPORT)
    page = await context.new_page()
    errors: list[str] = []
    _watch(page, errors)

    for route in wanted:
        errors.clear()
        await page.goto(f"{FRONTEND}{route}", wait_until="networkidle")
        landed = urlparse(page.url).path or "/"
        if landed.rstrip("/") != route.rstrip("/"):
            print(f"{route:16} -> REDIRECTED to {landed} signed out; not shot")
            continue
        name = (route.strip("/") or "landing").replace("/", "-")
        await page.screenshot(path=str(OUT / f"{name}.png"), full_page=full_page, timeout=90_000)
        flag = f"  [{len(errors)} console error(s)]" if errors else ""
        if errors:
            broken += 1
        print(f"{route:16} -> screenshots/{name}.png  [signed out]{flag}")

    await context.close()
    return broken


async def shoot(routes: tuple[str, ...], *, seed: bool, full_page: bool) -> int:
    """Screenshot each route. Returns the number of pages that logged a console error."""
    _refuse_remote()
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeout  # noqa: PLC0415
        from playwright.async_api import async_playwright  # noqa: PLC0415 — optional
    except ImportError as exc:  # pragma: no cover — an environment thing, not a code path
        # Named rather than raised bare: the docstring advertises this command, and a bare
        # `ModuleNotFoundError` arrives *after* the account has been created, which reads
        # like the script broke rather than like a dependency is missing.
        msg = (
            "playwright is not installed. It is deliberately not a hard dependency — the "
            "backend does not need a browser — so install it on demand:\n"
            "    pip install playwright && playwright install chromium"
        )
        raise SystemExit(msg) from exc

    OUT.mkdir(exist_ok=True)
    async with httpx.AsyncClient() as client:
        token = await _token(client)
        if seed:
            await _seed(client, token)

    broken = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport=VIEWPORT)
        # Before any page script runs, so the app boots already signed in.
        await context.add_init_script(
            f"try {{ localStorage.setItem({TOKEN_KEY!r}, {token!r}); }} catch (e) {{}}"
        )
        page = await context.new_page()

        # Registered **once**, appending into a list cleared per route. Registering inside the
        # loop bound `errors` late, so every listener wrote into whichever list the last
        # iteration had made — and removing them with a fresh lambda removed nothing, since
        # Playwright matches listeners by identity. Route three reported route one's errors.
        errors: list[str] = []
        _watch(page, errors)

        for route in routes:
            if route in SIGNED_OUT:
                continue  # shot below, without a token
            errors.clear()
            await page.goto(f"{FRONTEND}{route}", wait_until="networkidle")
            # **Where it landed, not where it was sent.** A guard or a `redirectTo` can move
            # the browser somewhere else, and the picture is then of a page under another
            # page's name — the whole defect `_routes()` guards against, arriving by a route
            # `_routes()` cannot see because the redirect happens at run time.
            landed = urlparse(page.url).path or "/"
            if landed.rstrip("/") != route.rstrip("/"):
                print(f"{route:16} -> REDIRECTED to {landed}; not shot")
                continue
            name = (route.strip("/") or "landing").replace("/", "-")
            # **One slow page must not end the run.** A full-page shot of `/artifacts` — 2,370
            # rows, tens of thousands of pixels tall — exceeds Playwright's 30s default, and
            # the raised `TimeoutError` took the whole walk down with it, losing the routes
            # after it as well as the one that failed. A harness whose job is "look at every
            # page" cannot stop at the first page too big to look at.
            #
            # So: a longer budget, then a viewport-sized fallback, then a reported failure.
            # A viewport shot of a huge page is worth far more than no shot, and the line
            # says which it got so nothing reads a cropped image as the whole page.
            shot = OUT / f"{name}.png"
            note = ""
            try:
                await page.screenshot(path=str(shot), full_page=full_page, timeout=90_000)
            except PlaywrightTimeout:
                try:
                    await page.screenshot(path=str(shot), full_page=False, timeout=30_000)
                    note = "  [too tall for a full-page shot; viewport only]"
                except PlaywrightTimeout:
                    note = "  [SCREENSHOT FAILED]"
                    broken += 1
            # A console error is not a failed screenshot, but it is the thing a picture
            # cannot show, so it is reported beside the file rather than swallowed.
            # A count, not a verdict. `/characters` reports two 404s every run — the two
            # portraits nanoka does not publish (Lumine, and the mannequins) — and those are
            # `CatalogueIcon`'s fallback working, not a fault. Filtering them out here would
            # mean deciding in advance which 404s are fine, which is how a real one gets
            # hidden; the flag exists to prompt a look, and a look settles it.
            flag = f"  [{len(errors)} console error(s)]" if errors else ""
            if errors:
                broken += 1
            print(f"{route:16} -> screenshots/{name}.png{flag}{note}")
            # **Print the text, not just the count.** The comment above says the flag exists
            # to prompt a look and that a look settles it — which was not true while the only
            # output was a number. Settling it meant re-running by hand with a patched script,
            # so in practice the flag was noise and got skipped. Deduplicated because one
            # broken image in a 150-card grid logs 150 identical lines and would bury a
            # second, different error underneath it.
            for message in dict.fromkeys(errors):
                first = message.strip().splitlines()[0]
                print(f"{'':16}    ! {first[:160]}")

        broken += await _shoot_signed_out(browser, routes, full_page=full_page)

        await browser.close()
    return broken


def main() -> None:
    """Parse the arguments and shoot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route", action="append", dest="routes",
        help="a route to shoot; repeatable. Defaults to every route.",
    )
    parser.add_argument(
        "--seed", action="store_true",
        help="import a GOOD export from references/ before shooting",
    )
    parser.add_argument(
        "--viewport", action="store_true", dest="viewport_only",
        help="shoot the viewport only, rather than the full scrollable page",
    )
    args = parser.parse_args()
    broken = asyncio.run(
        shoot(
            tuple(args.routes) if args.routes else ROUTES,
            seed=args.seed,
            full_page=not args.viewport_only,
        )
    )
    print(f"\nwritten to {OUT}")
    if broken:
        print(f"{broken} page(s) logged a console error — see the flags above")


if __name__ == "__main__":
    main()
