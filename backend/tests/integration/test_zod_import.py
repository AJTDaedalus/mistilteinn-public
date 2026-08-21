"""Integration tests for ``import_zod_payload`` disc modes (Task 5).

``disc_mode="clean"`` wipes the owner's disc inventory before the import,
inside the caller's transaction.  ``merge`` (the default) dedups against
the existing inventory and deletes nothing.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.data.importers.scanner_importer import import_zod_payload
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Rarity, StatType
from app.models.user import User
from app.services.password import hash_password

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Hakushin IDs for this module — offset to avoid colliding with other suites.
_HD1 = 7300  # Puffer Electro


async def _seed_set(db: AsyncSession) -> str:
    disc_set = DiscSet(hakushin_id=_HD1, name="Puffer Electro")
    db.add(disc_set)
    await db.flush()
    return disc_set.id


def _zod(discs: list[dict]) -> dict:
    return {"format": "ZOD", "version": 1, "source": "test", "discs": discs}


def _disc(slot: int, main: str, *, level: int = 15) -> dict:
    return {
        "setKey": "PufferElectro",
        "slotKey": slot,
        "rarity": "S",
        "level": level,
        "mainStatKey": main,
        "substats": [{"key": "crit_", "upgrades": 2}],
    }


_PAYLOAD = _zod([_disc(1, "hp"), _disc(2, "atk"), _disc(4, "crit_dmg_")])


class TestZodImportCleanMode:
    async def test_clean_disc_mode_replaces_inventory(
        self, db_session: AsyncSession, authed_user: tuple
    ):
        user, _ = authed_user
        await _seed_set(db_session)

        await import_zod_payload(_PAYLOAD, db_session, owner_id=user.id)

        # A clean re-import wipes the 3 existing discs, then re-imports all 3
        # as new rows — nothing left to dedup against.
        result = await import_zod_payload(
            _PAYLOAD, db_session, owner_id=user.id, disc_mode="clean"
        )
        assert result.discs_deleted == 3
        assert result.imported == 3
        assert result.skipped_duplicate == 0

        discs = (
            await db_session.execute(select(Disc).where(Disc.owner_id == user.id))
        ).scalars().all()
        assert len(discs) == 3

    async def test_clean_removes_discs_absent_from_payload(
        self, db_session: AsyncSession, authed_user: tuple
    ):
        user, _ = authed_user
        set_id = await _seed_set(db_session)

        stale = Disc(
            owner_id=user.id,
            disc_set_id=set_id,
            slot=DiscSlot.SIX,
            rarity=Rarity.S,
            level=15,
            main_stat_type=StatType.ENERGY_REGEN,
            main_stat_value=6000,
            substats=[],
        )
        db_session.add(stale)
        await db_session.flush()
        stale_id = stale.id

        result = await import_zod_payload(
            _PAYLOAD, db_session, owner_id=user.id, disc_mode="clean"
        )
        assert result.discs_deleted == 1
        assert result.imported == 3
        assert await db_session.get(Disc, stale_id) is None

    async def test_merge_is_the_default_and_deletes_nothing(
        self, db_session: AsyncSession, authed_user: tuple
    ):
        user, _ = authed_user
        await _seed_set(db_session)

        first = await import_zod_payload(_PAYLOAD, db_session, owner_id=user.id)
        assert first.discs_deleted == 0
        assert first.imported == 3

        second = await import_zod_payload(_PAYLOAD, db_session, owner_id=user.id)
        assert second.discs_deleted == 0
        assert second.imported == 0
        assert second.skipped_duplicate == 3

    async def test_clean_is_owner_scoped(
        self, db_session: AsyncSession, authed_user: tuple
    ):
        user, _ = authed_user
        set_id = await _seed_set(db_session)

        other = User(
            email=f"other_{secrets.token_hex(4)}@test.example",
            label="Other",
            password_hash=hash_password("alpha-test-password-1234"),
        )
        db_session.add(other)
        await db_session.flush()
        other_disc = Disc(
            owner_id=other.id,
            disc_set_id=set_id,
            slot=DiscSlot.ONE,
            rarity=Rarity.S,
            level=15,
            main_stat_type=StatType.HP,
            main_stat_value=2200,
            substats=[],
        )
        db_session.add(other_disc)
        await db_session.flush()
        other_disc_id = other_disc.id

        result = await import_zod_payload(
            _PAYLOAD, db_session, owner_id=user.id, disc_mode="clean"
        )
        assert result.discs_deleted == 0
        assert await db_session.get(Disc, other_disc_id) is not None

    async def test_clean_without_owner_id_raises(self, db_session: AsyncSession):
        await _seed_set(db_session)

        with pytest.raises(ValueError, match="owner_id"):
            await import_zod_payload(_PAYLOAD, db_session, disc_mode="clean")
