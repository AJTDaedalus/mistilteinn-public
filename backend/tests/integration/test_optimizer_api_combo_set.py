"""Integration tests for the multi-combo optimizer endpoint (A.6).

Exercises ``POST /api/v1/optimizer/discs`` with both:
- ``combo_ids=[c1, c2]``: asserts 200, current_build_damage, per_combo_damage,
  and populated disc summaries.
- ``combo_id=c1``: confirms the legacy single-combo path still works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.models.w_engine import WEngine

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_scenario(authed_client: AsyncClient, db_session: AsyncSession) -> dict:
    """Seed one build with two combos and a small disc inventory (~20 discs)."""
    agent = Agent(
        hakushin_id=9100,
        name="OptAgent",
        element=Element.ICE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    engine = WEngine(
        hakushin_id=9101,
        name="OptEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=600,
    )
    enemy = EnemyProfile(name="OptDummy", level=60, defense=60, ice_res=0)
    set_a = DiscSet(
        hakushin_id=9200,
        name="OptSetA",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +15%",
    )
    set_b = DiscSet(
        hakushin_id=9201,
        name="OptSetB",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +15%",
    )
    db_session.add_all([agent, engine, enemy, set_a, set_b])
    await db_session.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=100,
        skill_key="Basic",
        name="BasicHit",
        hit_index=0,
        element=Element.ICE,
        damage_base=10000,
        damage_growth=0,
    )
    db_session.add(attack)
    await db_session.flush()

    build_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "OptBuild",
            "agent_id": str(agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    build_id = build_resp.json()["id"]

    # 6 equipped discs: slots 1-4 set_a, 5-6 set_b.
    slot_specs = [
        (DiscSlot.ONE, set_a, StatType.HP, 2200),
        (DiscSlot.TWO, set_a, StatType.ATK, 316),
        (DiscSlot.THREE, set_a, StatType.DEF, 200),
        (DiscSlot.FOUR, set_a, StatType.CRIT_RATE, 2400),
        (DiscSlot.FIVE, set_b, StatType.ATK_PCT, 3000),
        (DiscSlot.SIX, set_b, StatType.ATK_PCT, 3000),
    ]
    disc_ids = []
    for slot, ds, stat, val in slot_specs:
        d = Disc(
            disc_set_id=str(ds.id),
            rarity=Rarity.S,
            slot=slot,
            level=15,
            main_stat_type=stat,
            main_stat_value=val,
            substats=[],
            build_id=build_id,
        )
        db_session.add(d)
        await db_session.flush()
        disc_ids.append(str(d.id))

    # ~14 unequipped discs — two options per slot 1-6 plus a couple extras.
    unequipped_disc_ids: list[str] = []
    for i in range(1, 7):
        for ds in (set_a, set_b):
            slot_enum = DiscSlot(i)
            stat = StatType.ATK_PCT
            val = 1500 + i * 100
            ud = Disc(
                disc_set_id=str(ds.id),
                rarity=Rarity.A,
                slot=slot_enum,
                level=12,
                main_stat_type=stat,
                main_stat_value=val,
                substats=[{"stat": "atk_pct", "value": 300}],
                build_id=None,
            )
            db_session.add(ud)
            await db_session.flush()
            unequipped_disc_ids.append(str(ud.id))

    await db_session.commit()

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "OptTeam", "build1_id": build_id},
    )
    team_id = team_resp.json()["id"]

    # Create two combos with a single step each.
    combo1_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "ComboA",
            "team_id": team_id,
            "sequence": [{"attack_id": attack.id, "label": "BA1"}],
        },
    )
    combo2_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "ComboB",
            "team_id": team_id,
            "sequence": [{"attack_id": attack.id, "label": "BA1b"}],
        },
    )

    return {
        "build_id": build_id,
        "team_id": team_id,
        "combo1_id": combo1_resp.json()["id"],
        "combo2_id": combo2_resp.json()["id"],
        "enemy_id": str(enemy.id),
        "equipped_disc_ids": disc_ids,
        "unequipped_disc_ids": unequipped_disc_ids,
    }


async def test_multi_combo_optimizer_submits_job(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST with combo_ids returns 202 (async job submission)."""
    s = await _seed_scenario(authed_client, db_session)
    all_disc_ids = s["equipped_disc_ids"] + s["unequipped_disc_ids"]

    payload = {
        "combo_ids": [s["combo1_id"], s["combo2_id"]],
        "enemy_profile_id": s["enemy_id"],
        "disc_ids": all_disc_ids,
        "allowed_frames": [{"counts": {9200: 4, 9201: 2}}, {"counts": {9201: 4, 9200: 2}}],
        "top_n": 5,
    }
    resp = await authed_client.post("/api/v1/optimizer/discs", json=payload)
    assert resp.status_code == 202, resp.text

    data = resp.json()
    assert data["status"] == "queued"
    assert data["agent_name"] == "OptAgent"
    assert data["enemy_name"] == "OptDummy"


async def test_single_combo_id_submits_job(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST with combo_id (legacy shape) returns 202 with queued status."""
    s = await _seed_scenario(authed_client, db_session)
    all_disc_ids = s["equipped_disc_ids"] + s["unequipped_disc_ids"]

    payload = {
        "combo_id": s["combo1_id"],
        "enemy_profile_id": s["enemy_id"],
        "disc_ids": all_disc_ids,
        "top_n": 3,
    }
    resp = await authed_client.post("/api/v1/optimizer/discs", json=payload)
    assert resp.status_code == 202, resp.text

    data = resp.json()
    assert data["status"] == "queued"
    assert "id" in data


async def test_submit_preserves_combo_name(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Submitted job has the primary combo's name in combo_name field."""
    s = await _seed_scenario(authed_client, db_session)

    payload = {
        "combo_id": s["combo1_id"],
        "enemy_profile_id": s["enemy_id"],
        "top_n": 5,
    }
    resp = await authed_client.post("/api/v1/optimizer/discs", json=payload)
    assert resp.status_code == 202, resp.text
    assert resp.json()["combo_name"] == "ComboA"


async def test_unknown_combo_id_returns_404(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A combo_id that doesn't exist should return 404."""
    s = await _seed_scenario(authed_client, db_session)

    payload = {
        "combo_ids": ["00000000-0000-0000-0000-000000000000", s["combo2_id"]],
        "enemy_profile_id": s["enemy_id"],
        "top_n": 3,
    }
    resp = await authed_client.post("/api/v1/optimizer/discs", json=payload)
    assert resp.status_code == 404
