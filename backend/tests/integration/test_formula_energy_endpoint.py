"""Math-fallback P3, task 14 — `/formula/energy`: burst costs, cooldowns and skill particles.

Three of the caller's builds: Xiangling (subject; burst cost 80 and the burst's own `CD` row,
the seeded catalogue's labels verbatim), Bennett (a curated tap count) and a Pyro mannequin
(no particle data, named rather than dropped).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.build import Build
from app.models.character import Character, Talent, TalentScaling
from app.models.enums import Element, Rarity, StatType, TalentType, WeaponType
from app.models.weapon import Weapon, WeaponRefinement

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio

ENERGY = "/api/v1/formula/energy"
CURVES = {
    "FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_S4",
    "FIGHT_PROP_BASE_ATTACK": "GROW_CURVE_ATTACK_S4",
    "FIGHT_PROP_BASE_DEFENSE": "GROW_CURVE_HP_S4",
}
#: Xiangling's burst at level 1 in the seeded catalogue (nanoka 7.2.51), verbatim.
XIANGLING_BURST = (
    ["1-Hit Swing DMG|{param1:P}", "2-Hit Swing DMG|{param2:P}", "3-Hit Swing DMG|{param3:P}",
     "Pyronado DMG|{param4:P}", "Duration|{param5:F1}s", "CD|{param6:F1}s",
     "Energy Cost|{param7:I}"],
    [0.72, 0.88, 1.096, 1.12, 10.0, 20.0, 80.0],
)


async def _character(
    session: AsyncSession, *, nanoka_id: str, name: str, cost: int | None,
    burst: tuple[list[str], list[float]] | None = None,
) -> Character:
    character = Character(
        nanoka_id=nanoka_id, name=name, element=Element.PYRO, weapon_type=WeaponType.POLEARM,
        rarity=Rarity.FOUR_STAR, base_hp=1000.0, base_atk=20.0, base_def=60.0,
        base_crit_rate=0.05, base_crit_dmg=0.5, prop_curves=CURVES, ascension_stats=[{}] * 6,
        burst_energy_cost=cost,
    )
    session.add(character)
    await session.flush()
    if burst is not None:
        talent = Talent(character_id=str(character.id), nanoka_id=int(nanoka_id[-3:]) * 10,
                        talent_type=TalentType.ELEMENTAL_BURST, name="Pyronado", description="")
        session.add(talent)
        await session.flush()
        session.add(TalentScaling(talent_id=str(talent.id), level=1, labels=burst[0],
                                  params=burst[1]))
    return character


@pytest.fixture
async def team(db_session: AsyncSession, authed_user: tuple[User, str]) -> dict[str, str]:
    user, _ = authed_user
    out = {}
    for key, character in {
        "xiangling": await _character(db_session, nanoka_id="10000023", name="Xiangling",
                                      cost=80, burst=XIANGLING_BURST),
        "bennett": await _character(db_session, nanoka_id="10000032", name="Bennett", cost=60),
        "manekin": await _character(db_session, nanoka_id="10000117-2", name="Manekin",
                                    cost=None),
    }.items():
        build = Build(owner_id=str(user.id), character_id=str(character.id), character_level=90,
                      ascension_phase=6, constellation_level=0)
        db_session.add(build)
        await db_session.flush()
        out[key] = str(build.id)
    return out


async def test_each_member_carries_cost_cooldown_and_cited_particles(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],
):
    db_session.expire_all()
    response = await authed_client.get(ENERGY, params={
        "subject_build_id": team["xiangling"],
        "member_build_id": [team["xiangling"], team["bennett"], team["manekin"]],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    by_name = {m["name"]: m for m in body["members"]}

    xiangling = by_name["Xiangling"]
    assert (xiangling["is_subject"], xiangling["burst_energy_cost"], xiangling["burst_cooldown"],
            xiangling["element"], xiangling["status"]) == (True, 80, 20.0, "pyro", "curated")
    [guoba] = xiangling["sources"]
    assert (guoba["per"], guoba["particles"], guoba["collector"]) == ("cast", 4, "active")
    assert "internal/characters/xiangling/skill.go:49,78,79" in guoba["citation"]

    [tap] = by_name["Bennett"]["sources"]
    assert tap["particles"] == pytest.approx(2.25)
    assert by_name["Bennett"]["is_subject"] is False
    assert by_name["Bennett"]["burst_cooldown"] is None

    manekin = by_name["Manekin"]
    assert (manekin["status"], manekin["sources"], manekin["burst_energy_cost"]) == (
        "no_particle_data", [], None)

    assert body["drip"]["interval_seconds"] == pytest.approx(599.5 / 60)
    assert body["drip"]["config"] == "energy every interval=480,720 amount=1;"


async def test_a_subject_outside_the_team_is_refused(
    authed_client: AsyncClient, team: dict[str, str],
):
    response = await authed_client.get(ENERGY, params={
        "subject_build_id": team["xiangling"], "member_build_id": [team["bennett"]],
    })
    assert response.status_code == 422


async def test_a_repeated_member_is_refused(authed_client: AsyncClient, team: dict[str, str]):
    response = await authed_client.get(ENERGY, params={
        "subject_build_id": team["bennett"],
        "member_build_id": [team["bennett"], team["bennett"]],
    })
    assert response.status_code == 422


async def test_someone_elses_build_is_not_found(
    authed_client: AsyncClient, team: dict[str, str],
):
    response = await authed_client.get(ENERGY, params={
        "subject_build_id": team["bennett"],
        "member_build_id": [team["bennett"], "00000000-0000-0000-0000-000000000009"],
    })
    assert response.status_code == 404


# ── Follow-ups (owner rulings 2026-11-15, DECISIONS §48) ─────────────────────────────────────

#: Raiden's burst labels in the seeded catalogue (nanoka 7.2.51), verbatim; the params carry the
#: level-9 row's restoration (param 17, 2.4), CD (param 19) and cost (param 20).
RAIDEN_BURST_LABELS = [
    "Musou no Hitotachi Base DMG|{param1:P}",
    "Resolve Bonus|{param2:F2P} Initial/{param3:F2P} ATK DMG Per Stack",
    "Resolve Stacks Gained|{param4:F2} Per Energy Consumed", "1-Hit DMG|{param5:F1P}",
    "2-Hit DMG|{param6:F1P}", "3-Hit DMG|{param7:F1P}", "4-Hit DMG|{param8:F1P}+{param9:F1P}",
    "5-Hit DMG|{param10:F1P}", "Charged Attack DMG|{param11:F1P}+{param12:F1P}",
    "Charged Attack Stamina Cost|{param13:F1}", "Plunge DMG|{param14:F1P}",
    "Low/High Plunge DMG|{param15:P}/{param16:P}",
    "Musou Isshin Energy Restoration|{param17:F1}", "Musou Isshin Duration|{param18:F1}s",
    "CD|{param19:F1}s", "Energy Cost|{param20:I}", "", "", "", "",
]
RAIDEN_BURST_9 = [7.21, 0.07, 0.013, 0.2, *([0.8] * 12), 2.4, 7.0, 18.0, 90.0]


@pytest.fixture
async def electro(db_session: AsyncSession, authed_user: tuple[User, str]) -> dict[str, str]:
    """Raiden (a Favonius Lance R3), Sara below ascension 4, and Yae."""
    user, _ = authed_user
    lance = Weapon(
        nanoka_id=13407, name="Favonius Lance", weapon_type=WeaponType.POLEARM,
        rarity=Rarity.FOUR_STAR, base_atk=44.0, base_atk_curve="GROW_CURVE_ATTACK_201",
        sub_stat_type=StatType.ENERGY_RECHARGE, sub_stat_base_value=0.067,
        sub_stat_curve="GROW_CURVE_CRITICAL_201",
        ascension_atk={str(p): {"fight_prop_base_attack": 25.9 * p} for p in range(1, 7)},
    )
    db_session.add(lance)
    await db_session.flush()
    # The seeded catalogue's Favonius rows, verbatim (every Favonius weapon carries these).
    for level, params in {1: [0.6, 12], 2: [0.7, 10.5], 3: [0.8, 9], 4: [0.9, 7.5],
                          5: [1, 6]}.items():
        db_session.add(WeaponRefinement(weapon_id=str(lance.id), level=level, name="",
                                        description="", param_list=[*params, 0, 0, 0, 0, 0, 0]))
    # `_character` publishes its burst row at level 1, so the build's level is 1 here.
    raiden = await _character(db_session, nanoka_id="10000052", name="Raiden Shogun", cost=90,
                              burst=(RAIDEN_BURST_LABELS, RAIDEN_BURST_9))
    sara = await _character(db_session, nanoka_id="10000056", name="Kujou Sara", cost=80)
    yae = await _character(db_session, nanoka_id="10000058", name="Yae Miko", cost=90)
    await db_session.flush()
    out = {}
    for key, character, weapon, phase in (("raiden", raiden, lance, 6), ("sara", sara, None, 3),
                                          ("yae", yae, None, 6)):
        build = Build(owner_id=str(user.id), character_id=str(character.id),
                      weapon_id=str(weapon.id) if weapon else None, weapon_level=90,
                      refinement=3, character_level=90, ascension_phase=phase,
                      constellation_level=0, talent_levels={"elemental_burst": 1})
        db_session.add(build)
        await db_session.flush()
        out[key] = str(build.id)
    return out


async def test_summons_refunds_a_favonius_holder_and_a_member_left_to_the_user(
    authed_client: AsyncClient, db_session: AsyncSession, electro: dict[str, str],
):
    db_session.expire_all()
    response = await authed_client.get(ENERGY, params={
        "subject_build_id": electro["raiden"],
        "member_build_id": [electro["raiden"], electro["sara"], electro["yae"]],
    })
    assert response.status_code == 200, response.text
    by_name = {m["name"]: m for m in response.json()["members"]}

    raiden = by_name["Raiden Shogun"]
    [eye] = raiden["sources"]
    assert (eye["per"], eye["chance"], eye["interval"], eye["max_seconds"], eye["on"]) == (
        "second", 0.5, 1, 25, "skill")
    assert "KQM keqingmains.com/raiden/" in eye["citation"]
    [refund] = raiden["refunds"]
    assert (refund["amount"], refund["count"], refund["recipients"], refund["scaling"],
            refund["unavailable"]) == (2.4, 5, "team", "raiden_a4", None)
    assert "internal/characters/raiden/burst.go:96,98,99,101" in refund["citation"]
    fav = raiden["favonius"]
    assert (fav["weapon"], fav["refinement"], fav["chance"], fav["cooldown_seconds"],
            fav["particles"]) == ("Favonius Lance", 3, 0.8, 9.0, 3)
    assert "internal/weapons/common/favonius.go" in fav["citation"]
    assert raiden["energy_recharge"] > 1.0
    assert raiden["crit_rate"] == pytest.approx(0.05)

    sara = by_name["Kujou Sara"]
    [a4] = sara["refunds"]
    assert a4["unavailable"] == "needs ascension 4; the build is at 3"
    assert sara["favonius"] is None

    yae = by_name["Yae Miko"]
    assert yae["status"] == "no_particle_data"
    assert yae["note"].startswith("Two cited sources disagree")
