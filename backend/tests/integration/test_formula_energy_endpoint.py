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
from app.models.enums import Element, Rarity, TalentType, WeaponType

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
