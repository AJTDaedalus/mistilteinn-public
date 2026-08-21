"""The Refringe credit reaches a scored step, and her AP moves it (#160).

The defect: `_owns` drops a teammate's `anomaly_tick` because
`_anomaly_owner_share` returns the scored build's **buildup** share, and a
Lumiflux agent applies Lumiflux points rather than Attribute Anomaly buildup —
so her share of a teammate's anomaly is 0.0. That is right for the teammate's own
damage and wrong for the Refringe uplift riding on it, which exists only because
of her and scales with her Anomaly Proficiency. Dropping both is what lets the
optimizer sell AP to buy CRIT on an agent whose kit barely crits.

This is the inverse of `test_optimizer_team_event_filter.py`'s scenario: there
Remielle is a support and the DPS's *own* anomalies carry her coefficient; here
**she is the optimized target** and the anomaly belongs to the teammate, which is
the case that produced zero attribution before this change.

Uses a synthetic two-agent team rather than any real account's data — the claim
under test is a property of the engine, not of one build.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.models.agent import Agent, Attack
from app.models.build import Build, EnemyProfile
from app.models.enums import Element, Rarity, Specialty
from app.repositories.attack import AttackRepository
from app.services.buff_resolver import ActiveConditions
from app.services.combo_types import AnomalyStep, RefringeCreditStep
from app.services.damage_dag_service import (
    build_refringe_credit_context,
    compute_luminize_with_accumulated_disc,
)
from app.services.optimizer_pipeline import resolve_stateful_am_step_lists
from app.services.snapshot_builder import build_snapshot_from_db, enemy_snapshot_from_db
from app.services.stat_calculator import DiscStats

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

REMIELLE_HAKUSHIN_ID = 1581
ARMING_MOVE = "EX Special Attack: Ode to Dawn"
FIRE_MOVE = "Basic Attack: Mixed Flame Blend"


def _agent(name, hakushin_id, element, specialty=Specialty.ANOMALY, ap=115):
    return Agent(
        hakushin_id=hakushin_id,
        name=name,
        element=element,
        specialty=specialty,
        rarity=Rarity.S,
        base_hp=8000,
        base_atk=1000,
        base_def=600,
        base_crit_rate=500,
        base_crit_dmg=5000,
        base_anomaly_mastery=100,
        base_anomaly_proficiency=ap,
    )


def _enemy(name):
    return EnemyProfile(
        name=name,
        level=60,
        defense=50,
        fire_res=0,
        electric_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_res_fire=0,
        anomaly_res_electric=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )


async def _build_team(db_session: AsyncSession):
    """Remielle as the optimized target, one Fire teammate to trigger the anomaly."""
    remielle = _agent("Remielle", REMIELLE_HAKUSHIN_ID, Element.LUMIFLUX, Specialty.ANOMALY, 200)
    burnice = _agent("Burnice", 90006, Element.FIRE)
    db_session.add_all([remielle, burnice])
    await db_session.flush()
    db_session.add_all(
        [
            Attack(
                agent_id=remielle.id,
                hakushin_skill_id=158114,
                skill_key="Special",
                name=ARMING_MOVE,
                hit_index=0,
                element=Element.LUMIFLUX,
                damage_base=8000,
                damage_growth=400,
            ),
            Attack(
                agent_id=burnice.id,
                hakushin_skill_id=9000601,
                skill_key="Basic",
                name=FIRE_MOVE,
                hit_index=0,
                element=Element.FIRE,
                damage_base=10000,
                damage_growth=500,
                anomaly_buildup=10_000,
            ),
        ]
    )
    enemy = _enemy("Refringe Credit Dummy")
    rem_build = Build(agent_id=remielle.id, mindscape_level=0)
    burn_build = Build(agent_id=burnice.id, mindscape_level=0)
    db_session.add_all([enemy, rem_build, burn_build])
    await db_session.flush()
    for b in (rem_build, burn_build):
        await db_session.refresh(b, ["agent", "w_engine", "discs"])
    return rem_build, burn_build, enemy


async def _steps(sequence, *, build, supports, base_snapshot, enemy, session, score_owner_id):
    am_map = await resolve_stateful_am_step_lists(
        combo=None,
        build=build,
        base_build=base_snapshot,
        enemy=enemy,
        attack_repo=AttackRepository(session),
        inventory=[],
        am_2pc_sets={},
        conditions=ActiveConditions(),
        support_builds=supports,
        sequence_override=sequence,
        score_owner_id=score_owner_id,
    )
    return [s for steps in am_map.values() for s in steps]


class TestTheCreditReachesAScoredStep:
    async def test_a_teammates_refringed_anomaly_produces_a_credit_for_her(
        self, db_session: AsyncSession
    ) -> None:
        rem_build, burn_build, enemy = await _build_team(db_session)
        base_snapshot = build_snapshot_from_db(rem_build, rem_build.agent)

        # She arms (banks a Lumiflux point); he triggers the Burn that consumes
        # it. Both halves are required for Refringe to fire at all.
        rotation = [
            {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
            {"move_name": FIRE_MOVE, "agent_id": str(burn_build.id)},
        ]
        steps = await _steps(
            rotation,
            build=rem_build,
            supports=[burn_build],
            base_snapshot=base_snapshot,
            enemy=enemy,
            session=db_session,
            score_owner_id="dps",
        )

        found = [s for s in steps if isinstance(s, RefringeCreditStep)]
        assert found, (
            "Remielle is the optimized target and her coefficient multiplied the "
            "teammate's Burn ticks, but no RefringeCreditStep was emitted — the "
            "AP-driven half of her contribution is still being discarded (#160)"
        )
        credit = found[0]
        assert credit.refringe_mult_at_stripped_ap > 10000, (
            "fixture broken: Refringe did not actually fire on this aura"
        )
        assert credit.frozen_tick_damage > 0
        assert credit.refringe_ap_ratio_bp > 0, (
            "the credit carries no AP coefficient, so her AP could not move it"
        )

    async def test_the_teammates_own_anomaly_is_still_not_scored_as_hers(
        self, db_session: AsyncSession
    ) -> None:
        """The credit must not become a backdoor for #112's over-credit.

        Only the uplift is attributable. The teammate's Burn itself is their
        damage and must stay out of her step list.
        """
        rem_build, burn_build, enemy = await _build_team(db_session)
        base_snapshot = build_snapshot_from_db(rem_build, rem_build.agent)
        rotation = [
            {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
            {"move_name": FIRE_MOVE, "agent_id": str(burn_build.id)},
        ]
        steps = await _steps(
            rotation,
            build=rem_build,
            supports=[burn_build],
            base_snapshot=base_snapshot,
            enemy=enemy,
            session=db_session,
            score_owner_id="dps",
        )

        fire_ticks = [
            s for s in steps if isinstance(s, AnomalyStep) and s.anomaly_type == "burn"
        ]
        assert not fire_ticks, (
            "the teammate's own Burn ticks are in HER step list and would be "
            "re-scored against her discs — that is the #112 over-credit"
        )


class TestHerAPMovesTheCredit:
    """The property the whole issue is about: her AP must change the number."""

    async def test_more_anomaly_proficiency_scores_a_larger_credit(
        self, db_session: AsyncSession
    ) -> None:
        rem_build, burn_build, enemy = await _build_team(db_session)
        base_snapshot = build_snapshot_from_db(rem_build, rem_build.agent)
        rotation = [
            {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
            {"move_name": FIRE_MOVE, "agent_id": str(burn_build.id)},
        ]
        steps = await _steps(
            rotation,
            build=rem_build,
            supports=[burn_build],
            base_snapshot=base_snapshot,
            enemy=enemy,
            session=db_session,
            score_owner_id="dps",
        )
        credit = next(s for s in steps if isinstance(s, RefringeCreditStep))

        enemy_snap = enemy_snapshot_from_db(enemy, base_snapshot.agent_element)
        ctx = build_refringe_credit_context(
            build=base_snapshot,
            enemy=enemy_snap,
            step=credit,
            conditions=ActiveConditions(),
        )

        low = compute_luminize_with_accumulated_disc(ctx, DiscStats(anomaly_proficiency=0))
        high = compute_luminize_with_accumulated_disc(ctx, DiscStats(anomaly_proficiency=200))

        assert high > low, (
            "adding 200 Anomaly Proficiency from discs did not increase her "
            "Refringe credit — the AP term is frozen, which is the defect #160 "
            "reported as 'the optimizer sells AP to buy CRIT'"
        )
        # Linear in AP with no cap, so double the AP delta doubles the increment.
        higher = compute_luminize_with_accumulated_disc(ctx, DiscStats(anomaly_proficiency=400))
        assert (higher - high) == pytest.approx(high - low)
