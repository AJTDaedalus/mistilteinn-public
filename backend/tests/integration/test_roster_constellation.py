"""The roster remembers a constellation for every owned character, built or not.

**Why this is not a join to builds.** A GOOD export carries a constellation for every
character the account owns, but `good_build_service`'s rule is *"a build for each character
holding a weapon or an artifact"* — so an owned-but-unequipped character had its constellation
parsed and thrown away. That is most of a 4-star roster, and the starglitter refund turns on
exactly those characters. `docs/DESIGN_wish_planner.md` §9.4.

**Null is not zero.** An unknown constellation and a C0 one produce different refund figures
and only one of them is a claim, so the column is nullable and the API keeps the two apart —
the same three-state rule `owned` already follows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType
from app.models.roster import CharacterRosterEntry
from app.repositories.roster import CharacterRosterRepository

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _character_id(session: AsyncSession, nanoka_id: str = "n-roster") -> str:
    """A catalogue row, made here: the test database holds no seeded catalogue, and a test
    that silently found none would pass by testing nothing."""
    existing = (await session.execute(
        select(Character).where(Character.nanoka_id == nanoka_id),
    )).scalar_one_or_none()
    if existing is None:
        existing = Character(
            nanoka_id=nanoka_id, name=f"Character {nanoka_id}", element=Element.CRYO,
            weapon_type=WeaponType.SWORD, rarity=Rarity.FOUR_STAR,
            base_hp=1000.0, base_atk=26.0, base_def=60.0,
            base_crit_rate=0.05, base_crit_dmg=0.5,
        )
        session.add(existing)
        await session.flush()
    return str(existing.id)


async def test_an_import_stores_the_constellation(
    authed_user: tuple, db_session: AsyncSession
) -> None:
    user, _ = authed_user
    character_id = await _character_id(db_session)

    repository = CharacterRosterRepository(db_session, str(user.id))
    await repository.upsert_imported([(character_id, 4)])
    await db_session.commit()

    entry = await repository.entry(character_id)
    assert entry is not None
    assert entry.constellation == 4
    assert entry.source == "import"


async def test_an_unknown_constellation_stays_null(
    authed_user: tuple, db_session: AsyncSession
) -> None:
    """Defaulting to 0 would make a maxed roster read as unmaxed and understate the refund."""
    user, _ = authed_user
    character_id = await _character_id(db_session)

    repository = CharacterRosterRepository(db_session, str(user.id))
    await repository.upsert_imported([(character_id, None)])
    await db_session.commit()

    entry = await repository.entry(character_id)
    assert entry is not None
    assert entry.constellation is None, "null means nobody has said, and that is not C0"


async def test_a_re_import_refreshes_the_constellation(
    authed_user: tuple, db_session: AsyncSession
) -> None:
    user, _ = authed_user
    character_id = await _character_id(db_session)
    repository = CharacterRosterRepository(db_session, str(user.id))

    await repository.upsert_imported([(character_id, 1)])
    await db_session.commit()
    await repository.upsert_imported([(character_id, 3)])
    await db_session.commit()

    entry = await repository.entry(character_id)
    assert entry is not None
    assert entry.constellation == 3


async def test_an_import_does_not_overwrite_a_manual_answer(
    authed_user: tuple, db_session: AsyncSession
) -> None:
    """The rule `owned` already follows, extended to the constellation beside it.

    A user who corrected a constellation by hand means it; a rescan that undid it every time
    would read as the app ignoring them.
    """
    user, _ = authed_user
    character_id = await _character_id(db_session)
    repository = CharacterRosterRepository(db_session, str(user.id))

    await repository.set_constellation(character_id, 6)
    await db_session.commit()
    await repository.upsert_imported([(character_id, 0)])
    await db_session.commit()

    entry = await repository.entry(character_id)
    assert entry is not None
    assert entry.constellation == 6
    assert entry.source == "manual"


async def test_the_api_reports_the_constellation(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    character_id = await _character_id(db_session)
    await db_session.commit()
    response = await authed_client.patch(
        f"/api/v1/roster/{character_id}", json={"owned": True, "constellation": 2},
    )
    assert response.status_code == 200
    assert response.json()["constellation"] == 2
    assert response.json()["source"] == "manual"

    listed = (await authed_client.get("/api/v1/roster")).json()["entries"]
    row = next(e for e in listed if e["character_id"] == character_id)
    assert row["constellation"] == 2


async def test_omitting_the_field_leaves_a_stored_constellation_alone(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Three states. Omitted is not the same as null, which is not the same as 0."""
    character_id = await _character_id(db_session)
    await db_session.commit()
    await authed_client.patch(
        f"/api/v1/roster/{character_id}", json={"owned": True, "constellation": 5},
    )
    response = await authed_client.patch(
        f"/api/v1/roster/{character_id}", json={"owned": True},
    )
    assert response.json()["constellation"] == 5


async def test_an_explicit_null_clears_it(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    character_id = await _character_id(db_session)
    await db_session.commit()
    await authed_client.patch(
        f"/api/v1/roster/{character_id}", json={"owned": True, "constellation": 5},
    )
    response = await authed_client.patch(
        f"/api/v1/roster/{character_id}", json={"owned": True, "constellation": None},
    )
    assert response.json()["constellation"] is None


@pytest.mark.parametrize("value", [-1, 7, 99])
async def test_a_constellation_outside_the_range_is_refused(
    authed_client: AsyncClient, db_session: AsyncSession, value: int
) -> None:
    character_id = await _character_id(db_session)
    await db_session.commit()
    response = await authed_client.patch(
        f"/api/v1/roster/{character_id}", json={"owned": True, "constellation": value},
    )
    assert response.status_code == 422


async def test_the_database_refuses_an_out_of_range_constellation(
    authed_user: tuple, db_session: AsyncSession
) -> None:
    """The check constraint, not only the schema — a repository write bypasses Pydantic."""
    from sqlalchemy.exc import IntegrityError

    user, _ = authed_user
    character_id = await _character_id(db_session)
    db_session.add(
        CharacterRosterEntry(
            owner_id=str(user.id), character_id=character_id,
            owned=True, constellation=9, source="manual",
        ),
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
