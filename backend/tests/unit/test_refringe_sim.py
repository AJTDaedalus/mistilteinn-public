"""Task 11 — Refringe hook in the simulator: consumption, aura snapshot, and
inheritance (DESIGN_remielle.md §7.1, §9.1 tests 8 and 11).

Scenario shared by most tests here: Velina (wind, VORTEX_ALLOWLIST) applies
Windswept, then a Fire agent overrides it -- disorder fires on the just-ended
wind aura and, because ``old_elem == "wind"``, so does a vortex -- while a
third, non-contributing Lumiflux build supplies the Refringe coefficient a
real Remielle kit JSON will supply once Task 18 lands (`lumiflux_specs` is
this test's stand-in for that JSON).
"""

from typing import ClassVar

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.lumiflux import LumifluxSpec, refringe_coefficient

_LUMIFLUX_AP = 200
_RATIO_BP = 2  # 0.02%/AP (guide line 68)


class _MoveSpec:
    def __init__(
        self,
        buildup=0,
        duration_s=1.0,
        hits=1,
        element=None,
        scope="basic",
        abloom_mv_by_element=None,
        abloom_ap_scaled=False,
        abloom_requires_mindscape=0,
        abloom_mv_multiplier_bp=10_000,
        consolidated=False,
        polarity_disorder=False,
        polarity_additional_mv=0,
    ):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.abloom_mv_by_element = abloom_mv_by_element
        self.abloom_ap_scaled = abloom_ap_scaled
        self.abloom_requires_mindscape = abloom_requires_mindscape
        self.abloom_mv_multiplier_bp = abloom_mv_multiplier_bp
        self.consolidated = consolidated
        self.polarity_disorder = polarity_disorder
        self.polarity_additional_mv = polarity_additional_mv


class _AgentMoves:
    def __init__(self, moves):
        self.moves = moves


def _spec(*, ratio_bp=_RATIO_BP, point_cap=4):
    return LumifluxSpec(
        point_cap=point_cap,
        voidflare_cap=3,
        refringe_ap_ratio_bp=ratio_bp,
        refringe_flat_bonuses={},
        luminize_multipliers={},
        luminize_ap_bonus_bp=10,
        phase_flow_tick_s=5.0,
        phase_flow_duration_s=40.0,
        flight_attack_points=(0, 1, 2),
        flight_attack_mv_bp=(8130, 20320, 16250),
        flight_attack_daze_bp=(27500, 37820, 37820),
    )


def _expected_coefficient_bp(ap=_LUMIFLUX_AP, ratio_bp=_RATIO_BP):
    return refringe_coefficient(_spec(ratio_bp=ratio_bp), ap, flat_bonus_bp=0)


def _lumiflux_build(agent_id="Remielle", ap=_LUMIFLUX_AP):
    return BuildSnapshot(
        agent_name=agent_id,
        agent_element="lumiflux",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=ap,
    )


def _velina_build():
    return BuildSnapshot(
        agent_name="Velina",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1500,
        agent_anomaly_proficiency=200,
    )


def _fire_build():
    return BuildSnapshot(
        agent_name="FireGuy",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )


def _enemy():
    return EnemyProfile(
        name="Refringe Target",
        level=60,
        defense=50,
        wind_res=0,
        fire_res=0,
        anomaly_capacity_wind=100,
        anomaly_capacity_fire=100,
        anomaly_duration_default=10.0,
    )


def _moves_db():
    return {
        "velina": _AgentMoves(
            {
                "wind_hit": _MoveSpec(15000, 4.0, 1, "wind"),
                "abloom_move": _MoveSpec(0, 1.0, 1, "fire", abloom_mv_by_element={"fire": 20_000}),
            }
        ),
        "fireguy": _AgentMoves({"fire_hit": _MoveSpec(15000, 4.0, 1, "fire")}),
    }


def _builds():
    return {
        "velina": _velina_build(),
        "fire_agent": _fire_build(),
        "remielle": _lumiflux_build(),
    }


_TWO_STEP = [
    SimulatedAttackStep("velina", "wind_hit", []),  # Windswept aura -- may Refringe
    SimulatedAttackStep("fire_agent", "fire_hit", []),  # disorder+vortex on old (wind) aura
]

_THREE_STEP = [
    *_TWO_STEP,
    SimulatedAttackStep("velina", "abloom_move", []),  # fractions the (new) fire aura
]


class TestRefringeConsumptionAndSnapshot:
    def test_consumes_one_point_per_trigger_and_snapshots_disorder(self):
        result = simulate(
            _builds(),
            _TWO_STEP,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=2,
        )

        refringe_events = [e for e in result.events if e.kind == "refringe"]
        assert len(refringe_events) == 2
        assert all(e.agent_id == "remielle" for e in refringe_events)
        assert refringe_events[0].detail["triggering_agent_id"] == "velina"
        assert refringe_events[1].detail["triggering_agent_id"] == "fire_agent"
        assert refringe_events[0].detail["points_remaining"] == 1
        assert refringe_events[1].detail["points_remaining"] == 0
        assert result.final_lumiflux_points == 0

        expected_mult = 10000 + _expected_coefficient_bp()
        assert refringe_events[0].detail["refringe_mult"] == expected_mult
        assert refringe_events[1].detail["refringe_mult"] == expected_mult

        disorder_events = [e for e in result.events if e.kind == "disorder"]
        assert len(disorder_events) == 1
        formulas = disorder_events[0].detail["zone_formulas"]
        assert "refringe" in formulas
        assert formulas["refringe"]["result_bp"] == expected_mult

    def test_no_refringe_when_pool_empty(self):
        result = simulate(
            _builds(),
            _TWO_STEP,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=0,
        )

        assert [e for e in result.events if e.kind == "refringe"] == []
        assert result.final_lumiflux_points == 0
        disorder_events = [e for e in result.events if e.kind == "disorder"]
        assert len(disorder_events) == 1
        assert "refringe" not in disorder_events[0].detail["zone_formulas"]

    def test_no_refringe_without_a_registered_lumiflux_spec(self):
        """Points banked but no `lumiflux_specs` entry (Task 18's kit JSON not
        authored yet in this run) -- the hook must no-op, not guess a coefficient."""
        result = simulate(
            _builds(),
            _TWO_STEP,
            _enemy(),
            _moves_db(),
            lumiflux_specs={},
            initial_lumiflux_points=2,
        )

        assert [e for e in result.events if e.kind == "refringe"] == []
        assert result.final_lumiflux_points == 2

    def test_never_fires_on_the_lumiflux_agents_own_anomaly(self):
        """Defensive: even if something forced buildup onto her own attack
        (she has none in reality -- DESIGN §7.1), the hook must not consume a
        point or Refringe her own trigger."""
        builds = {"remielle": _lumiflux_build()}
        moves_db = {
            "remielle": _AgentMoves({"own_hit": _MoveSpec(15000, 1.0, 1, "fire")}),
        }
        steps = [SimulatedAttackStep("remielle", "own_hit", [])]

        result = simulate(
            builds,
            steps,
            _enemy(),
            moves_db,
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=1,
        )

        assert [e for e in result.events if e.kind == "refringe"] == []
        assert result.final_lumiflux_points == 1
        anomaly_events = [e for e in result.events if e.kind == "anomaly"]
        assert len(anomaly_events) == 1


class TestRefringeVortexInheritance:
    def test_vortex_damage_is_larger_when_the_overridden_aura_was_refringed(self):
        refringed = simulate(
            _builds(),
            _TWO_STEP,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=2,
        )
        unrefringed = simulate(
            _builds(),
            _TWO_STEP,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=0,
        )

        vortex_with = [e for e in refringed.events if e.kind == "vortex"]
        vortex_without = [e for e in unrefringed.events if e.kind == "vortex"]
        assert len(vortex_with) >= 1
        assert len(vortex_without) >= 1
        assert vortex_with[0].damage > vortex_without[0].damage


class TestRefringeAbloomInheritance:
    def test_abloom_fractions_the_refringed_fire_aura(self):
        """Isolates the *fire* aura's own Refringe (its trigger is the 2nd
        point consumption) from the wind aura's: seeding exactly 1 point means
        only the wind trigger Refringes and the fire aura Abloom fractions is
        plain; seeding 2 means the fire aura is Refringed too."""
        fire_aura_unrefringed = simulate(
            _builds(),
            _THREE_STEP,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=1,
        )
        fire_aura_refringed = simulate(
            _builds(),
            _THREE_STEP,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=2,
        )

        assert fire_aura_unrefringed.totals["abloom"] > 0
        assert fire_aura_refringed.totals["abloom"] > 0
        assert fire_aura_refringed.totals["abloom"] > fire_aura_unrefringed.totals["abloom"]


class TestRefringeAttributionUnmoved:
    def test_two_agent_attribution_shares_unmoved_by_refringe(self):
        """DESIGN §9.1 test 11: Refringe is a uniform post-hoc multiplier, so
        the buildup-share split between two contributors must stay (almost)
        identical whether or not the trigger was Refringed. `almost` because
        the multiplier is threaded through each contributor's own independent
        integer floor-division chain (DESIGN_remielle.md §7.1's zone), so a
        few-ULP drift from that -- not from Refringe favoring one contributor
        -- is expected; a large shift would mean the hook broke attribution."""
        enemy = EnemyProfile(
            name="F-20 Attribution Target",
            level=60,
            defense=50,
            ice_res=0,
            anomaly_capacity_ice=100,
            anomaly_duration_default=10.0,
        )
        builds = {
            "agent_a": BuildSnapshot(
                agent_name="agent_a",
                agent_element="ice",
                agent_level=60,
                agent_base_atk=3000,
                agent_anomaly_proficiency=300,
            ),
            "agent_b": BuildSnapshot(
                agent_name="agent_b",
                agent_element="ice",
                agent_level=60,
                agent_base_atk=200,
                agent_anomaly_proficiency=50,
            ),
            "remielle": _lumiflux_build(),
        }
        moves_db = {
            "agent_a": _AgentMoves({"hit_a": _MoveSpec(8000, 1.0, 1, "ice")}),
            "agent_b": _AgentMoves({"hit_b": _MoveSpec(2000, 0.5, 1, "ice")}),
        }
        steps = [
            SimulatedAttackStep("agent_a", "hit_a", []),
            SimulatedAttackStep("agent_b", "hit_b", []),
        ]

        refringed = simulate(
            builds,
            steps,
            enemy,
            moves_db,
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=1,
        )
        unrefringed = simulate(
            builds,
            steps,
            enemy,
            moves_db,
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=0,
        )

        assert [e for e in refringed.events if e.kind == "refringe"]
        assert [e for e in unrefringed.events if e.kind == "refringe"] == []

        share_with = refringed.per_agent_attribution["agent_a"] / (
            refringed.per_agent_attribution["agent_a"] + refringed.per_agent_attribution["agent_b"]
        )
        share_without = unrefringed.per_agent_attribution["agent_a"] / (
            unrefringed.per_agent_attribution["agent_a"]
            + unrefringed.per_agent_attribution["agent_b"]
        )
        assert share_with == pytest.approx(share_without, rel=1e-3)


class TestPolarityDisorderInheritsRefringe:
    """Engine finding E-F4 / hardening Task 9.

    `calculate_disorder_damage` takes a `refringe_mult` kwarg defaulting to
    10000 (neutral). Four of the five call sites in `anomaly_simulator` pass
    it; the Polarity Disorder site did not, so a Polarity Disorder fired on a
    Refringed aura silently dropped Remielle's entire contribution to it --
    the one anomaly type in the engine that ignored her.

    Yanagi is the only agent with Polarity Disorder, and Yanagi + Remielle is
    a headline team, so this was not a corner case.
    """

    _YANAGI_AP = 300

    def _yanagi_build(self):
        return BuildSnapshot(
            agent_name="Yanagi",
            agent_element="electric",
            agent_level=60,
            agent_base_atk=1500,
            agent_anomaly_proficiency=self._YANAGI_AP,
        )

    def _builds(self):
        return {
            "fire_agent": _fire_build(),
            "yanagi": self._yanagi_build(),
            "remielle": _lumiflux_build(),
        }

    def _moves_db(self):
        return {
            "fireguy": _AgentMoves({"fire_hit": _MoveSpec(15000, 4.0, 1, "fire")}),
            "yanagi": _AgentMoves(
                {
                    "polarity_ex": _MoveSpec(
                        15000,
                        1.5,
                        2,
                        "electric",
                        consolidated=True,
                        polarity_disorder=True,
                    )
                }
            ),
        }

    def _enemy(self):
        return EnemyProfile(
            name="Polarity Refringe Target",
            level=60,
            defense=50,
            fire_res=0,
            electric_res=0,
            anomaly_capacity_fire=100,
            anomaly_capacity_electric=100,
            anomaly_duration_default=10.0,
        )

    _STEPS: ClassVar[list] = [
        # Fire aura, Refringed by Remielle if she has a point to spend...
        SimulatedAttackStep("fire_agent", "fire_hit", []),
        # ...then Yanagi's polarity EX fires Polarity Disorder on that aura.
        SimulatedAttackStep("yanagi", "polarity_ex", []),
    ]

    def _polarity(self, *, points: int):
        result = simulate(
            self._builds(),
            self._STEPS,
            self._enemy(),
            self._moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=points,
        )
        events = [
            e
            for e in result.events
            if e.kind == "disorder" and e.detail.get("disorder_kind") == "polarity"
        ]
        assert len(events) == 1, f"expected exactly one polarity event, got {len(events)}"
        return events[0]

    def test_polarity_carries_the_refringe_zone(self):
        """The direct assertion: pre-fix there is no `refringe` zone at all."""
        event = self._polarity(points=2)
        formulas = event.detail["zone_formulas"]
        assert "refringe" in formulas, (
            "Polarity Disorder dropped refringe_mult -- the zone is absent entirely"
        )
        assert formulas["refringe"]["result_bp"] == 10000 + _expected_coefficient_bp()

    def test_unrefringed_polarity_has_no_refringe_zone(self):
        """Control: with no points to spend, no Refringe happens and the
        neutral default is correctly reported as absent."""
        formulas = self._polarity(points=0).detail["zone_formulas"]
        assert "refringe" not in formulas

    def test_refringed_polarity_is_the_coefficient_times_the_unrefringed_one(self):
        """Magnitude, not just presence -- guards a zone that is reported but
        multiplied in wrong."""
        refringed = self._polarity(points=2).damage
        plain = self._polarity(points=0).damage
        mult = 10000 + _expected_coefficient_bp()

        assert plain > 0
        assert refringed > plain
        # Polarity's base is two independently-truncated terms (the -85%
        # ATK x MV part and the flat AP term), so the Refringe factor does
        # not survive as a bit-exact integer ratio -- 11934 / 11472 = 1.04027
        # against a target of 1.0400. Assert the ratio to within 0.1%, which
        # is two orders of magnitude tighter than the ~4% effect itself and
        # far tighter than the 0% the pre-fix code produced.
        assert refringed / plain == pytest.approx(mult / 10000, rel=1e-3)


class TestRefringeResolvesUnderHerOwnEquipperConditions:
    """Engine finding E-F5(a) / hardening Task 13.

    `_resolve_refringe` resolved Remielle's buffs under the *acting
    teammate's* condition set, which carries `equipper_is_<teammate>`. Every
    `equipper_is_lumiflux`-gated row she owns was therefore invisible on the
    Refringe path -- Feathered Fate's 4pc, and (after hardening Task 3) both
    of Ode of Resurrected Wings' Refringe rows.
    """

    def _remielle_with(self, modifiers):
        return BuildSnapshot(
            agent_name="Remielle",
            agent_element="lumiflux",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=_LUMIFLUX_AP,
            modifiers=modifiers,
        )

    def _coefficient(self, modifiers):
        builds = {
            "velina": _velina_build(),
            "fire_agent": _fire_build(),
            "remielle": self._remielle_with(modifiers),
        }
        result = simulate(
            builds,
            _TWO_STEP,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=2,
        )
        refringes = [e for e in result.events if e.kind == "refringe"]
        assert refringes
        return refringes[0].detail["refringe_coefficient_bp"]

    def test_an_equipper_gated_row_of_hers_applies(self):
        from app.services.modifiers import (
            Condition,
            Modifier,
            ModifierSource,
            ModifierTarget,
        )

        gated = Modifier(
            stat="refringe_flat_bonus_bp",
            value=2000,
            source=ModifierSource.MINDSCAPE,
            source_label="M2: Refringe Coefficient +20%",
            target=ModifierTarget.SELF,
            conditions=(Condition.EQUIPPER_IS_LUMIFLUX,),
        )
        # The trigger is Velina (wind) or the fire agent -- never Remielle --
        # so pre-fix the condition set said `equipper_is_wind`/`_fire` and this
        # row was dropped.
        assert self._coefficient([gated]) == self._coefficient([]) + 2000


class TestRefringeOnBurstReapplication:
    """A burst anomaly re-applied onto its own live aura is a *trigger*, so it
    consumes a Lumiflux point like any other.

    DESIGN_remielle.md §7.1 sets the unit explicitly — "1 point per trigger",
    and consumption fires "at the anomaly-trigger site ... if the triggering
    agent is not the Lumiflux agent and the enemy holds >=1 point". The question
    could not arise before burst re-triggers resolved damage at all (they were
    swallowed by the same-element `continue`), so nothing pinned it. It is
    pinned here rather than left to the next reader's inference.
    """

    _STEPS: ClassVar = [SimulatedAttackStep("velina", "wind_hit", []) for _ in range(3)]

    def test_each_windswept_reapplication_consumes_its_own_point(self):
        result = simulate(
            _builds(),
            self._STEPS,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=3,
        )

        # Three crossings 4s apart: the 3s per-attribute CD is clear each time and
        # the 20s Windswept aura is still live, so #2 and #3 are re-applications.
        assert len([e for e in result.events if e.kind == "anomaly_tick"]) == 3
        assert [e.kind for e in result.events if e.kind in ("anomaly", "refresh")] == [
            "anomaly",
            "refresh",
            "refresh",
        ]

        refringes = [e for e in result.events if e.kind == "refringe"]
        assert len(refringes) == 3
        assert [e.detail["points_remaining"] for e in refringes] == [2, 1, 0]
        assert result.final_lumiflux_points == 0

    def test_reapplication_refringe_stops_at_an_empty_pool(self):
        """The pool gates re-procs exactly as it gates first triggers — the extra
        instances must not conjure coefficient out of an empty bank."""
        result = simulate(
            _builds(),
            self._STEPS,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=1,
        )

        assert len([e for e in result.events if e.kind == "anomaly_tick"]) == 3
        assert len([e for e in result.events if e.kind == "refringe"]) == 1
        assert result.final_lumiflux_points == 0
