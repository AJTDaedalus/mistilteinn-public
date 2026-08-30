"""Capture KeqingMains' weapon recommendations into a committed snapshot.

    cd backend && python -m scripts.capture_kqm_weapons nahida furina

**Owner ruling, 2026-08-29: "Manual, cited, small first."** Hand-curate a handful of characters
with committed source URLs and retrieval dates, the same discipline as the reaction table —
because this is *"exactly the shape of the failure `CLAUDE.md` names as fairy's worst"*:
fabricated citations in curated data.

So nothing here is written from memory. The script fetches a guide, finds the weapons section
by its **anchor**, reads the table under it, and records where every row came from. What it
cannot resolve it **refuses and names** rather than guessing.

## What is captured, and what is claimed

The table is two columns — a weapon and KQM's note about it — and it carries **no rank
numbers**. What it does carry is an order, and the top row is described as the character's
best-in-slot. So the snapshot stores `position`, not `rank`, and the API says "KQM lists these
in this order" rather than "KQM ranks this first". That distinction is the difference between
citing a source and putting words in its mouth.

**A weapon name that does not resolve to this catalogue is dropped and reported.** KQM writes
`A Thousand Floating Dreams (TFD)` and `Kagura's Verity` with a curly apostrophe; both reduce
through `gcsim_keys.normalise`. Anything left over is a mapping this repo has not made, and
guessing at it is how a recommendation ends up naming a weapon the character cannot hold.

## Not a live fetch, ever

The output is committed and read from disk, like `app/data/yuanshen/`. A guide is somebody
else's page and it changes; a recommendation that silently became a different one between two
page loads would be unciteable. Re-run this deliberately, and the diff is the review.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select

from app.database import async_session_factory
from app.models.character import Character
from app.models.weapon import Weapon
from app.services import gcsim_keys

if TYPE_CHECKING:
    from collections.abc import Sequence

BASE = "https://keqingmains.com"
OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "kqm" / "weapons.json"

#: The heading that starts the weapons section. Found by **anchor**, not by counting tables:
#: the Nahida guide's weapons table is the twelfth on the page, and a positional read would
#: silently return artifact recommendations the day a guide gains a table above it.
_WEAPONS_ANCHOR = re.compile(r'id="Weapons"', re.I)
_TABLE = re.compile(r"<table.*?</table>", re.S | re.I)
_ROW = re.compile(r"<tr.*?</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh].*?</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
#: A weapons row is a weapon and a note. Fewer columns is a different table.
_WEAPON_AND_NOTE = 2
#: `A Thousand Floating Dreams (TFD)` — the parenthetical is KQM's abbreviation, not a name.
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")
#: `R5 Festering Desire` — KQM states a refinement for some entries. Captured as data rather
#: than discarded: "R5 Festering Desire" and "Festering Desire" are different recommendations.
_REFINEMENT = re.compile(r"^R([1-5])\s+")
#: A row listing several weapons in one cell — `The Widsith, Lost Prayer…, Solar Pearl` or
#: `Iron Sting & Toukabou Shigure`. Both separators appear in real guides.
#: Split, and **all or nothing**: if any part fails to resolve the whole row is refused, so a
#: partial split can never publish two of three recommendations as though that were the list.
_SEPARATOR = re.compile(r",\s+|\s+&\s+")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", fragment))).strip()


def weapons_table(page: str) -> str | None:
    """The first table after the Weapons anchor, or None if the page has no such section."""
    anchor = _WEAPONS_ANCHOR.search(page)
    if anchor is None:
        return None
    found = _TABLE.search(page, anchor.end())
    return found.group(0) if found is not None else None


def rows_of(table: str) -> list[tuple[str, str]]:
    """`(weapon cell, note)` for each body row, in the order the page lists them.

    A header row is skipped rather than refused. Some guides give the table a `Weapon` header
    and some do not, and reporting "'Weapon' is not a weapon in this catalogue" would be a
    false positive — which is how a refusal list stops being read.
    """
    out: list[tuple[str, str]] = []
    for row in _ROW.findall(table):
        if "<th" in row.lower():
            continue
        cells = [_text(cell) for cell in _CELL.findall(row)]
        if len(cells) < _WEAPON_AND_NOTE or not cells[0]:
            continue
        # Some guides write the header in `<td>`. Skipped by content, narrowly: a row whose
        # first cell is the literal word is a header, and reporting "'Weapon' is not a weapon
        # in this catalogue" is a false positive — which is how a refusal list stops being read.
        if cells[0].strip().lower() in {"weapon", "weapons"}:
            continue
        out.append((cells[0], cells[1]))
    return out


def named(cell: str) -> list[tuple[str, int | None]]:
    """`(name, refinement)` for every weapon a cell names.

    Two mechanical transforms, and neither is a guess: `A Thousand Floating Dreams (TFD)` loses
    KQM's own abbreviation, and `R5 Festering Desire` keeps its refinement as a number instead
    of inside the name. A cell naming several weapons splits on commas.
    """
    found: list[tuple[str, int | None]] = []
    for part in _SEPARATOR.split(cell):
        name = _PARENTHETICAL.sub("", part).strip()
        refinement = _REFINEMENT.match(name)
        if refinement is not None:
            name = _REFINEMENT.sub("", name).strip()
            found.append((name, int(refinement.group(1))))
        else:
            found.append((name, None))
    return [(name, refine) for name, refine in found if name]


async def catalogue() -> dict[str, tuple[str, str]]:
    """`normalised name -> (weapon id, name)` for every weapon this repo knows."""
    async with async_session_factory() as session:
        rows = (await session.execute(select(Weapon))).scalars().all()
    return {gcsim_keys.normalise(w.name): (str(w.id), w.name) for w in rows}


async def characters() -> dict[str, tuple[str, str]]:
    """`normalised name -> (nanoka id, name)` for every character this repo knows."""
    async with async_session_factory() as session:
        rows = (await session.execute(select(Character))).scalars().all()
    return {gcsim_keys.normalise(c.name): (c.nanoka_id, c.name) for c in rows}


def split_target(argument: str) -> tuple[str, str]:
    """`nahida` or `kazuha=Kaedehara Kazuha` → `(slug, character name)`.

    **A guide's slug is not always the character's name**, and guessing the difference is the
    whole failure mode this file exists to avoid: KQM's Kazuha guide is `/kazuha/` and the
    character is *Kaedehara Kazuha*. So the mapping is stated by whoever runs the capture, and
    a name that does not resolve refuses rather than being approximated.
    """
    slug, _, name = argument.partition("=")
    return slug.strip(), (name.strip() or slug.strip())


async def capture(targets: Sequence[str]) -> dict[str, Any]:
    """Fetch each guide and build the snapshot, recording every refusal."""
    roster = await characters()
    known = await catalogue()
    captured: dict[str, Any] = {}
    refused: list[str] = []

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for argument in targets:
            slug, character_name = split_target(argument)
            person = roster.get(gcsim_keys.normalise(character_name))
            if person is None:
                refused.append(
                    f"{slug}: no character named {character_name!r}. "
                    f"Pass `slug=Character Name` when the guide's slug differs.",
                )
                continue
            nanoka_id, canonical_character = person
            url = f"{BASE}/{slug}/"
            response = await client.get(url)
            if response.status_code != httpx.codes.OK:
                refused.append(f"{slug}: HTTP {response.status_code}")
                continue

            table = weapons_table(response.text)
            if table is None:
                # **Refused, not skipped quietly.** A guide whose shape changed would otherwise
                # drop out of the snapshot and look like a character nobody recommends weapons
                # for, which is a different and wrong claim.
                refused.append(f"{slug}: no Weapons section found at {url}")
                continue

            entries = []
            for position, (cell, note) in enumerate(rows_of(table), start=1):
                parts = named(cell)
                resolved = [(n, r, known.get(gcsim_keys.normalise(n))) for n, r in parts]
                if any(match is None for _, _, match in resolved):
                    # **All or nothing per row.** Publishing two of a row's three weapons would
                    # present a partial split as though it were KQM's list.
                    missing = [n for n, _, match in resolved if match is None]
                    refused.append(
                        f"{slug}: {cell!r} — {missing} not in this catalogue",
                    )
                    continue
                for name, refinement, match in resolved:
                    if match is None:  # pragma: no cover — the check above excludes this
                        continue
                    weapon_id, canonical = match
                    entries.append({
                        "position": position,
                        "weapon_id": weapon_id,
                        "weapon_name": canonical,
                        "as_written": name,
                        "refinement": refinement,
                        "note": note,
                    })
            if entries:
                captured[nanoka_id] = {
                    "slug": slug,
                    "character": canonical_character,
                    "url": url,
                    "weapons": entries,
                }

    return {
        "source": "KeqingMains",
        "retrieved_at": datetime.now(UTC).date().isoformat(),
        "characters": captured,
        # Kept in the file. An exclusion that deletes its own evidence reads as an oversight to
        # the next person and cannot be reviewed.
        "refused": refused,
    }


def main() -> None:
    """Fetch each guide, write the snapshot, and print what was refused."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets", nargs="+",
        help="guide slugs, or slug=Character Name when they differ (kazuha=Kaedehara Kazuha)",
    )
    args = parser.parse_args()

    snapshot = asyncio.run(capture(args.targets))
    if not snapshot["characters"]:
        sys.stderr.write("captured nothing; refusing to write an empty snapshot\n")
        for line in snapshot["refused"]:
            sys.stderr.write(f"  {line}\n")
        raise SystemExit(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    for entry in snapshot["characters"].values():
        print(f"{entry['character']}: {len(entry['weapons'])} weapons")
    for line in snapshot["refused"]:
        print(f"refused: {line}")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
