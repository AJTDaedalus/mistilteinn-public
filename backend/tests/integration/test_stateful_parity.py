"""Task 15 — Stateless parity test.

For a solo standard attacker with zero anomaly buildup, the stateful
simulate() standard total must equal the sum of calculate_build_damage
calls for the same hits.

This is the foundation of single-engine trust.  Once degenerate-mode
(Task 18) is wired, these assertions will route through that entry
point instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.enums import Element, Rarity, Specialty
from app.services.anomaly_simulator import SimulatedAttackStep, simulate, simulate_single_hit
from app.services.build_damage_service import (
    BuildSnapshot,
    CritMode,
    EnemySnapshot,
    calculate_build_damage,
)
from app.services.modifiers import ActiveConditions, AttackScope, Condition

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enemy_snap_for_simulator(enemy: EnemyProfile, element: str) -> EnemySnapshot:
    """Replicate the EnemySnapshot the simulator constructs per-hit.

    Mirrors anomaly_simulator.py lines 685-691 exactly so any future
    change to one must be mirrored in the other.
    """
    elem_res = getattr(enemy, f"{element}_res", 0) or 0
    stun_dmg_taken_ratio = getattr(enemy, "stun_dmg_taken_ratio", 5000) or 5000
    return EnemySnapshot(
        level=enemy.level,
        base_def=enemy.defense,
        element_res=elem_res,
        stun_dmg_mult=10000 + stun_dmg_taken_ratio,
    )


def _conditions_for_snapshot(snapshot) -> ActiveConditions:
    """Replicate the ActiveConditions the simulator injects for a solo agent.

    Mirrors anomaly_simulator.py lines 251-278 for a solo, unstunned
    attacker with no user-provided conditions.
    """
    active: set[Condition] = {Condition.ALWAYS}
    specialty = getattr(snapshot, "agent_specialty", "")
    elem = getattr(snapshot, "agent_element", "")
    if specialty:
        with __import__("contextlib").suppress(ValueError):
            active.add(Condition(f"equipper_is_{specialty.lower()}"))
    if elem:
        with __import__("contextlib").suppress(ValueError):
            active.add(Condition(f"equipper_is_{elem.lower()}"))
    return ActiveConditions(
        active=active,
        stack_counts=dict(getattr(snapshot, "stack_counts", {}) or {}),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def parity_agent(db_session: AsyncSession) -> Agent:
    """Physical Attack agent with no modifier JSON (hakushin_id 99901)."""
    a = Agent(
        hakushin_id=99901,
        name="ParityDPS",
        element=Element.PHYSICAL,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_hp=10000,
        base_atk=800,
        base_def=600,
        base_crit_rate=500,  # 5%
        base_crit_dmg=5000,  # 50%
        base_anomaly_proficiency=0,
        base_anomaly_mastery=100,
    )
    db_session.add(a)
    await db_session.flush()
    return a


@pytest.fixture
async def parity_attacks(db_session: AsyncSession, parity_agent: Agent) -> list[Attack]:
    """Two physical Basic attacks with zero anomaly buildup."""
    a1 = Attack(
        agent_id=parity_agent.id,
        hakushin_skill_id=9000,
        skill_key="Basic",
        name="Basic Attack: Parity Hit 1",
        hit_index=0,
        element=Element.PHYSICAL,
        damage_base=20000,  # 200% ATK
        damage_growth=0,
        anomaly_buildup=0,
    )
    a2 = Attack(
        agent_id=parity_agent.id,
        hakushin_skill_id=9001,
        skill_key="Basic",
        name="Basic Attack: Parity Hit 2",
        hit_index=0,
        element=Element.PHYSICAL,
        damage_base=35000,  # 350% ATK
        damage_growth=0,
        anomaly_buildup=0,
    )
    db_session.add_all([a1, a2])
    await db_session.flush()
    return [a1, a2]


@pytest.fixture
async def parity_enemy(db_session: AsyncSession) -> EnemyProfile:
    """Neutral enemy: no RES, default DEF, default stun ratio."""
    e = EnemyProfile(
        name="Parity Dummy",
        level=60,
        defense=953,
        physical_res=0,
        stun_dmg_taken_ratio=5000,
        anomaly_capacity_physical=10000,  # huge — won't trigger in test
    )
    db_session.add(e)
    await db_session.flush()
    return e


@pytest.fixture
def parity_snapshot(parity_agent: Agent) -> BuildSnapshot:
    """BuildSnapshot built directly from agent stats — no DB round-trip needed.

    Snapshot construction via build_snapshot_from_db is tested separately
    (test_snapshot_builder_supports.py).  Parity is purely about two
    engines receiving the same snapshot and agreeing on the result.
    """
    return BuildSnapshot(
        agent_base_atk=parity_agent.base_atk,
        agent_base_hp=parity_agent.base_hp,
        agent_base_def=parity_agent.base_def,
        agent_crit_rate=parity_agent.base_crit_rate,
        agent_crit_dmg=parity_agent.base_crit_dmg,
        agent_anomaly_mastery=getattr(parity_agent, "base_anomaly_mastery", 100) or 100,
        agent_name=parity_agent.name,
        agent_element="physical",
        agent_specialty="attack",
        agent_level=60,
        skill_levels="12,12,12,12,12",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStatefulParity:
    """Stateful simulate() standard total == sum of stateless calculate_build_damage."""

    async def test_single_step_parity(
        self,
        db_session: AsyncSession,
        parity_attacks: list[Attack],
        parity_enemy: EnemyProfile,
        parity_snapshot: BuildSnapshot,
    ) -> None:
        """Single 2-hit step: stateful standard total == stateless sum."""
        snap = parity_snapshot

        steps = [
            SimulatedAttackStep(
                agent_id="dps",
                move_name="Basic Attack: Parity Hit 1",
                attacks=parity_attacks,
                conditions=[],
            )
        ]

        result = simulate(
            builds={"dps": snap},
            steps=steps,
            enemy=parity_enemy,
            moves_db={},
        )

        # Stateless: compute the same hits independently
        conditions = _conditions_for_snapshot(snap)
        stateless_total = 0
        for attack in parity_attacks:
            elem = str(
                attack.element.value if hasattr(attack.element, "value") else attack.element
            )
            enemy_snap = _enemy_snap_for_simulator(parity_enemy, elem)
            multiplier = (attack.damage_base or 0) + (attack.damage_growth or 0) * (12 - 1)
            dmg = calculate_build_damage(
                build=snap,
                enemy=enemy_snap,
                multiplier=multiplier,
                conditions=conditions,
                attack_scope=AttackScope.ALL,
                crit_mode=CritMode.EXPECTED,
            )
            stateless_total += dmg.damage.total

        assert result.totals["standard"] == stateless_total, (
            f"Stateful standard total {result.totals['standard']} != "
            f"stateless sum {stateless_total} — engines diverge"
        )
        assert result.totals["anomaly"] == 0, "Expected zero anomaly triggers"
        assert result.totals["standard"] > 0, "Expected non-zero standard damage"

    async def test_multi_step_parity(
        self,
        db_session: AsyncSession,
        parity_attacks: list[Attack],
        parity_enemy: EnemyProfile,
        parity_snapshot: BuildSnapshot,
    ) -> None:
        """Three steps with the same attacks: stateful standard total == sum of stateless calls."""
        snap = parity_snapshot

        attack1, attack2 = parity_attacks
        steps = [
            SimulatedAttackStep(
                agent_id="dps",
                move_name="Basic Attack: Parity Hit 1",
                attacks=[attack1],
                conditions=[],
            ),
            SimulatedAttackStep(
                agent_id="dps",
                move_name="Basic Attack: Parity Hit 2",
                attacks=[attack2],
                conditions=[],
            ),
            SimulatedAttackStep(
                agent_id="dps",
                move_name="Basic Attack: Parity Hit 1",
                attacks=[attack1],
                conditions=[],
            ),
        ]

        result = simulate(
            builds={"dps": snap},
            steps=steps,
            enemy=parity_enemy,
            moves_db={},
        )

        conditions = _conditions_for_snapshot(snap)

        def _hit_dmg(attack: Attack) -> int:
            elem = str(
                attack.element.value if hasattr(attack.element, "value") else attack.element
            )
            enemy_snap = _enemy_snap_for_simulator(parity_enemy, elem)
            multiplier = (attack.damage_base or 0) + (attack.damage_growth or 0) * (12 - 1)
            return calculate_build_damage(
                build=snap,
                enemy=enemy_snap,
                multiplier=multiplier,
                conditions=conditions,
                attack_scope=AttackScope.ALL,
                crit_mode=CritMode.EXPECTED,
            ).damage.total

        expected = _hit_dmg(attack1) + _hit_dmg(attack2) + _hit_dmg(attack1)

        assert result.totals["standard"] == expected, (
            f"Stateful {result.totals['standard']} != stateless {expected}"
        )
        assert result.totals["anomaly"] == 0
        assert result.totals["total"] == result.totals["standard"]


class TestDegenerateSingleHit:
    """Task 18: simulate_single_hit() routes through the stateful engine
    and produces the same result as the full simulate() parity tests.
    """

    async def test_degenerate_matches_stateless(
        self,
        db_session,
        parity_attacks: list,
        parity_enemy: EnemyProfile,
        parity_snapshot: BuildSnapshot,
    ) -> None:
        """simulate_single_hit for two attacks == sum of stateless calculate_build_damage."""
        snap = parity_snapshot
        result = simulate_single_hit(
            build=snap,
            attacks=parity_attacks,
            enemy=parity_enemy,
        )

        conditions = _conditions_for_snapshot(snap)
        stateless_total = 0
        for attack in parity_attacks:
            elem = str(
                attack.element.value if hasattr(attack.element, "value") else attack.element
            )
            enemy_snap = _enemy_snap_for_simulator(parity_enemy, elem)
            multiplier = (attack.damage_base or 0) + (attack.damage_growth or 0) * (12 - 1)
            dmg = calculate_build_damage(
                build=snap,
                enemy=enemy_snap,
                multiplier=multiplier,
                conditions=conditions,
                attack_scope=AttackScope.ALL,
                crit_mode=CritMode.EXPECTED,
            )
            stateless_total += dmg.damage.total

        assert result.totals["standard"] == stateless_total, (
            f"degenerate stateful {result.totals['standard']} != stateless {stateless_total}"
        )
        assert result.totals["anomaly"] == 0
        assert result.totals["standard"] > 0

    async def test_degenerate_rejects_buildup(
        self,
        db_session,
        parity_agent,
        parity_enemy: EnemyProfile,
        parity_snapshot: BuildSnapshot,
    ) -> None:
        """simulate_single_hit raises ValueError when any attack has non-zero buildup."""
        from app.models.agent import Attack
        from app.models.enums import Element

        buildup_attack = Attack(
            agent_id=parity_agent.id,
            hakushin_skill_id=9099,
            skill_key="Basic",
            name="Attack With Buildup",
            hit_index=0,
            element=Element.PHYSICAL,
            damage_base=20000,
            damage_growth=0,
            anomaly_buildup=500,  # non-zero — must be rejected
        )
        db_session.add(buildup_attack)
        await db_session.flush()

        with pytest.raises(ValueError, match="anomaly_buildup"):
            simulate_single_hit(
                build=parity_snapshot,
                attacks=[buildup_attack],
                enemy=parity_enemy,
            )
