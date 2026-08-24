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
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.character import Character, Talent
from app.models.enums import TalentType
from app.services import gcsim_keys
from app.services.talent_scaling import TalentScalingError, parse_talent_row

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
            f"{len(self.refusals)} refused by the parser"
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
            except TalentScalingError as exc:
                report.refusals.append(f"{character.name} L{level}: {exc}")
                continue

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
                agreed = [
                    any(abs(value - hit.multiplier) < TOLERANCE for value in theirs)
                    for hit in members
                ]
                # Alternatives: gcsim may implement only one of them.
                if any(agreed) if exclusive else all(agreed):
                    report.matched += len(members)
                else:
                    report.mismatches.append(
                        f"{character.name} {action} {label!r} L{level}: "
                        f"ours={[h.multiplier for h in members]} gcsim={theirs}",
                    )
    return report


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
