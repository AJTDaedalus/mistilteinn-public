"""Phase 4 combo-engine convergence — golden snapshot tests (Task 1).

Captures current (stateless-default) numeric responses for the 5 key
endpoints so Tasks 2-7 can verify parity after each migration step.

Four scenarios:
  solo_attacker   — physical DPS, standard attacks, no support.
  anomaly_attacker— fire anomaly DPS, anomaly steps in combo.
  lucy_support    — fire DPS + fire-support (fire_dmg_bonus team buff).
  caesar_support  — physical DPS + phys-support (atk_pct team buff).

Endpoints covered:
  /damage/build              → solo_attacker (single-hit, direct calc path)
  /combos/{id}/evaluate      → solo_attacker (3-hit) + anomaly_attacker
  /scorer/disc               → anomaly_attacker (DAG scorer path)
  rank pipeline (direct)     → anomaly_attacker
  /teams/{id}/calculate      → lucy_support + caesar_support

Run with UPDATE_GOLDENS=1 to regenerate stored JSON files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent, Attack
from app.models.build import Build, EnemyProfile
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.models.w_engine import WEngine
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.schemas.scorer import RankContextSchema, RankRequest
from app.services.rank_pipeline import resolve_rank_payload, run_rank_pipeline_with_progress

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Golden file helpers
# ---------------------------------------------------------------------------

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden_phase4"
UPDATE_GOLDENS = os.getenv("UPDATE_GOLDENS", "0") == "1"


def _check_or_write_golden(name: str, actual: dict) -> None:
    """Compare *actual* to the stored golden, or write it if UPDATE_GOLDENS=1."""
    path = GOLDEN_DIR / f"{name}.json"
    if UPDATE_GOLDENS or not path.exists():
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, indent=2, sort_keys=True))
        return
    expected = json.loads(path.read_text())
    assert actual == expected, (
        f"Golden mismatch for '{name}'. Re-run with UPDATE_GOLDENS=1 to refresh."
    )


def _damage_build_snapshot(r: dict) -> dict:
    return {
        "total": r["total"],
        "base_dmg": r["base_dmg"],
        "boost_mult": r["boost_mult"],
        "crit_mult": r["crit_mult"],
        "def_mult": r["def_mult"],
        "res_mult": r["res_mult"],
        "vulnerability_mult": r["vulnerability_mult"],
        "stun_mult": r["stun_mult"],
        "total_atk": r["total_atk"],
        "total_crit_rate": r["total_crit_rate"],
        "total_crit_dmg": r["total_crit_dmg"],
        "total_pen_ratio": r["total_pen_ratio"],
        "attack_multiplier": r["attack_multiplier"],
    }


def _combo_evaluate_snapshot(r: dict) -> dict:
    return {
        "total_damage": r["total_damage"],
        "standard_total": r["standard_total"],
        "anomaly_total": r["anomaly_total"],
        "by_category": sorted(r["by_category"], key=lambda x: x["category"]),
        "by_element": sorted(r["by_element"], key=lambda x: x["element"]),
        "steps": [{"label": s["label"], "total": s.get("total", 0)} for s in r["steps"]],
    }


def _score_disc_snapshot(r: dict) -> dict:
    sc = r["score"]
    return {
        "mean_improvement": sc["mean_improvement"],
        "max_improvement": sc["max_improvement"],
        "baseline_damage": sc["baseline_damage"],
        "rolls_used": sc["rolls_used"],
        "remaining_rolls": sc["remaining_rolls"],
    }


def _rank_pipeline_snapshot(results: list[dict]) -> dict:
    # Sort by slot + disc_set_id proxy (stable ordering without UUIDs).
    def _key(item: dict) -> tuple:
        pb = item.get("per_build", [{}])
        return (item.get("slot", 0), pb[0].get("build_avg", 0.0) if pb else 0.0)

    return {
        "count": len(results),
        "results": sorted(
            [
                {
                    "slot": r.get("slot"),
                    "best_build_avg": round(r["best_build_avg"], 6),
                    "best_build_max": round(r["best_build_max"], 6),
                }
                for r in results
            ],
            key=_key,
        ),
    }


def _teams_calculate_snapshot(r: dict) -> dict:
    return {
        "total_damage": r["total_damage"],
        "standard_total": r["standard_total"],
        "anomaly_total": r["anomaly_total"],
        "auto_conditions": sorted(r["auto_conditions"]),
        "applied_team_buffs": sorted(
            [{"stat": b["stat"], "value": b["value"]} for b in r["applied_team_buffs"]],
            key=lambda x: x["stat"],
        ),
        "by_category": sorted(r["by_category"], key=lambda x: x["category"]),
        "by_element": sorted(r["by_element"], key=lambda x: x["element"]),
    }


# ---------------------------------------------------------------------------
# Shared disc seeding helpers
# ---------------------------------------------------------------------------

_S_DISC_MAIN_BY_SLOT = {
    1: (StatType.HP, 7300),  # slot 1: flat HP (S-rank lv15)
    2: (StatType.ATK, 594),  # slot 2: flat ATK
    3: (StatType.DEF, 46),  # slot 3: flat DEF (kept minimal)
    4: (StatType.CRIT_RATE, 2400),  # slot 4: CRIT Rate 24%
    5: (StatType.CRIT_DMG, 4800),  # slot 5: CRIT DMG 48%
    6: (StatType.ATK_PCT, 3000),  # slot 6: ATK% 30%
}

_CRIT_SUBSTATS = [
    {"stat": "crit_rate", "value": 720, "rolls": 3},
    {"stat": "crit_dmg", "value": 1440, "rolls": 3},
    {"stat": "hp_pct", "value": 300, "rolls": 1},
    {"stat": "atk_pct", "value": 300, "rolls": 1},
]


def _make_disc(slot: int, disc_set: DiscSet, build: Build, owner_id: str) -> Disc:
    main_type, main_val = _S_DISC_MAIN_BY_SLOT[slot]
    return Disc(
        owner_id=owner_id,
        disc_set_id=str(disc_set.id),
        slot=DiscSlot(slot),
        rarity=Rarity.S,
        level=15,
        main_stat_type=main_type,
        main_stat_value=main_val,
        substats=_CRIT_SUBSTATS,
        build_id=str(build.id),
        build_slot=slot,
    )


def _make_unequipped_disc(slot: int, disc_set: DiscSet, owner_id: str) -> Disc:
    """An unequipped candidate disc for scoring / ranking."""
    main_type, _main_val = _S_DISC_MAIN_BY_SLOT[slot]
    return Disc(
        owner_id=owner_id,
        disc_set_id=str(disc_set.id),
        slot=DiscSlot(slot),
        rarity=Rarity.S,
        level=0,
        main_stat_type=main_type,
        main_stat_value=0,
        substats=[
            {"stat": "crit_dmg", "value": 480, "rolls": 1},
            {"stat": "hp_pct", "value": 300, "rolls": 1},
            {"stat": "atk_pct", "value": 300, "rolls": 1},
        ],
    )


# ---------------------------------------------------------------------------
# Scenario 1: solo_attacker
# ---------------------------------------------------------------------------


async def _seed_solo_attacker(
    authed_client: AsyncClient,
    db: AsyncSession,
    owner_id: str,
) -> dict:
    """Physical DPS, 3 standard-attack combo, no support.

    Used for /damage/build (single-hit) and /combos (multi-hit).
    """
    agent = Agent(
        hakushin_id=60001,
        name="SoloPhysAgent",
        element=Element.PHYSICAL,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=800,
        base_hp=8000,
        base_def=600,
    )
    engine = WEngine(
        hakushin_id=60002,
        name="SoloEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=594,
    )
    enemy = EnemyProfile(name="SoloDummy", level=60, defense=60, physical_res=0)
    disc_set = DiscSet(
        hakushin_id=60100,
        name="SoloSet",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +25%",
    )
    db.add_all([agent, engine, enemy, disc_set])
    await db.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=1,
        skill_key="Basic",
        name="Basic 1",
        hit_index=0,
        element=Element.PHYSICAL,
        damage_base=10_000,
        damage_growth=500,
    )
    db.add(attack)
    await db.flush()

    # Build via API so owner_id is set.
    resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "SoloBuild",
            "agent_id": str(agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    assert resp.status_code == 201
    build_id = resp.json()["id"]

    build = await db.get(Build, build_id)
    assert build is not None

    for slot in range(1, 7):
        d = _make_disc(slot, disc_set, build, owner_id)
        db.add(d)
    await db.flush()

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "SoloTeam", "build1_id": build_id},
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "SoloCombo",
            "team_id": team_id,
            "sequence": [
                {"attack_id": str(attack.id), "label": "BA1"},
                {"attack_id": str(attack.id), "label": "BA2"},
                {"attack_id": str(attack.id), "label": "BA3"},
            ],
        },
    )
    assert combo_resp.status_code == 201
    combo_id = combo_resp.json()["id"]

    return {
        "team_id": team_id,
        "build_id": build_id,
        "combo_id": combo_id,
        "attack_id": str(attack.id),
        "enemy_id": str(enemy.id),
    }


# ---------------------------------------------------------------------------
# Scenario 2: anomaly_attacker
# ---------------------------------------------------------------------------


async def _seed_anomaly_attacker(
    authed_client: AsyncClient,
    db: AsyncSession,
    owner_id: str,
) -> dict:
    """Fire anomaly DPS with anomaly steps.

    Used for /scorer/disc and rank pipeline.
    """
    agent = Agent(
        hakushin_id=60010,
        name="AnomalyFireAgent",
        element=Element.FIRE,
        specialty=Specialty.ANOMALY,
        rarity=Rarity.S,
        base_atk=700,
        base_hp=9000,
        base_def=550,
        base_anomaly_mastery=100,
    )
    engine = WEngine(
        hakushin_id=60011,
        name="AnomalyEngine",
        rarity=Rarity.S,
        specialty=Specialty.ANOMALY,
        base_atk=500,
    )
    enemy = EnemyProfile(name="AnomalyDummy", level=60, defense=60, fire_res=0)
    disc_set = DiscSet(
        hakushin_id=60110,
        name="AnomalySet",
        two_piece_text="Anomaly Prof +94",
        four_piece_text="Anomaly DMG +10%",
    )
    db.add_all([agent, engine, enemy, disc_set])
    await db.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=2,
        skill_key="Special",
        name="Flame Hit",
        hit_index=0,
        element=Element.FIRE,
        damage_base=8_000,
        damage_growth=400,
        anomaly_buildup=500,
    )
    db.add(attack)
    await db.flush()

    resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "AnomalyBuild",
            "agent_id": str(agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    assert resp.status_code == 201
    build_id = resp.json()["id"]

    build = await db.get(Build, build_id)
    assert build is not None

    for slot in range(1, 7):
        d = _make_disc(slot, disc_set, build, owner_id)
        db.add(d)
    await db.flush()

    # Unequipped candidate for scoring.
    cand = _make_unequipped_disc(4, disc_set, owner_id)
    db.add(cand)
    await db.flush()

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "AnomalyTeam", "build1_id": build_id},
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "AnomalyCombo",
            "team_id": team_id,
            "sequence": [
                {"attack_id": str(attack.id), "label": "Flame1"},
                {"attack_id": str(attack.id), "label": "Flame2"},
                {
                    "anomaly_type": "burn",
                    "label": "Burn",
                    "element": "fire",
                    "procs_override": 3,
                },
            ],
        },
    )
    assert combo_resp.status_code == 201
    combo_id = combo_resp.json()["id"]

    return {
        "team_id": team_id,
        "build_id": build_id,
        "combo_id": combo_id,
        "attack_id": str(attack.id),
        "enemy_id": str(enemy.id),
        "candidate_disc_id": str(cand.id),
    }


# ---------------------------------------------------------------------------
# Scenario 3: lucy_support (fire DPS + fire-team-buff support)
# ---------------------------------------------------------------------------


async def _seed_lucy_support(
    authed_client: AsyncClient,
    db: AsyncSession,
    owner_id: str,
) -> dict:
    """Fire DPS + Lucy-like support contributing fire_dmg_bonus team buff."""
    dps_agent = Agent(
        hakushin_id=60020,
        name="FireDPS",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=850,
        base_hp=8500,
        base_def=600,
    )
    supp_agent = Agent(
        hakushin_id=60021,
        name="LucyLike",
        element=Element.FIRE,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
        base_atk=500,
        base_hp=10_000,
        base_def=700,
    )
    engine = WEngine(
        hakushin_id=60022,
        name="FireEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=594,
    )
    supp_engine = WEngine(
        hakushin_id=60023,
        name="SuppEngine",
        rarity=Rarity.S,
        specialty=Specialty.SUPPORT,
        base_atk=400,
    )
    enemy = EnemyProfile(name="LucyDummy", level=60, defense=60, fire_res=0)
    disc_set = DiscSet(
        hakushin_id=60120,
        name="FireSet",
        two_piece_text="ATK +10%",
        four_piece_text="Fire DMG +25%",
    )
    filler_set = DiscSet(
        hakushin_id=60121,
        name="FillerSet",
        two_piece_text="DEF +16%",
        four_piece_text="ATK +10%",
    )
    filler_agent = Agent(
        hakushin_id=60025,
        name="FillerAgent",
        element=Element.FIRE,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.A,
        base_atk=400,
        base_hp=9000,
        base_def=600,
    )
    filler_engine = WEngine(
        hakushin_id=60026,
        name="FillerEngine",
        rarity=Rarity.A,
        specialty=Specialty.SUPPORT,
        base_atk=320,
    )
    db.add_all(
        [
            dps_agent,
            supp_agent,
            filler_agent,
            engine,
            supp_engine,
            filler_engine,
            enemy,
            disc_set,
            filler_set,
        ]
    )
    await db.flush()

    attack = Attack(
        agent_id=dps_agent.id,
        hakushin_skill_id=3,
        skill_key="Basic",
        name="Fire Basic",
        hit_index=0,
        element=Element.FIRE,
        damage_base=12_000,
        damage_growth=600,
    )
    db.add(attack)
    await db.flush()

    # Support build (no discs needed — buffs come from agent kit).
    supp_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "LucyBuild",
            "agent_id": str(supp_agent.id),
            "w_engine_id": str(supp_engine.id),
        },
    )
    assert supp_resp.status_code == 201
    supp_build_id = supp_resp.json()["id"]

    supp_build = await db.get(Build, supp_build_id)
    assert supp_build is not None
    for slot in range(1, 7):
        d = Disc(
            owner_id=owner_id,
            disc_set_id=str(filler_set.id),
            slot=DiscSlot(slot),
            rarity=Rarity.A,
            level=0,
            main_stat_type=_S_DISC_MAIN_BY_SLOT[slot][0],
            main_stat_value=0,
            substats=[],
            build_id=str(supp_build.id),
            build_slot=slot,
        )
        db.add(d)
    await db.flush()

    # DPS build.
    dps_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "FireDPSBuild",
            "agent_id": str(dps_agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    assert dps_resp.status_code == 201
    dps_build_id = dps_resp.json()["id"]

    dps_build = await db.get(Build, dps_build_id)
    assert dps_build is not None
    for slot in range(1, 7):
        d = _make_disc(slot, disc_set, dps_build, owner_id)
        db.add(d)
    await db.flush()

    # Filler third build (separate agent, just for Team.build3_id).
    filler_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "FillerBuild",
            "agent_id": str(filler_agent.id),
            "w_engine_id": str(filler_engine.id),
        },
    )
    assert filler_resp.status_code == 201
    filler_build_id = filler_resp.json()["id"]

    filler_build = await db.get(Build, filler_build_id)
    assert filler_build is not None
    for slot in range(1, 7):
        d = Disc(
            owner_id=owner_id,
            disc_set_id=str(filler_set.id),
            slot=DiscSlot(slot),
            rarity=Rarity.A,
            level=0,
            main_stat_type=_S_DISC_MAIN_BY_SLOT[slot][0],
            main_stat_value=0,
            substats=[],
            build_id=str(filler_build.id),
            build_slot=slot,
        )
        db.add(d)
    await db.flush()

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={
            "name": "LucyTeam",
            "build1_id": dps_build_id,
            "build2_id": supp_build_id,
            "build3_id": filler_build_id,
        },
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "FireDPSCombo",
            "team_id": team_id,
            "sequence": [
                {"attack_id": str(attack.id), "label": "F1"},
                {"attack_id": str(attack.id), "label": "F2"},
            ],
        },
    )
    assert combo_resp.status_code == 201
    combo_id = combo_resp.json()["id"]

    return {
        "team_id": team_id,
        "dps_build_id": dps_build_id,
        "combo_id": combo_id,
        "enemy_id": str(enemy.id),
    }


# ---------------------------------------------------------------------------
# Scenario 4: caesar_support (physical DPS + phys-support with atk_pct buff)
# ---------------------------------------------------------------------------


async def _seed_caesar_support(
    authed_client: AsyncClient,
    db: AsyncSession,
    owner_id: str,
) -> dict:
    """Physical DPS + Caesar-like support contributing atk_pct team buff."""
    dps_agent = Agent(
        hakushin_id=60030,
        name="PhysDPS",
        element=Element.PHYSICAL,
        specialty=Specialty.STUN,
        rarity=Rarity.S,
        base_atk=820,
        base_hp=9200,
        base_def=650,
    )
    supp_agent = Agent(
        hakushin_id=60031,
        name="CaesarLike",
        element=Element.PHYSICAL,
        specialty=Specialty.DEFENSE,
        rarity=Rarity.S,
        base_atk=450,
        base_hp=12_000,
        base_def=1200,
    )
    engine = WEngine(
        hakushin_id=60032,
        name="StunEngine",
        rarity=Rarity.S,
        specialty=Specialty.STUN,
        base_atk=540,
    )
    supp_engine = WEngine(
        hakushin_id=60033,
        name="DefEngine",
        rarity=Rarity.S,
        specialty=Specialty.DEFENSE,
        base_atk=400,
    )
    enemy = EnemyProfile(name="CaesarDummy", level=60, defense=60, physical_res=0)
    disc_set = DiscSet(
        hakushin_id=60130,
        name="PhysSet",
        two_piece_text="ATK +10%",
        four_piece_text="Physical DMG +25%",
    )
    filler_set = DiscSet(
        hakushin_id=60131,
        name="CaesarFiller",
        two_piece_text="DEF +16%",
        four_piece_text="ATK +10%",
    )
    filler_agent = Agent(
        hakushin_id=60035,
        name="CaesarFillerAgent",
        element=Element.PHYSICAL,
        specialty=Specialty.DEFENSE,
        rarity=Rarity.A,
        base_atk=400,
        base_hp=8000,
        base_def=550,
    )
    filler_engine = WEngine(
        hakushin_id=60036,
        name="CaesarFillerEngine",
        rarity=Rarity.A,
        specialty=Specialty.DEFENSE,
        base_atk=300,
    )
    db.add_all(
        [
            dps_agent,
            supp_agent,
            filler_agent,
            engine,
            supp_engine,
            filler_engine,
            enemy,
            disc_set,
            filler_set,
        ]
    )
    await db.flush()

    attack = Attack(
        agent_id=dps_agent.id,
        hakushin_skill_id=4,
        skill_key="Special",
        name="Stun Special",
        hit_index=0,
        element=Element.PHYSICAL,
        damage_base=15_000,
        damage_growth=800,
    )
    db.add(attack)
    await db.flush()

    supp_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "CaesarBuild",
            "agent_id": str(supp_agent.id),
            "w_engine_id": str(supp_engine.id),
        },
    )
    assert supp_resp.status_code == 201
    supp_build_id = supp_resp.json()["id"]

    supp_build = await db.get(Build, supp_build_id)
    assert supp_build is not None
    for slot in range(1, 7):
        d = Disc(
            owner_id=owner_id,
            disc_set_id=str(filler_set.id),
            slot=DiscSlot(slot),
            rarity=Rarity.A,
            level=0,
            main_stat_type=_S_DISC_MAIN_BY_SLOT[slot][0],
            main_stat_value=0,
            substats=[],
            build_id=str(supp_build.id),
            build_slot=slot,
        )
        db.add(d)
    await db.flush()

    dps_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "PhysDPSBuild",
            "agent_id": str(dps_agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    assert dps_resp.status_code == 201
    dps_build_id = dps_resp.json()["id"]

    dps_build = await db.get(Build, dps_build_id)
    assert dps_build is not None
    for slot in range(1, 7):
        d = _make_disc(slot, disc_set, dps_build, owner_id)
        db.add(d)
    await db.flush()

    filler_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "FillerBuild3",
            "agent_id": str(filler_agent.id),
            "w_engine_id": str(filler_engine.id),
        },
    )
    assert filler_resp.status_code == 201
    filler_build_id = filler_resp.json()["id"]

    filler_build = await db.get(Build, filler_build_id)
    assert filler_build is not None
    for slot in range(1, 7):
        d = Disc(
            owner_id=owner_id,
            disc_set_id=str(filler_set.id),
            slot=DiscSlot(slot),
            rarity=Rarity.A,
            level=0,
            main_stat_type=_S_DISC_MAIN_BY_SLOT[slot][0],
            main_stat_value=0,
            substats=[],
            build_id=str(filler_build.id),
            build_slot=slot,
        )
        db.add(d)
    await db.flush()

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={
            "name": "CaesarTeam",
            "build1_id": dps_build_id,
            "build2_id": supp_build_id,
            "build3_id": filler_build_id,
        },
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "PhysDPSCombo",
            "team_id": team_id,
            "sequence": [{"attack_id": str(attack.id), "label": "S1"}],
        },
    )
    assert combo_resp.status_code == 201
    combo_id = combo_resp.json()["id"]

    return {
        "team_id": team_id,
        "dps_build_id": dps_build_id,
        "combo_id": combo_id,
        "enemy_id": str(enemy.id),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_golden_damage_build_solo_attacker(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Golden: /damage/build single-hit for solo physical attacker."""
    user, _ = authed_user
    s = await _seed_solo_attacker(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        "/api/v1/damage/build",
        json={
            "build_id": s["build_id"],
            "attack_id": s["attack_id"],
            "enemy_profile_id": s["enemy_id"],
        },
    )
    assert resp.status_code == 200
    _check_or_write_golden("damage_build_solo_attacker", _damage_build_snapshot(resp.json()))


@pytest.mark.asyncio
async def test_golden_combos_evaluate_solo_attacker(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Evaluate endpoint removed (B0c); assert 404."""
    user, _ = authed_user
    s = await _seed_solo_attacker(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/combos/{s['combo_id']}/evaluate",
        json={"enemy_profile_id": s["enemy_id"]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_golden_combos_evaluate_anomaly_attacker(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Evaluate endpoint removed (B0c); assert 404."""
    user, _ = authed_user
    s = await _seed_anomaly_attacker(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/combos/{s['combo_id']}/evaluate",
        json={"enemy_profile_id": s["enemy_id"]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_golden_scorer_disc_anomaly_attacker(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Golden: /scorer/disc for anomaly attacker (DAG scorer path)."""
    user, _ = authed_user
    s = await _seed_anomaly_attacker(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        "/api/v1/scorer/disc",
        json={
            "combo_id": s["combo_id"],
            "disc_id": s["candidate_disc_id"],
            "enemy_profile_id": s["enemy_id"],
        },
    )
    assert resp.status_code == 200
    _check_or_write_golden(
        "scorer_disc_anomaly_attacker",
        _score_disc_snapshot(resp.json()),
    )


@pytest.mark.asyncio
async def test_golden_rank_pipeline_anomaly_attacker(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Golden: rank pipeline (direct) for anomaly attacker."""
    user, _ = authed_user
    s = await _seed_anomaly_attacker(authed_client, db_session, str(user.id))

    body = RankRequest(
        contexts=[
            RankContextSchema(
                build_id=s["build_id"],
                combo_id=s["combo_id"],
                enemy_profile_id=s["enemy_id"],
            ),
        ],
        scope="default",
    )
    payload = await resolve_rank_payload(
        db_session,
        body,
        build_repo=BuildRepository(db_session),
        combo_repo=ComboRepository(db_session),
        attack_repo=AttackRepository(db_session),
        enemy_repo=EnemyProfileRepository(db_session),
    )
    results = run_rank_pipeline_with_progress(payload, lambda p: None, max_workers=2)
    _check_or_write_golden(
        "rank_pipeline_anomaly_attacker",
        _rank_pipeline_snapshot(results),
    )


@pytest.mark.asyncio
async def test_golden_teams_calculate_lucy_support(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Golden: /teams/{id}/calculate fire DPS + Lucy-like support."""
    user, _ = authed_user
    s = await _seed_lucy_support(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
        },
    )
    assert resp.status_code == 200
    _check_or_write_golden(
        "teams_calculate_lucy_support",
        _teams_calculate_snapshot(resp.json()),
    )


@pytest.mark.asyncio
async def test_golden_teams_calculate_caesar_support(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: tuple,
) -> None:
    """Golden: /teams/{id}/calculate physical DPS + Caesar-like support."""
    user, _ = authed_user
    s = await _seed_caesar_support(authed_client, db_session, str(user.id))

    resp = await authed_client.post(
        f"/api/v1/teams/{s['team_id']}/calculate",
        json={
            "combo_id": s["combo_id"],
            "enemy_profile_id": s["enemy_id"],
        },
    )
    assert resp.status_code == 200
    _check_or_write_golden(
        "teams_calculate_caesar_support",
        _teams_calculate_snapshot(resp.json()),
    )
