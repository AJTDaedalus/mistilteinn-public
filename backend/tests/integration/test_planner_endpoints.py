"""The leveling planner, end to end over HTTP.

`docs/DESIGN_planner.md`. The cases that matter are the ones where a wrong answer looks right:
a level cap accepted that the game refuses, a material counted as free because nobody knows
its rate, and mora rendered as zero when it is actually unknown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.character import Character, Talent
from app.models.enums import Element, Rarity, TalentType, WeaponType
from app.models.planner import (
    CharacterAscensionCost,
    CharacterTalentCost,
    Material,
    UserMaterial,
    WeaponAscensionCost,
)
from app.models.weapon import Weapon

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

#: Teachings of Freedom — a real domain drop with a published expected yield of 2.2 per
#: 20-resin run, so the resin arithmetic in these tests is checkable by hand.
TEACHINGS = 104301
#: Shivada Jade Sliver — an elemental gem, which costs **no resin**: gems drop from a world
#: boss alongside the boss's own material, in a run that is already paid for.
SLIVER = 104161
#: 60,000 mora per 20-resin Blossom of Wealth, and 122,500 character EXP per 20-resin Blossom
#: of Revelation, both at World Level 9 (owner, 2026-09-07). Restated here so a test that
#: prices mora reads as arithmetic rather than as a magic number.
MORA_PER_RUN, EXP_PER_RUN, LEY_LINE_RESIN = 60_000, 122_500, 20
#: Base-tier equivalents a talent domain yields per 20-resin run, across **both** of its
#: rolls. The game's own preview publishes only the guaranteed 2-star roll's 2.2.
TALENT_DOMAIN_PER_RUN, DOMAIN_RESIN = 10.12, 20
#: Bloodjade Branch — a trounce-domain drop. Costs resin at a yield nobody publishes.
WEEKLY = 113018
#: Sakura Bloom — a local specialty. Costs no resin at all, which is a different thing.
SPECIALTY = 101202


def _auth(authed_user: tuple[User, str]) -> dict[str, str]:
    _, token = authed_user
    return {"Authorization": f"Bearer {token}"}


async def _catalogue(db_session: AsyncSession) -> tuple[Character, Talent, Weapon]:
    """One character with one levelable talent, one weapon, and bills for both."""
    for material_id, name in (
        (TEACHINGS, "Teachings of Freedom"),
        (SLIVER, "Shivada Jade Sliver"),
        (SPECIALTY, "Sakura Bloom"),
        (WEEKLY, "Bloodjade Branch"),
    ):
        db_session.add(
            Material(
                id=material_id, name=name, icon=f"UI_ItemIcon_{material_id}", rarity=2,
            ),
        )

    character = Character(
        nanoka_id="10000002", name="Planner Test", element=Element.CRYO,
        weapon_type=WeaponType.SWORD, rarity=Rarity.FIVE_STAR,
        base_hp=1001.0, base_atk=26.6, base_def=61.0,
        prop_curves={"fight_prop_base_hp": "GROW_CURVE_HP_S5"},
        # Per level, not cumulative: 89 entries of 1,000 is 89,000 EXP from 1 to 90.
        level_exp=[1000] * 90,
    )
    db_session.add(character)
    await db_session.flush()

    talent = Talent(
        character_id=character.id, nanoka_id=10024, talent_type=TalentType.ELEMENTAL_BURST,
        name="Test Burst", description="", icon="Skill_E_Test",
    )
    db_session.add(talent)
    db_session.add(
        CharacterAscensionCost(
            character_id=character.id, phase=1, mora=20000,
            items=[
                {"id": SPECIALTY, "count": 3},
                {"id": SLIVER, "count": 1},
                {"id": WEEKLY, "count": 2},
            ],
        ),
    )
    await db_session.flush()
    for level in range(1, 10):
        db_session.add(
            CharacterTalentCost(
                character_id=character.id, talent_id=talent.id, level=level,
                mora=1000, items=[{"id": TEACHINGS, "count": 2}],
            ),
        )

    weapon = Weapon(
        nanoka_id=11501, name="Planner Sword", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FIVE_STAR, base_atk=48.0, base_atk_curve="GROW_CURVE_ATTACK_101",
        xp_requirements={str(level): 500 for level in range(1, 91)},
    )
    db_session.add(weapon)
    await db_session.flush()
    db_session.add(
        WeaponAscensionCost(
            weapon_id=weapon.id, phase=1, mora=10000, items=[{"id": TEACHINGS, "count": 5}],
        ),
    )
    await db_session.flush()
    return character, talent, weapon


def _request(character: Character, talent: Talent, **overrides: object) -> dict:
    body = {
        "character_id": character.id,
        "character_from": {"level": 1, "ascension": 0},
        "character_to": {"level": 20, "ascension": 1},
        "talents": [{"talent_id": talent.id, "current": 1, "target": 10}],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_a_plan_prices_each_section_separately(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    character, talent, _ = await _catalogue(db_session)
    await db_session.commit()

    response = await client.post(
        "/api/v1/planner/plan", json=_request(character, talent), headers=_auth(authed_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    sections = {section["key"]: section for section in body["sections"]}
    assert set(sections) == {"levels", "ascension", "talents"}
    # Nine talent steps at two Teachings each.
    talent_line = next(
        line for line in sections["talents"]["materials"] if line["material_id"] == TEACHINGS
    )
    assert talent_line["required"] == 18
    assert sections["talents"]["mora"] == 9000
    assert sections["ascension"]["mora"] == 20000
    # 19,000 EXP from level 1 to 20 at 1,000 a level.
    assert sections["levels"]["exp"]["exp_required"] == 19_000


@pytest.mark.asyncio
async def test_owned_stock_is_subtracted(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    user, _ = authed_user
    character, talent, _ = await _catalogue(db_session)
    db_session.add(UserMaterial(owner_id=user.id, material_id=TEACHINGS, count=10))
    await db_session.commit()

    response = await client.post(
        "/api/v1/planner/plan", json=_request(character, talent), headers=_auth(authed_user),
    )
    line = next(
        line
        for section in response.json()["sections"]
        if section["key"] == "talents"
        for line in section["materials"]
        if line["material_id"] == TEACHINGS
    )
    assert (line["required"], line["owned"], line["still_needed"]) == (18, 10, 8)


@pytest.mark.asyncio
async def test_resin_distinguishes_no_cost_from_a_real_one(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """A specialty and a gem cost no resin; a weekly-boss drop costs 30 a run.

    One field for all three would say the specialties are a farming cost and the weekly
    bosses are free — wrong in opposite directions. Gems sit with the specialties because
    they drop alongside a world-boss material in a run already paid for.
    """
    character, talent, _ = await _catalogue(db_session)
    await db_session.commit()

    response = await client.post(
        "/api/v1/planner/plan", json=_request(character, talent), headers=_auth(authed_user),
    )
    ascension = next(s for s in response.json()["sections"] if s["key"] == "ascension")
    by_id = {line["material_id"]: line for line in ascension["materials"]}
    assert by_id[SLIVER]["resin_status"] == "not_farmable"
    assert by_id[SPECIALTY]["resin_status"] == "not_farmable"
    assert by_id[WEEKLY]["resin_status"] == "priced"
    # 2.2 items a run split across the boss's three materials, at 30 resin a run.
    assert by_id[WEEKLY]["resin"]["expected_per_run"] == pytest.approx(2.2 / 3)
    assert by_id[WEEKLY]["resin"]["resin_per_run"] == 30
    assert ascension["resin"]["unpriced"] == []
    assert ascension["resin"]["not_farmable"] == [SPECIALTY, SLIVER]


@pytest.mark.asyncio
async def test_resin_is_priced_and_carries_a_histogram(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    character, talent, _ = await _catalogue(db_session)
    await db_session.commit()

    response = await client.post(
        "/api/v1/planner/plan", json=_request(character, talent), headers=_auth(authed_user),
    )
    body = response.json()
    talents = next(s for s in body["sections"] if s["key"] == "talents")
    # 18 Teachings at 10.12 base-equivalents per 20-resin domain run, plus the section's
    # 9,000 mora at a 20-resin Blossom of Wealth. Mora is resin too.
    expected = (
        18 / TALENT_DOMAIN_PER_RUN * DOMAIN_RESIN
        + 9_000 / MORA_PER_RUN * LEY_LINE_RESIN
    )
    assert talents["resin"]["expected"] == pytest.approx(expected)
    mass = sum(b["probability"] for b in talents["resin"]["histogram"])
    assert mass == pytest.approx(1.0, abs=1e-3)
    assert "narrowest distribution" in body["histogram_note"]


@pytest.mark.asyncio
async def test_feeding_exp_material_charges_no_mora(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """Zero, and it is a fact rather than a gap.

    Owner, 2026-09-07: *"there is no more per exp point conversion"*. The total still charges
    mora, because ascension and talent levels do — this is the levelling half only.
    """
    character, talent, _ = await _catalogue(db_session)
    await db_session.commit()

    response = await client.post(
        "/api/v1/planner/plan", json=_request(character, talent), headers=_auth(authed_user),
    )
    body = response.json()
    levels = next(s for s in body["sections"] if s["key"] == "levels")
    assert levels["mora"] == 0
    # 20,000 for the ascension phase and 9,000 for the nine talent steps.
    assert body["total"]["mora"] == 29_000


@pytest.mark.asyncio
async def test_ascending_without_levelling_is_accepted(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """The owner's stay-at-80/90 case: phase moves, level does not, no EXP is charged."""
    character, talent, _ = await _catalogue(db_session)
    await db_session.commit()

    response = await client.post(
        "/api/v1/planner/plan",
        json=_request(
            character, talent,
            character_from={"level": 20, "ascension": 0},
            character_to={"level": 20, "ascension": 1},
        ),
        headers=_auth(authed_user),
    )
    assert response.status_code == 200, response.text
    levels = next(s for s in response.json()["sections"] if s["key"] == "levels")
    assert levels["exp"]["exp_required"] == 0


@pytest.mark.asyncio
async def test_a_level_above_its_phase_cap_is_refused(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    character, talent, _ = await _catalogue(db_session)
    await db_session.commit()

    response = await client.post(
        "/api/v1/planner/plan",
        json=_request(
            character, talent,
            character_from={"level": 1, "ascension": 0},
            character_to={"level": 50, "ascension": 0},
        ),
        headers=_auth(authed_user),
    )
    assert response.status_code == 422
    assert "ascension phase 0 unlocks" in response.json()["detail"]


@pytest.mark.asyncio
async def test_talent_levels_above_ten_are_free_and_flagged(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    character, talent, _ = await _catalogue(db_session)
    await db_session.commit()

    to_ten = await client.post(
        "/api/v1/planner/plan", json=_request(character, talent), headers=_auth(authed_user),
    )
    to_thirteen = await client.post(
        "/api/v1/planner/plan",
        json=_request(character, talent, talents=[
            {"talent_id": talent.id, "current": 1, "target": 13},
        ]),
        headers=_auth(authed_user),
    )
    ten = next(s for s in to_ten.json()["sections"] if s["key"] == "talents")
    thirteen = next(s for s in to_thirteen.json()["sections"] if s["key"] == "talents")
    assert ten["materials"] == thirteen["materials"]
    assert to_thirteen.json()["talent_free_levels"] is True
    assert to_ten.json()["talent_free_levels"] is False


@pytest.mark.asyncio
async def test_the_weapon_section_appears_only_when_a_weapon_is_asked_for(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    character, talent, weapon = await _catalogue(db_session)
    await db_session.commit()

    response = await client.post(
        "/api/v1/planner/plan",
        json=_request(
            character, talent,
            weapon_id=weapon.id,
            weapon_from={"level": 1, "ascension": 0},
            weapon_to={"level": 20, "ascension": 1},
        ),
        headers=_auth(authed_user),
    )
    body = response.json()
    assert [s["key"] for s in body["sections"]][-1] == "weapon"
    assert body["weapon_name"] == "Planner Sword"


@pytest.mark.asyncio
async def test_the_total_does_not_bill_one_domain_twice(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """Talents and the weapon both want Teachings; that is one domain, not two."""
    character, talent, weapon = await _catalogue(db_session)
    await db_session.commit()

    body = (
        await client.post(
            "/api/v1/planner/plan",
            json=_request(
                character, talent,
                weapon_id=weapon.id,
                weapon_from={"level": 1, "ascension": 0},
                weapon_to={"level": 20, "ascension": 1},
            ),
            headers=_auth(authed_user),
        )
    ).json()
    total_line = next(
        line for line in body["total"]["materials"] if line["material_id"] == TEACHINGS
    )
    assert total_line["required"] == 23  # 18 talent + 5 weapon
    # Priced as one run of 23, not as two runs of 18 and 5. The section resin totals also
    # carry mora and EXP, so the merge is asserted on this line rather than on the sum.
    assert total_line["resin"]["expected_resin"] == pytest.approx(
        23 / TALENT_DOMAIN_PER_RUN * DOMAIN_RESIN,
    )


@pytest.mark.asyncio
async def test_options_offer_only_levelable_talents(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """An alternate sprint has no cost ladder and must not be offered then priced at zero."""
    character, talent, _ = await _catalogue(db_session)
    sprint = Talent(
        character_id=character.id, nanoka_id=10013, talent_type=TalentType.NORMAL_ATTACK,
        name="Alternate Sprint", description="", icon="Skill_S_Test",
    )
    db_session.add(sprint)
    await db_session.commit()

    response = await client.get(
        f"/api/v1/planner/options?character_id={character.id}", headers=_auth(authed_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [t["talent_id"] for t in body["talents"]] == [talent.id]
    assert body["level_caps"] == {"0": 20, "1": 40, "2": 50, "3": 60, "4": 70, "5": 80, "6": 90}
    # All five curated numbers arrived on 2026-09-07, so nothing is left unpriced. This
    # should start failing the day a patch adds a resin source nobody has costed.
    assert body["uncurated_sources"] == []


@pytest.mark.asyncio
async def test_the_summary_does_not_merge_two_different_exp_pools(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """Character EXP books and weapon Enhancement Ore are different currencies.

    Driving the real page caught this: the summary added both requirements while crediting
    only the character's stock, and reported a shortfall of 9,047,100 EXP when each half was
    separately covered. Each section shows its own bill; the summary shows none.
    """
    character, talent, weapon = await _catalogue(db_session)
    await db_session.commit()

    body = (
        await client.post(
            "/api/v1/planner/plan",
            json=_request(
                character, talent,
                weapon_id=weapon.id,
                weapon_from={"level": 1, "ascension": 0},
                weapon_to={"level": 20, "ascension": 1},
            ),
            headers=_auth(authed_user),
        )
    ).json()
    sections = {section["key"]: section for section in body["sections"]}
    assert sections["levels"]["exp"]["exp_required"] == 19_000
    assert sections["weapon"]["exp"]["exp_required"] == 9_500
    assert body["total"]["exp"] is None


@pytest.mark.asyncio
async def test_a_material_you_already_hold_is_satisfied_not_unknown(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
) -> None:
    """Nothing to farm is not the same as a rate nobody publishes.

    Found by looking at the rendered page: a domain material with nothing outstanding fell
    through to `unknown` and drew a "?", which says the rate is not known -- false, and about
    the one row the user least needs to worry about.
    """
    user, _ = authed_user
    character, talent, _ = await _catalogue(db_session)
    db_session.add(UserMaterial(owner_id=user.id, material_id=TEACHINGS, count=999))
    await db_session.commit()

    body = (
        await client.post(
            "/api/v1/planner/plan", json=_request(character, talent), headers=_auth(authed_user),
        )
    ).json()
    line = next(
        line
        for section in body["sections"]
        if section["key"] == "talents"
        for line in section["materials"]
        if line["material_id"] == TEACHINGS
    )
    assert line["still_needed"] == 0
    assert line["resin_status"] == "satisfied"
