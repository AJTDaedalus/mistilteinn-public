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
from app.models.build import EnemyProfile
from app.models.character import Character, Talent
from app.models.weapon import Weapon
from app.services import element_symbols, weapon_symbols
from app.services.practice_dummies import is_practice_dummy

#: Where nanoka publishes them. `gi`, not `genshin` — checked, not guessed.
CDN = "https://static.nanoka.cc/assets/gi"

#: Basenames the catalogue names and nanoka does not publish. **Measured, not assumed** — each
#: answered a real 404 during a download run, and re-checking one is
#: `curl -o /dev/null -w '%{http_code}' https://static.nanoka.cc/assets/gi/<name>.webp`.
#:
#: Both Travelers and the male mannequin have an avatar icon upstream but no *gacha portrait*,
#: which is why their cards fall back to the small icon rather than showing nothing.
#:
#: This exists so `--check` can pass. Without it a complete directory still reported these as
#: missing, forever — the cry-wolf shape this script already refuses for a 404 during a
#: download. Adding a name here is a claim that upstream does not have it; verify before
#: adding, because a name added to silence a real failure silences it permanently.
ABSENT_UPSTREAM: frozenset[str] = frozenset({
    # Both Travelers have an avatar icon but no gacha portrait, which is why their cards fall
    # back to the small icon rather than showing nothing.
    "UI_Gacha_AvatarIcon_PlayerBoy",
    "UI_Gacha_AvatarIcon_PlayerGirl",
    "UI_Gacha_AvatarIcon_MannequinBoy",
    # An unreleased weapon's placeholder and two artifact sets — the three CLAUDE.md already
    # names. All four above and these were re-checked against the CDN on 2026-08-29.
    "Sword_Template",
    "UI_RelicIcon_15004_4",
    "UI_RelicIcon_15012_3",
})

OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "icons"

#: How many downloads run at once. Polite rather than fast: this is somebody else's CDN and
#: the whole catalogue is a few hundred small files.
CONCURRENCY = 8

#: The tables that carry an icon basename, in the order a reader would look for them.
SOURCES = (
    (Character, "character"),
    (Weapon, "weapon"),
    (ArtifactSet, "artifact set"),
    (EnemyProfile, "enemy"),
)

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
                # The practice mannequins are hidden from the catalogue entirely (owner
                # ruling), so fetching their art vendors 14 rows' worth of pictures nothing
                # will ever draw — and their portraits are not published upstream, so
                # `--check` reported them as missing forever.
                if model is Character and is_practice_dummy(row.nanoka_id):
                    continue
                if not row.icon:
                    continue
                found.append((row.icon, f"{label} {row.name}"))
                portrait = portrait_name(row.icon) if model is Character else None
                if portrait:
                    found.append((portrait, f"{label} {row.name} portrait"))
                # **A set has five pieces and five pictures.** `artifact_sets.icon` is the
                # *flower* — nanoka's representative icon — so vendoring only that left every
                # plume, sands, goblet and circlet in the app drawing a flower. The other four
                # are named in `part_icons`, read from the payload rather than guessed from
                # the basename's trailing digit.
                for slot, icon in (getattr(row, "part_icons", None) or {}).items():
                    if icon and icon != row.icon:
                        found.append((icon, f"{label} {row.name} {slot}"))
        # The talents' own sprites — the game's picture of each character's normal attack,
        # elemental skill and burst. The rotation builder draws these on its move buttons and
        # on the timeline (`DESIGN_rotation_builder_gui.md`), and nothing fetched them before:
        # only the five class marks below reached the disk, because they are the only talent
        # icons `weapon_symbols` had a reason to name.
        #
        # **The basename is read, never constructed.** `Skill_E_Ayaka` carries no `_01` and
        # `Skill_E_Varesa_01` does; `Skill_E_Mavuika` 404s while `Skill_E_Flins_01` is served.
        # No rule predicts which, so anything that builds the name from a character key would
        # 404 on an unpredictable subset and leave gaps nobody could explain.
        #
        # Joined to `characters` rather than read alone, so a practice mannequin's talents are
        # skipped with its portrait and the label can say whose talent it is.
        talents = (
            await session.execute(
                select(Talent, Character.name, Character.nanoka_id)
                .join(Character, Character.id == Talent.character_id)
                .where(Talent.icon.is_not(None)),
            )
        ).all()
        for talent, character_name, character_nanoka_id in talents:
            if is_practice_dummy(character_nanoka_id):
                continue
            found.append((talent.icon, f"talent {character_name} — {talent.name}"))

    # The five weapon-class marks. Not a catalogue row's `icon` — they are per *class*, not
    # per entity, so nothing in the loop above would ever reach them. Derived from the
    # talents table rather than named here; `app/services/weapon_symbols.py` explains why the
    # catalyst's `Skill_A_Catalyst_MD` is the reason that matters.
    found.extend(
        (symbol, f"weapon class symbol {symbol}") for symbol in weapon_symbols.all_symbols()
    )
    # The seven vision emblems, for the same reason: per *element*, not per row. nanoka serves
    # these under the element's plain name with no prefix — `Pyro.webp` — which is why no
    # sweep of `UI_*` shapes finds them. `app/services/element_symbols.py` and
    # `docs/RESEARCH_element_symbols.md`.
    found.extend(
        (symbol, f"vision emblem {symbol}") for symbol in element_symbols.all_symbols()
    )
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
        # `--check` cannot ask the network — that would make a *check* do the thing it is
        # checking for — so it cannot tell "never fetched" from "upstream has none" by
        # itself. It reads `ABSENT_UPSTREAM` instead, which is the answer a real run already
        # obtained.
        #
        # Without that list this check **could never pass**: three basenames are genuinely
        # unpublished, so a complete directory still reported three failures, forever. That
        # is the cry-wolf shape this script's own docstring rejects for 404s during a
        # download, arriving one function later.
        for basename, what in icons:
            if (OUT / f"{basename}.webp").exists():
                continue
            if basename in ABSENT_UPSTREAM:
                report.absent_upstream.append(f"{basename} ({what})")
            else:
                report.failed.append(f"{basename} ({what}): not vendored")
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
