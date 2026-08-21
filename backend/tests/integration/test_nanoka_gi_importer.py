"""D.1 — the importer's shared pass machinery, against a real Postgres.

`_run_pass` and `_prune` are the parts every D.3-D.6 mapping runs on, and both are
database behaviour: prune issues a DELETE, and the pass flushes. They are exercised here
through `Weapon` because its key column is an ordinary integer — the mappings themselves
land in their own tasks.

The mappers below are deliberately trivial. What is under test is the *frame*: that every
index entry is accounted for, that one bad payload does not abandon the rest of the pass,
that a failure is reported rather than logged and forgotten, and that prune deletes exactly
what left the index and nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import func, select

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.build import EnemyProfile
from app.models.enums import Rarity, WeaponType
from app.models.weapon import Weapon
from tests.unit.nanoka_transport import FixtureTransport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _weapon_transport(*keys: str, fail: set[str] | None = None) -> FixtureTransport:
    """An index of `keys`, each with a minimal detail payload."""
    return FixtureTransport(
        indexes={"weapon": {key: {} for key in keys}},
        details={("weapon", key): {"name": f"Weapon {key}"} for key in keys},
        fail={("weapon", key) for key in (fail or set())},
    )


async def _make_weapon(session: AsyncSession, nanoka_id: int, name: str = "Existing") -> Weapon:
    weapon = Weapon(
        nanoka_id=nanoka_id,
        name=name,
        weapon_type=WeaponType.SWORD,
        rarity=Rarity.FOUR_STAR,
    )
    session.add(weapon)
    await session.flush()
    return weapon


async def test_a_pass_imports_every_index_entry(db_session: AsyncSession):
    importer = NanokaGIImporter(db_session, transport=_weapon_transport("11501", "11502"))

    async def mapper(key: str, payload: dict[str, Any]) -> bool:
        db_session.add(
            Weapon(
                nanoka_id=int(key),
                name=payload["name"],
                weapon_type=WeaponType.SWORD,
                rarity=Rarity.FOUR_STAR,
            ),
        )
        return True

    result = await importer._run_pass("weapon", Weapon, mapper)

    assert (result.total, result.imported, result.skipped, result.pruned) == (2, 2, 0, 0)
    assert result.ok
    names = (await db_session.execute(select(Weapon.name).order_by(Weapon.nanoka_id))).scalars()
    assert list(names) == ["Weapon 11501", "Weapon 11502"]


async def test_a_mapper_may_skip_a_row_without_that_counting_as_a_failure(
    db_session: AsyncSession,
):
    """`imported + skipped + failed == total`, so a seed summary always adds up."""
    importer = NanokaGIImporter(db_session, transport=_weapon_transport("1", "2", "3"))

    async def mapper(key: str, payload: dict[str, Any]) -> bool:
        if key == "2":
            return False
        await _make_weapon(db_session, int(key), payload["name"])
        return True

    result = await importer._run_pass("weapon", Weapon, mapper)

    assert (result.imported, result.skipped, result.failed) == (2, 1, [])
    assert result.imported + result.skipped + len(result.failed) == result.total


async def test_one_bad_payload_neither_aborts_the_pass_nor_disappears(
    db_session: AsyncSession,
):
    """The fairy lesson: a swallowed per-item exception is how a silent regression ships."""
    importer = NanokaGIImporter(db_session, transport=_weapon_transport("1", "2", "3"))

    async def mapper(key: str, payload: dict[str, Any]) -> bool:
        if key == "2":
            msg = "unmappable payload"
            raise ValueError(msg)
        await _make_weapon(db_session, int(key), payload["name"])
        return True

    result = await importer._run_pass("weapon", Weapon, mapper)

    assert result.failed == ["2"]
    assert not result.ok
    assert result.imported == 2


async def test_a_failed_fetch_is_reported_against_its_own_id(db_session: AsyncSession):
    importer = NanokaGIImporter(
        db_session, transport=_weapon_transport("1", "2", fail={"2"}),
    )

    async def mapper(key: str, payload: dict[str, Any]) -> bool:
        await _make_weapon(db_session, int(key), payload["name"])
        return True

    result = await importer._run_pass("weapon", Weapon, mapper)

    assert result.failed == ["2"]
    assert result.imported == 1


async def test_prune_deletes_exactly_what_left_the_index(db_session: AsyncSession):
    """Beta content gets retracted between patches; the row must go with it."""
    await _make_weapon(db_session, 11501, "Still listed")
    await _make_weapon(db_session, 99999, "Retracted beta weapon")
    importer = NanokaGIImporter(db_session, transport=_weapon_transport("11501"))

    pruned = await importer._prune(Weapon, {"11501"})

    assert pruned == 1
    remaining = (await db_session.execute(select(Weapon.nanoka_id))).scalars().all()
    assert remaining == [11501]


async def test_prune_leaves_hand_authored_rows_alone(db_session: AsyncSession):
    """`EnemyProfile.nanoka_id` is nullable: those rows are the user's, not nanoka's."""
    db_session.add(EnemyProfile(name="Hand-authored dummy", nanoka_id=None))
    db_session.add(EnemyProfile(name="From nanoka", nanoka_id=21010101))
    await db_session.flush()
    importer = NanokaGIImporter(db_session, transport=FixtureTransport())

    pruned = await importer._prune(EnemyProfile, set())

    assert pruned == 1
    survivors = (await db_session.execute(select(EnemyProfile.name))).scalars().all()
    assert survivors == ["Hand-authored dummy"]


async def test_prune_is_a_no_op_when_nothing_is_stale(db_session: AsyncSession):
    """No DELETE is issued at all — a seed that re-runs must not churn the table."""
    await _make_weapon(db_session, 11501)
    importer = NanokaGIImporter(db_session, transport=FixtureTransport())

    assert await importer._prune(Weapon, {"11501"}) == 0
    assert await db_session.scalar(select(func.count()).select_from(Weapon)) == 1


async def test_results_accumulate_across_passes(db_session: AsyncSession):
    """`seed_db` (D.7) reports these and exits non-zero if any pass has failures."""
    importer = NanokaGIImporter(db_session, transport=_weapon_transport("1"))

    async def mapper(key: str, payload: dict[str, Any]) -> bool:
        await _make_weapon(db_session, int(key), payload["name"])
        return True

    await importer._run_pass("weapon", Weapon, mapper)

    assert [str(result) for result in importer.results] == [
        "weapon: 1/1 imported, 0 skipped, 0 pruned, 0 failed",
    ]


@pytest.mark.parametrize("concurrency", [1, 2, 8])
async def test_batching_does_not_change_what_gets_imported(
    db_session: AsyncSession, concurrency: int,
):
    """Detail fetches are batched for speed; mapping stays in index order regardless."""
    keys = [str(index) for index in range(1, 6)]
    importer = NanokaGIImporter(
        db_session, transport=_weapon_transport(*keys), concurrency=concurrency,
    )
    seen: list[str] = []

    async def mapper(key: str, payload: dict[str, Any]) -> bool:
        seen.append(key)
        await _make_weapon(db_session, int(key), payload["name"])
        return True

    await importer._run_pass("weapon", Weapon, mapper)

    assert seen == keys
