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
import difflib
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
from app.models.artifact import ArtifactSet
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
#: Guides spell the section two ways — `id="Weapons"` on most, `id="Weapons_and_Artifacts"`
#: on Bennett, Zhongli and Raiden among others. Anchored on both, still by **name** rather
#: than by counting tables, so a guide that gains a table above this one does not silently
#: hand back its artifact recommendations instead.
#: Guides decorate the heading and the id carries the decoration: `id="Weapons"` on most,
#: `id="Weapons_and_Artifacts"` on Bennett, `id="%E2%80%BB_Weapons_%E2%80%BB"` on Raiden
#: — reference marks, URL-encoded. So the id must *contain the word* `Weapons` rather
#: than equal it.
#:
#: Still by name and never by position. The original reason stands: Nahida's weapons
#: table is the twelfth on the page, so counting tables would one day hand back artifact
#: recommendations instead and look like it had worked.
_WEAPONS_ANCHOR = re.compile(r'id="[^"]*(?<![A-Za-z])Weapons(?![A-Za-z])[^"]*"', re.I)
_TABLE = re.compile(r"<table.*?</table>", re.S | re.I)
_ROW = re.compile(r"<tr.*?</tr>", re.S | re.I)
#: Any heading, for labelling a full guide's tables with the playstyle above them.
_HEADING = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.S | re.I)
#: A relative-DPS cell is a **bare** percentage, give or take a `~` or a range.
#: `"%" in cell` was the first test and it matched a weapon's stat line —
#: `674 ATK 44.1% CDMG 5*` — which then sat in a field called `relative_dps`
#: claiming to be KQM's comparison. A number KQM did not publish is worse than
#: no number at all.
_PERCENT_ONLY = re.compile(
    "^[~\u2248]?\\s*\\d+(?:\\.\\d+)?\\s*%"
    "(?:\\s*[-\u2013]\\s*\\d+(?:\\.\\d+)?\\s*%)?$",
)
_CELL = re.compile(r"<t[dh].*?</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
#: What a guide calls the weapon column. Used to find it and to skip a header written
#: in `<td>` rather than `<th>`.
_WEAPON_HEADERS = frozenset({"weapon", "weapons"})
#: What a guide calls the artifact column. Same tables, same two shapes, different
#: word — so the finder and the row reader take the header set rather than assuming
#: one. Sets are the other half of the tiering the owner asked for.
#: `4pc Golden Troupe`, `2pc/4pc Tenacity of the Millelith` — KQM writes the piece
#: count in front of the name. It is data rather than noise (a 2-piece and a 4-piece
#: of the same set are different recommendations) and it blocks the name match while
#: it is part of the name.
#: `5★ Mistsplitter Reforged`, `4★ Finale of the Deep`, `3* Harbinger of Dawn`. KQM leads
#: with the rarity on many guides, and it was the largest single class of refusal in the
#: first roster-wide run — 167 of them, every one a name that matches perfectly without it.
_RARITY = re.compile("^[1-5]\\s*[\u2605*\u2606]\\s*")
_PIECES = re.compile(r"^((?:[24]pc)(?:\s*/\s*[24]pc)?)\s+", re.I)

#: A trailing `(EoSF)`, `(1 Stack)`, `(4Husk)` — KQM's qualifier, not part of the set's name.
#: Stripped only after the name as written fails to resolve; `as_written` keeps it verbatim.
_QUALIFIER = re.compile(r"\s*\([^)]*\)\s*$")
_SET_HEADERS = frozenset({"artifact", "artifacts", "artifact set", "artifact sets", "set"})
#: `A Thousand Floating Dreams (TFD)` — the parenthetical is KQM's abbreviation, not a name.
#: Anywhere, not only at the end. `Staff of (T)Homa` puts KQM's aside in the middle of the
#: name, and a trailing-only strip left it unresolvable. No weapon in this catalogue has a
#: parenthesis in its name, so removing them all costs nothing.
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*")
#: `R5 Festering Desire` — KQM states a refinement for some entries. Captured as data rather
#: than discarded: "R5 Festering Desire" and "Festering Desire" are different recommendations.
#: Leading, and a range too: `R1-R5 Favonius Warbow`.
_REFINEMENT = re.compile("^R\\s?([1-5])(?:\\s*[-\u2013]\\s*R?[1-5])?\\+?\\s+")

#: KQM writes the refinement on **either** side — `R5 Festering Desire` on one guide and
#: `Staff of Homa R1` on the next. Only the prefix was handled, and the suffix was the single
#: cause of nearly every refusal in the first wide run: `Dragon's Bane R1` does not reduce to
#: `Dragon's Bane`, so a name that would have matched perfectly was reported as unknown.
#: A range is as common as a single value — `Favonius Lance R1-R5`, `Fav Lance R1-5`.
#: Both mean "at any refinement", and with the refinement dropped either way the
#: only job left is to stop it being read as part of the name.
#: Trailing, with everything KQM writes after it: a range, a `+`, a space inside `R 1`, and
#: a condition — `Staff of Homa R1 <50% HP`, `Lithic Spear R1 1 Stack`, `Sacrificial Sword
#: R3+`. The refinement is dropped either way, so the only job is to stop the tail being
#: read as part of the name.
_REFINEMENT_SUFFIX = re.compile(
    "\\s+R\\s?([1-5])(?:\\s*[-\u2013]\\s*R?[1-5])?\\+?(?:\\s+.*)?$",
)
#: A row listing several weapons in one cell — `The Widsith, Lost Prayer…, Solar Pearl` or
#: `Iron Sting & Toukabou Shigure`. Both separators appear in real guides.
#: Split, and **all or nothing**: if any part fails to resolve the whole row is refused, so a
#: partial split can never publish two of three recommendations as though that were the list.
#: `and` joins two weapons as often as `&` does — `Sac and Favonius` is two.
#: KQM joins alternatives four ways. `or` and `/` were missing, so
#: `Light of Foliar Incision or Haran Geppaku Futsu` and `Prototype Archaic / Luxurious
#: Sea-Lord` were each read as one impossible weapon name.
_SEPARATOR = re.compile(r",\s*|\s+&\s+|\s+and\s+|\s+or\s+|\s*/\s*")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", fragment))).strip()


def tables_headed(page: str, headers: frozenset[str]) -> list[tuple[str, str]]:
    """Every weapons table on a guide, as `(section heading, table)`.

    **A full guide has several, and all of them count.** Owner, 2026-09-02: *"He also has stat
    tables for each playstyle, include all"* — Zhongli's guide recommends per playstyle, so one
    flattened list would attribute to "Zhongli" a ranking KQM wrote for *Burst Support
    Zhongli*. That is the same misattribution as an uncited recommendation, one level down.

    **Found by the table's own header, not by an anchor.** The anchor worked for quick guides
    and produced three different spellings before it stopped working at all: `Weapons`,
    `Weapons_and_Artifacts`, and `※ Weapons ※` URL-encoded. A full guide's tables sit under
    playstyle headings that do not mention weapons, so the reliable signal is the table saying
    `Weapon` at the top of its first column — which is what makes it a weapons table.
    """
    anchored = []
    for anchor in (_WEAPONS_ANCHOR.finditer(page) if headers == _WEAPON_HEADERS else []):
        table = _TABLE.search(page, anchor.end())
        if table is not None:
            anchored.append((_section_before(page, table.start()), table.group(0)))
    if anchored:
        return anchored

    # **The fallback, and only that.** Reading every table with a `Weapon` header found
    # Zhongli's playstyle tables, and also found Ganyu's team-build tables and lost Nilou's,
    # whose header is spelled differently. The anchor is the precise signal where it exists;
    # this is for the full guides where it does not.
    found: list[tuple[str, str]] = []
    for match in _TABLE.finditer(page):
        table = match.group(0)
        first = _ROW.search(table)
        if first is None:
            continue
        cells = [_text(cell) for cell in _CELL.findall(first.group(0))]
        if not cells or cells[0].strip().lower() not in headers:
            continue
        found.append((_section_before(page, match.start()), table))
    return found


def _section_before(page: str, offset: int) -> str:
    """The playstyle a table belongs to, or `""` on a guide that has only one.

    **One level up from the section heading.** A full guide nests
    `h3 Shield Bot` → `h4 Weapons` → the table, so the *nearest* heading is always the word
    "Weapons" and labelling by it made all forty-six of Zhongli's recommendations say the same
    thing. The playstyle is the nearest heading above that one with a smaller level.
    """
    headings = [(int(m.group(1)), _text(m.group(2))) for m in _HEADING.finditer(page, 0, offset)]
    if not headings:
        return ""
    level = headings[-1][0]
    for depth, text in reversed(headings[:-1]):
        if depth < level:
            return text
    return ""


def rows_of(
    table: str, headers: frozenset[str] = frozenset(_WEAPON_HEADERS),
) -> list[tuple[str, str, str]]:
    """`(weapon cell, note, percent)` for each body row, in the order the page lists them.

    A header row is skipped rather than refused. Some guides give the table a `Weapon` header
    and some do not, and reporting "'Weapon' is not a weapon in this catalogue" would be a
    false positive — which is how a refusal list stops being read.
    """
    rows = _ROW.findall(table)
    # **Which column holds the weapon is read off the header, not assumed to be the first.**
    # Raiden's table is `Weapon Image | Weapon | % | Notes`, so column zero is an `<img>` whose
    # text is empty — and every row was skipped as blank, leaving a table that was found and
    # yielded nothing.
    column = 0
    for row in rows:
        cells = [_text(cell) for cell in _CELL.findall(row)]
        named_at = [i for i, cell in enumerate(cells) if cell.strip().lower() in headers]
        if named_at:
            column = named_at[0]
            break

    out: list[tuple[str, str, str]] = []
    for row in rows:
        if "<th" in row.lower():
            continue
        cells = [_text(cell) for cell in _CELL.findall(row)]
        if len(cells) <= column or not cells[column].strip():
            continue
        # Some guides write the header in `<td>`. Skipped by content, narrowly: a row whose
        # weapon cell is the literal word is a header, and reporting "'Weapon' is not a weapon
        # in this catalogue" is a false positive — which is how a refusal list stops being read.
        if cells[column].strip().lower() in headers:
            continue
        # **Two shapes.** A quick guide's table is `weapon | note`. A full guide's adds a
        # percentage against a named baseline, and reading that as the note stored `"119.6%"`
        # as KQM's sentence about the weapon. The note is the last cell either way.
        rest = cells[column + 1:]
        percent = (
            rest[0].strip()
            if len(rest) > 1 and _PERCENT_ONLY.match(rest[0].strip())
            else ""
        )
        note = rest[-1].strip() if rest else ""
        out.append((cells[column], note, percent))
    return out


def named(cell: str) -> list[tuple[str, int | None]]:
    """`(name, refinement)` for every weapon a cell names.

    Three mechanical transforms, and none is a guess: `A Thousand Floating Dreams (TFD)` loses
    KQM's own abbreviation, and a refinement written on **either** side — `R5 Festering
    Desire` or `Staff of Homa R1` — becomes a number instead of part of the name. A cell
    naming several weapons splits on commas.
    """
    found: list[tuple[str, int | None]] = []
    # **Stripped before the split, not after.** `Vortex Vanquisher R1 (Dynamic Buff, Shielded)`
    # has a comma *inside* KQM's parenthetical, so splitting first tore one weapon into two
    # fragments and refused both.
    for part in _SEPARATOR.split(_PARENTHETICAL.sub(" ", cell.strip())):
        name = _RARITY.sub("", _PARENTHETICAL.sub("", part).strip()).strip()
        prefix = _REFINEMENT.match(name)
        suffix = _REFINEMENT_SUFFIX.search(name)
        if prefix is not None:
            found.append((_REFINEMENT.sub("", name).strip(), int(prefix.group(1))))
        elif suffix is not None:
            found.append((_REFINEMENT_SUFFIX.sub("", name).strip(), int(suffix.group(1))))
        else:
            found.append((name, None))
    return [(name, refine) for name, refine in found if name]


#: Seconds between guides. Polite rather than tuned — see `capture`.
FETCH_DELAY_SECONDS = 1.0

#: How close a catalogue name has to be before it is worth showing as "did you mean". Above
#: this the nearest thing is noise and naming it would send a reader to check a coincidence.
_SUGGEST_RATIO = 0.6


def _why(name: str, matches: list[tuple[int, str]], pool: dict[str, tuple[int, str]]) -> str:
    """Why one cell could not be resolved, in the form its answer takes.

    Ambiguity and absence are different questions and get different sentences: one asks *which
    of these*, the other asks *what is this*.
    """
    if len(matches) > 1:
        names = sorted(canonical for _, canonical in matches)
        return f"{name!r} matches {len(names)} weapons this character can hold: {names}"
    return _nearest(name, pool)


def _nearest(name: str, known: dict[str, tuple[int, str]]) -> str:
    """A refusal that names the closest catalogue entry, so it can be answered rather than chased.

    **The suggestion is never applied.** Owner, 2026-09-02: *"If you really can't resolve any
    abbreviations or names, you can pass them by me."* — so this is an escalation, and its job
    is to make the ruling cheap. `Sacrificial Jade` against a catalogue holding `Sacrificial
    Fragments` should say so; a name with nothing near it should say that too, rather than
    offer a coincidence.

    Automatic fuzzy matching is exactly how a fabricated citation gets written, which
    `CLAUDE.md` names as fairy's worst failure. This suggests; a human decides.
    """
    target = gcsim_keys.normalise(name)
    best = difflib.get_close_matches(target, known.keys(), n=1, cutoff=_SUGGEST_RATIO)
    if not best:
        return f"{name!r} is in no catalogue entry, and nothing is close to it"
    return f"{name!r} is not in this catalogue — did you mean {known[best[0]][1]!r}?"


def _tokens(name: str) -> list[str]:
    """A name's words, lowercased, with punctuation gone. `"The Catch"` → `['the', 'catch']`."""
    return [word for word in re.split(r"[^A-Za-z0-9]+", name.lower()) if word]


def resolve(name: str, pool: dict[str, tuple[int, str]]) -> list[tuple[int, str]]:
    """Every weapon in *pool* that *name* can mean. One is a resolution; more is a refusal.

    **The pool is the character's own weapon class**, and that is most of the work. `Blackcliff`
    names five weapons in the catalogue and exactly one a sword user can hold — and until this
    was scoped, the suggestion offered for Bennett was `Blackcliff Pole`, which is wrong in a
    way that a human confirming suggestions would eventually have rubber-stamped.

    Beyond an exact match, one rule: **KQM's words must be an in-order subsequence of the
    catalogue name's words, each matching as a prefix.** That is what the shorthand on these
    pages actually is —

        Fav Lance              → Favonius Lance
        Mistsplitter           → Mistsplitter Reforged
        Haran                  → Haran Geppaku Futsu
        Alley Flash            → The Alley Flash
        Staff of Scarlet Sands → Staff of the Scarlet Sands

    — and it is a rule rather than a guess: it never reorders, never drops a word KQM wrote,
    and never invents one. Ambiguity is a **refusal**, not a coin flip, so a shorthand naming
    two weapons in the class comes to a human instead of picking one.
    """
    exact = pool.get(gcsim_keys.normalise(name))
    if exact is not None:
        return [exact]
    wanted = _tokens(name)
    if not wanted:
        return []
    matches = []
    for nanoka_id, canonical in pool.values():
        have = _tokens(canonical)
        index = 0
        for word in wanted:
            while index < len(have) and not have[index].startswith(word):
                index += 1
            if index == len(have):
                break
            index += 1
        else:
            matches.append((nanoka_id, canonical))
    return matches


async def set_catalogue() -> dict[str, tuple[int, str]]:
    """`normalised name -> (nanoka id, name)` for every artifact set this repo knows.

    Not split by class the way weapons are: a set has no weapon type, and any character can
    wear any of them. The **nanoka** id for the reason `weapon_catalogue` gives.
    """
    async with async_session_factory() as session:
        rows = (await session.execute(select(ArtifactSet))).scalars().all()
    return {gcsim_keys.normalise(s.name): (s.nanoka_id, s.name) for s in rows}


async def catalogue() -> dict[str, dict[str, tuple[int, str]]]:
    """`weapon type -> normalised name -> (nanoka id, name)`.

    Split by class because a recommendation is for a character, and a character holds one
    class. Matching against all 260 weapons is what made `Blackcliff` ambiguous and
    `Blackcliff Pole` the suggested answer for a sword user.
    """
    async with async_session_factory() as session:
        rows = (await session.execute(select(Weapon))).scalars().all()
    by_type: dict[str, dict[str, tuple[int, str]]] = {}
    for weapon in rows:
        key = str(getattr(weapon.weapon_type, "value", weapon.weapon_type))
        # **The game's id, not the row's.** A row id is minted per insert, so capturing one
        # would make this snapshot a set of pointers into whichever database the capture ran
        # against — which is exactly what it was until 2026-09-04, and zero of the 205 ids
        # existed in production. `docs/RESEARCH_kqm_not_reaching_the_ui.md`.
        by_type.setdefault(key, {})[gcsim_keys.normalise(weapon.name)] = (
            weapon.nanoka_id, weapon.name,
        )
    return by_type


async def characters() -> dict[str, tuple[str, str, str]]:
    """`normalised name -> (nanoka id, name, weapon type)`.

    The weapon type rides along because it is what scopes the match — see `resolve`.
    """
    async with async_session_factory() as session:
        rows = (await session.execute(select(Character))).scalars().all()
    return {
        gcsim_keys.normalise(c.name): (
            c.nanoka_id, c.name, str(getattr(c.weapon_type, "value", c.weapon_type)),
        )
        for c in rows
    }


def split_target(argument: str) -> tuple[str, str]:
    """`nahida` or `kazuha=Kaedehara Kazuha` → `(slug, character name)`.

    **A guide's slug is not always the character's name**, and guessing the difference is the
    whole failure mode this file exists to avoid: KQM's Kazuha guide is `/kazuha/` and the
    character is *Kaedehara Kazuha*. So the mapping is stated by whoever runs the capture, and
    a name that does not resolve refuses rather than being approximated.
    """
    slug, _, name = argument.partition("=")
    return slug.strip(), (name.strip() or slug.strip())


def _entries_of(
    table: str, pool: dict[str, tuple[int, str]], section: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    """One guide's weapons table, resolved — and every row it could not resolve.

    Lifted out of `capture` so that the fetch loop reads as fetch-and-record and this reads as
    the resolution rules, which are the part with the argument in them.
    """
    entries: list[dict[str, Any]] = []
    refusals: list[str] = []
    for position, (cell, note, percent) in enumerate(rows_of(table), start=1):
        found = [(name, resolve(name, pool)) for name, _refinement in named(cell)]
        if any(len(matches) != 1 for _, matches in found):
            # **All or nothing per row.** Publishing two of a row's three weapons would present
            # a partial split as though it were KQM's list.
            refusals.append(
                f"{cell!r} — "
                + "; ".join(_why(n, m, pool) for n, m in found if len(m) != 1),
            )
            continue
        if not note.strip():
            # **A recommendation without KQM's words is an uncited one.** `note` is the
            # citation — the sentence that makes this KQM's judgement rather than this repo's —
            # and one guide has a row whose note cell is empty. Refused rather than published
            # with a blank, which would read as "KQM said nothing about this" when what
            # happened is that the capture found nothing to quote.
            refusals.append(f"{cell!r} — KQM's note cell is empty, so there is nothing to cite")
            continue
        for _name, matches in found:
            weapon_nanoka_id, canonical = matches[0]
            # **The refinement is stripped and not stored.** Owner, 2026-09-02: *"you can strip
            # out refinement, the user can specify the refinement they have."* It is read off
            # the weapon they own, so a captured `R5` would be a number from somebody else's
            # account sitting in a field nothing consults. KQM's own sentence still says it, in
            # `note`, where it is a citation rather than a claim about this user's inventory.
            entries.append({
                "position": position,
                "weapon_nanoka_id": weapon_nanoka_id,
                "weapon_name": canonical,
                "as_written": _name,
                "note": note,
                # Present only when KQM published one. A full guide states each weapon as a
                # percentage of a named baseline; a quick guide states an order and no number,
                # and inventing one for it would be putting a figure in KQM's mouth.
                **({"relative_dps": percent} if percent else {}),
                **({"playstyle": section} if section else {}),
            })

    # **Deduplicated, keeping the better position.** Guides list the same weapon twice —
    # `Deathmatch R5` high and `Deathmatch R1` lower — which was two rows while the refinement
    # was part of the name and is one weapon now that it is not. The earlier row wins, because
    # KQM's order is the recommendation.
    seen: dict[int, dict[str, Any]] = {}
    for entry in entries:
        seen.setdefault(entry["weapon_nanoka_id"], entry)
    return list(seen.values()), refusals


def _sets_of(
    table: str, pool: dict[str, tuple[int, str]], section: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    """One guide's artifact-set table, resolved — and every row it could not name.

    **A row that is not a named set is kept and not mapped.** `2pc HP% / Skill% / ER / Hydro%`
    describes a two-piece by the stat it grants, not by a set, and resolving it to a catalogue
    id would be inventing a name KQM did not write. It is recorded as `kind: "stat"` with the
    text KQM used, and the UI colours the 2-piece selector from it — every set whose two-piece
    grants that stat, which this catalogue already knows.

    A refusal here is quieter than in the weapons table on purpose: a set table's rows are
    prose as often as they are names, so an unmatched row is the normal case rather than a
    failure to chase.
    """
    entries: list[dict[str, Any]] = []
    refusals: list[str] = []
    for position, (cell, note, percent) in enumerate(rows_of(table, _SET_HEADERS), start=1):
        if not note.strip():
            refusals.append(f"{cell!r} — KQM's note cell is empty, so there is nothing to cite")
            continue
        pieces_match = _PIECES.match(cell.strip())
        bare = _PIECES.sub("", cell.strip()) if pieces_match else cell.strip()
        matches = resolve(bare, pool)
        if not matches:
            # **A trailing qualifier is not part of the name.** `resolve` requires every word
            # KQM wrote to match a word of the catalogue name, which is right — it is what
            # stops a shorthand being stretched onto the wrong weapon — and it means an
            # abbreviation or a stack count in brackets sinks the whole row:
            #
            #     4pc Emblem of Severed Fate (EoSF)      4pc Gilded Dreams (3 Stack EM)
            #     4pc Crimson Witch of Flames (1 Stack)  4pc Husk of Opulent Dreams (4Husk)
            #
            # **47 rows across the captured guides were filed as stat descriptions for this**,
            # so a quarter of the set half named a set and did not say so. Tried second, never
            # instead: a row that resolves as written is never re-read, and `resolve` still
            # refuses ambiguity, so this widens what can be recognised without loosening what
            # counts as a match.
            matches = resolve(_QUALIFIER.sub("", bare).strip(), pool)
        entry: dict[str, Any] = {
            "position": position,
            "as_written": cell.strip(),
            "note": note,
            **({"pieces": pieces_match.group(1).lower()} if pieces_match else {}),
            **({"relative_dps": percent} if percent else {}),
            **({"playstyle": section} if section else {}),
        }
        if len(matches) == 1:
            set_nanoka_id, canonical = matches[0]
            entry |= {
                "kind": "set", "set_nanoka_id": set_nanoka_id, "set_name": canonical,
            }
        else:
            # Not a name this catalogue holds, and not treated as one. The text is the claim.
            entry |= {"kind": "stat"}
        entries.append(entry)
    return entries, refusals


async def _guide_for(
    client: httpx.AsyncClient, slug: str,
) -> tuple[str, httpx.Response | None, list[tuple[str, str]]]:
    """The guide page for a character, and its weapons tables.

    **Two URLs, because KQM has two kinds of guide.** `/{slug}/` is the full guide, which older
    characters have; for everyone else it is a stub with no tables at all — Alhaitham's is
    138 KB of scripts and no recommendation in sight — that links to
    `/q/{slug}-quickguide/`, where the guide actually lives. Fifty-five characters came back as
    "no weapons table found" for exactly this reason.

    The full guide is tried first because where both exist it is the richer one: it recommends
    per playstyle and publishes a percentage.
    """
    url, response, tables = "", None, []
    for index, candidate in enumerate((f"{BASE}/{slug}/", f"{BASE}/q/{slug}-quickguide/")):
        if index:
            await asyncio.sleep(FETCH_DELAY_SECONDS)
        attempt = await client.get(candidate)
        if attempt.status_code != httpx.codes.OK:
            continue
        found = tables_headed(attempt.text, _WEAPON_HEADERS)
        if found:
            return candidate, attempt, found
        if response is None:
            url, response = candidate, attempt
    return url, response, tables


async def capture(targets: Sequence[str]) -> dict[str, Any]:
    """Fetch each guide and build the snapshot, recording every refusal."""
    roster = await characters()
    known = await catalogue()
    sets_known = await set_catalogue()
    captured: dict[str, Any] = {}
    refused: list[str] = []

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for index, argument in enumerate(targets):
            # **A guide at a time, with a pause.** Three characters was a handful of
            # requests; the roster is around a hundred and fifty, and a hundred and fifty
            # requests as fast as httpx can issue them is not a thing to do to somebody
            # else's site. This runs once and the output is committed, so the wait costs
            # nothing anybody is waiting on.
            if index:
                await asyncio.sleep(FETCH_DELAY_SECONDS)
            slug, character_name = split_target(argument)
            person = roster.get(gcsim_keys.normalise(character_name))
            if person is None:
                refused.append(
                    f"{slug}: no character named {character_name!r}. "
                    f"Pass `slug=Character Name` when the guide's slug differs.",
                )
                continue
            nanoka_id, canonical_character, weapon_type = person
            pool = known.get(weapon_type, {})
            url, response, tables = await _guide_for(client, slug)
            if response is None:
                refused.append(f"{slug}: no guide at {BASE}/{slug}/ or its quick guide")
                continue
            if not tables:
                # **Refused, not skipped quietly.** A guide whose shape changed would otherwise
                # drop out of the snapshot and look like a character nobody recommends weapons
                # for, which is a different and wrong claim.
                refused.append(f"{slug}: no weapons table found at {url}")
                continue

            entries: list[dict[str, Any]] = []
            for section, table in tables:
                rows, row_refusals = _entries_of(table, pool, section)
                if not rows:
                    # **A table where nothing resolved was not a weapons table.** The fallback
                    # finder matches any table headed `Weapon`, and some guides head a team or
                    # a stat table that way — so `1st Rotation`, `ATK%`, `Any` and `Barbara`
                    # arrived as unresolvable weapon names, 98 of them in the first roster-wide
                    # run. Reporting each is how a refusal list stops being read. One line for
                    # the table, and its rows are not weapons to refuse.
                    refused.append(
                        f"{slug}: a table headed 'Weapon' under {section or 'no heading'!r} "
                        f"held no weapon this catalogue knows; not treated as a weapons table",
                    )
                    continue
                entries.extend(rows)
                refused.extend(f"{slug}: {line}" for line in row_refusals)

            sets: list[dict[str, Any]] = []
            for section, table in tables_headed(response.text, _SET_HEADERS):
                rows, row_refusals = _sets_of(table, sets_known, section)
                sets.extend(rows)
                refused.extend(f"{slug} (sets): {line}" for line in row_refusals)

            # **A found table that yields nothing is a refusal, not a skip.** Raiden's guide
            # was dropped from *both* lists by an `if entries:` — captured nowhere, refused
            # nowhere, and so invisible in a run that otherwise looked complete.
            if not entries:
                refused.append(
                    f"{slug}: {len(tables)} weapons table(s) found at {url}, and no row in any "
                    f"of them resolved to a weapon.",
                )
            if entries:
                captured[nanoka_id] = {
                    "slug": slug,
                    "character": canonical_character,
                    "url": url,
                    "weapons": entries,
                    "sets": sets,
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

    # **Merged, not replaced.** `OUT.write_text` used to publish whatever this run captured,
    # so re-running for one character would delete the other hundred and forty-nine — silently,
    # because the file would still be valid and still look like a snapshot. Every character the
    # run touched is refreshed; every character it did not is kept.
    merged = snapshot
    if OUT.exists():
        previous = json.loads(OUT.read_text())
        kept = {
            nanoka_id: entry
            for nanoka_id, entry in previous.get("characters", {}).items()
            if nanoka_id not in snapshot["characters"]
        }
        merged = {**snapshot, "characters": {**kept, **snapshot["characters"]}}
        if kept:
            print(f"kept {len(kept)} character(s) this run did not touch")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    for entry in merged["characters"].values():
        print(f"{entry['character']}: {len(entry['weapons'])} weapons")
    for line in snapshot["refused"]:
        print(f"refused: {line}")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
