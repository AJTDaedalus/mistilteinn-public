"""D.8 — `scripts/verify_seed`, and the proof that it can go red.

**A gate never observed failing is not a gate.** Every check below is exercised in its
failing state; the acceptance criterion for D.8 was to corrupt an anchor and watch it fail,
and these are that demonstration made repeatable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.seed_provenance import SeedRun
from app.models.weapon import Weapon
from scripts.seed_db import PASSES, run_passes
from scripts.verify_seed import FIXTURE_VERSION, load_indexes, verify
from tests.unit.nanoka_transport import FixtureTransport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"

#: One entity each, so a whole "seed" fits in a rolled-back transaction. The index lengths
#: are passed to `verify` to match, which is what `indexes=` is for.
_KEYS = {
    "character": "10000002",
    "weapon": "11501",
    "artifact": "15025",
    "monster": "21010101",
}
_ONE_EACH = dict.fromkeys(_KEYS, 1)


def _transport() -> FixtureTransport:
    return FixtureTransport(
        indexes={entity: {key: {}} for entity, key in _KEYS.items()},
        details={
            (entity, key): json.loads((_FIX / f"{entity}_{key}.json").read_text())
            for entity, key in _KEYS.items()
        },
    )


async def _seed(db: AsyncSession) -> None:
    importer = NanokaGIImporter(db, transport=_transport())
    await run_passes(db, importer, list(PASSES), commit=False)


async def test_an_unseeded_database_fails_rather_than_passing_vacuously(
    db_session: AsyncSession,
):
    failures = await verify(db_session, indexes=_ONE_EACH)

    assert len(failures) == 1
    assert "must not report a pass" in failures[0]


async def test_a_run_that_never_finished_fails(db_session: AsyncSession):
    """`succeeded` is written False first, so a crashed seed is visible here."""
    await _seed(db_session)
    run = await db_session.scalar(SeedRun.__table__.select())
    await db_session.execute(
        SeedRun.__table__.update().values(succeeded=False),
    )
    await db_session.flush()

    failures = await verify(db_session, indexes=_ONE_EACH)

    assert any("did not finish" in failure for failure in failures)
    assert run is not None


async def test_a_database_from_a_different_patch_fails(db_session: AsyncSession):
    """The index grew; this database was seeded before it did."""
    await _seed(db_session)

    failures = await verify(db_session, indexes={**_ONE_EACH, "character": 151})

    assert any(
        "the run saw 1 index entries but the index holds 151" in failure
        for failure in failures
    )


async def test_rows_disappearing_after_the_run_fails(db_session: AsyncSession):
    """Catches a truncate, a bad migration, or a cascade nobody expected."""
    await _seed(db_session)
    await db_session.execute(delete(Weapon))
    await db_session.flush()

    failures = await verify(db_session, indexes=_ONE_EACH)

    assert any("0 importer-owned rows in weapons against 1" in failure for failure in failures)


async def test_a_corrupted_anchor_fails_and_names_its_source(db_session: AsyncSession):
    """The D.8 acceptance criterion, made repeatable."""
    await _seed(db_session)
    weapon = await db_session.scalar(Weapon.__table__.select())
    await db_session.execute(Weapon.__table__.update().values(base_atk=47.5))
    await db_session.flush()

    failures = await verify(db_session, indexes=_ONE_EACH)

    assert any(
        "Aquila Favonia's base ATK" in failure and "weapon_11501.json" in failure
        for failure in failures
    )
    assert weapon is not None


async def test_a_seed_from_an_unexpected_version_fails_rather_than_comparing_wrong():
    """Offline, the fixtures *are* the index. Comparing against another patch is worse
    than not comparing, so it raises rather than quietly using the wrong numbers."""
    with pytest.raises(SystemExit, match="committed fixtures are"):
        await load_indexes(live=False, version="9.9.9")


async def test_the_offline_index_lengths_come_from_the_committed_fixtures():
    lengths = await load_indexes(live=False, version=FIXTURE_VERSION)

    assert lengths == {"character": 150, "weapon": 286, "artifact": 65, "monster": 585}


async def test_a_hand_authored_enemy_profile_does_not_make_the_gate_red(
    db_session: AsyncSession,
):
    """`EnemyProfile.nanoka_id` is nullable and `_prune` preserves those rows on purpose.

    Counting them here would turn the first Chunk F crossval dummy into a permanently red
    verifier, and a gate that goes red for a supported configuration gets switched off.
    """
    from app.models.build import EnemyProfile

    await _seed(db_session)
    before = await verify(db_session, indexes=_ONE_EACH)
    db_session.add(EnemyProfile(name="Crossval dummy", nanoka_id=None, level=90))
    await db_session.flush()

    # Compared against the same run without the dummy rather than against `[]`: this
    # four-row stand-in cannot satisfy anchors that name the Pyro Traveler or the Prayers
    # sets, and those failures are not what this test is about.
    assert await verify(db_session, indexes=_ONE_EACH) == before
    assert not any("enemy_profiles" in failure for failure in before)
