"""Vendor the catalogue's icons from nanoka's CDN. N.1.

    cd backend && python -m scripts.download_icons [--check] [--force]

The basenames were seeded by Chunk D — `characters.icon` is `UI_AvatarIcon_Ayaka`,
`weapons.icon` is `UI_EquipIcon_Sword_Blunt`, `artifact_sets.icon` is `UI_RelicIcon_10001_4`.
Nothing was missing; nothing was ever fetched. This fetches them.

## Three rules it follows, and why each

**Vendored, never hot-linked.** The same rule `app/data/yuanshen/` and the gcsim key snapshot
follow: nothing in `app/` reaches the network at runtime. A page whose art depends on a
third-party CDN being up is a page that breaks for a reason its owner cannot fix.

**A script, not the seeder.** `python -m scripts.seed_db` must stay runnable offline — the
crossval harness seeds from committed fixtures precisely so it needs no network, and folding a
download into it would take that away.

**Committed** — reversed 2026-08-28, `docs/DECISIONS.md` §4. This paragraph used to say the
opposite, on the reasoning that fairy committed 207 files and this is ~475, so a repository is
not a CDN. Measured, the comparison inverts: **446 distinct files at 9.6 MB here against
fairy's 207 at 27 MB**, about a third the weight of the set already committed one repository
over. And the cost of not committing them was a production site that served no art at all —
nothing ever ran this script there, `Dockerfile.prod` copied a tree without the directory, and
nginx's SPA fallback answered every `/icons/*.webp` with `200 text/html`, so every image
failed silently.

This script is still how the directory is *filled*; `--check` is still how it is audited.
Nothing about obtaining the art changed.

## What it refuses to do

**A failed download is reported, never silently skipped.** An icon directory quietly missing
forty files is a UI with forty broken images and no way to tell whether the fetch or the
catalogue is wrong. The exit code says whether every named icon arrived.

**It does not invent a basename.** A row whose `icon` column is null is counted and named,
because that is a *seeding* gap and fixing it here would paper over the importer.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import select

from app.database import async_session_factory
from app.models.artifact import ArtifactSet
from app.models.character import Character
from app.models.weapon import Weapon

#: Where nanoka publishes them. `gi`, not `genshin` — checked, not guessed.
CDN = "https://static.nanoka.cc/assets/gi"

OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "icons"

#: How many downloads run at once. Polite rather than fast: this is somebody else's CDN and
#: the whole catalogue is a few hundred small files.
CONCURRENCY = 8

#: The tables that carry an icon basename, in the order a reader would look for them.
SOURCES = ((Character, "character"), (Weapon, "weapon"), (ArtifactSet, "artifact set"))

#: Characters have a second image: the half-body gacha portrait, ~118 KB against the 22 KB
#: avatar icon. `UI_AvatarIcon_Ayaka` -> `UI_Gacha_AvatarIcon_Ayaka`, which is the same
#: substitution nanoka's own paths use.
#:
#: Fetched because a character card wants a face, not a thumbnail — the avatar icon is a
#: 64-pixel circle and reads as a bullet point at card size. 124 distinct portraits is about
#: 15 MB, against fairy's committed 27 MB of ZZZ art.
#:
#: **Not every character has one**, and that is `absent_upstream` like any other 404 rather
#: than a failure: the catalogue carries unreleased entries whose art is not published.
PORTRAIT_OF = ("UI_AvatarIcon_", "UI_Gacha_AvatarIcon_")


def portrait_name(icon: str) -> str | None:
    """The gacha portrait for an avatar icon basename, or None if it is not one."""
    prefix, replacement = PORTRAIT_OF
    return icon.replace(prefix, replacement, 1) if icon.startswith(prefix) else None


@dataclass
class Report:
    """What a run did. Counts as well as failures, so a run that fetched nothing is visible."""

    downloaded: int = 0
    already_present: int = 0
    #: Rows whose `icon` column is null — a **seeding** gap, not a download failure.
    missing_basename: list[str] = field(default_factory=list)
    #: Named by the catalogue, and upstream answers **404**. Not a failure: nanoka simply
    #: publishes no art for them — an unreleased weapon's placeholder, two sets whose icon
    #: the CDN does not carry. Conflating "they have no picture" with "the fetch broke" would
    #: make this script fail forever and stop being usable as a check.
    absent_upstream: list[str] = field(default_factory=list)
    #: Everything else: a timeout, a 5xx, a connection refused. These are worth retrying and
    #: are what the exit code is about.
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Green only if nothing *failed* **and** something was seen.

        A run over an empty database downloads nothing and fails nothing, and reporting that
        as success is the green-by-absence shape this repo refuses everywhere else.

        `absent_upstream` does not count against it — see that field.
        """
        return not self.failed and (self.downloaded + self.already_present) > 0

    def summary(self) -> str:
        """One line naming every bucket."""
        return (
            f"{self.downloaded} downloaded, {self.already_present} already present, "
            f"{len(self.missing_basename)} rows with no icon name, "
            f"{len(self.absent_upstream)} not published upstream, {len(self.failed)} failed"
        )


async def wanted() -> list[tuple[str, str]]:
    """`(basename, what it is)` for every catalogue row that names an icon."""
    found: list[tuple[str, str]] = []
    async with async_session_factory() as session:
        for model, label in SOURCES:
            rows = (await session.execute(select(model))).scalars().all()
            for row in rows:
                if not row.icon:
                    continue
                found.append((row.icon, f"{label} {row.name}"))
                portrait = portrait_name(row.icon) if model is Character else None
                if portrait:
                    found.append((portrait, f"{label} {row.name} portrait"))
    return found


async def _fetch(
    client: httpx.AsyncClient,
    limit: asyncio.Semaphore,
    basename: str,
    what: str,
    report: Report,
    *,
    force: bool,
) -> None:
    target = OUT / f"{basename}.webp"
    if target.exists() and not force:
        report.already_present += 1
        return
    async with limit:
        try:
            response = await client.get(f"{CDN}/{basename}.webp")
        except httpx.HTTPError as exc:
            report.failed.append(f"{basename} ({what}): {type(exc).__name__}")
            return
    if response.status_code == httpx.codes.NOT_FOUND:
        # Upstream has no art for this entity. Recorded, not failed.
        report.absent_upstream.append(f"{basename} ({what})")
        return
    if response.is_error:
        report.failed.append(f"{basename} ({what}): HTTP {response.status_code}")
        return
    # **Not the status code.** Portrait basenames are *derived* by substitution rather than
    # read from a payload, and this CDN answers `200 text/html` for a name it does not have —
    # the same shape as the SPA fallback that hid production's missing art for months. Without
    # this, a bad guess is written as `<name>.webp`, counted as downloaded, committed by the
    # art guard, and reported as vendored by `--check` forever after.
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        report.failed.append(
            f"{basename} ({what}): served {content_type or 'no content-type'}, not an image"
        )
        return
    # Written only after a successful, complete response: a half-written file is a broken
    # image that looks like a present one, and the next run would skip it.
    target.write_bytes(response.content)
    report.downloaded += 1


async def download(*, force: bool = False, check: bool = False) -> Report:
    """Fetch every named icon that is not already vendored."""
    report = Report()
    icons = await wanted()

    async with async_session_factory() as session:
        for model, label in SOURCES:
            rows = (await session.execute(select(model))).scalars().all()
            report.missing_basename.extend(
                f"{label} {row.name}" for row in rows if not row.icon
            )

    if check:
        report.already_present = sum(
            1 for basename, _ in icons if (OUT / f"{basename}.webp").exists()
        )
        # `--check` cannot tell "never fetched" from "upstream has none" without asking the
        # network, and asking would make a *check* do the thing it is checking for. So it
        # reports them as missing and says so; the exit code is about whether the vendored
        # directory is complete, which is what a build wants to know.
        report.failed = [
            f"{basename} ({what}): not vendored"
            for basename, what in icons
            if not (OUT / f"{basename}.webp").exists()
        ]
        return report

    OUT.mkdir(parents=True, exist_ok=True)
    limit = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await asyncio.gather(*(
            _fetch(client, limit, basename, what, report, force=force)
            for basename, what in icons
        ))
    return report


def main() -> None:
    """Run the download and exit non-zero on anything that is not complete success."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="report what is missing without downloading anything",
    )
    parser.add_argument(
        "--force", action="store_true", help="re-download icons already vendored",
    )
    args = parser.parse_args()

    report = asyncio.run(download(force=args.force, check=args.check))

    print(report.summary())
    for line in report.missing_basename[:20]:
        print(f"  NO ICON NAME  {line}")
    for line in report.absent_upstream[:20]:
        print(f"  NOT PUBLISHED {line}")
    for line in report.failed[:20]:
        print(f"  FAILED        {line}")
    if not report.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
