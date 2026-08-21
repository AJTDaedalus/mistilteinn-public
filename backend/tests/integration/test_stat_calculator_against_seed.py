"""F.3 — the stat layer, driven by rows the importer wrote rather than by fixtures.

The unit tests read the committed payloads directly; these read what Chunk D actually
*stored*, which is the only way to catch a mapping that lost something between the payload
and the database. Ayaka's 12858 HP has to survive the round trip, not just the arithmetic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.formula.genshin import stats
from app.models.character import Character
from app.models.weapon import Weapon
from app.pando.calculator import Calculator, NodeRegistry
from app.services.stat_calculator import (
    CharacterStats,
    WeaponStats,
    add_character,
    add_weapon,
    build_log,
)
from tests.unit.nanoka_transport import FixtureTransport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(db: AsyncSession) -> None:
    """Import Ayaka and Aquila Favonia from the committed payloads."""
    transport = FixtureTransport.from_committed_fixtures()
    for entity, key in (("character", "10000002"), ("weapon", "11501")):
        transport.indexes[entity] = {key: transport.indexes[entity][key]}
    importer = NanokaGIImporter(db, transport=transport)
    await importer.import_characters()
    await importer.import_weapons()


def _character_stats(row: Character) -> CharacterStats:
    """Map a stored row into the calculator's inputs.

    This mapping lives in the test for now, deliberately: the first *product* caller is
    G.6's read surface, and writing the adapter before there is somewhere to call it from
    would be building ahead of need (DESIGN §1 A6). What the test proves is that everything
    the adapter will need is on the row.
    """
    return CharacterStats(
        name=row.name,
        base_hp=row.base_hp,
        base_atk=row.base_atk,
        base_def=row.base_def,
        prop_curves=row.prop_curves,
        ascension_rows=row.ascension_stats,
        elemental_mastery=row.base_elemental_mastery,
        crit_rate=row.base_crit_rate,
        crit_dmg=row.base_crit_dmg,
    )


async def test_a_seeded_ayaka_reaches_the_same_base_stats(db_session: AsyncSession):
    await _seed(db_session)
    row = await db_session.scalar(select(Character).where(Character.nanoka_id == "10000002"))

    log = build_log(NodeRegistry())
    add_character(log, _character_stats(row), level=90, ascension_phase=6)
    calculator = Calculator(registry=log.registry)

    assert calculator.compute(stats.HP_NODE) == pytest.approx(12858.2, abs=0.1)
    assert calculator.compute(stats.ATK_NODE) == pytest.approx(342.0, abs=0.1)
    assert calculator.compute(stats.CRIT_DMG_NODE) == pytest.approx(0.884)


async def test_a_seeded_weapon_contributes_its_stored_curve_and_base(db_session: AsyncSession):
    await _seed(db_session)
    row = await db_session.scalar(select(Weapon).where(Weapon.nanoka_id == 11501))

    log = build_log(NodeRegistry())
    add_weapon(
        log,
        WeaponStats(
            name=row.name,
            props=[
                {"prop_type": "FIGHT_PROP_BASE_ATTACK", "init_value": row.base_atk,
                 "type": row.base_atk_curve},
                {"prop_type": row.sub_stat_type, "init_value": row.sub_stat_base_value,
                 "type": row.sub_stat_curve},
            ],
            ascension=row.ascension_atk,
        ),
        level=90,
        ascension_phase=6,
    )

    assert Calculator(registry=log.registry).compute(stats.ATK_NODE) == pytest.approx(
        674.0, abs=1.0,
    )
