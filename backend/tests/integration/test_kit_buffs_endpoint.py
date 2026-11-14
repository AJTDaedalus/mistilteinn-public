"""Math-fallback P2, task 9 — `/formula/kit-buffs`: the two-pass team evaluation, end to end.

A team of three of the caller's builds: Hu Tao (no sheet; this was Xiangling until task 11 gave
her one), Bennett and Kazuha. The buffs must be computed from **each giver's own build**
(pass 1) — Bennett's burst from Bennett's base ATK, Kazuha's A4 from Kazuha's EM — and reach
the optimized character. Each giver figure is checked against an independent route:
`/builds/{id}/search-context`, which publishes the same build's base, so the kit's number and
the base it claims to come from cannot drift apart.

Rows are the seeded catalogue's, verbatim (nanoka 7.2.51): Bennett's burst at level 10, his
constellation lists, Kazuha's A4 list. The sheets pin those same lists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.formula.genshin import sheets
from app.models.artifact import Artifact, ArtifactSet
from app.models.build import Build
from app.models.character import (
    AscensionPassive,
    Character,
    Constellation,
    Talent,
    TalentScaling,
)
from app.models.enums import ArtifactSlot, Element, Rarity, StatType, TalentType, WeaponType
from app.models.weapon import Weapon

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User

pytestmark = pytest.mark.asyncio

KIT = "/api/v1/formula/kit-buffs"
CURVES = {
    "FIGHT_PROP_BASE_HP": "GROW_CURVE_HP_S4",
    "FIGHT_PROP_BASE_ATTACK": "GROW_CURVE_ATTACK_S4",
    "FIGHT_PROP_BASE_DEFENSE": "GROW_CURVE_HP_S4",
}
BENNETT_BURST_LABELS = [
    "Skill DMG|{param1:P}", "Continuous Regeneration Per Sec|{param2:F2P} Max HP+{param3:I}",
    "ATK Bonus Ratio|{param4:P}", "Duration|{param5:F1}s",
]
BENNETT_BURST_10 = [4.1904, 0.108, 1270.2417, 1.008, 12.0]
BENNETT_CONS = {1: [0.2], 2: [0.7, 0.3], 3: [], 4: [1.35], 5: [], 6: [0.15]}
KAZUHA_BURST_LABELS = ["Slashing DMG|{param1:P}", "DoT|{param2:P}",
                       "Additional Elemental DMG|{param3:P}"]
KAZUHA_BURST_10 = [4.7232, 2.16, 0.648]


def _pad(values: list[float], n: int) -> list[float]:
    return [*values, *([0.0] * (n - len(values)))]


async def _character(
    session: AsyncSession, *, nanoka_id: str, name: str, element: Element,
    weapon_type: WeaponType, base_atk: float, burst: tuple[list[str], list[float]] | None,
) -> Character:
    character = Character(
        nanoka_id=nanoka_id, name=name, element=element, weapon_type=weapon_type,
        rarity=Rarity.FOUR_STAR if name != "Kaedehara Kazuha" else Rarity.FIVE_STAR,
        base_hp=1000.0, base_atk=base_atk, base_def=60.0, base_crit_rate=0.05,
        base_crit_dmg=0.5, prop_curves=CURVES, ascension_stats=[{}] * 6,
    )
    session.add(character)
    await session.flush()
    if burst is not None:
        talent = Talent(character_id=str(character.id), nanoka_id=int(nanoka_id[-3:]) * 10,
                        talent_type=TalentType.ELEMENTAL_BURST, name="Burst", description="")
        session.add(talent)
        await session.flush()
        session.add(TalentScaling(talent_id=str(talent.id), level=10, labels=burst[0],
                                  params=burst[1]))
    return character


async def _build(session: AsyncSession, owner: str, character: Character, *,
                 weapon: Weapon | None = None, constellation: int = 0) -> Build:
    build = Build(
        owner_id=owner, character_id=str(character.id),
        weapon_id=str(weapon.id) if weapon else None, character_level=90,
        ascension_phase=6, weapon_level=90, constellation_level=constellation,
        talent_levels={"elemental_burst": 10},
    )
    session.add(build)
    await session.flush()
    return build


@pytest.fixture
async def team(db_session: AsyncSession, authed_user: tuple[User, str]) -> dict[str, str]:
    """Hu Tao (subject, no sheet), a C1 Bennett with a weapon, and Kazuha with 200 EM."""
    user, _ = authed_user
    owner = str(user.id)
    hu_tao = await _character(
        db_session, nanoka_id="10000046", name="Hu Tao", element=Element.PYRO,
        weapon_type=WeaponType.POLEARM, base_atk=18.9, burst=None,
    )
    bennett = await _character(
        db_session, nanoka_id="10000032", name="Bennett", element=Element.PYRO,
        weapon_type=WeaponType.SWORD, base_atk=16.0,
        burst=(BENNETT_BURST_LABELS, BENNETT_BURST_10),
    )
    kazuha = await _character(
        db_session, nanoka_id="10000047", name="Kaedehara Kazuha", element=Element.ANEMO,
        weapon_type=WeaponType.SWORD, base_atk=23.1,
        burst=(KAZUHA_BURST_LABELS, KAZUHA_BURST_10),
    )
    for position, params in BENNETT_CONS.items():
        db_session.add(Constellation(
            character_id=str(bennett.id), nanoka_id=300 + position, position=position,
            name=f"C{position}", description="", param_list=_pad(params, 10),
        ))
    db_session.add(AscensionPassive(
        character_id=str(kazuha.id), nanoka_id=471, unlock_ascension=4, name="Poetics",
        description="", param_list=_pad([0.0004, 8.0], 30),
    ))
    weapon = Weapon(
        nanoka_id=11402, name="The Flute", weapon_type=WeaponType.SWORD,
        rarity=Rarity.FOUR_STAR, base_atk=42.0, base_atk_curve="GROW_CURVE_ATTACK_201",
        sub_stat_type=StatType.ATK_PCT, sub_stat_base_value=0.09,
        sub_stat_curve="GROW_CURVE_CRITICAL_201",
        ascension_atk={str(p): {"fight_prop_base_attack": 25.9 * p} for p in range(1, 7)},
    )
    artifact_set = ArtifactSet(nanoka_id=15002, name="Viridescent Venerer",
                               piece_thresholds=[2, 4], available_ranks=[4, 5])
    db_session.add_all([weapon, artifact_set])
    await db_session.flush()

    builds = {
        "hu_tao": await _build(db_session, owner, hu_tao),
        "bennett": await _build(db_session, owner, bennett, weapon=weapon, constellation=1),
        "kazuha": await _build(db_session, owner, kazuha),
    }
    # Kazuha's EM is his flower's substat; Bennett's plume flat ATK must NOT reach his burst.
    db_session.add(Artifact(
        owner_id=owner, artifact_set_id=str(artifact_set.id), build_id=str(builds["kazuha"].id),
        slot=ArtifactSlot.FLOWER, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.HP_FLAT, main_stat_value=4780.0,
        substats=[{"stat": "FIGHT_PROP_ELEMENT_MASTERY", "value": 200.0}],
    ))
    db_session.add(Artifact(
        owner_id=owner, artifact_set_id=str(artifact_set.id), build_id=str(builds["bennett"].id),
        slot=ArtifactSlot.PLUME, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.ATK_FLAT, main_stat_value=311.0, substats=[],
    ))
    await db_session.flush()
    return {k: str(v.id) for k, v in builds.items()}


async def _base(client: AsyncClient, build_id: str, label: str) -> dict[str, float]:
    """The build's character-and-weapon base, from the route the kernel reads it from."""
    body = {
        "hit": {"channel": "pyro", "scope": "burst", "scaling_stat": "atk", "flat_damage": 0.0,
                "talent": {"talent": "elemental_burst", "label": label, "index": 0}},
        "enemy": {"level": 90, "resistances": {}, "default_resistance": 0.1},
    }
    response = await client.post(f"/api/v1/builds/{build_id}/search-context", json=body)
    assert response.status_code == 200, response.text
    return response.json()["base"]


async def _kit(client: AsyncClient, team: dict[str, str], subject: str) -> dict:
    response = await client.get(KIT, params={
        "subject_build_id": team[subject],
        "member_build_id": [team["hu_tao"], team["bennett"], team["kazuha"]],
    })
    assert response.status_code == 200, response.text
    return response.json()


async def test_teammates_buffs_come_from_their_own_builds(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],
):
    db_session.expire_all()
    kit = await _kit(authed_client, team, "hu_tao")
    by_id = {s["id"]: s for s in kit["sources"]}
    assert set(by_id) == {"kit:bennett", "kit:kaedehara_kazuha"}

    bennett_base = (await _base(authed_client, team["bennett"], "Skill DMG"))["base_atk"]
    bennett = by_id["kit:bennett"]
    assert bennett["giver_stats"] == {"base_atk": pytest.approx(bennett_base)}
    # Burst at 10 (C1 adds no level) and C1's 20%, each of his **base** ATK: his plume's 311
    # flat ATK is in his total and must not be in this.
    assert [e["value"] for e in bennett["bonus"]["effects"] if e["stat"] == "flat_atk"] == [
        pytest.approx(1.008 * bennett_base), pytest.approx(0.2 * bennett_base)]
    assert bennett["build_id"] == team["bennett"]
    assert bennett["verified"] is True
    [field] = bennett["bonus"]["conditions"]
    assert (field["key"], field["default"], field["default_reason"]) == (
        "in_field", 0, "situational")

    kazuha_base = await _base(authed_client, team["kazuha"], "Slashing DMG")
    kazuha_em = kazuha_base.get("elemental_mastery", 0.0) + 200
    kazuha = by_id["kit:kaedehara_kazuha"]
    assert kazuha["giver_stats"] == {"elemental_mastery": pytest.approx(kazuha_em)}
    assert {e["elements"][0]: e["value"] for e in kazuha["bonus"]["effects"]} == {
        e: pytest.approx(0.0004 * kazuha_em) for e in ("pyro", "hydro", "electro", "cryo")}


async def test_a_member_with_no_sheet_is_named_not_dropped(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],
):
    db_session.expire_all()
    kit = await _kit(authed_client, team, "hu_tao")
    members = {m["name"]: m for m in kit["members"]}
    assert members["Hu Tao"]["status"] == "no_sheet"
    assert members["Hu Tao"]["is_subject"] is True
    assert members["Bennett"]["status"] == "partial"


async def test_the_subject_receives_their_own_kit_as_themselves(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],
):
    """Kazuha optimized: his A4 moves with his own EM, so it is a coefficient, not a number;
    Bennett's field is still off by default, since Kazuha standing in it is situational."""
    db_session.expire_all()
    kit = await _kit(authed_client, team, "kazuha")
    by_id = {s["id"]: s for s in kit["sources"]}
    assert {(e["stat"], e["value"]) for e in by_id["kit:kaedehara_kazuha"]["bonus"]["effects"]} \
        == {("dmg_bonus_from_em", 0.0004)}
    assert by_id["kit:bennett"]["bonus"]["conditions"][0]["default"] == 0


async def test_the_subject_must_be_a_member_and_builds_must_be_the_callers(
    authed_client: AsyncClient, db_session: AsyncSession, team: dict[str, str],
):
    db_session.expire_all()
    outside = await authed_client.get(KIT, params={
        "subject_build_id": team["hu_tao"], "member_build_id": [team["bennett"]],
    })
    assert outside.status_code == 422
    missing = await authed_client.get(KIT, params={
        "subject_build_id": team["hu_tao"],
        "member_build_id": [team["hu_tao"], "00000000-0000-0000-0000-000000000000"],
    })
    assert missing.status_code == 404
    repeated = await authed_client.get(KIT, params={
        "subject_build_id": team["hu_tao"],
        "member_build_id": [team["hu_tao"], team["hu_tao"]],
    })
    assert repeated.status_code == 422


async def test_team_elements_reach_a_sheet_that_counts_them(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
    team: dict[str, str],
):
    """Task 11: Vesna's A4 counts the party's Anemo/Cryo members and the others (GO
    `team.common.count.<ele>`), so the route must hand `resolve` every member's element. With
    Kazuha and Vesna (Anemo) and Hu Tao and Bennett (Pyro): ATK 6% x 2 and EM 25 x 2."""
    user, _ = authed_user
    vesna = await _character(
        db_session, nanoka_id="10000143", name="Vesna", element=Element.ANEMO,
        weapon_type=WeaponType.SWORD, base_atk=27.6, burst=None,
    )
    sheet = next(s for s in sheets.all_sheets().values() if s.slug == "vesna")
    db_session.add(AscensionPassive(
        character_id=str(vesna.id), nanoka_id=1431, unlock_ascension=4, name="Truth Prevails",
        description="", param_list=list(sheet.pins.passives[4]),
    ))
    build_id = str((await _build(db_session, str(user.id), vesna)).id)
    await db_session.flush()
    db_session.expire_all()
    response = await authed_client.get(KIT, params={
        "subject_build_id": build_id,
        "member_build_id": [team["hu_tao"], team["bennett"], team["kazuha"], build_id],
    })
    assert response.status_code == 200, response.text
    by_id = {s["id"]: s for s in response.json()["sources"]}
    effects = {e["stat"]: e["value"] for e in by_id["kit:vesna"]["bonus"]["effects"]}
    assert effects == {"atk_pct": pytest.approx(sheet.pins.passives[4][0] * 2),
                       "elemental_mastery": pytest.approx(sheet.pins.passives[4][1] * 2)}


async def test_the_party_highest_em_is_read_from_the_teammates_pass_one(
    authed_client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
    team: dict[str, str],
):
    """Task 11, fourth batch: Nahida's A1 is 25% of the party's **highest** EM (GO
    `team.premod.eleMas.max`), capped. The highest is each teammate's pass-1 EM — Kazuha's 200
    from his flower beats Nahida's bare build — and never the subject's: Hu Tao's 2,000-EM
    sands must not enter it, since her EM moves with every candidate. As the subject, Nahida's
    own A1 is withheld by name."""
    user, _ = authed_user
    owner = str(user.id)
    nahida = await _character(
        db_session, nanoka_id="10000073", name="Nahida", element=Element.DENDRO,
        weapon_type=WeaponType.CATALYST, base_atk=23.3, burst=None,
    )
    sheet = next(s for s in sheets.all_sheets().values() if s.slug == "nahida")
    db_session.add(AscensionPassive(
        character_id=str(nahida.id), nanoka_id=731, unlock_ascension=1,
        name="Compassion Illuminated", description="", param_list=list(sheet.pins.passives[1]),
    ))
    nahida_id = str((await _build(db_session, owner, nahida)).id)
    artifact_set = ArtifactSet(nanoka_id=15099, name="A set", piece_thresholds=[2, 4],
                               available_ranks=[4, 5])
    db_session.add(artifact_set)
    await db_session.flush()
    db_session.add(Artifact(
        owner_id=owner, artifact_set_id=str(artifact_set.id), build_id=team["hu_tao"],
        slot=ArtifactSlot.SANDS, rarity=Rarity.FIVE_STAR, level=20,
        main_stat_type=StatType.ELEMENTAL_MASTERY, main_stat_value=2000.0, substats=[],
    ))
    await db_session.flush()
    db_session.expire_all()
    members = [team["hu_tao"], team["bennett"], team["kazuha"], nahida_id]

    response = await authed_client.get(KIT, params={
        "subject_build_id": team["hu_tao"], "member_build_id": members})
    assert response.status_code == 200, response.text
    nahida_kit = {s["id"]: s for s in response.json()["sources"]}["kit:nahida"]
    kazuha_em = (await _base(authed_client, team["kazuha"], "Slashing DMG")).get(
        "elemental_mastery", 0.0) + 200
    assert nahida_kit["giver_stats"] == {"team_max_elemental_mastery": pytest.approx(kazuha_em)}
    [a1] = [e for e in nahida_kit["bonus"]["effects"] if e["stat"] == "elemental_mastery"]
    assert a1["value"] == pytest.approx(min(0.25 * kazuha_em, 250.0))

    response = await authed_client.get(KIT, params={
        "subject_build_id": nahida_id, "member_build_id": members})
    assert response.status_code == 200, response.text
    own = {s["id"]: s for s in response.json()["sources"]}["kit:nahida"]
    assert not [e for e in own["bonus"]["effects"] if e["stat"] == "elemental_mastery"]
    assert any(u["reason"].startswith("withheld: it reads the team's highest")
               for u in own["bonus"]["unmodelled"])
