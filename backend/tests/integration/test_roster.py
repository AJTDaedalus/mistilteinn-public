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


async def _character(
    session, nanoka_id: str, name: str,
    weapon_type: WeaponType = WeaponType.SWORD,
) -> Character:
    row = Character(
        nanoka_id=nanoka_id, name=name, element=Element.CRYO,
        weapon_type=weapon_type, rarity=Rarity.FIVE_STAR,
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


async def test_a_character_of_an_unshipped_weapon_class_is_never_offered(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """Two Traveler variants carry `WEAPON_CROSSBOW`, a class the game has not shipped.

    The same argument as the mannequins one line up: this list asks *"do you own this
    character?"* about every row it draws, and nobody owns one that does not exist.

    **This route reads `select(Character)` directly**, so it does not inherit the catalogue
    repository's exclusion and had to be told separately — which is exactly how the mannequin
    rule already came to be written out in two places. Found by reading for the second copy
    after the first was fixed, not by anything failing.
    """
    await _character(db_session, "10000005-9", "Traveler", WeaponType.CROSSBOW)
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


async def test_a_character_of_an_unshipped_class_cannot_be_owned_by_asking_directly(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """The list hides these (#271, `app/services/unreleased.py`) and the write route did not.

    A `PATCH` on one wrote a roster row that `list_roster` then filtered out: owned, invisible,
    and impossible to un-own through the UI that never drew it. The mannequin rule above
    guards both surfaces, which is the precedent this one was written from and had only half
    copied.
    """
    traveler = await _character(
        db_session, "10000005-9", "Traveler", weapon_type=WeaponType.CROSSBOW,
    )
    await db_session.commit()

    response = await authed_client.patch(
        f"{ROSTER}/{traveler.id}", json={"owned": True},
    )

    assert response.status_code == 422
    # And nothing was written — a refusal that still persisted the row would be the bug with
    # a status code on it.
    listed = await authed_client.get(ROSTER)
    assert all(entry["character_id"] != str(traveler.id) for entry in listed.json()["entries"])
    assert listed.json()["owned_count"] == 0


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


# ── the Travelers ────────────────────────────────────────────────────────────


async def _traveler(
    session, nanoka_id: str, icon: str, element: Element | None,
    weapon_type: WeaponType = WeaponType.SWORD,
) -> Character:
    """One of the sixteen rows named `Traveler`. The name is identical by design.

    The class is a parameter because the two unreleased bodies carry `WEAPON_CROSSBOW`, which
    is what `is_unreleased_class` reads — see `app/services/unreleased.py` and #271.
    """
    row = Character(
        nanoka_id=nanoka_id, name="Traveler", element=element,
        weapon_type=weapon_type, rarity=Rarity.FIVE_STAR, icon=icon,
        base_hp=1000.0, base_atk=26.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    session.add(row)
    await session.flush()
    return row


async def test_two_travelers_of_one_element_are_two_different_rows(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """**The bug.** Every Traveler row is *named* `Traveler`, so this tab drew Aether Dendro and
    Lumine Dendro as the same row twice — same name, same element chip, differing only in a
    72px face — on the one tab whose whole purpose is letting a user correct ownership by hand.
    """
    await _traveler(db_session, "10000005-8", "UI_AvatarIcon_PlayerBoy", Element.DENDRO)
    await _traveler(db_session, "10000007-8", "UI_AvatarIcon_PlayerGirl", Element.DENDRO)
    await db_session.commit()

    body = (await authed_client.get(ROSTER)).json()

    assert [e["display_name"] for e in body["entries"]] == [
        "Traveler (Aether · Dendro)", "Traveler (Lumine · Dendro)",
    ]
    # `name` is untouched: it is what the catalogue says, and a client that wants to search or
    # group by the character rather than the variant still needs it.
    assert {e["name"] for e in body["entries"]} == {"Traveler"}


async def test_a_character_gcsim_cannot_run_says_so_on_the_row(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """**gcsim implements six Traveler elements, not seven.**

    The owner's account holds exactly one Traveler — Cryo — which is the one that cannot be
    compiled. `character_key` has always refused it correctly; nothing above it asked before
    the roster offered the row and the builds tab offered to build it, so the first sign was a
    search failing after several minutes.
    """
    await _traveler(db_session, "10000005-5", "UI_AvatarIcon_PlayerBoy", Element.CRYO)
    await _traveler(db_session, "10000005-4", "UI_AvatarIcon_PlayerBoy", Element.ANEMO)
    await db_session.commit()

    rows = {e["display_name"]: e for e in (await authed_client.get(ROSTER)).json()["entries"]}

    assert rows["Traveler (Aether · Anemo)"]["simulatable"] is True
    assert rows["Traveler (Aether · Anemo)"]["unsimulatable_reason"] is None
    assert rows["Traveler (Aether · Cryo)"]["simulatable"] is False
    # gcsim's own terms, not a sentence this repo composed about somebody else's engine.
    assert "Cryo Traveler" in rows["Traveler (Aether · Cryo)"]["unsimulatable_reason"]


async def test_an_unreleased_body_is_withheld_and_counted(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """`10000134` and `10000135` have no element and no talents, so they rendered as two
    *identical* blank rows — no name to tell them apart and no chip either.

    **Counted rather than silently dropped.** Withholding is the one thing this endpoint does
    that a user cannot see, so a rule that misfired would empty the roster with no symptom.

    Selected by **weapon class**, not by talent count: #271 landed `is_unreleased_class` while
    this branch was open, and `WEAPON_CROSSBOW` is the stronger signal — it also hides eight
    unreleased weapon *names*, which a talent count never touched. Both rules pick out the
    same two rows at nanoka 7.0.51.
    """
    await _traveler(
        db_session, "10000134", "UI_AvatarIcon_PlayerBoy", None, WeaponType.CROSSBOW,
    )
    await _character(db_session, "10000027", "Ningguang")
    await db_session.commit()

    body = (await authed_client.get(ROSTER)).json()

    assert [e["name"] for e in body["entries"]] == ["Ningguang"]
    assert body["withheld"] == 1


async def test_a_real_character_whose_talents_failed_to_import_is_kept(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """**A talentless row is still a character, and the roster keeps it.**

    Element is read from the index row and talents from the detail fetch, so a seed whose
    detail pass failed leaves real characters talentless. Dropping them would be the quiet,
    one-directional failure this whole design exists to fix — a roster missing a character —
    and it would look exactly like success.

    This test argued for a conjunction when the exclusion was `element is None and no talents`.
    The exclusion is by weapon class now (#271), so a talent count cannot exclude anyone at
    all — which makes the property here easier to hold, not less worth pinning.
    """
    await _character(db_session, "10000027", "Ningguang")  # element set, no talents
    await db_session.commit()

    body = (await authed_client.get(ROSTER)).json()

    assert [e["name"] for e in body["entries"]] == ["Ningguang"]
    assert body["withheld"] == 0


async def test_an_unreleased_body_cannot_be_owned_by_hand_either(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """Refused **by name**, and with its own message: "cannot be owned" and "is not in the game
    yet" are different facts, and a user waiting for a character learns nothing from the first.

    A silent no-op would leave a toggle that appears to work and does not.

    A write route that accepts what the read route will not show writes a row nobody can see
    or undo, which is why both surfaces carry the guard.
    """
    row = await _traveler(
        db_session, "10000135", "UI_AvatarIcon_PlayerGirl", None, WeaponType.CROSSBOW,
    )
    await db_session.commit()

    answer = await authed_client.patch(f"{ROSTER}/{row.id}", json={"owned": True})

    assert answer.status_code == 422
    assert "not in the game" in answer.json()["detail"]


async def test_the_correction_route_returns_the_row_the_list_would_have(
    authed_client: AsyncClient, db_session: AsyncSession,
) -> None:
    """Both routes build a row through `_entry`. They did not, and the drift was the kind that
    puts a name on one route and not the other."""
    row = await _traveler(db_session, "10000007-4", "UI_AvatarIcon_PlayerGirl", Element.ANEMO)
    await db_session.commit()

    patched = (await authed_client.patch(f"{ROSTER}/{row.id}", json={"owned": True})).json()
    listed = (await authed_client.get(ROSTER)).json()["entries"][0]

    assert patched == listed
