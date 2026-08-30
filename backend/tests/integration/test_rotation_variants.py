"""Kit variants and groups, end to end.

`DESIGN_rotation_builder_gui.md` §3 and §5. A hold-E is a different move to a tap-E from the
player's side, and only 55 of gcsim's 117 characters have one — so the vocabulary an editor is
offered is **per character**, and so is the refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from app.models.build import Build
from app.models.character import Character, Talent
from app.models.enums import Element, Rarity, TalentType, WeaponType
from app.models.team import Team

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio

ROTATIONS = "/api/v1/rotations"

#: Chevreuse declares `hold` on her skill and Xingqiu declares nothing — the pair the whole
#: chunk turns on. Both are read from gcsim's own generated validation table, not asserted here.
CHEVREUSE = ("10000088", "Chevreuse", Element.PYRO)
XINGQIU = ("10000025", "Xingqiu", Element.HYDRO)


@dataclass
class Party:
    team_id: str
    chevreuse: str
    xingqiu: str


@pytest.fixture
async def party(db_session: AsyncSession, authed_user: tuple[User, str]) -> Party:
    user, _ = authed_user
    builds = {}
    for nanoka_id, name, element in (CHEVREUSE, XINGQIU):
        character = Character(
            nanoka_id=nanoka_id, name=name, element=element,
            weapon_type=WeaponType.POLEARM, rarity=Rarity.FOUR_STAR,
            base_hp=1000.0, base_atk=26.0, base_def=60.0,
            base_crit_rate=0.05, base_crit_dmg=0.5,
        )
        db_session.add(character)
        await db_session.flush()
        # One talent each, so the offers carry a real name and a real sprite basename rather
        # than falling back to the action key for every entry.
        db_session.add(
            Talent(
                character_id=str(character.id), nanoka_id=1,
                talent_type=TalentType.ELEMENTAL_SKILL,
                name=f"{name}'s skill", icon=f"Skill_S_{name}_01",
            ),
        )
        build = Build(owner_id=str(user.id), character_id=str(character.id))
        db_session.add(build)
        await db_session.flush()
        builds[nanoka_id] = str(build.id)

    team = Team(
        owner_id=str(user.id), name="Overload",
        build1_id=builds[CHEVREUSE[0]], build2_id=builds[XINGQIU[0]],
    )
    db_session.add(team)
    await db_session.flush()
    return Party(team_id=str(team.id), chevreuse=CHEVREUSE[0], xingqiu=XINGQIU[0])


async def _offers(client: AsyncClient, nanoka_id: str) -> list[dict]:
    teams = (await client.get(f"{ROTATIONS}/options")).json()["teams"]
    roster = teams[0]["characters"]
    return next(c["actions"] for c in roster if c["nanoka_id"] == nanoka_id)


# ── The vocabulary is per character ──────────────────────────────────────────


async def test_a_character_with_a_hold_skill_is_offered_one(
    authed_client: AsyncClient, party: Party,
):
    offered = {o["action"] for o in await _offers(authed_client, party.chevreuse)}

    assert "skill_hold" in offered


async def test_a_character_without_one_is_not(authed_client: AsyncClient, party: Party):
    """The same endpoint, the same team, a different answer per character."""
    offered = {o["action"] for o in await _offers(authed_client, party.xingqiu)}

    assert "skill_hold" not in offered
    assert "skill" in offered


async def test_every_offer_carries_its_base_and_its_variant(
    authed_client: AsyncClient, party: Party,
):
    """The badge reads `variant`; the compiler reads `action`; the sprite belongs to `base`."""
    offers = {o["action"]: o for o in await _offers(authed_client, party.chevreuse)}

    assert offers["skill"]["variant"] is None
    assert offers["skill_hold"]["variant"] == "hold"
    assert offers["skill_hold"]["base"] == "skill"


async def test_a_variant_is_named_and_illustrated_like_its_base(
    authed_client: AsyncClient, party: Party,
):
    """A hold-E is the same talent, so it carries the same name and the same sprite.

    The variant is the only thing that differs, which is what makes a badge the right way to
    draw it rather than a second unrelated button.
    """
    offers = {o["action"]: o for o in await _offers(authed_client, party.chevreuse)}

    assert offers["skill_hold"]["name"] == offers["skill"]["name"] == "Chevreuse's skill"
    assert offers["skill_hold"]["icon"] == offers["skill"]["icon"] == "Skill_S_Chevreuse_01"


async def test_an_action_that_is_not_a_talent_keeps_its_key_and_has_no_sprite(
    authed_client: AsyncClient, party: Party,
):
    """Owner ruling: the other seven are words, not glyphs.

    And they keep their key rather than borrowing the normal attack's name, because calling a
    charged attack "Chevreuse's skill" would be a wrong name rather than a missing one.
    """
    offers = {o["action"]: o for o in await _offers(authed_client, party.chevreuse)}

    assert offers["charge"]["name"] == "charge"
    assert offers["charge"]["icon"] is None


# ── The picker offers exactly what the validator accepts, per character ──────


async def test_every_offered_action_can_actually_be_saved(
    authed_client: AsyncClient, party: Party,
):
    """Not "the list looks sensible" — every entry is posted.

    `RotationOptions` has always made this guarantee over one global list. Making it per
    character is a stronger claim and an easier one to break, so it is checked per character.
    """
    for nanoka_id in (party.chevreuse, party.xingqiu):
        offers = await _offers(authed_client, nanoka_id)
        assert offers, "an empty list would pass this vacuously"
        for offer in offers:
            saved = await authed_client.post(ROTATIONS, json={
                "name": f"try {offer['action']} {nanoka_id}", "team_id": party.team_id,
                "steps": [{"character": nanoka_id, "action": offer["action"]}],
            })
            assert saved.status_code == 201, f"offered but refused: {offer['action']}"


async def test_a_variant_the_character_does_not_have_is_refused(
    authed_client: AsyncClient, party: Party,
):
    """And the reason is not that gcsim would complain — **measured, it does not**.

    `xingqiu skill[hold=1]` and `xingqiu skill` produce byte-identical damage through the
    committed wasm build, while the same pair for Chevreuse differs. So an unrefused hold here
    would mean a run that quietly performed a tap and a number that looks entirely reasonable
    for a rotation the user did not write.
    """
    refused = await authed_client.post(ROTATIONS, json={
        "name": "xingqiu holds nothing", "team_id": party.team_id,
        "steps": [{"character": party.xingqiu, "action": "skill_hold"}],
    })

    assert refused.status_code == 422
    assert "Xingqiu has no hold skill" in refused.json()["detail"]


async def test_a_patch_is_checked_too(authed_client: AsyncClient, party: Party):
    """The write path is two endpoints and the check belongs to both."""
    created = await authed_client.post(ROTATIONS, json={
        "name": "fine", "team_id": party.team_id,
        "steps": [{"character": party.xingqiu, "action": "skill"}],
    })

    patched = await authed_client.patch(
        f"{ROTATIONS}/{created.json()['id']}",
        json={"steps": [{"character": party.xingqiu, "action": "skill_hold"}]},
    )

    assert patched.status_code == 422


# ── Groups ──────────────────────────────────────────────────────────────────


async def test_a_group_saves_and_reads_back(authed_client: AsyncClient, party: Party):
    """`DECISIONS.md` §27. JSONB, so a group needed no migration — only fields on a step."""
    steps = [
        {"character": party.chevreuse, "action": "skill", "group": "g", "group_repeat": 3},
        {"character": party.xingqiu, "action": "burst", "group": "g", "group_repeat": 3},
    ]

    created = await authed_client.post(ROTATIONS, json={
        "name": "three cycles", "team_id": party.team_id, "steps": steps,
    })

    assert created.status_code == 201
    read = created.json()["steps"]
    assert [s["group"] for s in read] == ["g", "g"]
    assert [s["group_repeat"] for s in read] == [3, 3]


async def test_a_group_compiles_to_its_steps_repeated(
    authed_client: AsyncClient, party: Party,
):
    """The whole justification for amending §2: the emitted config is the flat form."""
    created = await authed_client.post(ROTATIONS, json={
        "name": "unrolls", "team_id": party.team_id,
        "steps": [
            {"character": party.chevreuse, "action": "skill", "group": "g", "group_repeat": 3},
        ],
    })

    compiled = await authed_client.post(f"{ROTATIONS}/{created.json()['id']}/compile")

    assert compiled.status_code == 200
    assert compiled.json()["config"].count("chevreuse skill;") == 3


async def test_a_scattered_group_is_refused(authed_client: AsyncClient, party: Party):
    """A group is a chunk. Gathering its members would reorder the user's rotation."""
    refused = await authed_client.post(ROTATIONS, json={
        "name": "scattered", "team_id": party.team_id,
        "steps": [
            {"character": party.chevreuse, "action": "skill", "group": "g", "group_repeat": 2},
            {"character": party.xingqiu, "action": "attack"},
            {"character": party.chevreuse, "action": "burst", "group": "g", "group_repeat": 2},
        ],
    })

    assert refused.status_code == 422


async def test_a_group_that_disagrees_with_itself_is_refused(
    authed_client: AsyncClient, party: Party,
):
    """`unroll` reads one member's count, so two answers would be one silently discarded."""
    refused = await authed_client.post(ROTATIONS, json={
        "name": "disagreeing", "team_id": party.team_id,
        "steps": [
            {"character": party.chevreuse, "action": "skill", "group": "g", "group_repeat": 2},
            {"character": party.xingqiu, "action": "burst", "group": "g", "group_repeat": 5},
        ],
    })

    assert refused.status_code == 422
