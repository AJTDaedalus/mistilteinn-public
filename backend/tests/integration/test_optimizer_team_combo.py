"""Integration tests for B10: team-owned combo step filter in optimizer.

Covers:
- Mixed-team combo with UUID agent_ids: optimizer filters to target steps → 202
- Combo with only support steps for target build → 422
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_team_combo_scenario(
    authed_client: AsyncClient,
    db: AsyncSession,
) -> dict:
    """Seed a 2-agent team with attacks for both members and a small disc pool."""
    dps_agent = Agent(
        hakushin_id=8100,
        name="B10DPS",
        element=Element.ICE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    sup_agent = Agent(
        hakushin_id=8101,
        name="B10Sup",
        element=Element.FIRE,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
        base_atk=500,
        base_hp=10_000,
        base_def=700,
    )
    enemy = EnemyProfile(name="B10Dummy", level=60, defense=60, ice_res=0)
    disc_set = DiscSet(
        hakushin_id=8200,
        name="B10Set",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +15%",
    )
    db.add_all([dps_agent, sup_agent, enemy, disc_set])
    await db.flush()

    dps_attack = Attack(
        agent_id=dps_agent.id,
        hakushin_skill_id=810,
        skill_key="Basic",
        name="B10 Basic",
        hit_index=0,
        element=Element.ICE,
        damage_base=10_000,
        damage_growth=0,
    )
    sup_attack = Attack(
        agent_id=sup_agent.id,
        hakushin_skill_id=811,
        skill_key="Basic",
        name="B10 Sup Basic",
        hit_index=0,
        element=Element.FIRE,
        damage_base=5_000,
        damage_growth=0,
    )
    db.add_all([dps_attack, sup_attack])
    await db.flush()

    dps_resp = await authed_client.post(
        "/api/v1/builds",
        json={"name": "B10DPSBuild", "agent_id": str(dps_agent.id)},
    )
    assert dps_resp.status_code == 201
    dps_build_id = dps_resp.json()["id"]

    sup_resp = await authed_client.post(
        "/api/v1/builds",
        json={"name": "B10SupBuild", "agent_id": str(sup_agent.id)},
    )
    assert sup_resp.status_code == 201
    sup_build_id = sup_resp.json()["id"]

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "B10Team", "build1_id": dps_build_id, "build2_id": sup_build_id},
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    # 6 equipped discs for DPS build (minimal, all same set).
    slot_specs = [
        (DiscSlot.ONE, StatType.HP, 2200),
        (DiscSlot.TWO, StatType.ATK, 316),
        (DiscSlot.THREE, StatType.DEF, 200),
        (DiscSlot.FOUR, StatType.CRIT_RATE, 2400),
        (DiscSlot.FIVE, StatType.ATK_PCT, 3000),
        (DiscSlot.SIX, StatType.ATK_PCT, 3000),
    ]
    disc_ids = []
    for slot, stat, val in slot_specs:
        d = Disc(
            disc_set_id=str(disc_set.id),
            rarity=Rarity.S,
            slot=slot,
            level=15,
            main_stat_type=stat,
            main_stat_value=val,
            substats=[],
            build_id=dps_build_id,
        )
        db.add(d)
        await db.flush()
        disc_ids.append(str(d.id))

    await db.commit()

    return {
        "team_id": team_id,
        "dps_build_id": dps_build_id,
        "sup_build_id": sup_build_id,
        "dps_attack_id": str(dps_attack.id),
        "sup_attack_id": str(sup_attack.id),
        "enemy_id": str(enemy.id),
        "disc_ids": disc_ids,
    }


@pytest.mark.asyncio
async def test_optimizer_filters_to_dps_steps_by_uuid(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Combo with mixed UUID agent_ids: optimizer filters to DPS steps → 202."""
    s = await _seed_team_combo_scenario(authed_client, db_session)

    # Combo has one DPS step and one support step, both tagged with build UUIDs.
    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "MixedCombo",
            "team_id": s["team_id"],
            "sequence": [
                {
                    "attack_id": s["dps_attack_id"],
                    "label": "DPS BA",
                    "agent_id": s["dps_build_id"],
                },
                {
                    "attack_id": s["sup_attack_id"],
                    "label": "Sup BA",
                    "agent_id": s["sup_build_id"],
                },
            ],
        },
    )
    assert combo_resp.status_code == 201
    combo_id = combo_resp.json()["id"]

    payload = {
        "combo_id": combo_id,
        "enemy_profile_id": s["enemy_id"],
        "disc_ids": s["disc_ids"],
        "top_n": 3,
        "active_index": 0,
    }
    resp = await authed_client.post("/api/v1/optimizer/discs", json=payload)
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_optimizer_422_when_no_target_steps(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Combo with only support steps for the target build → 422."""
    s = await _seed_team_combo_scenario(authed_client, db_session)

    # Combo has only a support step (no DPS step).
    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "SupportOnlyCombo",
            "team_id": s["team_id"],
            "sequence": [
                {
                    "attack_id": s["sup_attack_id"],
                    "label": "Sup BA",
                    "agent_id": s["sup_build_id"],
                },
            ],
        },
    )
    assert combo_resp.status_code == 201
    combo_id = combo_resp.json()["id"]

    payload = {
        "combo_id": combo_id,
        "enemy_profile_id": s["enemy_id"],
        "disc_ids": s["disc_ids"],
        "top_n": 3,
        "active_index": 0,
    }
    resp = await authed_client.post("/api/v1/optimizer/discs", json=payload)
    assert resp.status_code == 422, resp.text
    assert "No steps for the target agent" in resp.text
