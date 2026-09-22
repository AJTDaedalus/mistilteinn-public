"""Refresh the banner roster — which characters and weapons each wish has featured.

    cd backend && python -m scripts.refresh_banners            # snapshot + database
    cd backend && python -m scripts.refresh_banners --dry-run
    cd backend && python -m scripts.refresh_banners --from-snapshot   # no network

**Nothing in `app/` calls this**, for the reason `refresh_wish_income` gives: `app/` has one
request-time fetch and a wiki on the request path would be a second.

## What it reads

The community wiki's per-banner pages, one per run, named `<Banner>/<YYYY-MM-DD>`. Each
carries a `{{Wish}}` infobox with `time_start`/`time_end` and a `{{Wish Pool}}` naming the
featured items:

    |character_5_F = Vesna
    |character_4_F = Diona; Faruzan; Chongyun

**Why the wiki and not the game data.** AnimeGameData has no wish-pool table in any of its
1,935 tables; pools are server-side. HoYoverse's own disclosure carries them, but its public
index is frozen at 2023 banners. The wiki is the only source covering every run.

## Names, never ids

A banner stores *Vesna*, not a uuid. `#263` shipped a snapshot holding `str(weapon.id)` from
whichever database the capture ran against, so **zero of 205 ids resolved in production** and
every recommendation missed in silence. A name that does not resolve is visible in a report;
a stale uuid is not.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.database import async_session_factory
from app.models.character import Character
from app.models.weapon import Weapon
from app.models.wish_banner import WishBanner

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

WIKI = "https://genshin-impact.fandom.com/api.php"
USER_AGENT = "mistilteinn/1.0 (+https://mistilteinn.aetherus.dev; banner roster)"
SNAPSHOT = Path(__file__).resolve().parents[1] / "app" / "data" / "wishes" / "banners.json"

CATEGORIES = {
    "character": "Category:Character Event Wishes",
    "weapon": "Category:Weapon Event Wishes",
}

#: A refresh returning fewer than this share of what is stored is refused — `seed_db`'s
#: PRUNE REFUSED rule. A truncated but valid response looks exactly like a real retraction.
MIN_RETAINED_SHARE = 0.8
#: Below this the category listing itself is suspect rather than any single page.
MIN_BANNERS = 200
#: Unresolved names printed before the list is elided.
REPORTED_UNRESOLVED = 8


class BannerRefreshError(RuntimeError):
    """The wiki did not have the shape this script knows how to read."""


@dataclass
class ParsedBanner:
    """One banner run."""

    slug: str
    name: str
    kind: str
    starts_at: str | None
    ends_at: str | None
    featured_five: list[str] = field(default_factory=list)
    featured_four: list[str] = field(default_factory=list)
    alongside: list[str] = field(default_factory=list)


def _fetch(params: dict[str, str], timeout: int = 45) -> dict:
    url = WIKI + "?" + urllib.parse.urlencode({**params, "format": "json"})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8", "replace"))


def _members(category: str) -> list[str]:
    """Dated runs only — the bare banner name is an overview page carrying no pool.

    **Follows `cmcontinue`.** A single 500-member page truncates silently once a category
    outgrows it, and neither guard would catch it: `MIN_BANNERS` is a combined floor across
    both categories and `MIN_RETAINED_SHARE` compares against a stored total the other
    category props up. That is the "valid HTTP 200 that no retry can detect" this file's
    other comments are written against.
    """
    titles: list[str] = []
    params = {
        "action": "query", "list": "categorymembers",
        "cmtitle": category, "cmlimit": "500",
    }
    while True:
        body = _fetch(params)
        titles.extend(
            row["title"] for row in body.get("query", {}).get("categorymembers", [])
        )
        cont = body.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        params = {**params, "cmcontinue": cont}
    return [title for title in titles if re.search(r"/\d{4}-\d{2}-\d{2}$", title)]


def _template_fields(text: str, marker: str) -> dict[str, str]:
    """The `|key = value` pairs of one template. None of the ones read here nest."""
    start = text.find(marker)
    if start < 0:
        return {}
    end = text.find("}}", start)
    fields: dict[str, str] = {}
    for line in text[start:end].splitlines():
        if "=" not in line or not line.lstrip().startswith("|"):
            continue
        key, _, value = line.partition("=")
        fields[key.strip().lstrip("|").strip()] = value.strip()
    return fields


def _items(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def parse_banner(title: str, kind: str) -> ParsedBanner:
    """Read one banner page into a row."""
    body = _fetch({"action": "parse", "page": title, "prop": "wikitext"})
    if "error" in body:
        raise BannerRefreshError(f"{title}: {body['error'].get('info')}")
    text = body["parse"]["wikitext"]["*"]

    info = _template_fields(text, "{{Wish\n")
    pool = _template_fields(text, "{{Wish Pool")
    if not pool:
        raise BannerRefreshError(f"{title}: no Wish Pool template")

    five = _items(pool.get("character_5_F", "")) + _items(pool.get("weapon_5_F", ""))
    four = _items(pool.get("character_4_F", "")) + _items(pool.get("weapon_4_F", ""))
    if not five or not four:
        raise BannerRefreshError(f"{title}: featured lists empty (five={five}, four={four})")

    return ParsedBanner(
        slug=title,
        name=title.rsplit("/", 1)[0],
        kind=kind,
        starts_at=info.get("time_start") or None,
        ends_at=info.get("time_end") or None,
        featured_five=five,
        featured_four=four,
        alongside=[v for k, v in info.items() if k.startswith("alongside") and v],
    )


def fetch_banners() -> list[ParsedBanner]:
    """Read every dated banner page. Raises rather than returning a partial roster."""
    work: list[tuple[str, str]] = []
    for kind, category in CATEGORIES.items():
        titles = _members(category)
        if not titles:
            raise BannerRefreshError(f"{category} listed no dated runs")
        work.extend((title, kind) for title in titles)

    if len(work) < MIN_BANNERS:
        raise BannerRefreshError(
            f"only {len(work)} banner pages listed, below the {MIN_BANNERS} floor — the "
            "category listing is suspect, so nothing is written"
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        banners = list(pool.map(lambda pair: parse_banner(*pair), work))

    banners.sort(key=lambda banner: (banner.starts_at or "", banner.slug), reverse=True)
    return banners


async def store(
    session: AsyncSession, banners: list[ParsedBanner], fetched_at: datetime,
) -> tuple[int, list[str]]:
    """Replace the table, refusing an implausible shrink. Returns (written, unresolved)."""
    existing = len((await session.execute(select(WishBanner))).all())
    if existing and len(banners) < existing * MIN_RETAINED_SHARE:
        raise BannerRefreshError(
            f"REFUSED: {len(banners)} banners against {existing} stored. A truncated but "
            "valid response looks exactly like a real retraction, so this writes nothing."
        )

    known = {row.name for row in (await session.execute(select(Character))).scalars()}
    known |= {row.name for row in (await session.execute(select(Weapon))).scalars()}

    unresolved = sorted({
        name
        for banner in banners
        for name in banner.featured_five + banner.featured_four
        if known and name not in known
    })

    await session.execute(delete(WishBanner))
    session.add_all([
        WishBanner(
            slug=b.slug, name=b.name, kind=b.kind, starts_at=b.starts_at, ends_at=b.ends_at,
            featured_five=b.featured_five, featured_four=b.featured_four,
            alongside=b.alongside, fetched_at=fetched_at,
        )
        for b in banners
    ])
    await session.commit()
    return len(banners), unresolved


def write_snapshot(banners: list[ParsedBanner], fetched_at: datetime) -> None:
    """Rewrite the committed seed so a fresh clone and CI need no network."""
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(
            {
                "note": (
                    "Every Genshin event banner and what it featured. Written by "
                    "scripts/refresh_banners.py from the community wiki; see that script and "
                    "docs/DESIGN_wish_planner.md section 9.5. Committed so a fresh clone and "
                    "the test suite need no network -- the live store is `wish_banners`."
                ),
                "fetched_at": fetched_at.isoformat(),
                "banners": [asdict(b) for b in banners],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )


def load_snapshot() -> tuple[list[ParsedBanner], datetime]:
    """Read the committed seed. Fills an empty table without touching the network.

    Raises:
        BannerRefreshError: If the snapshot is empty or truncated. Without this a mangled
            file escaped every guard and failed the deploy step with a raw `IndexError`
            rather than the script's own refusal.
    """
    raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    banners = [ParsedBanner(**entry) for entry in raw["banners"]]
    if len(banners) < MIN_BANNERS:
        raise BannerRefreshError(
            f"the committed snapshot holds {len(banners)} banners, below the {MIN_BANNERS} "
            "floor — it is truncated, so nothing is written"
        )
    return banners, datetime.fromisoformat(raw["fetched_at"])


async def _main(arguments: argparse.Namespace) -> int:
    fetched_at = datetime.now(UTC)
    if arguments.from_snapshot:
        banners, fetched_at = load_snapshot()
        print(f"loaded {len(banners)} banners from the committed snapshot")
    else:
        print("reading the wiki's banner pages…")
        banners = fetch_banners()
        print(f"read {len(banners)} banners")

    newest = banners[0]
    print(f"  newest: {newest.name} ({newest.starts_at}) "
          f"5★ {newest.featured_five} · 4★ {newest.featured_four}")

    if arguments.dry_run:
        print("dry run: nothing written")
        return 0

    if not arguments.from_snapshot:
        write_snapshot(banners, fetched_at)
        print(f"wrote {SNAPSHOT.name}")

    if arguments.snapshot_only:
        return 0

    async with async_session_factory() as session:
        written, unresolved = await store(session, banners, fetched_at)
    print(f"stored {written} banners")
    if unresolved:
        # Reported, not fatal: a new character reaches the wiki before this repo's catalogue
        # is re-seeded, and refusing the roster for that would make every banner unavailable
        # in the week a character ships.
        print(f"  {len(unresolved)} names do not resolve against the catalogue: "
              f"{unresolved[:REPORTED_UNRESOLVED]}"
              f"{' …' if len(unresolved) > REPORTED_UNRESOLVED else ''}", file=sys.stderr)
    return 0


def main() -> int:
    """Entry point: refresh the banner roster, or explain why it refused to."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch and check, write nothing"
    )
    parser.add_argument("--snapshot-only", action="store_true", help="skip the database")
    parser.add_argument(
        "--from-snapshot", action="store_true",
        help="seed from the committed snapshot, with no network access",
    )
    arguments = parser.parse_args()
    try:
        return asyncio.run(_main(arguments))
    except BannerRefreshError as error:
        print(f"banner refresh refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
