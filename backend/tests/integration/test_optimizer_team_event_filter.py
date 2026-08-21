"""Task 26 / issue #112 — the optimizer's acceptance tests for full-team
simulation plus event-level ownership.

The defect these pin: `resolve_optimize_payload` used to cut a team combo's
rotation down to the target agent's own steps *before* simulating, on the
reasoning that "the optimizer only evaluates the target". That reasoning is
about which damage to **score**; the cut also decided which state **exists**.
Refringe needs Remielle's move to bank a Lumiflux point AND a teammate's anomaly
trigger to consume it, so a target-only rotation could never produce one — every
optimizer run scored the DPS's anomalies with her signature buff switched off,
and Task 35 / E-6 already established that RefringeArea moves the AP/AM-vs-CRIT
optimum and changes disc *ranking*.

Each test therefore runs the SAME rotation twice: once shaped the way the old
pre-simulation filter shaped it (target steps only), once the way the pipeline
now does (full team + `score_owner_id`). The first is the red, and it is kept in
the assertion rather than deleted so that re-introducing the filter fails here
instead of silently reverting a ranking fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.agent import Agent, Attack
from app.models.build import Build, Combo, EnemyProfile
from app.models.enums import Element, Rarity, Specialty
from app.models.team import Team
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.repositories.team import TeamRepository
from app.schemas.optimizer import DiscOptimizeRequest
from app.services.buff_resolver import ActiveConditions
from app.services.combo_types import AnomalyStep, ComboStep, LuminizeStep
from app.services.optimizer_pipeline import (
    resolve_optimize_payload,
    resolve_stateful_am_step_lists,
)
from app.services.snapshot_builder import build_snapshot_from_db

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

REMIELLE_HAKUSHIN_ID = 1581
ARMING_MOVE = "EX Special Attack: Ode to Dawn"
LUMINIZE_MOVE = "Ultimate: Dazzling Curtain Call"
FIRE_MOVE = "Basic Attack: Mixed Flame Blend"
ELECTRIC_MOVE = "Basic Attack: Tsukuyomi"


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
        base_anomaly_proficiency=ap,
        base_anomaly_mastery=100,
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


class TestRefringeReachesTheOptimizer:
    """The headline defect: her coefficient never reached a scored step."""

    async def test_the_dps_own_anomaly_ticks_carry_refringe_only_with_the_full_rotation(
        self, db_session: AsyncSession
    ) -> None:
        remielle = _agent(
            "Remielle", REMIELLE_HAKUSHIN_ID, Element.LUMIFLUX, Specialty.SUPPORT, 200
        )
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
        enemy = _enemy("Refringe Reachability Dummy")
        dps_build = Build(agent_id=burnice.id, mindscape_level=0)
        rem_build = Build(agent_id=remielle.id, mindscape_level=0)
        db_session.add_all([enemy, dps_build, rem_build])
        await db_session.flush()
        for b in (dps_build, rem_build):
            await db_session.refresh(b, ["agent", "w_engine", "discs"])
        base_snapshot = build_snapshot_from_db(dps_build, dps_build.agent)

        # Her arming move banks the points; his hit triggers the anomaly that
        # consumes one. Both halves are required, which is exactly what the old
        # pre-simulation filter made impossible.
        full_rotation = [
            {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
            {"move_name": FIRE_MOVE, "agent_id": str(dps_build.id)},
        ]
        target_only = [s for s in full_rotation if s["agent_id"] == str(dps_build.id)]

        common = {
            "build": dps_build,
            "supports": [rem_build],
            "base_snapshot": base_snapshot,
            "enemy": enemy,
            "session": db_session,
        }
        old_shape = await _steps(target_only, score_owner_id=None, **common)
        new_shape = await _steps(full_rotation, score_owner_id="dps", **common)

        old_ticks = [s for s in old_shape if isinstance(s, AnomalyStep)]
        new_ticks = [s for s in new_shape if isinstance(s, AnomalyStep)]
        assert old_ticks, "fixture broken: the DPS triggered no anomaly at all"
        assert new_ticks, "the DPS's own anomaly ticks vanished from the step list"

        # `procs_override` is effective proc-equivalents — RefringeArea is folded
        # into it as a plain linear scale (Task 35). Neutral is 1.0.
        assert all(t.procs_override == 1.0 for t in old_ticks), (
            "fixture broken: the target-only rotation should be unable to Refringe"
        )
        assert all(t.procs_override > 1.0 for t in new_ticks), (
            "Remielle is on the team and armed, but the DPS's own anomaly ticks "
            "still score at a neutral RefringeArea — her coefficient is not "
            "reaching the optimizer, which is issue #112"
        )


class TestTeammateDamageIsNotScoredAgainstTheCandidate:
    """The other half of the fix. Simulating the full rotation puts
    teammate-owned events in the stream, and every step the mapping emits is
    re-scored against the candidate discs — so without the ownership filter this
    change would trade a silent under-credit for a silent over-credit."""

    async def test_teammate_hits_and_teammate_anomalies_do_not_become_steps(
        self, db_session: AsyncSession
    ) -> None:
        remielle = _agent(
            "Remielle", REMIELLE_HAKUSHIN_ID, Element.LUMIFLUX, Specialty.SUPPORT, 200
        )
        burnice = _agent("Burnice", 90006, Element.FIRE)
        yanagi = _agent("Yanagi", 90007, Element.ELECTRIC)
        db_session.add_all([remielle, burnice, yanagi])
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
                Attack(
                    agent_id=yanagi.id,
                    hakushin_skill_id=9000701,
                    skill_key="Basic",
                    name=ELECTRIC_MOVE,
                    hit_index=0,
                    element=Element.ELECTRIC,
                    damage_base=10000,
                    damage_growth=500,
                    anomaly_buildup=10_000,
                ),
            ]
        )
        enemy = _enemy("Ownership Dummy")
        dps_build = Build(agent_id=burnice.id, mindscape_level=0)
        rem_build = Build(agent_id=remielle.id, mindscape_level=0)
        yan_build = Build(agent_id=yanagi.id, mindscape_level=0)
        db_session.add_all([enemy, dps_build, rem_build, yan_build])
        await db_session.flush()
        for b in (dps_build, rem_build, yan_build):
            await db_session.refresh(b, ["agent", "w_engine", "discs"])
        base_snapshot = build_snapshot_from_db(dps_build, dps_build.agent)

        # Yanagi's electric hit lands on Burnice's fire aura: it is a teammate
        # hit, a teammate-owned electric anomaly, AND a Disorder — the three
        # kinds whose ownership fields disagree with each other.
        rotation = [
            {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
            {"move_name": FIRE_MOVE, "agent_id": str(dps_build.id)},
            {"move_name": ELECTRIC_MOVE, "agent_id": str(yan_build.id)},
        ]
        steps = await _steps(
            rotation,
            build=dps_build,
            supports=[rem_build, yan_build],
            base_snapshot=base_snapshot,
            enemy=enemy,
            session=db_session,
            score_owner_id="dps",
        )

        hits = [s for s in steps if isinstance(s, ComboStep)]
        assert hits, "fixture broken: the DPS landed no hit"
        # Every mapped hit is the DPS's own move. Remielle's arming hit and
        # Yanagi's basic are both damage events in the stream now.
        assert {h.element for h in hits} == {"fire"}, (
            f"a teammate's hit was scored against the candidate build: "
            f"{sorted({h.element for h in hits})}"
        )

        anomalies = [s for s in steps if isinstance(s, AnomalyStep)]
        assert anomalies, "fixture broken: the DPS triggered no anomaly"
        assert {a.element for a in anomalies} == {"fire"}, (
            f"a teammate-owned anomaly was scored against the candidate build's "
            f"stats: {sorted({a.element for a in anomalies})}"
        )

        # Disorder ownership is the subtle one, and it goes the opposite way to
        # intuition. This Disorder was TRIGGERED by Yanagi, but it consumed
        # Burnice's fire aura, and the engine computes it from that overridden
        # aura's applier context (`old_ctx`) and credits
        # `per_agent_attribution[applier_id]`. Its every stat term is therefore
        # the scored build's, so it must be KEPT — filtering Disorder on
        # `agent_id` (who acted) rather than `applier_agent_id` (whose aura) would
        # drop real damage here and, in the mirror case below, invent some.
        disorders = [a for a in anomalies if a.label.startswith("Disorder")]
        assert disorders, (
            "the Disorder that consumed the scored build's own aura was dropped"
        )
        assert {a.element for a in disorders} == {"fire"}

    async def test_a_disorder_that_consumes_a_teammates_aura_is_not_scored(
        self, db_session: AsyncSession
    ) -> None:
        """The mirror of the case above: same three agents, reversed order, so
        the scored build's hit is what triggers a Disorder — on a teammate's
        aura, computed from the teammate's context. Filtering on the acting
        agent would credit the candidate build every stat term of it."""
        remielle = _agent(
            "Remielle", REMIELLE_HAKUSHIN_ID, Element.LUMIFLUX, Specialty.SUPPORT, 200
        )
        burnice = _agent("Burnice", 90006, Element.FIRE)
        yanagi = _agent("Yanagi", 90007, Element.ELECTRIC)
        db_session.add_all([remielle, burnice, yanagi])
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
                Attack(
                    agent_id=yanagi.id,
                    hakushin_skill_id=9000701,
                    skill_key="Basic",
                    name=ELECTRIC_MOVE,
                    hit_index=0,
                    element=Element.ELECTRIC,
                    damage_base=10000,
                    damage_growth=500,
                    anomaly_buildup=10_000,
                ),
            ]
        )
        enemy = _enemy("Disorder Ownership Dummy")
        dps_build = Build(agent_id=burnice.id, mindscape_level=0)
        rem_build = Build(agent_id=remielle.id, mindscape_level=0)
        yan_build = Build(agent_id=yanagi.id, mindscape_level=0)
        db_session.add_all([enemy, dps_build, rem_build, yan_build])
        await db_session.flush()
        for b in (dps_build, rem_build, yan_build):
            await db_session.refresh(b, ["agent", "w_engine", "discs"])
        base_snapshot = build_snapshot_from_db(dps_build, dps_build.agent)

        steps = await _steps(
            [
                {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
                {"move_name": ELECTRIC_MOVE, "agent_id": str(yan_build.id)},
                {"move_name": FIRE_MOVE, "agent_id": str(dps_build.id)},
            ],
            build=dps_build,
            supports=[rem_build, yan_build],
            base_snapshot=base_snapshot,
            enemy=enemy,
            session=db_session,
            score_owner_id="dps",
        )

        anomalies = [s for s in steps if isinstance(s, AnomalyStep)]
        assert anomalies, "fixture broken: the DPS triggered no anomaly"
        disorders = [a for a in anomalies if a.label.startswith("Disorder")]
        assert not disorders, (
            f"a Disorder computed from a teammate's aura context was scored "
            f"against the candidate build: {[a.label for a in disorders]}"
        )


class TestLuminizeBecomesReachableWhenSheIsTheOptimizedDps:
    """Task 15 Piece 1's `luminize_owner_scaled_node` was correct but could
    never fire from `/optimize`: her filtered rotation was hers alone, she
    applies no anomaly buildup, and `_resolve_refringe` refuses a Lumiflux
    acting agent — so no Voidflare was ever banked and no `luminize` event ever
    reached the step list. This is the test that was missing."""

    async def test_a_luminize_step_reaches_the_step_list(
        self, db_session: AsyncSession
    ) -> None:
        remielle = _agent(
            "Remielle", REMIELLE_HAKUSHIN_ID, Element.LUMIFLUX, Specialty.SUPPORT, 200
        )
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
                    agent_id=remielle.id,
                    hakushin_skill_id=158118,
                    skill_key="Ultimate",
                    name=LUMINIZE_MOVE,
                    hit_index=0,
                    element=Element.LUMIFLUX,
                    damage_base=12000,
                    damage_growth=600,
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
        enemy = _enemy("Luminize Reachability Dummy")
        # SHE is the build whose discs are enumerated; Burnice is the support.
        rem_build = Build(agent_id=remielle.id, mindscape_level=0)
        bur_build = Build(agent_id=burnice.id, mindscape_level=0)
        db_session.add_all([enemy, rem_build, bur_build])
        await db_session.flush()
        for b in (rem_build, bur_build):
            await db_session.refresh(b, ["agent", "w_engine", "discs"])
        base_snapshot = build_snapshot_from_db(rem_build, rem_build.agent)

        full_rotation = [
            {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
            {"move_name": FIRE_MOVE, "agent_id": str(bur_build.id)},
            {"move_name": LUMINIZE_MOVE, "agent_id": str(rem_build.id)},
        ]
        target_only = [s for s in full_rotation if s["agent_id"] == str(rem_build.id)]

        common = {
            "build": rem_build,
            "supports": [bur_build],
            "base_snapshot": base_snapshot,
            "enemy": enemy,
            "session": db_session,
        }
        old_shape = await _steps(target_only, score_owner_id=None, **common)
        new_shape = await _steps(full_rotation, score_owner_id="dps", **common)

        assert not [s for s in old_shape if isinstance(s, LuminizeStep)], (
            "fixture broken: a rotation of her moves alone cannot bank a Voidflare"
        )
        lum = [s for s in new_shape if isinstance(s, LuminizeStep)]
        assert lum, (
            "no LuminizeStep reached the step list — the largest part of her own "
            "damage still contributes nothing to ranking her discs"
        )
        # Captured from a support, so the teammate half is frozen; but SHE is the
        # optimized build, so her half must vary with the candidate (Task 15
        # Piece 1's third node shape).
        assert any(s.is_owner_scaled for s in lum), (
            "the Luminize steps are fully frozen — her AP and Anomaly DMG% would "
            "stay at their disc-stripped values for every candidate"
        )


class TestLuminizeOwnershipWhenSheIsASupport:
    """The follow-up to Task 26's `_owns`, which kept every `luminize` event.

    Simulating the full team made her Luminize reachable in the common shape --
    she is a Support by specialty -- and it arrives in three provenances, only
    two of which the scored build's discs can move. Splitting them at the mapping
    site fixes each step's *value*; it never asked whether the step belongs in
    this build's list at all.
    """

    async def test_a_voidflare_captured_from_a_teammate_is_not_scored(
        self, db_session: AsyncSession
    ) -> None:
        """Two Voidflares, two provenances, one Luminize. The fire one snapshotted
        the scored build and must be scored against its candidates; the electric
        one snapshotted a third teammate and is frozen at a build the optimizer
        never strips, so no candidate disc can move it by a single point. It used
        to ride along as a constant inflating `total_damage` with a teammate's
        move -- the same call `phase_flow_tick` already makes for the same reason.
        """
        remielle = _agent(
            "Remielle", REMIELLE_HAKUSHIN_ID, Element.LUMIFLUX, Specialty.SUPPORT, 200
        )
        burnice = _agent("Burnice", 90006, Element.FIRE)
        yanagi = _agent("Yanagi", 90007, Element.ELECTRIC)
        db_session.add_all([remielle, burnice, yanagi])
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
                    agent_id=remielle.id,
                    hakushin_skill_id=158118,
                    skill_key="Ultimate",
                    name=LUMINIZE_MOVE,
                    hit_index=0,
                    element=Element.LUMIFLUX,
                    damage_base=12000,
                    damage_growth=600,
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
                Attack(
                    agent_id=yanagi.id,
                    hakushin_skill_id=9000701,
                    skill_key="Basic",
                    name=ELECTRIC_MOVE,
                    hit_index=0,
                    element=Element.ELECTRIC,
                    damage_base=10000,
                    damage_growth=500,
                    anomaly_buildup=10_000,
                ),
            ]
        )
        enemy = _enemy("Luminize Ownership Dummy")
        # Burnice is the optimized DPS; Remielle and Yanagi are the supports.
        dps_build = Build(agent_id=burnice.id, mindscape_level=0)
        rem_build = Build(agent_id=remielle.id, mindscape_level=0)
        yan_build = Build(agent_id=yanagi.id, mindscape_level=0)
        db_session.add_all([enemy, dps_build, rem_build, yan_build])
        await db_session.flush()
        for b in (dps_build, rem_build, yan_build):
            await db_session.refresh(b, ["agent", "w_engine", "discs"])
        base_snapshot = build_snapshot_from_db(dps_build, dps_build.agent)

        # Arm ONCE -- `ARMING_MOVE` carries `phase_flow_entry`, and E-F3 wired
        # Phase Flow entry to `clear_voidflare_store`, so re-arming between the
        # two triggers would wipe the fire Voidflare before it could Luminize.
        # One arming banks two points, which reaches both Refringes.
        rotation = [
            {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
            {"move_name": FIRE_MOVE, "agent_id": str(dps_build.id)},
            {"move_name": ELECTRIC_MOVE, "agent_id": str(yan_build.id)},
            {"move_name": LUMINIZE_MOVE, "agent_id": str(rem_build.id)},
        ]
        common = {
            "build": dps_build,
            "supports": [rem_build, yan_build],
            "base_snapshot": base_snapshot,
            "enemy": enemy,
            "session": db_session,
        }
        unfiltered = await _steps(rotation, score_owner_id=None, **common)
        scored = await _steps(rotation, score_owner_id="dps", **common)

        # The fixture only proves anything if both provenances really occur.
        all_lum = [s for s in unfiltered if isinstance(s, LuminizeStep)]
        assert {s.voidflare_element for s in all_lum} == {"fire", "electric"}, (
            "fixture broken: the store did not end up holding one Voidflare of "
            f"each provenance, got {sorted({s.voidflare_element for s in all_lum})}"
        )

        lum = [s for s in scored if isinstance(s, LuminizeStep)]
        assert {s.voidflare_element for s in lum} == {"fire"}, (
            "a Luminize fired by one teammate off another teammate's Voidflare "
            "was scored into the optimized build's total: "
            f"{sorted({s.voidflare_element for s in lum})}"
        )
        # The one that survives is the live branch, not a constant — it snapshotted
        # the scored build, so every candidate has to rebuild it.
        assert all(s.frozen_damage is None for s in lum), (
            "the surviving Luminize is frozen, so it cannot vary with the "
            "candidate discs — which would make keeping it pointless"
        )


class TestSupportsResolveWithoutAnExplicitTeamId:
    """The target build is resolved from `body.team_id or combo.team_id`, and so
    is `fluxed_element` — but `support_builds` was gated on `body.team_id` alone.

    Task 26 turned that from harmless into a third route to the same defect: the
    full team rotation now survives normalization, so with no supports in
    `sim_builds` every teammate step reaches `simulate()` with no build behind it
    and is dropped as "Build not found" (`anomaly_simulator.py:1893`). Refringe
    silently off again, from a request that named a perfectly good team — just
    not in the field the gate happened to read.
    """

    async def test_a_combo_only_request_still_sees_its_team(
        self, db_session: AsyncSession
    ) -> None:
        remielle = _agent(
            "Remielle", REMIELLE_HAKUSHIN_ID, Element.LUMIFLUX, Specialty.SUPPORT, 200
        )
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
        enemy = _enemy("Combo-Only Request Dummy")
        dps_build = Build(agent_id=burnice.id, mindscape_level=0)
        rem_build = Build(agent_id=remielle.id, mindscape_level=0)
        db_session.add_all([enemy, dps_build, rem_build])
        await db_session.flush()

        team = Team(name="Combo-Only Team", build1_id=dps_build.id, build2_id=rem_build.id)
        db_session.add(team)
        await db_session.flush()
        combo = Combo(
            name="Combo-Only Rotation",
            team_id=team.id,
            sequence=[
                {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
                {"move_name": FIRE_MOVE, "agent_id": str(dps_build.id)},
            ],
        )
        db_session.add(combo)
        await db_session.flush()

        async def _ticks(team_id: str | None) -> list[AnomalyStep]:
            payload = await resolve_optimize_payload(
                db_session,
                DiscOptimizeRequest(
                    team_id=team_id,
                    active_index=0,
                    combo_id=str(combo.id),
                    enemy_profile_id=str(enemy.id),
                ),
                ComboRepository(db_session),
                BuildRepository(db_session),
                AttackRepository(db_session),
                EnemyProfileRepository(db_session),
                team_repo=TeamRepository(db_session),
            )
            return [
                s
                for steps in payload.all_step_lists
                for s in steps
                if isinstance(s, AnomalyStep)
            ]

        with_team_id = await _ticks(str(team.id))
        combo_only = await _ticks(None)

        assert with_team_id, "fixture broken: the explicit-team_id request scored no anomaly"
        assert all(t.procs_override > 1.0 for t in with_team_id), (
            "fixture broken: Remielle is armed and on the team, so the explicit "
            "request's ticks should already carry a non-neutral RefringeArea"
        )
        # The whole point: naming only the combo must not silently cost the
        # request its teammates.
        assert combo_only, "the combo-only request scored no anomaly at all"
        assert all(t.procs_override > 1.0 for t in combo_only), (
            "a request that named only a combo lost its supports — its anomaly "
            "ticks scored at a neutral RefringeArea while the identical request "
            "naming the team scored them Refringed"
        )
        assert [t.procs_override for t in combo_only] == [
            t.procs_override for t in with_team_id
        ], "the two request shapes resolved different teams"
