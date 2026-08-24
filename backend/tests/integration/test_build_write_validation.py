"""T.1 — the build write path refuses what cannot be simulated.

`create_build` was one `repo.create` call. `DESIGN_teams_builds.md` §2.1 and §2.2 record what
that let through; the worst of it is silent. `gcsim_config._talents` reads a missing key as
level 1, so a misspelled `talent_levels` key simulates a talent-9 burst at talent 1 — a wrong
number that looks right, which is the one failure mode this repo treats as non-negotiable.

Every refusal here is checked on **POST and PATCH**. Create is not the only way a build
changes, and R.4's review found exactly that hole in the rotation API.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from app.models.character import Character
from app.models.enums import Element, Rarity, StatType, WeaponType
from app.models.weapon import Weapon

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

BUILDS = "/api/v1/builds"
ABSENT = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
async def catalogue(db_session: AsyncSession) -> dict[str, str]:
    """A sword character, a sword, and a bow — enough to mismatch on purpose."""
    ayaka = Character(
        nanoka_id="10000002", name="Kamisato Ayaka", element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1001.0, base_atk=26.6, base_def=61.0,
        base_crit_rate=0.05, base_crit_dmg=0.5,
    )
    sword = Weapon(
        nanoka_id=11509, name="Mistsplitter Reforged", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=48.0, sub_stat_type=StatType.CRIT_DMG,
        sub_stat_base_value=0.096,
    )
    bow = Weapon(
        nanoka_id=15502, name="Amos' Bow", weapon_type=WeaponType.BOW,
        rarity=Rarity.FIVE_STAR, base_atk=46.0, sub_stat_type=StatType.ATK_PCT,
        sub_stat_base_value=0.108,
    )
    db_session.add_all([ayaka, sword, bow])
    await db_session.flush()
    return {
        "character": str(ayaka.id), "sword": str(sword.id), "bow": str(bow.id),
    }


def _body(catalogue: dict[str, str], **overrides) -> dict:
    body = {"character_id": catalogue["character"], "weapon_id": catalogue["sword"]}
    body.update(overrides)
    return body


async def _existing(client: AsyncClient, catalogue: dict[str, str]) -> str:
    created = await client.post(BUILDS, json=_body(catalogue))
    assert created.status_code == 201, created.text
    return created.json()["id"]


# ── the happy path still works ───────────────────────────────────────────────


async def test_a_valid_build_still_saves(authed_client: AsyncClient, catalogue):
    """Guards the guard. Every assertion below is about a refusal, and all of them would
    pass if the endpoint refused everything."""
    created = await authed_client.post(BUILDS, json=_body(
        catalogue, talent_levels={"normal_attack": 10, "elemental_burst": 9},
    ))

    assert created.status_code == 201, created.text
    assert created.json()["talent_levels"]["elemental_burst"] == 9


async def test_a_build_may_have_no_weapon(authed_client: AsyncClient, catalogue):
    """OQ-T3. A build being assembled is a real state, and the damage chain already refuses
    to run without a weapon — which is the right place for that requirement, at use rather
    than at save."""
    created = await authed_client.post(BUILDS, json=_body(catalogue, weapon_id=None))

    assert created.status_code == 201, created.text


# ── the character must exist ─────────────────────────────────────────────────


async def test_an_absent_character_is_a_422_not_a_500(
    authed_client: AsyncClient, catalogue,
):
    """It used to be a 500: the FK rejected it at flush and the IntegrityError escaped. The
    user was told the server broke, when what happened is they named something not there."""
    response = await authed_client.post(BUILDS, json=_body(catalogue, character_id=ABSENT))

    assert response.status_code == 422, response.text
    assert ABSENT in response.json()["detail"]


async def test_a_patch_naming_an_unpatchable_field_is_refused_not_ignored(
    authed_client: AsyncClient, catalogue,
):
    """`BuildUpdate` has no `character_id`, and used to drop it silently.

    A caller sending one got **200 having changed nothing** — told their edit succeeded when
    it had been discarded. Changing a build's character makes it a different build, so the
    field stays out; `extra="forbid"` makes that a refusal rather than a pretence.
    """
    build_id = await _existing(authed_client, catalogue)

    response = await authed_client.patch(
        f"{BUILDS}/{build_id}", json={"character_id": ABSENT},
    )

    assert response.status_code == 422
    assert "character_id" in json.dumps(response.json()["detail"])


# ── the weapon must exist, and must be one the character can hold ────────────


async def test_an_absent_weapon_is_refused(authed_client: AsyncClient, catalogue):
    response = await authed_client.post(BUILDS, json=_body(catalogue, weapon_id=ABSENT))

    assert response.status_code == 422
    assert ABSENT in response.json()["detail"]


async def test_a_weapon_the_character_cannot_hold_is_refused(
    authed_client: AsyncClient, catalogue,
):
    """OQ-T1: a refusal, not a warning. The game cannot equip a Bow on a Sword character and
    gcsim cannot simulate it, so there is no reading under which the build is meaningful."""
    response = await authed_client.post(BUILDS, json=_body(catalogue, weapon_id=catalogue["bow"]))

    assert response.status_code == 422
    detail = response.json()["detail"]
    # Both types named: "wrong weapon" does not tell anyone what to do next.
    assert "Sword" in detail
    assert "Bow" in detail


async def test_a_patch_cannot_equip_a_weapon_the_character_cannot_hold(
    authed_client: AsyncClient, catalogue,
):
    build_id = await _existing(authed_client, catalogue)

    response = await authed_client.patch(
        f"{BUILDS}/{build_id}", json={"weapon_id": catalogue["bow"]},
    )

    assert response.status_code == 422


async def test_a_patch_checks_the_merged_pairing_not_just_the_patch_body(
    authed_client: AsyncClient, catalogue,
):
    """What is validated is character-and-weapon *together*.

    A patch naming only `weapon_id` is a body in which every field is individually fine; it
    is illegal only against the character the row already holds. Checking the patch alone
    would let it through.
    """
    build_id = await _existing(authed_client, catalogue)

    response = await authed_client.patch(
        f"{BUILDS}/{build_id}", json={"weapon_id": catalogue["bow"]},
    )

    assert response.status_code == 422
    assert "Sword" in response.json()["detail"]


async def test_a_build_can_be_unequipped(authed_client: AsyncClient, catalogue):
    """An explicit `null` weapon means unequip, and must survive the merge as None rather
    than falling back to the stored weapon."""
    build_id = await _existing(authed_client, catalogue)

    patched = await authed_client.patch(f"{BUILDS}/{build_id}", json={"weapon_id": None})

    assert patched.status_code == 200, patched.text
    assert patched.json()["weapon_id"] is None


# ── talent levels ────────────────────────────────────────────────────────────


async def test_a_misspelled_talent_key_is_refused(authed_client: AsyncClient, catalogue):
    """DESIGN §2.2, and the reason T.1 comes before any page.

    `gcsim_config._talents` reads a missing key as level 1, so `"burst": 9` — which looks
    entirely reasonable — simulates a talent-9 burst at talent 1. Nothing errors, and the
    number is wrong.
    """
    response = await authed_client.post(BUILDS, json=_body(
        catalogue, talent_levels={"burst": 9},
    ))

    assert response.status_code == 422
    # Pydantic's 422 body is a list of errors, so search the serialised detail rather than
    # indexing into a shape that changes with the number of failures.
    detail = json.dumps(response.json()["detail"])
    assert "burst" in detail
    assert "elemental_burst" in detail, "the message must name what was meant"


async def test_a_talent_with_no_level_is_refused(authed_client: AsyncClient, catalogue):
    """`alternate_sprint` is a real `TalentType` and has no level — it is a mode, not a skill
    with a scaling table. Accepting it would store a number nothing reads."""
    response = await authed_client.post(BUILDS, json=_body(
        catalogue, talent_levels={"alternate_sprint": 5},
    ))

    assert response.status_code == 422


@pytest.mark.parametrize("level", [0, -1, 16, 999])
async def test_a_talent_level_out_of_range_is_refused(
    authed_client: AsyncClient, catalogue, level: int,
):
    response = await authed_client.post(BUILDS, json=_body(
        catalogue, talent_levels={"elemental_burst": level},
    ))

    assert response.status_code == 422


async def test_fifteen_is_allowed_because_the_scaling_table_defines_it(
    authed_client: AsyncClient, catalogue,
):
    """Not a typo for 10, and not derived from constellation arithmetic.

    Every levelled talent in the committed fixtures carries a 15-row `promote` table keyed
    `0..14`, so level 15 has a scaling row. Refusing it would be this repo asserting a game
    rule it has not cited — see `MAX_TALENT_LEVEL`.
    """
    created = await authed_client.post(BUILDS, json=_body(
        catalogue, talent_levels={"elemental_burst": 15},
    ))

    assert created.status_code == 201, created.text


async def test_a_patch_checks_talent_levels_too(authed_client: AsyncClient, catalogue):
    build_id = await _existing(authed_client, catalogue)

    response = await authed_client.patch(
        f"{BUILDS}/{build_id}", json={"talent_levels": {"skill": 9}},
    )

    assert response.status_code == 422


async def test_the_accepted_talent_keys_are_the_ones_gcsim_is_given(
    authed_client: AsyncClient, catalogue,
):
    """The validator and the config renderer must not be able to disagree.

    If the schema accepted a key `_talents` does not read, that talent's level would be
    stored and then silently ignored. Both come from `LEVELLED_TALENTS`; this checks the
    result rather than the intention.

    Patched rather than created three times: `uq_builds_owner_character` allows one build per
    character, so three creates would collide on the constraint and prove nothing about
    talents.
    """
    from app.models.enums import LEVELLED_TALENTS

    build_id = await _existing(authed_client, catalogue)
    assert LEVELLED_TALENTS, "an empty tuple would pass this vacuously"

    for talent in LEVELLED_TALENTS:
        accepted = await authed_client.patch(
            f"{BUILDS}/{build_id}", json={"talent_levels": {str(talent): 9}},
        )
        assert accepted.status_code == 200, f"{talent} is rendered but refused"


async def test_a_second_build_of_the_same_character_is_refused_not_a_500(
    authed_client: AsyncClient, catalogue,
):
    """`uq_builds_owner_character` was enforced only by the database, so an ordinary action —
    a second Ayaka build — raised a UniqueViolationError and the user was told the server
    broke. The limit is real and under review (`app/models/build.py`); this makes it legible
    rather than endorsing it.
    """
    await _existing(authed_client, catalogue)

    second = await authed_client.post(BUILDS, json=_body(catalogue))

    assert second.status_code == 409, second.text
    assert "one build per character" in second.json()["detail"]


async def test_another_users_build_does_not_block_mine(
    authed_client: AsyncClient, db_session: AsyncSession, catalogue,
):
    """`get_by_filters` was not owner-scoped, so the duplicate check asked "does a build for
    this character exist?" across every tenant.

    Two failures in one: a legitimate build refused because a stranger owns one, and the
    stranger's row id disclosed in the refusal. It is the third method on `BaseRepository` to
    have been written without the owner filter, after `get_all` and `count`.
    """
    from app.models.build import Build
    from app.models.user import User

    stranger = User(email="stranger@example.com", password_hash="not-a-hash")  # noqa: S106
    db_session.add(stranger)
    await db_session.flush()
    theirs = Build(owner_id=str(stranger.id), character_id=catalogue["character"])
    db_session.add(theirs)
    await db_session.flush()

    mine = await authed_client.post(BUILDS, json=_body(catalogue))

    assert mine.status_code == 201, mine.text
    assert str(theirs.id) not in mine.text


async def test_a_typod_field_on_create_is_refused_not_dropped(
    authed_client: AsyncClient, catalogue,
):
    """`constellation` for `constellation_level` would otherwise save a C0 build silently."""
    response = await authed_client.post(BUILDS, json=_body(catalogue, constellation=6))

    assert response.status_code == 422
    assert "constellation" in json.dumps(response.json()["detail"])
