"""Math-fallback P3, task 12 — weapon passives through `/formula/kit-buffs`, end to end.

A team of four of the caller's builds: a Pyro practice mannequin (the subject) wielding Staff of
Homa R1, Bennett wielding Sword of Narzissenkreuz (no passive file: named, not dropped), Kazuha
wielding Thrilling Tales of Dragon Slayers R5, and a second mannequin wielding Thrilling Tales R1 —
the same weapon twice, so the second source gets its own id. Refinement lists are the seeded
catalogue's (nanoka 7.2.51), the ones each file pins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.formula.genshin import weapon_passives
from app.models.build import Build
from app.models.enums import Element, Rarity, StatType, WeaponType
from app.models.weapon import Weapon, WeaponRefinement
from tests.integration.test_kit_buffs_endpoint import (
    BENNETT_BURST_10,
    BENNETT_BURST_LABELS,
    KAZUHA_BURST_10,
    KAZUHA_BURST_LABELS,
    _character,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.character import Character
    from app.models.user import User

pytestmark = pytest.mark.asyncio

KIT = "/api/v1/formula/kit-buffs"


async def _weapon(session: AsyncSession, nanoka_id: int, name: str, kind: WeaponType, *,
                  params: dict[int, list[float]] | None = None) -> Weapon:
    weapon = Weapon(
        nanoka_id=nanoka_id, name=name, weapon_type=kind, rarity=Rarity.FIVE_STAR,
        base_atk=46.0, base_atk_curve="GROW_CURVE_ATTACK_301", sub_stat_type=StatType.ATK_PCT,
        sub_stat_base_value=0.1, sub_stat_curve="GROW_CURVE_CRITICAL_301",
        ascension_atk={str(p): {"fight_prop_base_attack": 31.1 * p} for p in range(1, 7)},
    )
    session.add(weapon)
    await session.flush()
    passive = weapon_passives.passive_for(nanoka_id)
    lists = params if params is not None else (
        {r: list(p) for r, p in passive.pins.items()} if passive else {})
    for level, param_list in lists.items():
        session.add(WeaponRefinement(weapon_id=str(weapon.id), level=level, name="",
                                     description="", param_list=param_list))
    await session.flush()
    return weapon


async def _build(session: AsyncSession, owner: str, character: Character, weapon: Weapon,
                 refinement: int) -> Build:
    build = Build(
        owner_id=owner, character_id=str(character.id), weapon_id=str(weapon.id),
        character_level=90, ascension_phase=6, weapon_level=90, refinement=refinement,
        constellation_level=0, talent_levels={"elemental_burst": 10},
    )
    session.add(build)
    await session.flush()
    return build


@pytest.fixture
async def team(db_session: AsyncSession, authed_user: tuple[User, str]) -> dict[str, str]:
    user, _ = authed_user
    owner = str(user.id)
    manekin = await _character(db_session, nanoka_id="10000117-2", name="Manekin",
                               element=Element.PYRO, weapon_type=WeaponType.POLEARM,
                               base_atk=18.9, burst=None)
    ally = await _character(db_session, nanoka_id="10000117-3", name="Ally",
                            element=Element.HYDRO, weapon_type=WeaponType.CATALYST,
                            base_atk=18.9, burst=None)
    bennett = await _character(db_session, nanoka_id="10000032", name="Bennett",
                               element=Element.PYRO, weapon_type=WeaponType.SWORD,
                               base_atk=16.0, burst=(BENNETT_BURST_LABELS, BENNETT_BURST_10))
    kazuha = await _character(db_session, nanoka_id="10000047", name="Kaedehara Kazuha",
                              element=Element.ANEMO, weapon_type=WeaponType.CATALYST,
                              base_atk=23.1, burst=(KAZUHA_BURST_LABELS, KAZUHA_BURST_10))
    homa = await _weapon(db_session, 13501, "Staff of Homa", WeaponType.POLEARM)
    # A sword with no passive file (The Flute, used here until 2026-11-15, has one now).
    flute = await _weapon(db_session, 11428, "Sword of Narzissenkreuz", WeaponType.SWORD,
                          params={1: [1.0, 0.5, 5.0, 1.0, 0.0, 0.0, 0.0, 0.0]})
    tales = await _weapon(db_session, 14302, "Thrilling Tales of Dragon Slayers",
                          WeaponType.CATALYST)
    builds = {
        "manekin": await _build(db_session, owner, manekin, homa, 1),
        "bennett": await _build(db_session, owner, bennett, flute, 1),
        "kazuha": await _build(db_session, owner, kazuha, tales, 5),
        "ally": await _build(db_session, owner, ally, tales, 1),
    }
    await db_session.flush()
    return {k: str(v.id) for k, v in builds.items()}


async def _kit(client: AsyncClient, team: dict[str, str], subject: str) -> dict:
    response = await client.get(KIT, params={
        "subject_build_id": team[subject],
        "member_build_id": [team["manekin"], team["bennett"], team["kazuha"], team["ally"]],
    })
    assert response.status_code == 200, response.text
    return response.json()


async def test_every_members_weapon_reaches_the_subject_as_its_rules_say(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],
):
    db_session.expire_all()
    kit = await _kit(authed_client, team, "manekin")
    weapons = {s["id"]: s for s in kit["sources"] if s["kind"] == "weapon"}
    assert set(weapons) == {"weapon:staff_of_homa", "weapon:thrilling_tales_of_dragon_slayers",
                            "weapon:thrilling_tales_of_dragon_slayers:2"}
    # The subject's own Homa: HP%, and ATK from their own Max HP per candidate.
    homa = weapons["weapon:staff_of_homa"]
    assert [(e["stat"], e["value"]) for e in homa["bonus"]["effects"]] == [
        ("hp_pct", 0.2), ("flat_atk_from_hp", 0.008), ("flat_atk_from_hp", 0.01)]
    assert homa["build_id"] == team["manekin"]
    assert homa["label"] == "Staff of Homa R1 (Manekin)"
    # A teammate's Thrilling Tales reaches the character switched in, at its refinement.
    r5 = weapons["weapon:thrilling_tales_of_dragon_slayers"]
    r1 = weapons["weapon:thrilling_tales_of_dragon_slayers:2"]
    assert [(e["stat"], e["value"]) for e in r5["bonus"]["effects"]] == [("atk_pct", 0.48)]
    assert [(e["stat"], e["value"]) for e in r1["bonus"]["effects"]] == [("atk_pct", 0.24)]
    assert r5["verified"] is True
    [heritage] = r5["bonus"]["conditions"]
    assert (heritage["default"], heritage["default_reason"]) == (1, "teammate")


async def test_a_weapon_with_no_file_is_named_not_dropped(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],
):
    db_session.expire_all()
    kit = await _kit(authed_client, team, "manekin")
    weapons = {w["wielder"]: w for w in kit["weapons"]}
    assert weapons["Bennett"]["status"] == "no_passive_data"
    assert weapons["Bennett"]["weapon"] == "Sword of Narzissenkreuz"
    assert weapons["Bennett"]["source_id"] is None
    assert weapons["Manekin"]["is_subject"] is True
    assert weapons["Manekin"]["source_id"] == "weapon:staff_of_homa"
    assert weapons["Kaedehara Kazuha"]["refinement"] == 5


async def test_a_teammates_homa_gives_the_subject_nothing(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],
):
    """Kazuha optimized: Homa is the mannequin's own, so it applies nothing to him."""
    db_session.expire_all()
    kit = await _kit(authed_client, team, "kazuha")
    by_id = {s["id"]: s for s in kit["sources"]}
    assert by_id["weapon:staff_of_homa"]["bonus"]["effects"] == []
    # And his own Thrilling Tales never reaches himself.
    assert by_id["weapon:thrilling_tales_of_dragon_slayers"]["bonus"]["effects"] == []
