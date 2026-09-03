"""The character roster, end to end — `TASKS_character_roster.md` 4, 5 and 6.

`DESIGN_character_roster.md`. Ownership moved off `builds` because a build is created only for
a character *holding gear*, so twelve characters the owner has carried no ownership record at
all — 22 furnishing sets, 440 Primogems the teapot tracker could not see.

These drive the routes rather than the model, because the failure this design fixes was never
visible in a model: every table was correct and the *question* was being asked of the wrong one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient  # noqa: TC002 — a fixture type, resolved at runtime

from app.data.importers.good_importer import GoodImportResult, ParsedCharacter
from app.models.character import Character
from app.models.enums import Element, Rarity, WeaponType
from app.models.roster import SOURCE_MANUAL, CharacterRosterEntry
from app.repositories.roster import CharacterRosterRepository
from app.services.good_build_service import rebuild_builds

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ROSTER = "/api/v1/roster"
pytestmark = pytest.mark.asyncio


async def _character(session, nanoka_id: str, name: str) -> Character:
    row = Character(
        nanoka_id=nanoka_id, name=name, element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1000.0, base_atk=26.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    session.add(row)
    await session.flush()
    return row


async def test_the_roster_offers_a_character_nobody_has_mentioned(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """The catalogue left-joined to the answers. A character with no row still needs a toggle,
    and a row that does not exist cannot carry one."""
    await _character(db_session, "10000027", "Ningguang")
    await db_session.commit()

    body = (await authed_client.get(ROSTER)).json()
    row = next(e for e in body["entries"] if e["name"] == "Ningguang")

    assert row["owned"] is None
    assert row["source"] is None


async def test_a_fresh_account_owns_nothing_without_claiming_it_owns_nothing(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """DESIGN §2.1 — the distinction that stops "we never asked" reading as "you have none"."""
    await _character(db_session, "10000027", "Ningguang")
    await db_session.commit()

    body = (await authed_client.get(ROSTER)).json()

    assert body["owned_count"] == 0
    assert all(entry["owned"] is None for entry in body["entries"])


async def test_a_mannequin_is_never_offered(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """They are real catalogue rows and `/characters` still shows them; they cannot be owned,
    so a toggle here would be a control that lies."""
    await _character(db_session, "10000117-2", "Manekin")
    await _character(db_session, "10000027", "Ningguang")
    await db_session.commit()

    body = (await authed_client.get(ROSTER)).json()

    assert [e["name"] for e in body["entries"]] == ["Ningguang"]


async def test_a_mannequin_cannot_be_owned_by_asking_directly(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """Refused **by name**, not silently ignored — the rule the rotation compiler follows for
    a condition it cannot model. A no-op would leave a route that appears to work."""
    dummy = await _character(db_session, "10000118-5", "Manekina")
    await db_session.commit()

    response = await authed_client.patch(
        f"{ROSTER}/{dummy.id}", json={"owned": True},
    )

    assert response.status_code == 422


async def test_the_user_can_say_they_have_a_character(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    character = await _character(db_session, "10000027", "Ningguang")
    await db_session.commit()

    response = await authed_client.patch(
        f"{ROSTER}/{character.id}", json={"owned": True},
    )

    assert response.status_code == 200
    assert response.json()["owned"] is True
    assert response.json()["source"] == SOURCE_MANUAL


async def test_an_answer_survives_a_reload(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """The whole point of the tab. Asserted through a second request rather than on the
    response body, which would only prove the handler can echo."""
    character = await _character(db_session, "10000027", "Ningguang")
    await db_session.commit()

    await authed_client.patch(f"{ROSTER}/{character.id}", json={"owned": True})
    body = (await authed_client.get(ROSTER)).json()

    assert next(e for e in body["entries"] if e["name"] == "Ningguang")["owned"] is True
    assert body["owned_count"] == 1


async def test_an_unknown_character_is_a_404(authed_client: AsyncClient) -> None:
    response = await authed_client.patch(
        f"{ROSTER}/01a00000-0000-7000-8000-00000000dead", json={"owned": True},
    )

    assert response.status_code == 404


async def test_an_import_leaves_a_manual_answer_alone(
    db_session: AsyncSession, authed_user,
) -> None:
    """**The reason `source` exists.** A user who un-owns a character means it; an import that
    undid that on every rescan would read as the app ignoring them."""
    user, _ = authed_user
    character = await _character(db_session, "10000027", "Ningguang")
    repository = CharacterRosterRepository(db_session, str(user.id))
    await repository.set_owned(str(character.id), owned=False)
    await db_session.commit()

    await repository.upsert_imported([str(character.id)])
    await db_session.commit()

    entry = await db_session.get(
        CharacterRosterEntry, {"owner_id": str(user.id), "character_id": str(character.id)},
    )
    assert entry.owned is False
    assert entry.source == SOURCE_MANUAL


async def test_a_reimport_refreshes_a_row_it_wrote_itself(
    db_session: AsyncSession, authed_user,
) -> None:
    """The other half of the same rule — `import` rows are the importer's to update."""
    user, _ = authed_user
    character = await _character(db_session, "10000027", "Ningguang")
    repository = CharacterRosterRepository(db_session, str(user.id))
    await repository.upsert_imported([str(character.id)])
    await db_session.commit()

    written = await repository.upsert_imported([str(character.id)])
    await db_session.commit()

    assert written == 1


async def test_the_import_gives_an_unequipped_character_a_roster_row_and_no_build(
    db_session: AsyncSession, authed_user,
) -> None:
    """**The bug this design exists for**, in one test.

    Ningguang is in the owner's export and holds nothing, so `rebuild_builds` correctly makes
    her no build. Before the roster she therefore had no ownership record either, and the
    teapot tracker could not see her — one of twelve, worth 440 Primogems between them.
    """
    user, _ = authed_user
    await _character(db_session, "10000027", "Ningguang")
    await db_session.commit()

    parsed = GoodImportResult(
        artifacts=(), rejected=(), source="Irminsul", version=3,
        characters=(
            ParsedCharacter(
                key="Ningguang", level=90, ascension=6, constellation=0, talents={},
            ),
        ),
        weapons=(),
    )
    report = await rebuild_builds(
        db_session, owner_id=str(user.id), parsed=parsed, stored={},
    )
    await db_session.commit()

    assert report.created == 0, "she holds nothing, so she gets no build"
    assert report.roster_written == 1, "she is still a character the account has"

    owned = await CharacterRosterRepository(db_session, str(user.id)).owned_nanoka_ids()
    assert owned == {"10000027"}


async def test_the_import_does_not_put_a_mannequin_on_the_roster(
    db_session: AsyncSession, authed_user,
) -> None:
    """The equipment rule used to exclude them for free. Now it is on purpose, and by id."""
    user, _ = authed_user
    await _character(db_session, "10000117-2", "Manekin")
    await db_session.commit()

    parsed = GoodImportResult(
        artifacts=(), rejected=(), source="Irminsul", version=3,
        characters=(
            ParsedCharacter(key="Manekin", level=1, ascension=0, constellation=0, talents={}),
        ),
        weapons=(),
    )
    report = await rebuild_builds(
        db_session, owner_id=str(user.id), parsed=parsed, stored={},
    )

    assert report.roster_written == 0
