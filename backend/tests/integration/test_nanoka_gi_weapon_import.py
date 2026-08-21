"""D.4 — the weapon pass end to end. Mapping rules are unit-tested offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.enums import Rarity, StatType, WeaponType
from app.models.weapon import Weapon, WeaponRefinement
from tests.unit.nanoka_transport import FixtureTransport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"

_SKIN = {
    "name": "Golden Bough of Nemorensis - Sublimation",
    "weapon_type": "WEAPON_SWORD_ONE_HAND",
    "rarity": 5,
    "tag": "TAG_TYPE_COLOR_BY_ELEMENT",
    "skin": True,
}
_TPS = {
    "name": "Shatanaya's Frostsilver",
    "weapon_type": "ITEM_TPS_WEAPON",
    "rarity": 4,
    "icon": "UI_EquipIcon_AssaultRifle_Glacia",
    "skill": 11344,
    "tps": True,
}


def _aquila() -> dict:
    return json.loads((_FIX / "weapon_11501.json").read_text())


def _transport(payloads: dict[str, dict]) -> FixtureTransport:
    return FixtureTransport(
        indexes={"weapon": {key: {} for key in payloads}},
        details={("weapon", key): payload for key, payload in payloads.items()},
    )


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_the_pass_imports_a_weapon_and_its_refinements(db_session: AsyncSession):
    importer = NanokaGIImporter(db_session, transport=_transport({"11501": _aquila()}))

    imported = await importer.import_weapons()

    assert imported == 1
    weapon = await db_session.scalar(select(Weapon))
    assert weapon.name == "Aquila Favonia"
    assert weapon.weapon_type is WeaponType.SWORD
    assert weapon.rarity is Rarity.FIVE_STAR
    assert weapon.sub_stat_type is StatType.PHYSICAL_DMG_BONUS
    await db_session.refresh(weapon, ["refinements"])
    assert [row.level for row in weapon.refinements] == [1, 2, 3, 4, 5]


async def test_a_skin_is_skipped_and_counted_as_such(db_session: AsyncSession):
    """`skipped` exists so a deliberate non-import is visible in the seed summary."""
    importer = NanokaGIImporter(
        db_session, transport=_transport({"11501": _aquila(), "310001": _SKIN}),
    )

    imported = await importer.import_weapons()

    assert imported == 1
    result = importer.results[-1]
    assert (result.total, result.imported, result.skipped, result.failed) == (2, 1, 1, [])
    assert await _count(db_session, Weapon) == 1


async def test_a_tps_weapon_is_imported_with_null_stats(db_session: AsyncSession):
    """C.4 made the columns nullable so these import visibly instead of dying (or vanishing)."""
    importer = NanokaGIImporter(db_session, transport=_transport({"224001": _TPS}))

    await importer.import_weapons()

    weapon = await db_session.scalar(select(Weapon))
    assert weapon.weapon_type is WeaponType.CROSSBOW
    assert weapon.base_atk is None
    assert weapon.sub_stat_type is None
    assert await _count(db_session, WeaponRefinement) == 0


async def test_a_second_run_is_a_no_op(db_session: AsyncSession):
    payloads = {"11501": _aquila(), "224001": _TPS, "310001": _SKIN}
    for _ in range(2):
        importer = NanokaGIImporter(db_session, transport=_transport(payloads))
        await importer.import_weapons()

    assert await _count(db_session, Weapon) == 2
    assert await _count(db_session, WeaponRefinement) == 5


async def test_a_shortened_refinement_ladder_leaves_no_orphans(db_session: AsyncSession):
    await NanokaGIImporter(
        db_session, transport=_transport({"11501": _aquila()}),
    ).import_weapons()

    trimmed = _aquila()
    trimmed["refinement"] = {"1": trimmed["refinement"]["1"]}
    await NanokaGIImporter(
        db_session, transport=_transport({"11501": trimmed}),
    ).import_weapons()

    assert await _count(db_session, WeaponRefinement) == 1


async def test_a_weapon_that_leaves_the_index_is_pruned(db_session: AsyncSession):
    await NanokaGIImporter(
        db_session, transport=_transport({"11501": _aquila(), "224001": _TPS}),
    ).import_weapons()

    importer = NanokaGIImporter(db_session, transport=_transport({"11501": _aquila()}))
    await importer.import_weapons()

    assert await _count(db_session, Weapon) == 1
    assert importer.results[-1].pruned == 1
    # The pruned weapon's refinements go with it; the survivor keeps its own.
    assert await _count(db_session, WeaponRefinement) == 5


async def test_a_weapon_reclassified_as_a_skin_loses_its_row(db_session: AsyncSession):
    """The skip path has to delete, not just decline to write.

    The key stays in the index, so prune never sees it as stale; without the delete the old
    stats would survive every future seed, counted as `skipped`, on a green run.
    """
    await NanokaGIImporter(
        db_session, transport=_transport({"11501": _aquila()}),
    ).import_weapons()
    assert await _count(db_session, Weapon) == 1

    importer = NanokaGIImporter(db_session, transport=_transport({"11501": _SKIN}))
    await importer.import_weapons()

    assert await _count(db_session, Weapon) == 0
    assert await _count(db_session, WeaponRefinement) == 0
    assert importer.results[-1].skipped == 1
