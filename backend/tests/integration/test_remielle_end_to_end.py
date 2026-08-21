"""Task 33 — end-to-end Lumiflux reachability (DESIGN_remielle.md §13.5).

Escalation E-5's lesson, restated: `simulate()`'s Lumiflux kwargs having
non-default values in a unit test proves nothing about production reachability.
It is the same class as `project_scaling_stat_gaps` — pure-formula tests do not
prove a modifier reaches the calc.

So there is one test per production entry point — API, optimizer, team combo —
and each one issues a **real** request for a team with Remielle and the
otherwise-identical request without her, asserting the Lumiflux contribution is
nonzero only in the first. None of them may pass `lumiflux_specs`,
`phase_flow_windows`, or `initial_lumiflux_points`; that is the whole point.

Each rotation deliberately arms Phase Flow and then swaps away from her —
DESIGN §13.3 is explicit that a rotation which never swaps produces no windows,
and such a test would assert on an all-zero result and pass for the wrong
reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.enums import Element, Rarity, Specialty
from app.services.buff_resolver import ActiveConditions
from app.services.build_damage_service import BuildSnapshot
from app.services.combo_types import ComboStep, LuminizeStep
from app.services.modifier_loader import load_agent_modifiers
from app.services.modifiers import AttackScope, Condition
from app.services.team_calculator import TeamMember, calculate_team_combo

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

REMIELLE_HAKUSHIN_ID = 1581

# Her real, committed move names — these must match
# app/data/moves/agents/remielle.json, because the API resolves the moves DB
# from that file and the assembler reads `phase_flow_entry` off it.
ARMING_MOVE = "EX Special Attack: Ode to Dawn"
LUMINIZE_MOVE = "Ultimate: Dazzling Curtain Call"
TEAMMATE_MOVE = "Basic Attack: Mixed Flame Blend"


def _lumiflux_sum(events: list[dict[str, Any]], *kinds: str) -> float:
    """Total damage across the named event kinds. Response-level, never internals."""
    return sum(e.get("damage") or 0 for e in events if e["kind"] in kinds)


def _count(events: list[dict[str, Any]], kind: str) -> int:
    return sum(1 for e in events if e["kind"] == kind)


# ---------------------------------------------------------------------------
# 1. API — POST /api/v1/simulate
# ---------------------------------------------------------------------------


class TestApiEntryPoint:
    async def _seed(self, db_session: AsyncSession) -> dict[str, Any]:
        remielle = Agent(
            hakushin_id=REMIELLE_HAKUSHIN_ID,
            name="Remielle",
            element=Element.LUMIFLUX,
            specialty=Specialty.SUPPORT,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=900,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=120,
            base_anomaly_mastery=100,
        )
        # DRIFT HAZARD (tests-review finding m-3, hardening Task 14 -- recorded,
        # NOT fixed here). The moves loader keys on agent NAME, so this
        # synthetic agent silently binds the real `moves/agents/burnice.json`
        # entries despite its throwaway hakushin_id. Its buildup values are
        # therefore whatever that file currently says, not what this fixture
        # implies -- and project memory records that burnice.json's buildup
        # values have drifted before.
        # Left as-is deliberately: renaming the agent would leave it with no
        # moves at all and break this test, and the real fix -- authoring
        # explicit synthetic move data -- cannot be verified in an environment
        # without a database. CI runs `tests/unit` only, so this file does not
        # gate merges either way. See docs/LOG_remielle.md, Phase 2.
        burnice = Agent(
            hakushin_id=90001,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=1000,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=115,
            base_anomaly_mastery=100,
        )
        db_session.add_all([remielle, burnice])
        await db_session.flush()

        db_session.add_all(
            [
                Attack(
                    agent_id=remielle.id,
                    hakushin_skill_id=1581_02,
                    skill_key="Special",
                    name=ARMING_MOVE,
                    hit_index=0,
                    element=Element.LUMIFLUX,
                    damage_base=8000,
                    damage_growth=400,
                ),
                Attack(
                    agent_id=remielle.id,
                    hakushin_skill_id=1581_05,
                    skill_key="Ultimate",
                    name=LUMINIZE_MOVE,
                    hit_index=0,
                    element=Element.LUMIFLUX,
                    damage_base=12000,
                    damage_growth=600,
                ),
                # Big fire buildup so the teammate reliably triggers an anomaly
                # for Refringe to fire on.
                Attack(
                    agent_id=burnice.id,
                    hakushin_skill_id=90001_01,
                    skill_key="Basic",
                    name=TEAMMATE_MOVE,
                    hit_index=0,
                    element=Element.FIRE,
                    damage_base=10000,
                    damage_growth=500,
                    anomaly_buildup=10_000,
                ),
            ]
        )
        enemy = EnemyProfile(
            name="Lumiflux Dummy",
            level=60,
            defense=50,
            fire_res=0,
            anomaly_capacity_fire=100,
            anomaly_res_fire=0,
            anomaly_duration_default=10.0,
            stun_buildup_multiplier=10000,
        )
        db_session.add(enemy)
        await db_session.flush()
        return {"remielle": remielle, "burnice": burnice, "enemy": enemy}

    async def _build(self, client: AsyncClient, agent, name: str) -> str:
        resp = await client.post(
            "/api/v1/builds",
            json={"name": name, "agent_id": str(agent.id), "mindscape_level": 0},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    async def test_refringe_luminize_and_phase_flow_reach_the_api(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        seeded = await self._seed(db_session)
        rem_build = await self._build(authed_client, seeded["remielle"], "Remielle E2E")
        burn_build = await self._build(authed_client, seeded["burnice"], "Burnice E2E")

        # Arms Phase Flow, swaps out to the teammate (whose anomaly Refringes),
        # then swaps back for a Luminize-triggering Ultimate.
        with_her = {
            "team_builds": {"rem": rem_build, "burn": burn_build},
            "steps": [
                {"agent_id": "rem", "move_name": ARMING_MOVE, "conditions": []},
                {"agent_id": "burn", "move_name": TEAMMATE_MOVE, "conditions": []},
                {"agent_id": "burn", "move_name": TEAMMATE_MOVE, "conditions": []},
                {"agent_id": "rem", "move_name": LUMINIZE_MOVE, "conditions": []},
            ],
            "enemy_profile_id": str(seeded["enemy"].id),
        }
        without_her = {
            "team_builds": {"burn": burn_build},
            "steps": [
                {"agent_id": "burn", "move_name": TEAMMATE_MOVE, "conditions": []},
                {"agent_id": "burn", "move_name": TEAMMATE_MOVE, "conditions": []},
            ],
            "enemy_profile_id": str(seeded["enemy"].id),
        }

        resp_with = await authed_client.post("/api/v1/simulate", json=with_her)
        assert resp_with.status_code == 200, resp_with.text
        resp_without = await authed_client.post("/api/v1/simulate", json=without_her)
        assert resp_without.status_code == 200, resp_without.text

        events_with = resp_with.json()["events"]
        events_without = resp_without.json()["events"]

        assert _count(events_with, "lumiflux_point") > 0, (
            "her EX Special's authored `lumiflux_points` never reached the pool — "
            "Task 31's per-move application is not wired"
        )
        assert _count(events_with, "refringe") > 0, (
            "no Refringe fired for a team with a Lumiflux agent, banked points, and "
            "a teammate anomaly — the API is not passing `lumiflux_specs`"
        )
        assert _count(events_without, "refringe") == 0
        assert _lumiflux_sum(events_with, "luminize") > 0
        assert _lumiflux_sum(events_without, "luminize") == 0

        # Delta, stated as the acceptance criterion does.
        delta = _lumiflux_sum(events_with, "luminize", "phase_flow_tick") - _lumiflux_sum(
            events_without, "luminize", "phase_flow_tick"
        )
        assert delta > 0

    async def test_phase_flow_windows_come_from_the_rotations_own_swaps(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """§13.3's consequence, asserted rather than assumed: the ticks exist
        only because the rotation swaps away from her after an arming move."""
        seeded = await self._seed(db_session)
        rem_build = await self._build(authed_client, seeded["remielle"], "Remielle PF")
        burn_build = await self._build(authed_client, seeded["burnice"], "Burnice PF")
        enemy_id = str(seeded["enemy"].id)

        swaps_away = {
            "team_builds": {"rem": rem_build, "burn": burn_build},
            "steps": [
                {"agent_id": "rem", "move_name": ARMING_MOVE, "conditions": []},
                *[
                    {"agent_id": "burn", "move_name": TEAMMATE_MOVE, "conditions": []}
                    for _ in range(6)
                ],
            ],
            "enemy_profile_id": enemy_id,
        }
        never_swaps = {
            "team_builds": {"rem": rem_build, "burn": burn_build},
            "steps": [
                {"agent_id": "rem", "move_name": ARMING_MOVE, "conditions": []},
                {"agent_id": "rem", "move_name": LUMINIZE_MOVE, "conditions": []},
            ],
            "enemy_profile_id": enemy_id,
        }

        armed = (await authed_client.post("/api/v1/simulate", json=swaps_away)).json()
        stayed = (await authed_client.post("/api/v1/simulate", json=never_swaps)).json()

        assert _count(armed["events"], "phase_flow_tick") > 0
        assert _lumiflux_sum(armed["events"], "phase_flow_tick") > 0
        assert _count(stayed["events"], "phase_flow_tick") == 0


# ---------------------------------------------------------------------------
# 2. Optimizer — resolve_stateful_am_step_lists
# ---------------------------------------------------------------------------


class TestOptimizerEntryPoint:
    async def test_refringe_reaches_the_optimizer_step_lists(
        self, db_session: AsyncSession
    ) -> None:
        from app.models.build import Build
        from app.repositories.attack import AttackRepository
        from app.services.optimizer_pipeline import resolve_stateful_am_step_lists
        from app.services.snapshot_builder import build_snapshot_from_db

        remielle = Agent(
            hakushin_id=REMIELLE_HAKUSHIN_ID,
            name="Remielle",
            element=Element.LUMIFLUX,
            specialty=Specialty.SUPPORT,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=900,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=120,
            base_anomaly_mastery=100,
        )
        burnice = Agent(
            hakushin_id=90002,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=1000,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=115,
            base_anomaly_mastery=100,
        )
        db_session.add_all([remielle, burnice])
        await db_session.flush()
        db_session.add_all(
            [
                Attack(
                    agent_id=remielle.id,
                    hakushin_skill_id=158112,
                    skill_key="Special",
                    name=ARMING_MOVE,
                    hit_index=0,
                    element=Element.LUMIFLUX,
                    damage_base=8000,
                    damage_growth=400,
                ),
                Attack(
                    agent_id=burnice.id,
                    hakushin_skill_id=9000201,
                    skill_key="Basic",
                    name=TEAMMATE_MOVE,
                    hit_index=0,
                    element=Element.FIRE,
                    damage_base=10000,
                    damage_growth=500,
                    anomaly_buildup=10_000,
                ),
            ]
        )
        enemy = EnemyProfile(
            name="Optimizer Dummy",
            level=60,
            defense=50,
            fire_res=0,
            anomaly_capacity_fire=100,
            anomaly_res_fire=0,
            anomaly_duration_default=10.0,
            stun_buildup_multiplier=10000,
        )
        dps_build = Build(agent_id=burnice.id, mindscape_level=0)
        sup_build = Build(agent_id=remielle.id, mindscape_level=0)
        db_session.add_all([enemy, dps_build, sup_build])
        await db_session.flush()
        # Eager-load every relationship `build_snapshot_from_db` touches — it is
        # sync, so a lazy load inside it raises MissingGreenlet.
        for b in (dps_build, sup_build):
            await db_session.refresh(b, ["agent", "w_engine", "discs"])

        base_snapshot = build_snapshot_from_db(dps_build, dps_build.agent)
        sup_snapshot = build_snapshot_from_db(sup_build, sup_build.agent)
        assert sup_snapshot.agent_element == "lumiflux"
        assert sup_snapshot.agent_source_id == str(REMIELLE_HAKUSHIN_ID), (
            "the optimizer's snapshots must carry the agent's hakushin_id, or the "
            "assembler can never find her kit block"
        )

        # `sequence_override` is the pipeline's own parameter for a caller-supplied
        # rotation — not a Lumiflux seam. She arms, then swaps out to the DPS.
        sequence = [
            {"move_name": ARMING_MOVE, "agent_id": str(sup_build.id)},
            {"move_name": TEAMMATE_MOVE, "agent_id": str(dps_build.id)},
            {"move_name": TEAMMATE_MOVE, "agent_id": str(dps_build.id)},
        ]
        attack_repo = AttackRepository(db_session)

        with_her = await resolve_stateful_am_step_lists(
            combo=None,
            build=dps_build,
            base_build=base_snapshot,
            enemy=enemy,
            attack_repo=attack_repo,
            inventory=[],
            am_2pc_sets={},
            conditions=ActiveConditions(),
            support_builds=[sup_build],
            sequence_override=sequence,
        )
        without_her = await resolve_stateful_am_step_lists(
            combo=None,
            build=dps_build,
            base_build=base_snapshot,
            enemy=enemy,
            attack_repo=attack_repo,
            inventory=[],
            am_2pc_sets={},
            conditions=ActiveConditions(),
            support_builds=None,
            sequence_override=[s for s in sequence if s["agent_id"] == str(dps_build.id)],
        )

        assert with_her
        assert without_her
        # The wiring IS live here: her arming step resolves and the sim runs
        # with her on the team. What does *not* survive is the Lumiflux damage —
        # see `test_lumiflux_damage_does_not_survive_the_event_to_step_mapping`
        # below and the E-6 escalation in docs/LOG_remielle.md.
        labels_with = [getattr(x, "label", "") for steps in with_her.values() for x in steps]
        assert ARMING_MOVE in labels_with
        assert ARMING_MOVE not in [
            getattr(x, "label", "") for steps in without_her.values() for x in steps
        ]

    async def test_refringe_survives_the_event_to_step_mapping(
        self, db_session: AsyncSession
    ) -> None:
        """Task 35 (E-6): the Refringe half of the optimizer bar, unpinned.

        `resolve_stateful_am_step_lists` maps `refringe` events to no step of
        their own — Refringe carries no damage, it multiplies the aura. It
        survives because `anomaly_detail` now stamps `refringe_mult` and the
        mapping folds it into `procs_override`, which is proc-*equivalents*
        rather than a literal count.

        The Luminize half is still open and pinned separately below (Task 36).
        """
        from app.models.build import Build
        from app.repositories.attack import AttackRepository
        from app.services.optimizer_pipeline import resolve_stateful_am_step_lists
        from app.services.snapshot_builder import build_snapshot_from_db

        remielle = Agent(
            hakushin_id=REMIELLE_HAKUSHIN_ID,
            name="Remielle",
            element=Element.LUMIFLUX,
            specialty=Specialty.SUPPORT,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=900,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=120,
            base_anomaly_mastery=100,
        )
        burnice = Agent(
            hakushin_id=90004,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=1000,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=115,
            base_anomaly_mastery=100,
        )
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
                    hakushin_skill_id=9000401,
                    skill_key="Basic",
                    name=TEAMMATE_MOVE,
                    hit_index=0,
                    element=Element.FIRE,
                    damage_base=10000,
                    damage_growth=500,
                    anomaly_buildup=10_000,
                ),
            ]
        )
        enemy = EnemyProfile(
            name="Optimizer Delta Dummy",
            level=60,
            defense=50,
            fire_res=0,
            anomaly_capacity_fire=100,
            anomaly_res_fire=0,
            anomaly_duration_default=10.0,
            stun_buildup_multiplier=10000,
        )
        dps_build = Build(agent_id=burnice.id, mindscape_level=0)
        sup_build = Build(agent_id=remielle.id, mindscape_level=0)
        db_session.add_all([enemy, dps_build, sup_build])
        await db_session.flush()
        for b in (dps_build, sup_build):
            await db_session.refresh(b, ["agent", "w_engine", "discs"])

        base_snapshot = build_snapshot_from_db(dps_build, dps_build.agent)
        sequence = [
            {"move_name": ARMING_MOVE, "agent_id": str(sup_build.id)},
            {"move_name": TEAMMATE_MOVE, "agent_id": str(dps_build.id)},
            {"move_name": TEAMMATE_MOVE, "agent_id": str(dps_build.id)},
        ]
        attack_repo = AttackRepository(db_session)
        dps_only = [s for s in sequence if s["agent_id"] == str(dps_build.id)]

        with_her = await resolve_stateful_am_step_lists(
            combo=None,
            build=dps_build,
            base_build=base_snapshot,
            enemy=enemy,
            attack_repo=attack_repo,
            inventory=[],
            am_2pc_sets={},
            conditions=ActiveConditions(),
            support_builds=[sup_build],
            sequence_override=sequence,
        )
        without_her = await resolve_stateful_am_step_lists(
            combo=None,
            build=dps_build,
            base_build=base_snapshot,
            enemy=enemy,
            attack_repo=attack_repo,
            inventory=[],
            am_2pc_sets={},
            conditions=ActiveConditions(),
            support_builds=None,
            sequence_override=dps_only,
        )

        def _anomaly_procs(step_lists) -> float:
            return sum(
                getattr(x, "procs_override", 0) or 0
                for steps in step_lists.values()
                for x in steps
                if type(x).__name__ == "AnomalyStep"
            )

        # Refringe multiplies the teammate's anomaly damage, so a mapping that
        # preserves it shows more anomaly weight with her than without.
        assert _anomaly_procs(with_her) > _anomaly_procs(without_her), (
            "`refringe_mult` is not reaching `procs_override` — either "
            "`anomaly_detail` stopped carrying it or `_refringe_scale` is not "
            "being applied in the event→step mapping"
        )

    async def test_luminize_survives_the_event_to_step_mapping(
        self, db_session: AsyncSession
    ) -> None:
        """Task 36 (E-6/E-8): the Luminize half of the optimizer bar, unpinned.

        Was `test_luminize_does_not_survive_the_event_to_step_mapping`, an
        `xfail(strict=True)` pin owned by Task 36 and deleted by it. It now
        asserts the positive: a `LuminizeStep` reaches the optimizer's step
        lists, and the one captured from the optimized build is marked for live
        rescoring rather than carrying the simulation's frozen value.
        """
        from app.models.build import Build
        from app.repositories.attack import AttackRepository
        from app.services.optimizer_pipeline import resolve_stateful_am_step_lists
        from app.services.snapshot_builder import build_snapshot_from_db

        remielle = Agent(
            hakushin_id=REMIELLE_HAKUSHIN_ID,
            name="Remielle",
            element=Element.LUMIFLUX,
            specialty=Specialty.SUPPORT,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=900,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=120,
            base_anomaly_mastery=100,
        )
        burnice = Agent(
            hakushin_id=90005,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=1000,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=115,
            base_anomaly_mastery=100,
        )
        db_session.add_all([remielle, burnice])
        await db_session.flush()
        db_session.add_all(
            [
                Attack(
                    agent_id=remielle.id,
                    hakushin_skill_id=158115,
                    skill_key="Special",
                    name=ARMING_MOVE,
                    hit_index=0,
                    element=Element.LUMIFLUX,
                    damage_base=8000,
                    damage_growth=400,
                ),
                # The Luminize trigger. Same rotation shape the API test proves
                # produces a nonzero `luminize` total.
                Attack(
                    agent_id=remielle.id,
                    hakushin_skill_id=158116,
                    skill_key="Ultimate",
                    name=LUMINIZE_MOVE,
                    hit_index=0,
                    element=Element.LUMIFLUX,
                    damage_base=12000,
                    damage_growth=600,
                ),
                Attack(
                    agent_id=burnice.id,
                    hakushin_skill_id=9000501,
                    skill_key="Basic",
                    name=TEAMMATE_MOVE,
                    hit_index=0,
                    element=Element.FIRE,
                    damage_base=10000,
                    damage_growth=500,
                    anomaly_buildup=10_000,
                ),
            ]
        )
        enemy = EnemyProfile(
            name="Optimizer Luminize Dummy",
            level=60,
            defense=50,
            fire_res=0,
            anomaly_capacity_fire=100,
            anomaly_res_fire=0,
            anomaly_duration_default=10.0,
            stun_buildup_multiplier=10000,
        )
        dps_build = Build(agent_id=burnice.id, mindscape_level=0)
        sup_build = Build(agent_id=remielle.id, mindscape_level=0)
        db_session.add_all([enemy, dps_build, sup_build])
        await db_session.flush()
        for b in (dps_build, sup_build):
            await db_session.refresh(b, ["agent", "w_engine", "discs"])

        base_snapshot = build_snapshot_from_db(dps_build, dps_build.agent)
        # Arms, swaps out so the teammate's anomaly banks a Voidflare, swaps back
        # for the Luminize-triggering Ultimate.
        sequence = [
            {"move_name": ARMING_MOVE, "agent_id": str(sup_build.id)},
            {"move_name": TEAMMATE_MOVE, "agent_id": str(dps_build.id)},
            {"move_name": TEAMMATE_MOVE, "agent_id": str(dps_build.id)},
            {"move_name": LUMINIZE_MOVE, "agent_id": str(sup_build.id)},
        ]

        with_her = await resolve_stateful_am_step_lists(
            combo=None,
            build=dps_build,
            base_build=base_snapshot,
            enemy=enemy,
            attack_repo=AttackRepository(db_session),
            inventory=[],
            am_2pc_sets={},
            conditions=ActiveConditions(),
            support_builds=[sup_build],
            sequence_override=sequence,
        )

        lum_steps = [
            x for steps in with_her.values() for x in steps if isinstance(x, LuminizeStep)
        ]
        assert lum_steps, (
            "no LuminizeStep reached the optimizer's step lists, so the rotation's "
            "Luminize damage was dropped in translation"
        )

        # The Voidflare here was captured from the optimized build — the teammate
        # who triggered the Refringed anomaly is the DPS whose discs are being
        # enumerated — so it must be live-rescored. `frozen_damage` set would mean
        # the mapping mistook it for a support-captured one and pinned it to the
        # disc-stripped number (E-8 Finding 2).
        assert all(x.frozen_damage is None for x in lum_steps), (
            "a Voidflare captured from the optimized build was carried as a "
            "constant; it would score as though that build wore no discs"
        )
        # A zero multiplier or a zero constant factor would leave the step
        # silently worthless while still looking wired up.
        assert all(x.effective_mult_bp > 0 for x in lum_steps)
        assert all(x.constant_factor > 0 for x in lum_steps)

    async def test_a_mixed_voidflare_store_splits_by_provenance(
        self, db_session: AsyncSession
    ) -> None:
        """E-8 Finding 1 — the case no single-support fixture can reach.

        The Voidflare store is keyed by the *Lumiflux* agent, and any teammate
        who triggers a Refringed anomaly banks into it. So one store can hold a
        capture from the optimized build and a capture from another support, and
        the two must score differently: the first has to be rebuilt against every
        candidate disc set, the second is already exact.

        Option (B) in the escalation — "treat every Voidflare as DPS-captured" —
        passes every other test in this file and fails only here.
        """
        from app.models.build import Build
        from app.repositories.attack import AttackRepository
        from app.services.optimizer_pipeline import resolve_stateful_am_step_lists
        from app.services.snapshot_builder import build_snapshot_from_db

        remielle = Agent(
            hakushin_id=REMIELLE_HAKUSHIN_ID,
            name="Remielle",
            element=Element.LUMIFLUX,
            specialty=Specialty.SUPPORT,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=900,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=120,
            base_anomaly_mastery=100,
        )
        burnice = Agent(
            hakushin_id=90006,
            name="Burnice",
            element=Element.FIRE,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=1000,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=115,
            base_anomaly_mastery=100,
        )
        # The second anomaly agent — a *support* in this optimization, so the
        # optimizer never strips her discs and her Voidflare is constant.
        yanagi = Agent(
            hakushin_id=90007,
            name="Yanagi",
            element=Element.ELECTRIC,
            specialty=Specialty.ANOMALY,
            rarity=Rarity.S,
            base_hp=8000,
            base_atk=1100,
            base_def=600,
            base_crit_rate=500,
            base_crit_dmg=5000,
            base_anomaly_proficiency=118,
            base_anomaly_mastery=100,
        )
        db_session.add_all([remielle, burnice, yanagi])
        await db_session.flush()
        db_session.add_all(
            [
                Attack(
                    agent_id=remielle.id,
                    hakushin_skill_id=158117,
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
                    name=TEAMMATE_MOVE,
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
                    name="Basic Attack: Tsukuyomi",
                    hit_index=0,
                    element=Element.ELECTRIC,
                    damage_base=10000,
                    damage_growth=500,
                    anomaly_buildup=10_000,
                ),
            ]
        )
        enemy = EnemyProfile(
            name="Mixed Store Dummy",
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
        dps_build = Build(agent_id=burnice.id, mindscape_level=0)
        rem_build = Build(agent_id=remielle.id, mindscape_level=0)
        yan_build = Build(agent_id=yanagi.id, mindscape_level=0)
        db_session.add_all([enemy, dps_build, rem_build, yan_build])
        await db_session.flush()
        for b in (dps_build, rem_build, yan_build):
            await db_session.refresh(b, ["agent", "w_engine", "discs"])

        base_snapshot = build_snapshot_from_db(dps_build, dps_build.agent)
        # Arm ONCE (2 Lumiflux points, one per Refringe), then let BOTH
        # non-Lumiflux agents trigger a Refringed anomaly, so two Voidflares of
        # different provenance sit in one store, then Luminize.
        #
        # Arming exactly once is load-bearing: `ARMING_MOVE` carries
        # `phase_flow_entry`, and Phase 2's E-F3 wired Phase Flow entry to
        # `clear_voidflare_store` ("all stored Voidflares are cleared when
        # Remielle enters the Phase Flow state"). The original fixture re-armed
        # between the two teammates, so the second entry wiped the DPS-captured
        # Voidflare and only the support's survived to Luminize -- the test went
        # red the moment E-F3 landed, on a fixture problem rather than the
        # provenance split it exists to pin. Two points off one arming reaches
        # both Refringes with no entry in between.
        sequence = [
            {"move_name": ARMING_MOVE, "agent_id": str(rem_build.id)},
            {"move_name": TEAMMATE_MOVE, "agent_id": str(dps_build.id)},
            {"move_name": "Basic Attack: Tsukuyomi", "agent_id": str(yan_build.id)},
            {"move_name": LUMINIZE_MOVE, "agent_id": str(rem_build.id)},
        ]

        step_lists = await resolve_stateful_am_step_lists(
            combo=None,
            build=dps_build,
            base_build=base_snapshot,
            enemy=enemy,
            attack_repo=AttackRepository(db_session),
            inventory=[],
            am_2pc_sets={},
            conditions=ActiveConditions(),
            support_builds=[rem_build, yan_build],
            sequence_override=sequence,
        )

        lum_steps = [
            x for steps in step_lists.values() for x in steps if isinstance(x, LuminizeStep)
        ]
        assert lum_steps, "no LuminizeStep reached the step lists"

        live = [x for x in lum_steps if x.frozen_damage is None]
        frozen = [x for x in lum_steps if x.frozen_damage is not None]

        assert live, (
            "no live LuminizeStep — the Voidflare the optimized build captured was "
            "treated as a constant, so its ATK/DMG%/PEN/AP would stay at the "
            "disc-stripped values for every candidate"
        )
        assert frozen, (
            "no frozen LuminizeStep — a support-captured Voidflare was marked for "
            "live rescoring, so a support's frozen stats would be rescaled by the "
            "optimized build's discs (escalation option B)"
        )
        # Provenance follows the anomaly's element here: fire is the optimized
        # build's, electric the support's.
        assert {x.voidflare_element for x in live} == {"fire"}
        assert {x.voidflare_element for x in frozen} == {"electric"}


# ---------------------------------------------------------------------------
# 3. Team combos — calculate_team_combo → simulate_combo_steps
# ---------------------------------------------------------------------------


class TestTeamComboEntryPoint:
    """The combo path is the one §13.4 says can silently drop Luminize, so this
    asserts a `luminize` event as well as a `refringe` one.

    `calculate_team_combo` is the production entry point, but its
    `ComboEvaluationResult` carries only standard hits — no event stream. So the
    event assertions run against `simulate_combo_steps`, the function §13.4
    names and the one the structural guard covers, called with **no** Lumiflux
    arguments; and `calculate_team_combo` is exercised separately to prove the
    layer above reaches it, via the per-agent attribution it does expose.
    """

    def _enemy(self) -> EnemyProfile:
        return EnemyProfile(
            name="Combo Dummy",
            level=60,
            defense=50,
            fire_res=0,
            anomaly_capacity_fire=100,
            anomaly_res_fire=0,
            anomaly_duration_default=10.0,
            stun_buildup_multiplier=10000,
        )

    def _snapshot(self, name: str, element: str, source_id: str, ap: int) -> BuildSnapshot:
        return BuildSnapshot(
            agent_name=name,
            agent_element=element,
            agent_source_id=source_id,
            agent_specialty="anomaly",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=ap,
            agent_anomaly_mastery=100,
            modifiers=load_agent_modifiers(source_id),
        )

    def _member(self, build_id: str, name: str, element: str) -> TeamMember:
        return TeamMember(
            build_id=build_id,
            agent_name=name,
            agent_element=element,
            agent_specialty="anomaly",
            agent_faction_id=0,
        )

    def _steps(self, *, with_remielle: bool) -> list[ComboStep]:
        steps = [
            ComboStep(
                label="Arm",
                attack_id="a0",
                attack_name=ARMING_MOVE,
                scope=AttackScope.EX_SPECIAL,
                multiplier=8000,
                element="lumiflux",
                agent_id="rem",
            ),
            # Task 37 made the combo path *derive* anomalies from each step's
            # gauge instead of never emitting one. These steps are hand-built
            # rather than resolved from DB `Attack` rows, so they carry no
            # buildup unless it is set here — and without an anomaly there is
            # nothing for Remielle to Refringe and no Voidflare for the Ultimate
            # below to Luminize. Two presses, because one does not fill the
            # enemy's gauge.
            ComboStep(
                label="Teammate",
                attack_id="a1",
                attack_name=TEAMMATE_MOVE,
                scope=AttackScope.BASIC,
                multiplier=10000,
                element="fire",
                agent_id="burn",
                anomaly_buildup=6000,
            ),
            ComboStep(
                label="Teammate 2",
                attack_id="a1",
                attack_name=TEAMMATE_MOVE,
                scope=AttackScope.BASIC,
                multiplier=10000,
                element="fire",
                agent_id="burn",
                anomaly_buildup=6000,
            ),
            ComboStep(
                label="Ult",
                attack_id="a2",
                attack_name=LUMINIZE_MOVE,
                scope=AttackScope.ULTIMATE,
                multiplier=12000,
                element="lumiflux",
                agent_id="rem",
            ),
        ]
        return steps if with_remielle else [s for s in steps if s.agent_id != "rem"]

    def _snapshots(self, *, with_remielle: bool) -> dict[str, BuildSnapshot]:
        snaps = {"burn": self._snapshot("Burnice", "fire", "90005", 115)}
        if with_remielle:
            snaps["rem"] = self._snapshot(
                "Remielle", "lumiflux", str(REMIELLE_HAKUSHIN_ID), 300
            )
        return snaps

    def _simulate(self, *, with_remielle: bool):
        from app.services.anomaly_simulator import simulate_combo_steps

        snaps = self._snapshots(with_remielle=with_remielle)
        return simulate_combo_steps(
            build=snaps["burn"],
            combo_steps=self._steps(with_remielle=with_remielle),
            enemy=self._enemy(),
            member_snapshots=snaps,
            base_conditions=[Condition.ALWAYS.value],
        )

    def test_points_reach_the_combo_path(self) -> None:
        """`_StepMoveSpec` enrichment (§13.4) plus the assembler, both live: her
        EX Special's authored `lumiflux_points` land on a path that synthesises
        its own moves_db and previously could not see them."""
        with_her = self._simulate(with_remielle=True)
        without_her = self._simulate(with_remielle=False)

        events_with = [{"kind": e.kind, "damage": e.damage} for e in with_her.events]
        events_without = [{"kind": e.kind, "damage": e.damage} for e in without_her.events]

        assert _count(events_with, "lumiflux_point") > 0, (
            "`simulate_combo_steps` is either not passing `lumiflux_specs` or "
            "`_StepMoveSpec` is not carrying `lumiflux_points`"
        )
        assert _count(events_without, "lumiflux_point") == 0

    def test_refringe_and_luminize_both_reach_the_combo_path(self) -> None:
        """Task 37 (E-6): the team-combo bar, unpinned.

        Was an `xfail(strict=True)` owned by Task 37 and deleted by it. The combo
        path emitted no `anomaly` event for *any* agent, so Refringe — which fires
        only on a teammate's anomaly trigger — could never reach it, and Luminize
        needs a Voidflare that only a Refringed anomaly banks. Both now do.
        """
        with_her = self._simulate(with_remielle=True)
        events_with = [{"kind": e.kind, "damage": e.damage} for e in with_her.events]

        assert _count(events_with, "refringe") > 0
        assert _lumiflux_sum(events_with, "luminize") > 0

    def test_team_calculator_reaches_the_same_wiring(self) -> None:
        """The production layer above: `calculate_team_combo`'s per-agent
        attribution must credit her Luminize damage."""
        snaps = self._snapshots(with_remielle=True)
        result = calculate_team_combo(
            dps_member=self._member("burn", "Burnice", "fire"),
            support_members=[self._member("rem", "Remielle", "lumiflux")],
            dps_snapshot=snaps["burn"],
            enemy=self._enemy(),
            combo_steps=self._steps(with_remielle=True),
            conditions=ActiveConditions(active={Condition.ALWAYS}),
            member_snapshots=snaps,
        )
        by_agent = {c.agent_name: c.damage for c in result.by_agent}
        assert by_agent.get("Remielle", 0) > 0

        control = calculate_team_combo(
            dps_member=self._member("burn", "Burnice", "fire"),
            support_members=[],
            dps_snapshot=self._snapshots(with_remielle=False)["burn"],
            enemy=self._enemy(),
            combo_steps=self._steps(with_remielle=False),
            conditions=ActiveConditions(active={Condition.ALWAYS}),
            member_snapshots=self._snapshots(with_remielle=False),
        )
        control_by_agent = {c.agent_name: c.damage for c in control.by_agent}
        assert "Remielle" not in control_by_agent
        # Not asserted here: that her presence raises the *teammate's* damage.
        # That is Refringe, and Refringe needs a teammate anomaly, which this
        # path cannot produce — see the xfail above and E-6.
