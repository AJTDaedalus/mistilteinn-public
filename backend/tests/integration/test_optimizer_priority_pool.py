"""Integration tests for T5: priority-aware disc pool in optimizer_pipeline.

Tests resolve_optimize_payload directly to verify the inventory query behavior
without needing to run the full optimizer search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.models.w_engine import WEngine
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.repositories.team import TeamRepository
from app.schemas.optimizer import DiscOptimizeRequest
from app.services.optimizer_pipeline import resolve_optimize_payload

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_base(db: AsyncSession) -> dict:
    """Seed shared agents, engine, enemy, disc set, and attack."""
    agent = Agent(
        hakushin_id=8800,
        name="PrioPoolAgent",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    agent2 = Agent(
        hakushin_id=8810,
        name="PrioPoolAgent2",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    agent3 = Agent(
        hakushin_id=8820,
        name="PrioPoolAgent3",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    engine = WEngine(
        hakushin_id=8801,
        name="PrioPoolEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=600,
    )
    enemy = EnemyProfile(name="PrioPoolDummy", level=60, defense=60, fire_res=0)
    disc_set = DiscSet(
        hakushin_id=8900,
        name="PrioPoolSet",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +15%",
    )
    db.add_all([agent, agent2, agent3, engine, enemy, disc_set])
    await db.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=200,
        skill_key="Basic",
        name="PrioHit",
        hit_index=0,
        element=Element.FIRE,
        damage_base=10000,
        damage_growth=0,
    )
    db.add(attack)
    await db.flush()

    return {
        "agent_id": str(agent.id),
        "agent2_id": str(agent2.id),
        "agent3_id": str(agent3.id),
        "engine_id": str(engine.id),
        "enemy_id": str(enemy.id),
        "disc_set_id": str(disc_set.id),
        "disc_set_hakushin_id": disc_set.hakushin_id,
        "attack_id": str(attack.id),
    }


async def _make_build(authed_client, agent_id: str, engine_id: str, name: str) -> str:
    resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": name,
            "agent_id": agent_id,
            "w_engine_id": engine_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_team(authed_client, build_id: str, name: str) -> str:
    resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": name, "build1_id": build_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_combo(authed_client, team_id: str, attack_id: str, name: str) -> str:
    resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": name,
            "team_id": team_id,
            "sequence": [{"attack_id": attack_id, "label": "hit"}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _make_disc(disc_set_id: str, slot: DiscSlot, build_id: str | None) -> Disc:
    return Disc(
        disc_set_id=disc_set_id,
        rarity=Rarity.S,
        slot=slot,
        level=15,
        main_stat_type=StatType.ATK_PCT,
        main_stat_value=3000,
        substats=[],
        build_id=build_id,
    )


async def _resolve_pool(
    session: AsyncSession,
    build_id: str,
    combo_id: str,
    enemy_id: str,
    inventory_scope: str,
    locked_slots: dict | None = None,
) -> set[str]:
    """Call resolve_optimize_payload and return the disc IDs in the inventory."""
    body = DiscOptimizeRequest(
        combo_id=combo_id,
        enemy_profile_id=enemy_id,
        inventory_scope=inventory_scope,
        locked_slots=locked_slots or {},
    )
    build_repo = BuildRepository(session)
    combo_repo = ComboRepository(session)
    attack_repo = AttackRepository(session)
    enemy_repo = EnemyProfileRepository(session)
    team_repo = TeamRepository(session)

    payload = await resolve_optimize_payload(
        session,
        body,
        combo_repo,
        build_repo,
        attack_repo,
        enemy_repo,
        team_repo=team_repo,
    )
    return {c.disc_id for c in payload.inventory}


class TestPriorityPool:
    async def test_priority_scope_excludes_higher_priority_disc(
        self,
        authed_client,
        db_session: AsyncSession,
    ) -> None:
        """A disc equipped on a higher-priority build is excluded from the pool."""
        base = await _seed_base(db_session)

        b1_id = await _make_build(authed_client, base["agent_id"], base["engine_id"], "PP_B1")
        b2_id = await _make_build(authed_client, base["agent2_id"], base["engine_id"], "PP_B2")
        t2_id = await _make_team(authed_client, b2_id, "PP_T2")
        combo2 = await _make_combo(authed_client, t2_id, base["attack_id"], "PP_C2")

        # Set priority: b1 > b2
        resp = await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1_id, b2_id]},
        )
        assert resp.status_code == 200

        # Disc equipped on b1 (higher priority)
        d_b1 = _make_disc(base["disc_set_id"], DiscSlot.ONE, b1_id)
        # Disc equipped on b2 (the target build — own disc always included)
        d_b2 = _make_disc(base["disc_set_id"], DiscSlot.TWO, b2_id)
        # Unequipped disc
        d_free = _make_disc(base["disc_set_id"], DiscSlot.THREE, None)
        db_session.add_all([d_b1, d_b2, d_free])
        await db_session.commit()

        pool = await _resolve_pool(
            db_session,
            b2_id,
            combo2,
            base["enemy_id"],
            "priority",
        )

        assert str(d_b1.id) not in pool, "higher-priority disc must be excluded"
        assert str(d_b2.id) in pool, "own disc must be included"
        assert str(d_free.id) in pool, "unequipped disc must be included"

    async def test_priority_scope_includes_lower_priority_disc(
        self,
        authed_client,
        db_session: AsyncSession,
    ) -> None:
        """A disc on a lower-priority build is NOT excluded."""
        base = await _seed_base(db_session)

        b1_id = await _make_build(authed_client, base["agent_id"], base["engine_id"], "PP2_B1")
        b2_id = await _make_build(authed_client, base["agent2_id"], base["engine_id"], "PP2_B2")
        b3_id = await _make_build(authed_client, base["agent3_id"], base["engine_id"], "PP2_B3")
        t2_id = await _make_team(authed_client, b2_id, "PP2_T2")
        combo2 = await _make_combo(authed_client, t2_id, base["attack_id"], "PP2_C2")

        # Priority: b1=1, b2=2, b3=3
        resp = await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1_id, b2_id, b3_id]},
        )
        assert resp.status_code == 200

        # Disc equipped on b3 (lower priority than b2)
        d_b3 = _make_disc(base["disc_set_id"], DiscSlot.FOUR, b3_id)
        db_session.add(d_b3)
        await db_session.commit()

        pool = await _resolve_pool(
            db_session,
            b2_id,
            combo2,
            base["enemy_id"],
            "priority",
        )

        assert str(d_b3.id) in pool, "lower-priority build's disc must be included"

    async def test_priority_scope_locked_disc_re_admitted(
        self,
        authed_client,
        db_session: AsyncSession,
    ) -> None:
        """A higher-priority build's disc locked to a slot is re-admitted."""
        base = await _seed_base(db_session)

        b1_id = await _make_build(authed_client, base["agent_id"], base["engine_id"], "PP3_B1")
        b2_id = await _make_build(authed_client, base["agent2_id"], base["engine_id"], "PP3_B2")
        t2_id = await _make_team(authed_client, b2_id, "PP3_T2")
        combo2 = await _make_combo(authed_client, t2_id, base["attack_id"], "PP3_C2")

        resp = await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1_id, b2_id]},
        )
        assert resp.status_code == 200

        d_b1 = _make_disc(base["disc_set_id"], DiscSlot.ONE, b1_id)
        db_session.add(d_b1)
        await db_session.commit()

        locked_disc_id = str(d_b1.id)

        pool = await _resolve_pool(
            db_session,
            b2_id,
            combo2,
            base["enemy_id"],
            "priority",
            locked_slots={"1": locked_disc_id},
        )

        assert locked_disc_id in pool, "locked higher-priority disc must be re-admitted"

    async def test_default_scope_matches_this_build(
        self,
        authed_client,
        db_session: AsyncSession,
    ) -> None:
        """Default scope (this_build) includes only own + unequipped; no regression."""
        base = await _seed_base(db_session)

        b1_id = await _make_build(authed_client, base["agent_id"], base["engine_id"], "PP4_B1")
        b2_id = await _make_build(authed_client, base["agent2_id"], base["engine_id"], "PP4_B2")
        t1_id = await _make_team(authed_client, b1_id, "PP4_T1")
        combo1 = await _make_combo(authed_client, t1_id, base["attack_id"], "PP4_C1")

        # Priority doesn't matter for this_build scope, but set it anyway
        resp = await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1_id, b2_id]},
        )
        assert resp.status_code == 200

        d_b1 = _make_disc(base["disc_set_id"], DiscSlot.ONE, b1_id)  # own
        d_b2 = _make_disc(base["disc_set_id"], DiscSlot.TWO, b2_id)  # other build
        d_free = _make_disc(base["disc_set_id"], DiscSlot.THREE, None)  # unequipped
        db_session.add_all([d_b1, d_b2, d_free])
        await db_session.commit()

        pool = await _resolve_pool(
            db_session,
            b1_id,
            combo1,
            base["enemy_id"],
            "this_build",
        )

        assert str(d_b1.id) in pool, "own disc must be included"
        assert str(d_b2.id) not in pool, "other build's disc excluded in this_build scope"
        assert str(d_free.id) in pool, "unequipped disc must be included"
