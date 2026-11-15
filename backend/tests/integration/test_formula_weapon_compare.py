"""Weapon comparison under the formula estimate, end to end (owner approval 2026-11-14,
`docs/DECISIONS.md` §45).

A candidate weapon flows through both halves of the estimate: `/builds/{id}/search-context`
(the base — candidate base ATK and substat at the build's weapon level) and
`/formula/kit-buffs` (the candidate's passive in place of the equipped one's, and the subject's
pass 1 on the candidate). **#240 is the case this guards**: a gcsim weapon comparison shipped
flat — every weapon at the worn weapon's number — because the candidate id never reached the
scoring. So each test here asserts that two weapons differ where they must, not merely that a
request succeeds.

The team is `test_weapon_passives_endpoint.py`'s: a Pyro mannequin (the subject) wielding Staff
of Homa R1, with Bennett, Kazuha and a second mannequin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.build import Build
from app.models.enums import Rarity, StatType, WeaponType
from app.models.weapon import Weapon
from tests.integration.test_weapon_passives_endpoint import _weapon, team  # noqa: F401

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

KIT = "/api/v1/formula/kit-buffs"
BUILDS = "/api/v1/builds"


def _members(team: dict[str, str]) -> list[str]:  # noqa: F811 - the fixture's value
    return [team["manekin"], team["bennett"], team["kazuha"], team["ally"]]


async def _kit(client: AsyncClient, team: dict[str, str], **extra: object) -> dict:  # noqa: F811
    response = await client.get(KIT, params={
        "subject_build_id": team["manekin"], "member_build_id": _members(team), **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


async def _candidates(session: AsyncSession) -> dict[str, str]:
    """Engulfing Lightning (a passive file), Skyward Spine (a proc), a polearm with no file and
    a claymore the subject cannot wield."""
    engulfing = await _weapon(session, 13509, "Engulfing Lightning", WeaponType.POLEARM)
    spine = await _weapon(session, 13502, "Skyward Spine", WeaponType.POLEARM)
    plain = Weapon(
        nanoka_id=13999, name="Plain Pike", weapon_type=WeaponType.POLEARM,
        rarity=Rarity.FOUR_STAR, base_atk=42.0, base_atk_curve="GROW_CURVE_ATTACK_201",
        sub_stat_type=StatType.CRIT_RATE, sub_stat_base_value=0.06,
        sub_stat_curve="GROW_CURVE_CRITICAL_201",
        ascension_atk={str(p): {"fight_prop_base_attack": 25.9 * p} for p in range(1, 7)},
    )
    session.add(plain)
    claymore = await _weapon(session, 12999, "Some Claymore", WeaponType.CLAYMORE, params={})
    await session.flush()
    return {"engulfing": str(engulfing.id), "spine": str(spine.id), "plain": str(plain.id),
            "claymore": str(claymore.id)}


def _subject_weapon(kit: dict) -> dict:
    [mine] = [w for w in kit["weapons"] if w["is_subject"]]
    return mine


async def test_a_candidate_weapons_passive_replaces_the_equipped_one(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],  # noqa: F811
):
    ids = await _candidates(db_session)
    db_session.expire_all()
    worn = await _kit(authed_client, team)
    swapped = await _kit(authed_client, team, subject_weapon_id=ids["engulfing"])
    worn_ids = {s["id"] for s in worn["sources"] if s["kind"] == "weapon"}
    swapped_ids = {s["id"] for s in swapped["sources"] if s["kind"] == "weapon"}
    assert "weapon:staff_of_homa" in worn_ids
    assert "weapon:staff_of_homa" not in swapped_ids
    assert "weapon:engulfing_lightning" in swapped_ids
    # Teammates' weapons are untouched.
    assert worn_ids - {"weapon:staff_of_homa"} == swapped_ids - {"weapon:engulfing_lightning"}
    assert _subject_weapon(swapped)["weapon"] == "Engulfing Lightning"
    # The subject's ATK% from ER is a per-candidate conversion, at the build's refinement (R1).
    [engulfing] = [s for s in swapped["sources"] if s["id"] == "weapon:engulfing_lightning"]
    [conversion] = [e for e in engulfing["bonus"]["effects"] if e["stat"] == "atk_pct_from_er"]
    assert (conversion["value"], conversion["cap"]) == (0.28, 0.8)
    # The build itself was not changed by being looked at with another weapon.
    build = await db_session.get(Build, team["manekin"])
    assert build is not None
    assert build.refinement == 1


async def test_a_candidate_refinement_is_read(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],  # noqa: F811
):
    ids = await _candidates(db_session)
    db_session.expire_all()
    r5 = await _kit(authed_client, team, subject_weapon_id=ids["engulfing"],
                    subject_weapon_refinement=5)
    [engulfing] = [s for s in r5["sources"] if s["id"] == "weapon:engulfing_lightning"]
    [conversion] = [e for e in engulfing["bonus"]["effects"] if e["stat"] == "atk_pct_from_er"]
    assert (conversion["value"], conversion["cap"]) == (0.56, 1.2)
    assert _subject_weapon(r5)["refinement"] == 5


async def test_a_candidate_with_no_passive_file_competes_on_base_stats(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],  # noqa: F811
):
    ids = await _candidates(db_session)
    db_session.expire_all()
    kit = await _kit(authed_client, team, subject_weapon_id=ids["plain"])
    assert _subject_weapon(kit)["status"] == "no_passive_data"
    assert _subject_weapon(kit)["weapon"] == "Plain Pike"


async def test_a_candidate_proc_reaches_the_subject(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],  # noqa: F811
):
    ids = await _candidates(db_session)
    db_session.expire_all()
    kit = await _kit(authed_client, team, subject_weapon_id=ids["spine"])
    [spine] = [s for s in kit["sources"] if s["id"] == "weapon:skyward_spine"]
    assert [(p["key"], p["multiplier"], p["element"]) for p in spine["procs"]] == [
        ("vacuum", 0.4, "physical")]


async def test_a_weapon_the_subject_cannot_wield_or_that_does_not_exist_is_refused(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],  # noqa: F811
):
    ids = await _candidates(db_session)
    db_session.expire_all()
    base = {"subject_build_id": team["manekin"], "member_build_id": _members(team)}
    claymore = await authed_client.get(KIT, params={**base, "subject_weapon_id": ids["claymore"]})
    assert claymore.status_code == 422
    assert "cannot wield" in claymore.text
    missing = await authed_client.get(
        KIT, params={**base, "subject_weapon_id": "00000000-0000-7000-8000-000000000000"})
    assert missing.status_code == 404
    lone = await authed_client.get(KIT, params={**base, "subject_weapon_refinement": 3})
    assert lone.status_code == 422


def _context_body(**extra: object) -> dict:
    return {
        "hit": {"channel": "pyro", "scope": "burst", "multiplier": 1.0, "scaling_stat": "atk",
                "flat_damage": 0.0},
        "enemy": {"level": 90, "resistances": {}, "default_resistance": 0.1},
        "compare_to_equipped": False, **extra,
    }


async def test_search_context_takes_the_candidates_base(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],  # noqa: F811
):
    """Two weapons must not tie by construction: each candidate's base ATK and substat."""
    ids = await _candidates(db_session)
    db_session.expire_all()
    url = f"{BUILDS}/{team['manekin']}/search-context"
    worn = (await authed_client.post(url, json=_context_body())).json()["base"]
    plain = (await authed_client.post(url, json=_context_body(weapon_id=ids["plain"]))).json()
    engulfing = (await authed_client.post(
        url, json=_context_body(weapon_id=ids["engulfing"]))).json()
    assert plain["base"]["base_atk"] != worn["base_atk"]
    assert plain["base"]["base_atk"] != engulfing["base"]["base_atk"]
    # The substat follows the weapon: the plain pike's CRIT Rate, not Homa's ATK%.
    assert plain["base"].get("crit_rate", 0) > worn.get("crit_rate", 0)
    assert plain["base"].get("atk_pct", 0) < worn.get("atk_pct", 0)
    claymore = await authed_client.post(url, json=_context_body(weapon_id=ids["claymore"]))
    assert claymore.status_code == 422
