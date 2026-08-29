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
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "screenshots"
REFERENCES = REPO / "references"

#: The dev frontend and backend. Both are refused if they are not local — see `_refuse_remote`.
FRONTEND = "http://localhost:4201"
BACKEND = "http://localhost:8001"

SERVICE_EMAIL = "screenshots@example.com"
SERVICE_PASSWORD = "ScreenshotsAreLocal123!"  # noqa: S105 — local-only, see the docstring
SERVICE_LABEL = "Screenshots"

#: Where localStorage keeps the session. Must match `api/auth.service.ts`.
TOKEN_KEY = "mistilteinn.token"  # noqa: S105 — a storage key, not a credential

#: Every route in `app.routes.ts` worth a picture, in the order the product intends them.
ROUTES = (
    "/",
    "/inventory",
    "/builds",
    "/teams",
    "/rotations",
    "/optimize",
    "/compare",
    "/explain",
    "/characters",
    "/weapons",
    "/artifact-sets",
    "/enemies",
)

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


async def _token(client: httpx.AsyncClient) -> str:
    """Sign the service account in, creating and approving it the first time."""
    body = {"email": SERVICE_EMAIL, "password": SERVICE_PASSWORD}
    signed_in = await client.post(f"{BACKEND}/api/v1/auth/login", json=body)
    if signed_in.status_code == httpx.codes.OK:
        return str(signed_in.json()["token"])

    await client.post(
        f"{BACKEND}/api/v1/auth/register", json={**body, "label": SERVICE_LABEL},
    )
    # Approval is a database state with no self-service endpoint, which is correct — an
    # account that could approve itself would not be an approval.
    from scripts.approve_user import approve_user  # noqa: PLC0415 — needs the DB, not the API

    await approve_user(SERVICE_EMAIL)
    signed_in = await client.post(f"{BACKEND}/api/v1/auth/login", json=body)
    signed_in.raise_for_status()
    return str(signed_in.json()["token"])


async def _seed(client: httpx.AsyncClient, token: str) -> None:
    """Import a GOOD export from `references/`, so the pages have something real to draw."""
    exports = sorted(REFERENCES.glob("*.json"))
    if not exports:
        print("no GOOD export in references/ — pages will render their empty states")
        return
    payload: Any = json.loads(exports[-1].read_text())
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
    print(f"seeded from {exports[-1].name}: {body['inserted']} artifacts, {built} builds")


async def shoot(routes: tuple[str, ...], *, seed: bool, full_page: bool) -> int:
    """Screenshot each route. Returns the number of pages that logged a console error."""
    _refuse_remote()
    try:
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
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on(
            "console",
            lambda msg: errors.append(msg.text) if msg.type == "error" else None,
        )

        for route in routes:
            errors.clear()
            await page.goto(f"{FRONTEND}{route}", wait_until="networkidle")
            name = (route.strip("/") or "landing").replace("/", "-")
            await page.screenshot(path=str(OUT / f"{name}.png"), full_page=full_page)
            # A console error is not a failed screenshot, but it is the thing a picture
            # cannot show, so it is reported beside the file rather than swallowed.
            flag = f"  [{len(errors)} console error(s)]" if errors else ""
            if errors:
                broken += 1
            print(f"{route:16} -> screenshots/{name}.png{flag}")

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
