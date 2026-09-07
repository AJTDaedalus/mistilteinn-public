"""D.3 — the character pass end to end, against a real Postgres and the committed payloads.

The mapping rules themselves are unit-tested offline in
`tests/unit/test_nanoka_gi_character_mapping.py`. What is under test here is everything
that needs a database: the upsert, the child rebuild, and that a second run of an unchanged
index is a no-op rather than a duplicate roster.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.character import AscensionPassive, Character, Constellation, Talent, TalentScaling
from app.models.enums import Element, StatType, TalentType
from tests.unit.nanoka_transport import FixtureTransport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"
_KEYS = ("10000002", "10000005-2")


def _transport(*keys: str, payloads: dict[str, dict] | None = None) -> FixtureTransport:
    details = {}
    for key in keys:
        payload = (payloads or {}).get(key)
        if payload is None:
            payload = json.loads((_FIX / f"character_{key}.json").read_text())
        details["character", key] = payload
    return FixtureTransport(
        indexes={"character": {key: {} for key in keys}},
        details=details,
    )


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_the_pass_imports_both_committed_characters(db_session: AsyncSession):
    importer = NanokaGIImporter(db_session, transport=_transport(*_KEYS))

    imported = await importer.import_characters()

    assert imported == 2
    ayaka = await db_session.scalar(select(Character).where(Character.nanoka_id == "10000002"))
    assert ayaka.name == "Kamisato Ayaka"
    assert ayaka.element is Element.CRYO
    assert ayaka.ascension_stat_type is StatType.CRIT_DMG
    assert ayaka.burst_energy_cost == 80


async def test_a_traveler_variant_survives_the_round_trip(db_session: AsyncSession):
    """The 28 string-keyed entries an integer column would have dropped (D.1)."""
    importer = NanokaGIImporter(db_session, transport=_transport(*_KEYS))

    await importer.import_characters()

    traveler = await db_session.scalar(
        select(Character).where(Character.nanoka_id == "10000005-2"),
    )
    assert traveler.name == "Traveler"
    assert traveler.element is Element.PYRO


async def test_children_land_with_their_parent(db_session: AsyncSession):
    importer = NanokaGIImporter(db_session, transport=_transport("10000002"))

    await importer.import_characters()

    character = await db_session.scalar(select(Character))
    await db_session.refresh(character, ["talents", "constellations", "ascension_passives"])
    assert [talent.talent_type for talent in character.talents] == [
        TalentType.NORMAL_ATTACK,
        TalentType.ELEMENTAL_SKILL,
        TalentType.ALTERNATE_SPRINT,
        TalentType.ELEMENTAL_BURST,
    ]
    assert len(character.constellations) == 6
    assert len(character.ascension_passives) == 3
    # 15 levels each for the three real talents, one for the alternate sprint.
    assert await _count(db_session, TalentScaling) == 46


async def test_a_second_run_of_an_unchanged_index_is_a_no_op(db_session: AsyncSession):
    """The D.7 acceptance criterion in miniature: re-seeding must not duplicate anything."""
    counts_before = {}
    for run in (1, 2):
        importer = NanokaGIImporter(db_session, transport=_transport(*_KEYS))
        await importer.import_characters()
        counts = {
            model.__name__: await _count(db_session, model)
            for model in (Character, Talent, TalentScaling, Constellation, AscensionPassive)
        }
        if run == 1:
            counts_before = counts
    assert counts == counts_before
    assert counts["Character"] == 2


async def test_an_updated_payload_replaces_the_row_rather_than_adding_one(
    db_session: AsyncSession,
):
    await NanokaGIImporter(
        db_session, transport=_transport("10000002"),
    ).import_characters()

    renamed = json.loads((_FIX / "character_10000002.json").read_text())
    renamed["name"] = "Kamisato Ayaka (rebalanced)"
    await NanokaGIImporter(
        db_session, transport=_transport("10000002", payloads={"10000002": renamed}),
    ).import_characters()

    assert await _count(db_session, Character) == 1
    character = await db_session.scalar(select(Character))
    assert character.name == "Kamisato Ayaka (rebalanced)"


async def test_a_reworked_kit_leaves_no_orphaned_children(db_session: AsyncSession):
    """Children are rebuilt, so a constellation removed upstream must disappear here."""
    await NanokaGIImporter(
        db_session, transport=_transport("10000002"),
    ).import_characters()
    assert await _count(db_session, Constellation) == 6

    trimmed = json.loads((_FIX / "character_10000002.json").read_text())
    removed = trimmed["constellations"].pop()
    trimmed["skills"] = trimmed["skills"][:2]
    # `materials.talents` is parallel to `skills` with no key to join on, so the importer
    # refuses a payload where the two disagree. Trim it alongside, because nanoka publishes
    # them consistently and a fixture that does not is testing a shape upstream cannot emit.
    trimmed["materials"]["talents"] = trimmed["materials"]["talents"][:2]
    await NanokaGIImporter(
        db_session, transport=_transport("10000002", payloads={"10000002": trimmed}),
    ).import_characters()

    assert await _count(db_session, Constellation) == 5
    assert await _count(db_session, Talent) == 2
    # The removed constellation is gone, not merely re-pointed.
    stale = await db_session.scalar(
        select(func.count()).select_from(Constellation).where(
            Constellation.nanoka_id == removed["id"],
        ),
    )
    assert stale == 0
    # `talent_scalings` has no explicit DELETE — the FK cascade removes them.
    assert await _count(db_session, TalentScaling) == 30


async def test_a_character_that_leaves_the_index_is_pruned(db_session: AsyncSession):
    await NanokaGIImporter(db_session, transport=_transport(*_KEYS)).import_characters()

    importer = NanokaGIImporter(db_session, transport=_transport("10000002"))
    await importer.import_characters()

    assert await _count(db_session, Character) == 1
    assert importer.results[-1].pruned == 1
    # The pruned character's children go with it, via ON DELETE CASCADE.
    assert await _count(db_session, Constellation) == 6


async def test_a_malformed_payload_fails_that_character_and_no_other(db_session: AsyncSession):
    """One unmappable kit must not cost the other 149 their rows."""
    broken = copy.deepcopy(json.loads((_FIX / "character_10000002.json").read_text()))
    broken["weapon"] = "WEAPON_TRIDENT_OF_THE_UNSPECIFIED"
    importer = NanokaGIImporter(
        db_session, transport=_transport(*_KEYS, payloads={"10000002": broken}),
    )

    imported = await importer.import_characters()

    assert imported == 1
    assert importer.results[-1].failed == ["10000002"]
    assert await _count(db_session, Character) == 1
