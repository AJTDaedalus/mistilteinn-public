"""Reconstituting builds from a GOOD export.

A user who imports 2,370 artifacts should not then hand-build every character. The export
already carries what a build is made of, and this puts it together:

* `characters[]` — level, ascension, constellation, and the three levelled talents;
* `weapons[]` — level, ascension, refinement, and **`location`**, the character holding it;
* `artifacts[].location` — the character wearing each piece.

Teams are **not** reconstituted, because GOOD has no concept of one (owner ruling). A team is
assembled from builds on `/teams`.

## Only characters who are actually equipped get a build

An export lists every character the account owns — 89 in the reference file, including
`Manekin` and `Manekina`, GO's practice mannequins. Building all of them would bury the six
the user plays under eighty they do not, and the mannequins are never used in combat (owner
ruling: out of scope, do not even list them).

So the rule is **a build for each character holding a weapon or an artifact**, which excludes
the mannequins without this module ever having to know their names.

## Existing builds are never overwritten

A re-import refreshes the *inventory*; a build carries decisions — notes, a weapon the user
chose over the equipped one — that no scanner knows about. A character who already has a
build is skipped and reported, so nothing a user typed is silently replaced by what the game
happened to have equipped. Deleting the build is the way to ask for a fresh one.

## The Traveler

`characters[]` names them by element (`TravelerCryo`), but `artifacts[].location` says only
`Traveler` — no element, and never a gender. The catalogue holds **16** variants: seven
elements for each of two bodies, plus the two unreleased crossbow bodies. (This said 28, which
was the mannequins counted in; seven for each of two is fourteen, and the line contradicted
itself.)

Owner ruling: place them rather than refuse. The element comes from the `characters` entry;
the gender cannot be recovered from the export at all, so the **lowest `nanoka_id`** is taken
— deterministically, and reported in `notes` on the build so the choice is visible on the row
rather than buried here.

**One Traveler build, not seven.** The owner's preferred model is a build per element, each
keeping its own level and talents, all *sharing* one artifact set — which is what the game
does, and the export agrees: talents arrive per elemental entry (`TravelerCryo` has its own
`talent` block) while artifacts carry only `location: "Traveler"`.

That cannot be expressed yet. `artifacts.build_id` is single-valued and
`uq_artifacts_build_slot` enforces one piece per slot per build, so seven builds cannot wear
the same five pieces without either duplicating the rows — which would inflate the inventory
and let the optimizer award one physical artifact to two characters — or a schema change
linking a build to another build's artifacts. Recorded in `docs/DECISIONS.md` as its own
chunk. Until then the import creates the one Traveler the export actually describes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.build import Build
from app.models.character import Character
from app.models.weapon import Weapon
from app.repositories.roster import CharacterRosterRepository
from app.services.roster import is_mannequin

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.data.importers.good_importer import (
        GoodImportResult,
        ParsedArtifact,
        ParsedCharacter,
        ParsedWeapon,
    )
    from app.models.artifact import Artifact

_NOT_ALNUM = re.compile(r"[^a-z0-9]")

#: `Build.notes` is `String(1000)` and not nullable, and `source` comes straight out of the
#: export unvalidated. A multi-kilobyte one raised `StringDataRightTruncation` on flush,
#: rolling back the *artifacts* as well and returning a 500 — a whole import lost to a field
#: nobody reads.
_MAX_SOURCE = 60


def lookup_key(name: str) -> str:
    """`"Hu Tao"` and `"HuTao"` both reduce to `hutao`.

    The same normalisation `set_lookup_key` applies to artifact sets, for the same reason:
    GOOD builds its keys by stripping punctuation and spaces out of the English display name
    this database stores.
    """
    return _NOT_ALNUM.sub("", name.lower())


@dataclass
class BuildImportReport:
    """What was built, and everything that was not."""

    created: int = 0
    #: Roster rows written — **a separate output from builds, answering a different question**.
    #:
    #: A build says *what gear this character has* and is made only for a character holding
    #: some. Ownership says *does this account have this character*, comes from `characters[]`,
    #: and is the reason twelve real characters used to be invisible to the teapot tracker.
    #: `DESIGN_character_roster.md` §4.
    roster_written: int = 0
    #: Characters that already had a build. Named, because "nothing happened" and "your
    #: edits were kept" look identical otherwise.
    skipped_existing: list[str] = field(default_factory=list)
    #: Character keys the catalogue could not identify. Reported rather than dropped — an
    #: unknown key usually means the export is newer than the seeded patch.
    unresolved: list[str] = field(default_factory=list)
    #: Weapons the catalogue could not identify, `"character: weapon"`. **Reported, because a
    #: build with no weapon is a legitimate state** — so an unresolved one is invisible
    #: otherwise, which is exactly how the key-normalisation bug survived its first outing.
    unresolved_weapons: list[str] = field(default_factory=list)
    #: Characters the export gave artifacts but **no weapon at all** — not an unresolvable
    #: weapon, an absent one.
    #:
    #: Reported for exactly the reason `unresolved_weapons` is: a build with no weapon is a
    #: legitimate state, so a missing one is invisible, and the user reads it as the importer
    #: having lost something. It was: an Irminsul export carrying 2,370 artifacts and 320
    #: weapons named a weapon's holder for only 68 of them, so 7 characters with a full set of
    #: artifacts got weaponless builds and the import said nothing.
    #:
    #: **This is a gap in the export, not in the import**, and naming it is what lets a user
    #: tell those apart — they can re-scan, and nothing here can.
    no_weapon_in_export: list[str] = field(default_factory=list)
    #: Equipped pieces that could not be placed, with the reason.
    unplaced: list[str] = field(default_factory=list)
    #: Pieces taken from a build that was already wearing them — see `_equip`.
    reassigned: list[str] = field(default_factory=list)
    #: Characters given **no build** because the export's talent levels cannot be stored,
    #: `"character: reason"` — a level present and outside 1-10 (owner ruling, 2026-11-14;
    #: `good_importer._talents_out_of_range`). Refused rather than clamped, and named, so the
    #: user can correct the scan or make the build by hand; their pieces stay unequipped.
    refused_talents: list[str] = field(default_factory=list)


async def _characters_by_key(session: AsyncSession) -> dict[str, list[Character]]:
    """`{normalised key: rows}`. A list, because the Traveler variants share a name."""
    rows = (await session.execute(select(Character))).scalars().all()
    table: dict[str, list[Character]] = defaultdict(list)
    for row in rows:
        table[lookup_key(row.name)].append(row)
        # Also indexed by name+element, which is how GOOD spells the Traveler
        # (`TravelerCryo`) and the only thing that separates the seven of them.
        if row.element is not None:
            table[lookup_key(f"{row.name}{row.element.value}")].append(row)
    return table


def _pick(rows: list[Character]) -> Character:
    """One row from a key that matched several — the lowest `nanoka_id`.

    Only the Traveler reaches this, and only after `_resolve` has narrowed it to one element:
    two Travelers share every elemental variant. The export records no gender, so there is
    nothing to match on and the choice is arbitrary; taking the lowest id at least makes it
    *the same* arbitrary choice every run.
    """
    return min(rows, key=lambda row: str(row.nanoka_id))


def _resolve(
    key: str,
    characters_by_key: dict[str, ParsedCharacter],
    by_key: dict[str, list[Character]],
) -> tuple[ParsedCharacter | None, list[Character]]:
    """The export entry and catalogue rows for one `location` key.

    **The Traveler is why this is not a dictionary lookup.** `artifacts[].location` says only
    `Traveler` — no element — while `characters[]` spells it `TravelerCryo`. All 28 catalogue
    variants are *named* `Traveler`, so `by_key["traveler"]` is a 28-row list rather than a
    miss, and a resolver that only handled the miss never ran at all: every Traveler build
    came out as the lowest id (Pyro Aether) at level 1 with no talents, whatever the user
    actually played. Verified in the database before this was written.

    So an ambiguous key is narrowed through the export's own `characters` list: exactly one
    entry extends `traveler` with an element, and that entry names both the levels to use and
    the smaller set of rows to pick from.
    """
    entry = characters_by_key.get(key)
    rows = by_key.get(key, [])
    if entry is not None and len(rows) <= 1:
        return entry, rows

    # Ambiguous, or the location is spelled shorter than the character entry. One extension
    # is an answer; several is a genuine ambiguity and gets none.
    extensions = [
        (other, characters_by_key[other])
        for other in characters_by_key
        if other != key and other.startswith(key) and other in by_key
    ]
    if len(extensions) == 1:
        found, entry = extensions[0]
        return entry, by_key[found]
    return entry, rows


async def rebuild_builds(
    session: AsyncSession,
    *,
    owner_id: str,
    parsed: GoodImportResult,
    stored: dict[int, Artifact],
) -> BuildImportReport:
    """Create a build per equipped character, and equip their artifacts to it.

    `stored` maps an artifact's `source_index` in the export to the row that was written, so
    the equip pass can bind the piece the user actually owns rather than re-matching on
    stats.
    """
    report = BuildImportReport()

    by_key = await _characters_by_key(session)
    weapons = (await session.execute(select(Weapon))).scalars().all()
    weapon_by_key = {lookup_key(w.name): w for w in weapons}
    # **Normalised on both sides.** Keying by the raw `w.key` ("FerrousShadow") and looking
    # it up in a table keyed by the normalised name ("ferrousshadow") missed every time, so
    # every reconstituted build came back holding nothing — silently, because a build with
    # no weapon is a legitimate state the editor supports.
    # **The `ParsedWeapon` itself, not its key.** Collapsing to a key string and re-finding
    # the weapon later matched the *first* export entry with that name — and owning several
    # copies of one weapon is routine, so a build holding an R5 L90 Favonius could be written
    # with the R1 L1 spare's numbers, silently changing every damage figure computed for it.
    held_weapon = {lookup_key(w.location): w for w in parsed.weapons if w.location}
    characters_by_key = {lookup_key(c.key): c for c in parsed.characters}

    # **Ownership, from `characters[]` — every character the account has, gear or not.**
    #
    # The build rule below is unchanged and still keys on *equipment*, which is right: an
    # unequipped character has nothing to optimize. But equipment was also standing in for
    # ownership, and that cost twelve of the owner's characters their roster entry — 22
    # furnishing sets, 440 Primogems the teapot tracker could not see.
    #
    # The mannequins were excluded for free by the equipment rule and now have to be excluded
    # on purpose; `services/roster.py` does it by nanoka id prefix rather than by name, which
    # is the part the old rule was sensibly avoiding.
    #
    # `upsert_imported` leaves `manual` rows alone, so a character the user deliberately
    # un-owned does not come back on every rescan.
    #
    # The constellation rides along: the export carries one for every owned character, and
    # only equipped ones become builds, so this row is the only place it survives for the
    # rest. `docs/DESIGN_wish_planner.md` section 9.4.
    owned_characters: list[tuple[str, int | None]] = []
    for parsed_character in parsed.characters:
        _, catalogue_rows = _resolve(
            lookup_key(parsed_character.key), characters_by_key, by_key,
        )
        if not catalogue_rows:
            continue
        catalogue_row = _pick(catalogue_rows)
        if is_mannequin(catalogue_row.nanoka_id):
            continue
        owned_characters.append((str(catalogue_row.id), parsed_character.constellation))
    report.roster_written = await CharacterRosterRepository(
        session, owner_id,
    ).upsert_imported(owned_characters)

    # Who is holding what. `location` is the only link the export gives.
    worn: dict[str, list[ParsedArtifact]] = defaultdict(list)
    for artifact in parsed.artifacts:
        if artifact.location:
            worn[lookup_key(artifact.location)].append(artifact)

    existing = {
        str(row.character_id)
        for row in (
            await session.execute(select(Build).where(Build.owner_id == owner_id))
        ).scalars().all()
    }

    # A build for everyone actually equipped — which leaves out the eighty-odd owned but
    # unused characters, and the mannequins with them.
    equipped_keys = set(worn) | set(held_weapon)
    for key in sorted(equipped_keys):
        entry, rows = _resolve(key, characters_by_key, by_key)
        if not rows:
            report.unresolved.append(key)
            continue

        character = _pick(rows)
        if str(character.id) in existing:
            report.skipped_existing.append(character.name)
            continue
        if entry is not None and entry.talent_refusal is not None:
            report.refused_talents.append(f"{character.name}: {entry.talent_refusal}")
            continue

        wielded = held_weapon.get(key)
        weapon = weapon_by_key.get(lookup_key(wielded.key)) if wielded else None
        if wielded is not None and weapon is None:
            report.unresolved_weapons.append(f"{character.name}: {wielded.key}")
        elif wielded is None:
            # Distinct from an unresolvable weapon: the export never named one. In Genshin a
            # character on the field always holds something, so this is a scan that missed it
            # rather than a character who owns nothing — and only the user can fix it.
            report.no_weapon_in_export.append(character.name)
        build = _new_build(
            owner_id=owner_id,
            character=character,
            entry=entry,
            weapon=weapon,
            wielded=wielded,
            source=parsed.source,
            ambiguous=len(rows) > 1,
        )
        session.add(build)
        await session.flush()
        existing.add(str(character.id))
        report.created += 1

        _equip(build, worn.get(key, ()), stored, report)

    await session.flush()
    return report




def _new_build(
    *,
    owner_id: str,
    character: Character,
    entry: ParsedCharacter | None,
    weapon: Weapon | None,
    wielded: ParsedWeapon | None,
    source: str,
    ambiguous: bool,
) -> Build:
    """A build from what the export said, falling back to a level-1 shell where it did not.

    `wielded` is the export's own weapon record — **the copy this character is holding**, not
    the first one in the file that shares its name.
    """
    notes = f"Imported from {(source or 'a GOOD export')[:_MAX_SOURCE]}"
    if ambiguous:
        # Said on the row, not only in a log: the user can see which Traveler they got and
        # change it, which they cannot do if the choice is invisible.
        notes += " · Traveler gender is not in a GOOD export; the first was used"
    return Build(
        owner_id=owner_id,
        character_id=character.id,
        weapon_id=weapon.id if weapon else None,
        character_level=entry.level if entry else 1,
        ascension_phase=entry.ascension if entry else 0,
        # A build column cannot hold "unknown"; the roster row can, and does.
        constellation_level=(entry.constellation if entry else None) or 0,
        weapon_level=wielded.level if wielded else 1,
        refinement=wielded.refinement if wielded else 1,
        talent_levels=dict(entry.talents) if entry else {},
        notes=notes,
    )


def _equip(
    build: Build,
    pieces: Sequence[ParsedArtifact],
    stored: dict[int, Artifact],
    report: BuildImportReport,
) -> None:
    """Bind each worn piece to the build, one per slot.

    A second piece in a slot is reported rather than written: `uq_artifacts_build_slot`
    refuses it anyway, and an export naming two goblets for one character is describing
    something the game cannot do.
    """
    filled: set[str] = set()
    for piece in pieces:
        row = stored.get(piece.source_index)
        if row is None:
            continue
        slot = str(row.slot)
        if slot in filled:
            report.unplaced.append(
                f"{piece.location}: a second {slot} was listed and could not be equipped"
            )
            continue
        if row.build_id is not None and row.build_id != build.id:
            # `store_good_import` runs `_restore_equipment` first, which re-points fresh rows
            # at *existing* builds by fingerprint. Taking one from under an existing build is
            # sometimes right — the user moved the piece in-game and re-scanned — but doing it
            # without saying so leaves that build a slot short, and `unequipped` was already
            # computed by then, so nothing else would ever mention it.
            report.reassigned.append(
                f"{piece.location}: took a {slot} that another build was wearing"
            )
        row.build_id = build.id
        filled.add(slot)
