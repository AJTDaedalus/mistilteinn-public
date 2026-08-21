"""D.6 — the enemy pass end to end."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.build import EnemyProfile
from tests.unit.nanoka_transport import FixtureTransport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"

_CRAB = {"codex": "CRITTER", "desc": "A crab.", "icon": "x", "name": "Golden Crab"}


def _monster(key: str) -> dict:
    return json.loads((_FIX / f"monster_{key}.json").read_text())


def _transport(payloads: dict[str, dict]) -> FixtureTransport:
    return FixtureTransport(
        indexes={"monster": {key: {} for key in payloads}},
        details={("monster", key): payload for key, payload in payloads.items()},
    )


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_the_pass_imports_a_profile_per_family(db_session: AsyncSession):
    importer = NanokaGIImporter(
        db_session,
        transport=_transport({"21010101": _monster("21010101"), "24010101": _monster("24010101")}),
    )

    imported = await importer.import_enemies()

    assert imported == 2
    guard = await db_session.scalar(
        select(EnemyProfile).where(EnemyProfile.nanoka_id == 24010101),
    )
    assert guard.name == "Ruin Guard"
    assert guard.tags == "AUTOMATRON"
    assert guard.physical_res == 0.7
    assert guard.variant_nanoka_id == 24010101
    assert guard.variant_count == 17
    assert guard.stat_curves["FIGHT_PROP_BASE_HP"].startswith("GROW_CURVE_HP")


async def test_a_stat_less_codex_entry_is_skipped(db_session: AsyncSession):
    """225 of 585 entries are wildlife; zeroed rows would look like a mapping bug."""
    importer = NanokaGIImporter(
        db_session, transport=_transport({"21010101": _monster("21010101"), "28010101": _CRAB}),
    )

    imported = await importer.import_enemies()

    assert imported == 1
    result = importer.results[-1]
    assert (result.total, result.imported, result.skipped, result.failed) == (2, 1, 1, [])


async def test_a_second_run_is_a_no_op(db_session: AsyncSession):
    payloads = {"21010101": _monster("21010101"), "28010101": _CRAB}
    for _ in range(2):
        await NanokaGIImporter(db_session, transport=_transport(payloads)).import_enemies()

    assert await _count(db_session, EnemyProfile) == 1


async def test_a_hand_authored_profile_survives_the_pass(db_session: AsyncSession):
    """`nanoka_id` is nullable so a Chunk F crossval target is not the importer's to delete."""
    db_session.add(EnemyProfile(name="Crossval dummy", nanoka_id=None, level=90))
    await db_session.flush()

    importer = NanokaGIImporter(
        db_session, transport=_transport({"21010101": _monster("21010101")}),
    )
    await importer.import_enemies()

    assert importer.results[-1].pruned == 0
    names = (await db_session.execute(select(EnemyProfile.name))).scalars().all()
    assert "Crossval dummy" in names


async def test_a_monster_that_leaves_the_index_is_pruned(db_session: AsyncSession):
    await NanokaGIImporter(
        db_session,
        transport=_transport({"21010101": _monster("21010101"), "24010101": _monster("24010101")}),
    ).import_enemies()

    importer = NanokaGIImporter(
        db_session, transport=_transport({"21010101": _monster("21010101")}),
    )
    await importer.import_enemies()

    assert await _count(db_session, EnemyProfile) == 1
    assert importer.results[-1].pruned == 1
