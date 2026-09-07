"""Drive Genshin Optimizer in a headless browser and screenshot its Artifact Upgrader.

    cd backend && python -m scripts.audit_genshin_optimizer
    cd backend && python -m scripts.audit_genshin_optimizer --export ../references/foo.json

Research tooling, not part of the app. `docs/TASKS_artifact_ranking.md` A.1, whose companion
is `docs/AUDIT_go_handson.md`.

## Why this exists

`docs/RESEARCH_genshin_optimizer_scoring.md` documents GO's upgrade-probability model from its
source, and says so in its own honesty note: *"I did not run GO or view its UI. Statements about
what the user sees are read off the JSX."* We are copying that display. This repo's most
expensive standing lesson is that a green suite is blind to what a page actually renders — the
icons that 404'd into an SPA fallback for months, the badge drawn in dark-on-dark by an
undefined custom property. **A chart nobody has looked at is the same bet.** So this looks.

## What it does, and the two things that made it non-trivial

Imports a GOOD export into GO's local database, builds a team, and walks to the character's
**Artifact Upgrader** tab (`#/teams/<team>/<char>/upopt` — *not* `Optimize`, which is the
five-piece search).

- **The upload control is not a file chooser.** Clicking *Upload* on a Database card mounts a
  hidden `input[type=file]`; `expect_file_chooser` waits forever. Set the input directly.
- **Ad iframes intercept clicks.** `Select an Optimization Target` sat under an `adsbygoogle`
  frame and Playwright retried the click 56 times before timing out. The route filter below is
  not politeness, it is the only way the page is drivable.

The Upgrader shows nothing until an optimization target is chosen — before that it says *"there
aren't any artifacts available for upgrading"*, which reads like an empty inventory and is not.

## What it does not do

It does not assert. Nothing here decides whether GO's chart is good, and a screenshot this
script fails to take is a screenshot the audit records as not taken — never one inferred from
the source. It touches no mistilteinn service and reads only a local export.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import Page, async_playwright

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "screenshots" / "go"
DEFAULT_EXPORT = REPO / "references" / "genshin_export_2026-08-28_11-07.json"

BASE = "https://frzyc.github.io/genshin-optimizer/"

#: Hosts whose frames sit on top of the controls this script has to click. See the docstring.
BLOCKED = (
    "googlesyndication",
    "doubleclick",
    "googletagservices",
    "adsbygoogle",
    "google-analytics",
    "googletagmanager",
    "ezoic",
    "ezodn",
    "lootbar",
)

#: GO renders progressively and offers no "done" signal this script can wait on, so the waits
#: are wall-clock. Generous on purpose: a short wait produces a screenshot of a half-drawn page,
#: which is worse than a slow run because it looks like a finding.
SETTLE_MS = 3_000
IMPORT_MS = 8_000
COMPUTE_MS = 25_000


async def _shot(page: Page, name: str, *, full: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(OUT / name), full_page=full)
    print(f"  [shot] screenshots/go/{name}")


async def _import(page: Page, export: Path) -> None:
    """Load a GOOD export into GO's Database 1."""
    await page.goto(BASE + "#/setting", wait_until="networkidle", timeout=90_000)
    await page.wait_for_timeout(SETTLE_MS)
    await _shot(page, "02_setting.png", full=True)

    await page.get_by_role("button", name="Upload").first.click()
    await page.wait_for_timeout(1_500)
    # Not `expect_file_chooser` — see the docstring.
    await page.locator("input[type=file]").first.set_input_files(str(export))
    await page.wait_for_timeout(6_000)
    await _shot(page, "03_upload_parsed.png")

    await page.get_by_role("button", name="Update Database").click()
    await page.wait_for_timeout(IMPORT_MS)
    await _shot(page, "04_after_import.png")


async def _team(page: Page, character: str) -> None:
    """Create a team holding one character, on that character's equipped build."""
    await page.goto(BASE + "#/teams", wait_until="networkidle", timeout=90_000)
    await page.wait_for_timeout(4_000)
    await page.get_by_role("button", name="Add Team").click()
    await page.wait_for_timeout(4_000)
    await page.get_by_role("button", name="Add Character").first.click()
    await page.wait_for_timeout(SETTLE_MS)
    await page.locator("input[type=text], input[type=search]").first.fill(character)
    await page.wait_for_timeout(2_000)
    await _shot(page, "10_char_picker.png")
    await page.get_by_text(character, exact=True).first.click()
    await page.wait_for_timeout(5_000)


async def _upgrader(page: Page, character: str, target: str) -> None:
    """The tab this whole script exists for."""
    await page.goto(
        f"{BASE}#/teams/team_0/{character}/upopt", wait_until="networkidle", timeout=90_000,
    )
    await page.wait_for_timeout(10_000)
    # Before a target is chosen the page reads "there aren't any artifacts available for
    # upgrading", which looks like an empty inventory and is not one.
    await _shot(page, "14_upopt_no_target.png")
    await _shot(page, "14b_upopt_no_target_full.png", full=True)

    await page.get_by_text("Select an Optimization Target").first.click(timeout=20_000)
    await page.wait_for_timeout(4_000)
    await _shot(page, "15_target_modal.png")

    await page.get_by_text(target, exact=True).first.click(timeout=20_000)
    await page.wait_for_timeout(COMPUTE_MS)
    await _shot(page, "16_upopt_computed.png")
    await _shot(page, "16b_upopt_computed_full.png", full=True)


async def run(export: Path, character: str, target: str) -> None:
    """Import, build a team, and screenshot the Artifact Upgrader end to end."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1100})

        async def _filter(route) -> None:  # noqa: ANN001 - playwright's Route
            if any(host in route.request.url for host in BLOCKED):
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", _filter)
        page = await context.new_page()

        await page.goto(BASE, wait_until="networkidle", timeout=90_000)
        await page.wait_for_timeout(SETTLE_MS)
        await _shot(page, "01_landing.png")

        await _import(page, export)
        await _team(page, character)
        await _upgrader(page, character, target)
        await browser.close()
    print(f"\nDone. Screenshots in {OUT}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--character", default="Furina")
    parser.add_argument(
        "--target",
        default="Ousia Bubble DMG",
        help="A leaf in GO's Target Selector, matched exactly.",
    )
    args = parser.parse_args()
    if not args.export.exists():
        raise SystemExit(
            f"no export at {args.export} — references/ is gitignored, so this is expected on a "
            "machine that has none",
        )
    asyncio.run(run(args.export, args.character, args.target))


if __name__ == "__main__":
    main()
