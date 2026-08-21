"""Task 7: the clean-mode wipe and the subsequent insert share one transaction.

A ``clean`` import deletes the owner's discs / builds *before* parsing anything.
That is only safe if a failure anywhere later in the import undoes the wipe.
These tests inject a failure immediately after the wipe and assert that, once
the transaction is rolled back, nothing was deleted.

The failure is injected into ``_normalize_set_key``, which both importers call
as the first statement of phase 1 — i.e. after every wipe, before any insert.

Each test runs the import inside a SAVEPOINT so it can be rolled back without
discarding the seeded fixtures. If an importer ever called ``session.commit()``
mid-import, that commit would release the savepoint and these tests would fail
at the rollback — which is exactly the regression they exist to catch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.data.importers import ezod_importer, scanner_importer
from app.data.importers.ezod_importer import import_ezod_payload
from app.data.importers.scanner_importer import import_zod_payload
from app.database import get_db
from app.main import create_app
from app.models.agent import Agent
from app.models.build import Build, Combo
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.models.team import Team
from app.models.w_engine import WEngine
from tests.conftest import get_test_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_EZOD_FIXTURE = Path(__file__).parent / "fixtures" / "ezod_small.json"

# Hakushin IDs for this module — offset from the other import suites.
_HA = 6100  # Rina
_HB = 6101  # Anby
_HC = 6102  # Lucy
_HE = 6200  # BashfulDemon
_HD1 = 6300  # PufferElectro
_HD2 = 6301  # AstralVoice
_HD3 = 6302  # WoodpeckerElectro


class InjectedImportError(RuntimeError):
    """Sentinel raised from the injected failure point."""


def _explode(*_args, **_kwargs) -> str:
    raise InjectedImportError("injected failure, immediately after the wipe")


@pytest.fixture
def ezod_payload() -> dict:
    return json.loads(_EZOD_FIXTURE.read_text())


async def _seed_ezod(db: AsyncSession) -> None:
    """Seed the agents, w-engine, and disc sets that ezod_small.json references."""
    db.add_all([
        Agent(
            hakushin_id=_HA, name="Rina",
            element=Element.ELECTRIC, specialty=Specialty.SUPPORT, rarity=Rarity.S,
        ),
        Agent(
            hakushin_id=_HB, name="Anby",
            element=Element.ELECTRIC, specialty=Specialty.STUN, rarity=Rarity.S,
        ),
        Agent(
            hakushin_id=_HC, name="Lucy",
            element=Element.FIRE, specialty=Specialty.SUPPORT, rarity=Rarity.S,
        ),
        WEngine(
            hakushin_id=_HE, name="Bashful Demon",
            rarity=Rarity.S, specialty=Specialty.SUPPORT, base_atk=46,
        ),
        DiscSet(hakushin_id=_HD1, name="Puffer Electro"),
        DiscSet(hakushin_id=_HD2, name="Astral Voice"),
        DiscSet(hakushin_id=_HD3, name="Woodpecker Electro"),
    ])
    await db.flush()


async def _seed_zod_set(db: AsyncSession) -> str:
    disc_set = DiscSet(hakushin_id=_HD1, name="Puffer Electro")
    db.add(disc_set)
    await db.flush()
    return disc_set.id


def _zod_payload(discs: list[dict]) -> dict:
    return {"format": "ZOD", "version": 1, "source": "test", "discs": discs}


def _zod_disc(slot: int, main: str) -> dict:
    return {
        "setKey": "PufferElectro",
        "slotKey": slot,
        "rarity": "S",
        "level": 15,
        "mainStatKey": main,
        "substats": [{"key": "crit_", "upgrades": 2}],
    }


_ZOD = _zod_payload([_zod_disc(1, "hp"), _zod_disc(2, "atk"), _zod_disc(4, "crit_dmg_")])


# All post-rollback assertions read columns rather than ORM entities: a rolled
# back savepoint leaves the identity map holding rows the database no longer
# agrees with, and `Session.get` would answer from it instead of re-reading.


async def _disc_ids(db: AsyncSession, owner_id: str) -> set[str]:
    rows = (await db.execute(select(Disc.id).where(Disc.owner_id == owner_id))).scalars()
    return set(rows.all())


async def _build_ids(db: AsyncSession, owner_id: str) -> set[str]:
    rows = (await db.execute(select(Build.id).where(Build.owner_id == owner_id))).scalars()
    return set(rows.all())


class TestEzodCleanRollback:
    async def test_disc_wipe_rolls_back_with_the_import(
        self,
        db_session: AsyncSession,
        authed_user: tuple,
        ezod_payload: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        user, _ = authed_user
        owner_id = user.id
        await _seed_ezod(db_session)
        await import_ezod_payload(ezod_payload, db_session, owner_id=owner_id)
        before = await _disc_ids(db_session, owner_id)
        assert len(before) == 12

        savepoint = await db_session.begin_nested()
        monkeypatch.setattr(ezod_importer, "_normalize_set_key", _explode)
        with pytest.raises(InjectedImportError):
            await import_ezod_payload(
                ezod_payload, db_session, owner_id=owner_id, disc_mode="clean"
            )
        await savepoint.rollback()

        assert await _disc_ids(db_session, owner_id) == before

    async def test_build_wipe_rolls_back_with_the_import(
        self,
        db_session: AsyncSession,
        authed_user: tuple,
        ezod_payload: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        user, _ = authed_user
        owner_id = user.id
        await _seed_ezod(db_session)
        await import_ezod_payload(ezod_payload, db_session, owner_id=owner_id)
        before = await _build_ids(db_session, owner_id)
        assert len(before) == 3

        savepoint = await db_session.begin_nested()
        monkeypatch.setattr(ezod_importer, "_normalize_set_key", _explode)
        with pytest.raises(InjectedImportError):
            await import_ezod_payload(
                ezod_payload, db_session, owner_id=owner_id, build_mode="clean"
            )
        await savepoint.rollback()

        assert await _build_ids(db_session, owner_id) == before

    async def test_build_wipe_rollback_leaves_teams_and_combos_intact(
        self,
        db_session: AsyncSession,
        authed_user: tuple,
        ezod_payload: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """A failed clean must not strand a team with nulled slots (D-IM1/D-IM3).

        The build wipe SET NULLs every slot pointing at it, and the all-null
        team sweep would delete the team outright. Both have to unwind.
        """
        user, _ = authed_user
        owner_id = user.id
        await _seed_ezod(db_session)
        await import_ezod_payload(ezod_payload, db_session, owner_id=owner_id)

        builds = sorted(await _build_ids(db_session, owner_id))
        team = Team(owner_id=owner_id, name="Rollback Squad", build1_id=builds[0])
        db_session.add(team)
        await db_session.flush()
        combo = Combo(owner_id=owner_id, name="Opener", team_id=team.id)
        db_session.add(combo)
        await db_session.flush()
        team_id, combo_id = team.id, combo.id

        savepoint = await db_session.begin_nested()
        monkeypatch.setattr(ezod_importer, "_normalize_set_key", _explode)
        with pytest.raises(InjectedImportError):
            await import_ezod_payload(
                ezod_payload, db_session, owner_id=owner_id, build_mode="clean"
            )
        await savepoint.rollback()

        surviving = (
            await db_session.execute(
                select(Team.build1_id).where(Team.id == team_id)
            )
        ).scalars().all()
        assert surviving == [builds[0]]

        combos = (
            await db_session.execute(select(Combo.id).where(Combo.id == combo_id))
        ).scalars().all()
        assert combos == [combo_id]

    async def test_successful_clean_import_never_commits(
        self,
        db_session: AsyncSession,
        authed_user: tuple,
        ezod_payload: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """The importer flushes but never commits — the caller owns the transaction."""
        user, _ = authed_user
        await _seed_ezod(db_session)

        commits: list[None] = []

        async def _spy() -> None:
            commits.append(None)

        monkeypatch.setattr(db_session, "commit", _spy)
        await import_ezod_payload(
            ezod_payload,
            db_session,
            owner_id=user.id,
            disc_mode="clean",
            build_mode="clean",
        )

        assert commits == []


class TestZodCleanRollback:
    async def test_disc_wipe_rolls_back_with_the_import(
        self,
        db_session: AsyncSession,
        authed_user: tuple,
        monkeypatch: pytest.MonkeyPatch,
    ):
        user, _ = authed_user
        owner_id = user.id
        set_id = await _seed_zod_set(db_session)
        db_session.add(
            Disc(
                owner_id=owner_id,
                disc_set_id=set_id,
                slot=DiscSlot.SIX,
                rarity=Rarity.S,
                level=15,
                main_stat_type=StatType.ENERGY_REGEN,
                main_stat_value=6000,
                substats=[],
            )
        )
        await db_session.flush()
        before = await _disc_ids(db_session, owner_id)
        assert len(before) == 1

        savepoint = await db_session.begin_nested()
        monkeypatch.setattr(scanner_importer, "_normalize_set_key", _explode)
        with pytest.raises(InjectedImportError):
            await import_zod_payload(_ZOD, db_session, owner_id=owner_id, disc_mode="clean")
        await savepoint.rollback()

        assert await _disc_ids(db_session, owner_id) == before

    async def test_successful_clean_import_never_commits(
        self,
        db_session: AsyncSession,
        authed_user: tuple,
        monkeypatch: pytest.MonkeyPatch,
    ):
        user, _ = authed_user
        await _seed_zod_set(db_session)

        commits: list[None] = []

        async def _spy() -> None:
            commits.append(None)

        monkeypatch.setattr(db_session, "commit", _spy)
        await import_zod_payload(_ZOD, db_session, owner_id=user.id, disc_mode="clean")

        assert commits == []


class TestImportEndpointRollback:
    """The route handler never commits — ``app.database.get_db`` owns the
    transaction and rolls it back when the request raises.

    The shared ``client`` fixtures override ``get_db`` with a bare ``yield``,
    which neither commits nor rolls back, so they cannot show this. Here the
    override mirrors the production dependency's shape (commit on success,
    rollback on error) against a savepoint. A ``session.commit()`` anywhere in
    the handler would release that savepoint and the wipe would survive.
    """

    async def test_failed_clean_import_leaves_the_inventory_intact(
        self,
        db_session: AsyncSession,
        authed_user: tuple,
        ezod_payload: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        user, raw_token = authed_user
        owner_id = user.id
        await _seed_ezod(db_session)
        await import_ezod_payload(ezod_payload, db_session, owner_id=owner_id)
        before = await _disc_ids(db_session, owner_id)
        assert len(before) == 12

        savepoint = await db_session.begin_nested()

        async def override_get_db():
            try:
                yield db_session
                await savepoint.commit()
            except Exception:
                await savepoint.rollback()
                raise

        app = create_app()
        app.state.job_runner = MagicMock()
        app.dependency_overrides[get_settings] = get_test_settings
        app.dependency_overrides[get_db] = override_get_db

        monkeypatch.setattr(ezod_importer, "_normalize_set_key", _explode)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {raw_token}"},
        ) as ac:
            # The security-headers middleware turns the unhandled InjectedImportError
            # into a 500 — by then the dependency has already unwound.
            response = await ac.post(
                "/api/v1/discs/import",
                json=ezod_payload,
                params={"disc_mode": "clean", "build_mode": "clean"},
            )
        assert response.status_code == 500
        app.dependency_overrides.clear()

        assert await _disc_ids(db_session, owner_id) == before
        assert len(await _build_ids(db_session, owner_id)) == 3
