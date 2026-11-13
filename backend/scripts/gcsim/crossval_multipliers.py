"""Check our parsed talent multipliers against gcsim's. `TASKS_multipliers.md` M.4.

    cd backend && python -m scripts.gcsim.crossval_multipliers          # the seeded database
    cd backend && python -m scripts.gcsim.crossval_multipliers --fixtures

**Why this is not an ordinary test.** `app/services/talent_scaling.py` decides which rows are
damage by asking whether the label contains `DMG` — a heuristic over English text. gcsim
implements the same characters from the same source independently, so agreeing with it turns
that heuristic into a checked claim. A heuristic that agrees with an independent
implementation across a hundred characters is not resting on the heuristic.

It has already earned its keep. The first run found the parser **summing** `{a}+{b}` when
gcsim keeps the parts as separate tables — Venti's `1-Hit DMG|{param1}+{param1}` is two arrows
of 0.20382, not one hit of 0.40764 — and summing applies crit and DEF once to a doubled
figure. It also identified `Elemental Mastery-Based Swirl DMG Increase` as a coefficient
rather than a hit (gcsim's comment for it ends `per Point`), and settled that a repeat binds
to the alternative it follows, from how gcsim models Clorinde's three lunges.

## What counts as agreement

Compared per `(action, label)`, because a character's skill and burst can share a label —
Rosaria's are both `Skill DMG`, and keying on the label alone silently compares one against
the other.

**Alternatives need only one match.** `{a}/{b}` is a low plunge against a high plunge, and
gcsim sometimes implements only one of them: Venti has `highPlunge` and no `lowPlunge`, Chasca
the reverse. Requiring both would report a coverage difference as a disagreement.

**A hit with no gcsim table is not a failure.** gcsim does not model every published row. It
is counted and reported, because a number that quietly grew would mean the comparison had
stopped comparing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.formula.genshin.damage import ScalingStat
from app.models.character import Character, Talent
from app.models.enums import TalentType
from app.services import gcsim_keys
from app.services.talent_scaling import (
    TalentScalingError,
    classify_talent_row,
    parse_talent_row,
)

REPO = Path(__file__).resolve().parents[3]
SNAPSHOT = REPO / "backend" / "app" / "data" / "gcsim" / "talent_multipliers.json"
FIXTURES = REPO / "backend" / "tests" / "fixtures" / "nanoka_gi" / "detail"

#: Our talent types, in gcsim's action vocabulary. An alternate sprint has no gcsim action and
#: is deliberately absent rather than mapped to something close.
ACTION_FOR = {
    TalentType.NORMAL_ATTACK: "attack",
    TalentType.ELEMENTAL_SKILL: "skill",
    TalentType.ELEMENTAL_BURST: "burst",
}

#: Multipliers are published to six decimals; this is far tighter than that and far looser
#: than float equality. A disagreement that mattered would be in the third decimal, not the
#: ninth — the tolerance cannot hide one.
TOLERANCE = 1e-9


@dataclass
class Report:
    """What a comparison found. Counts as well as failures, so a run that stopped comparing
    is visible rather than green."""

    characters: int = 0
    matched: int = 0
    #: Our hits under an `(action, label)` gcsim has no table for. Not a failure.
    uncovered: int = 0
    mismatches: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    #: Hits whose scaling stat was checked against the words gcsim's `tail` carries (P0).
    #: Counted so a check that stopped checking is visible, like `matched`.
    stats_checked: int = 0

    @property
    def ok(self) -> bool:
        """Green only if something was compared **and** nothing disagreed.

        A run that compared nothing is a failure. That is the green-by-absence shape fairy
        shipped a stale golden fixture behind, and the rule this repo states as: a skipped
        check blocks, it is never a pass.
        """
        return not self.mismatches and not self.refusals and self.matched > 0

    def summary(self) -> str:
        """One line naming every bucket, so a number that quietly moved is visible."""
        return (
            f"{self.characters} characters, {self.matched} hits matched, "
            f"{self.uncovered} with no gcsim table, {len(self.mismatches)} mismatched, "
            f"{len(self.refusals)} refused by the parser, "
            f"{self.stats_checked} scaling stats checked against gcsim's tail"
        )


@dataclass(frozen=True)
class CharacterRows:
    """One character's talent rows, in the shape the comparison needs."""

    gcsim_key: str
    name: str
    #: `(gcsim action, level, labels, params)` — one entry per talent level.
    rows: tuple[tuple[str, int, list, list], ...]


def load_snapshot() -> dict:
    """The gcsim tables, from the committed snapshot. Never from a clone at run time."""
    return json.loads(SNAPSHOT.read_text())["characters"]


def compare(characters: list[CharacterRows], snapshot: dict) -> Report:
    """Our hits against gcsim's tables."""
    report = Report()
    for character in characters:
        tables = snapshot.get(character.gcsim_key)
        if not tables:
            continue
        report.characters += 1
        by_key: dict[tuple[str, str], list[dict]] = {}
        for table in tables:
            by_key.setdefault((table["action"], table["label"]), []).append(table)

        for action, level, labels, params in character.rows:
            try:
                hits = parse_talent_row(labels, params)
                unrecognised = [
                    refused for refused in classify_talent_row(labels, params).refused
                    if refused.unrecognised
                ]
            except TalentScalingError as exc:
                report.refusals.append(f"{character.name} L{level}: {exc}")
                continue
            # A tail word the parser has never seen is a refusal *by name*, not a pass: the
            # next patch's vocabulary must arrive red here rather than as a silent gap.
            report.refusals.extend(
                f"{character.name} L{level}: {refused.reason}" for refused in unrecognised
            )

            groups: dict[tuple[str, bool], list] = {}
            for hit in hits:
                groups.setdefault((hit.label, hit.exclusive), []).append(hit)

            for (label, exclusive), members in groups.items():
                candidates = by_key.get((action, label))
                if not candidates:
                    report.uncovered += len(members)
                    continue
                theirs = [
                    table["values"][level - 1]
                    for table in candidates
                    if level - 1 < len(table["values"])
                ]
                # Every term of a mixed-stat hit, not only the first: Nahida's EM half is a
                # table of its own in gcsim, and a parser that misread it must not pass.
                agreed = [
                    all(
                        any(abs(value - multiplier) < TOLERANCE for value in theirs)
                        for multiplier in (
                            hit.multiplier, *(term.multiplier for term in hit.extra_terms),
                        )
                    )
                    for hit in members
                ]
                _check_stats(report, character.name, action, level, members, candidates)
                # Alternatives: gcsim may implement only one of them.
                if any(agreed) if exclusive else all(agreed):
                    report.matched += len(members)
                else:
                    report.mismatches.append(
                        f"{character.name} {action} {label!r} L{level}: "
                        f"ours={[h.multiplier for h in members]} gcsim={theirs}",
                    )
    return report


#: gcsim's tail words, as the payload spells them — the same four the parser reads.
_GCSIM_STAT_WORDS = {
    "ATK": ScalingStat.ATK,
    "Max HP": ScalingStat.HP,
    "DEF": ScalingStat.DEF,
    "Elemental Mastery": ScalingStat.ELEMENTAL_MASTERY,
}

#: A repeat marker, `×3` (U+00D7) or `*4`, which says nothing about the stat.
_REPEAT = re.compile("[\u00d7*]\\s*\\d+")


def tail_stats(tail: str) -> list[ScalingStat] | None:
    """The stats one gcsim table's `tail` names for its own alternative, in order.

    `tail` is the desc text after the table's own param, with other params as `{N}`:
    `"ATK+{3} Elemental Mastery"` is `[ATK, EM]`, `"Max HP ×3"` is `[HP]`. Only the words
    up to the first `/` count — what follows is another alternative.

    `None` when any part carries no stat word (`"+{8} DEF"`, `""`) or a word that is not a
    stat (`"Cryo + {5} Physical"`): the tail then does not say the stat by itself, and
    reading one into it would be re-deriving the parser's inheritance rule rather than
    checking it.
    """
    own = _REPEAT.sub("", tail.split("/", 1)[0]).replace("(", "").replace(")", "")
    words = [re.sub(r"\{\d+\}", "", piece).strip() for piece in own.split("+")]
    if not all(word in _GCSIM_STAT_WORDS for word in words):
        return None
    return [_GCSIM_STAT_WORDS[word] for word in words]


def _check_stats(
    report: Report,
    name: str,
    action: str,
    level: int,
    hits: list,
    tables: list[dict],
) -> None:
    """Each hit's scaling stats against the words gcsim's tail carries for it (P0).

    The parser used to drop the tail, so every hit was ATK; M.4 compared numbers and could
    not see it. A hit is checked when a table with its first multiplier has a tail naming
    every part's stat, and then the parser's `[scaling_stat, *extra_terms]` must be exactly
    that list — Nahida's Tri-Karma is `[ATK, EM]`, not `[ATK]` twice.
    """
    for hit in hits:
        stats = [hit.scaling_stat, *(term.stat for term in hit.extra_terms)]
        for table in tables:
            if level - 1 >= len(table["values"]):
                continue
            if abs(table["values"][level - 1] - hit.multiplier) >= TOLERANCE:
                continue
            theirs = tail_stats(table["tail"])
            if theirs is None:
                continue
            report.stats_checked += 1
            if theirs != stats:
                report.mismatches.append(
                    f"{name} {action} {hit.label!r} L{level}: ours scales off "
                    f"{[str(s) for s in stats]}, gcsim's tail {table['tail']!r} says "
                    f"{[str(s) for s in theirs]}",
                )
            break


def from_fixtures() -> list[CharacterRows]:
    """The committed nanoka payloads. No database, no network."""
    characters = []
    for path in sorted(FIXTURES.glob("character_*.json")):
        payload = json.loads(path.read_text())
        nanoka_id = path.stem.removeprefix("character_")
        try:
            key = gcsim_keys.character_key(nanoka_id, payload["name"], payload.get("element"))
        except gcsim_keys.GcsimKeyError:
            continue
        rows = []
        for skill in payload.get("skills", []):
            promote = skill.get("promote") or {}
            # The icon is on the **level row**, not the skill: `TalentType.from_skill_icon`
            # documents it as `promote["0"].icon`, and reading `skill["icon"]` finds nothing
            # and classifies every talent as unknown — which showed up as "0 characters
            # compared" rather than as an error, because the run is built to fail on that.
            action = ACTION_FOR.get(
                TalentType.from_skill_icon((promote.get("0") or {}).get("icon")),
            )
            if action is None:
                continue
            for raw_level, row in promote.items():
                # The table is published 1-indexed with level 1 at key "0" — the same shift
                # `artifact_main_stat_value` makes, made here for the same reason.
                rows.append((action, int(raw_level) + 1, row.get("desc"), row.get("param")))
        if rows:
            characters.append(
                CharacterRows(gcsim_key=key, name=payload["name"], rows=tuple(rows)),
            )
    return characters


async def from_database() -> list[CharacterRows]:
    """Every seeded character — around a hundred that gcsim also implements."""
    async with async_session_factory() as session:
        found = (
            (
                await session.execute(
                    select(Character).options(
                        selectinload(Character.talents).selectinload(Talent.scalings),
                    ),
                )
            )
            .scalars()
            .unique()
            .all()
        )

    characters = []
    for character in found:
        try:
            key = gcsim_keys.character_key(
                character.nanoka_id, character.name, character.element,
            )
        except gcsim_keys.GcsimKeyError:
            continue
        rows = [
            (action, scaling.level, scaling.labels, scaling.params)
            for talent in character.talents
            if (action := ACTION_FOR.get(talent.talent_type)) is not None
            for scaling in talent.scalings
        ]
        if rows:
            characters.append(
                CharacterRows(gcsim_key=key, name=character.name, rows=tuple(rows)),
            )
    return characters


def main() -> None:
    """Run the comparison and exit non-zero on anything that is not agreement."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures", action="store_true",
        help="compare the committed fixtures instead of the seeded database",
    )
    args = parser.parse_args()

    characters = from_fixtures() if args.fixtures else asyncio.run(from_database())
    report = compare(characters, load_snapshot())

    print(report.summary())
    for line in report.refusals[:20]:
        print(f"  REFUSED  {line}")
    for line in report.mismatches[:20]:
        print(f"  MISMATCH {line}")
    if not report.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
