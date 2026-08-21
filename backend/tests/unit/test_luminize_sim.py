"""Task 14 — Luminize emission in the simulator (DESIGN_remielle.md §7.2,
§9.1 tests 5 and 9).
"""

from dataclasses import replace

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.lumiflux import LumifluxSpec
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


class _MoveSpec:
    def __init__(
        self,
        buildup=0,
        duration_s=1.0,
        hits=1,
        element=None,
        scope="basic",
        triggers_luminize=False,
        luminize_mult_bp=0,
    ):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.triggers_luminize = triggers_luminize
        self.luminize_mult_bp = luminize_mult_bp


class _AgentMoves:
    def __init__(self, moves):
        self.moves = moves


def _spec():
    return LumifluxSpec(
        point_cap=4,
        voidflare_cap=3,
        refringe_ap_ratio_bp=2,
        refringe_flat_bonuses={},
        luminize_multipliers={},
        luminize_ap_bonus_bp=10,  # 0.1%/AP
        phase_flow_tick_s=5.0,
        phase_flow_duration_s=40.0,
        flight_attack_points=(0, 1, 2),
        flight_attack_mv_bp=(8130, 20320, 16250),
        flight_attack_daze_bp=(27500, 37820, 37820),
    )


def _remielle_build():
    return BuildSnapshot(
        agent_name="Remielle",
        agent_element="lumiflux",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=200,
    )


def _teammate_build(name, element, atk=1000, ap=100):
    return BuildSnapshot(
        agent_name=name,
        agent_element=element,
        agent_level=60,
        agent_base_atk=atk,
        agent_anomaly_proficiency=ap,
    )


def _enemy():
    return EnemyProfile(
        name="Luminize Target",
        level=60,
        defense=50,
        fire_res=1000,
        ice_res=2000,
        physical_res=3000,
        anomaly_capacity_fire=100,
        anomaly_capacity_ice=100,
        anomaly_capacity_physical=100,
        anomaly_duration_default=10.0,
    )


def _builds():
    return {
        "fire_agent": _teammate_build("FireGuy", "fire"),
        "ice_agent": _teammate_build("IceGuy", "ice"),
        "physical_agent": _teammate_build("PhysicalGuy", "physical"),
        "remielle": _remielle_build(),
    }


_SETUP_STEPS = [
    SimulatedAttackStep("fire_agent", "fire_hit", []),
    SimulatedAttackStep("ice_agent", "ice_hit", []),
    SimulatedAttackStep("physical_agent", "physical_hit", []),
]


def _moves_db(*, luminize_mult_bp=20_000):
    return {
        "fireguy": _AgentMoves({"fire_hit": _MoveSpec(15000, 4.0, 1, "fire")}),
        "iceguy": _AgentMoves({"ice_hit": _MoveSpec(15000, 4.0, 1, "ice")}),
        "physicalguy": _AgentMoves({"physical_hit": _MoveSpec(15000, 4.0, 1, "physical")}),
        "remielle": _AgentMoves(
            {
                "ultimate": _MoveSpec(
                    0, 1.0, 1, None, triggers_luminize=True, luminize_mult_bp=luminize_mult_bp
                ),
                # Remielle's own RES-sensitive, non-Luminize damage. Nothing in
                # this file needs it except `TestM1LuminizeResIgnoreIsScopedToLuminize`,
                # and that test's leak-side assertion is VACUOUS without it: the
                # `ultimate` above has no buildup, no element and no MV, so it
                # emits Luminize and nothing else, and every other damage event
                # in the rotation belongs to a teammate. M1's row is
                # `target: self`, so it can never enter a teammate's buff
                # context under ANY wiring -- which means "every non-Luminize
                # event is byte-identical" held trivially, over damage that was
                # structurally incapable of moving. Mutation-checked: routing
                # `luminize_res_ignore` into the generic `res_ignore` bucket
                # (i.e. reintroducing S1-A verbatim) passed the whole unit
                # suite before this move existed, and fails on it now.
                #
                # An anomaly applier is the channel available here -- this
                # fixture's `_MoveSpec` carries no MV, so `totals["standard"]`
                # is 0 by construction. Her own anomaly ticks resolve through
                # her own buff context, which is exactly the path the generic
                # bucket would leak into.
                "rem_hit": _MoveSpec(15000, 4.0, 1, "fire"),
            }
        ),
    }


class TestLuminizeFiresOncePerStoredVoidflareAgainstItsOwnRES:
    def test_three_voidflares_produce_three_instances_against_three_res_values(self):
        steps = [*_SETUP_STEPS, SimulatedAttackStep("remielle", "ultimate", [])]
        result = simulate(
            _builds(),
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=3,
        )

        luminize_events = [e for e in result.events if e.kind == "luminize"]
        assert len(luminize_events) == 3
        assert {e.element for e in luminize_events} == {"fire", "ice", "physical"}
        assert all(e.agent_id == "remielle" for e in luminize_events)
        assert all(e.damage > 0 for e in luminize_events)

        # Higher enemy RES (fire=10% < ice=20% < physical=30%) must mean
        # strictly lower res_mult and, since every other input is identical
        # across the three teammates, strictly lower damage too.
        by_element = {e.element: e for e in luminize_events}
        assert (
            by_element["fire"].detail["res_mult"]
            > by_element["ice"].detail["res_mult"]
            > by_element["physical"].detail["res_mult"]
        )
        assert by_element["fire"].damage > by_element["ice"].damage > by_element["physical"].damage

        assert result.totals["luminize"] == sum(e.damage for e in luminize_events)
        assert result.totals["total"] >= result.totals["luminize"]

    def test_damage_is_attributed_to_remielle(self):
        steps = [*_SETUP_STEPS, SimulatedAttackStep("remielle", "ultimate", [])]
        result = simulate(
            _builds(),
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=3,
        )

        assert result.per_agent_attribution["remielle"] >= result.totals["luminize"] > 0

    def test_no_luminize_without_a_triggering_move(self):
        result = simulate(
            _builds(),
            _SETUP_STEPS,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=3,
        )
        assert [e for e in result.events if e.kind == "luminize"] == []
        assert result.totals["luminize"] == 0


class TestLuminizeCannotTriggerDisorderAbloomOrVortex:
    def test_adding_the_luminize_step_changes_no_other_damage_bucket(self):
        """DESIGN §9.1 test 5: Luminize is structurally incapable of
        triggering Disorder/Abloom/Vortex. Proven by delta: the setup-only
        run's disorder/abloom/vortex totals (from the three real anomaly
        overrides) must be byte-identical to the same run with Remielle's
        Luminize step appended -- the only buckets that may change are
        `luminize` and `total`."""
        setup_only = simulate(
            _builds(),
            _SETUP_STEPS,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=3,
        )
        with_luminize = simulate(
            _builds(),
            [*_SETUP_STEPS, SimulatedAttackStep("remielle", "ultimate", [])],
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=3,
        )

        # Sanity: the setup steps really did produce real anomaly triggers
        # (and at least one disorder override), so this is a meaningful check.
        assert setup_only.totals["anomaly"] > 0
        assert setup_only.totals["disorder"] > 0

        assert with_luminize.totals["anomaly"] == setup_only.totals["anomaly"]
        assert with_luminize.totals["disorder"] == setup_only.totals["disorder"]
        assert with_luminize.totals["vortex"] == setup_only.totals["vortex"]
        assert with_luminize.totals["abloom"] == setup_only.totals["abloom"]
        assert with_luminize.totals["luminize"] > setup_only.totals["luminize"]

        assert all(e.kind != "disorder" for e in with_luminize.events if e.agent_id == "remielle")
        assert all(e.kind != "vortex" for e in with_luminize.events if e.agent_id == "remielle")
        assert all(e.kind != "abloom" for e in with_luminize.events if e.agent_id == "remielle")


class TestLuminizeEventCarriesTheOwnerRescaleInputs:
    """P-F2 / hardening Task 15. The optimizer's event->step mapping sees only
    events, so the two inputs needed to re-fold the multiplier against a
    candidate AP have to ride in the detail. Without them the mapping silently
    falls back to the plain frozen branch and the fix is inert -- which no
    scoring test would catch, because they construct steps directly.
    """

    def _run(self):
        steps = [*_SETUP_STEPS, SimulatedAttackStep("remielle", "ultimate", [])]
        return simulate(
            _builds(),
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=3,
        )

    def test_detail_carries_the_base_multiplier_and_the_ap_coefficient(self):
        result = self._run()
        luminizes = [e for e in result.events if e.kind == "luminize"]
        assert luminizes, "expected a Luminize event"
        detail = luminizes[0].detail

        # The UNFOLDED multiplier and the per-AP coefficient are what let the
        # scorer redo the fold; `luminize_effective_mult_bp` is the same fold
        # already evaluated at her stripped AP and is the rescale denominator.
        assert detail["luminize_mult_bp"] > 0
        assert detail["luminize_ap_bonus_bp"] > 0
        assert detail["luminize_effective_mult_bp"] > 0

        # And the fold has to be self-consistent, or the rescale re-bases.
        assert detail["luminize_effective_mult_bp"] >= detail["luminize_mult_bp"]

    def test_detail_names_the_agent_the_luminize_belongs_to(self):
        """The mapping gates on this equalling "dps" -- it must be the acting
        Lumiflux agent's id, not the captured teammate's."""
        result = self._run()
        luminizes = [e for e in result.events if e.kind == "luminize"]
        detail = luminizes[0].detail
        assert detail["luminize_owner_agent_id"] == luminizes[0].agent_id
        assert detail["luminize_owner_agent_id"] != detail["voidflare_captured_from"]


class TestM1LuminizeResIgnoreIsScopedToLuminize:
    """Hardening Task 19 — audit finding S1-A, inverted.

    S1-A was the leak: M1's 50% RES ignore was authored as a generic `res_ignore`
    row, which every damage path reads, so it cut enemy RES for her Ultimate,
    Chain, EX and Phase Flow ticks too. The acceptance criterion for the fix is
    that same repro with the assertion flipped — Luminize DOES move, everything
    else is byte-identical.

    Both halves matter and neither implies the other. A bucket wired nowhere
    passes "everything else unchanged" trivially while doing nothing (the
    `anomaly_mastery_excess` failure shape: a stat key that resolves, resolves
    to 0, and silently no-ops). A bucket wired into the generic path passes
    "Luminize moved" while re-opening the leak.
    """

    def _run(self, *, luminize_res_ignore):
        builds = _builds()
        if luminize_res_ignore:
            rem = builds["remielle"]
            builds["remielle"] = replace(
                rem,
                modifiers=[
                    *rem.modifiers,
                    Modifier(
                        stat="luminize_res_ignore",
                        value=luminize_res_ignore,
                        source=ModifierSource.MINDSCAPE,
                        source_label="M1: Naive Oath",
                        target=ModifierTarget.SELF,
                        conditions=(Condition.ALWAYS,),
                        scopes=(AttackScope.ALL,),
                        max_stacks=1,
                    ),
                ],
            )
        # `rem_hit` is load-bearing, not scene-setting: it is the only
        # Remielle-owned non-Luminize damage in the rotation, and therefore the
        # only thing the leak-side assertion below can actually observe. See
        # `_moves_db`. Ordered before the Ultimate so its anomaly has resolved
        # by the time Luminize fires.
        steps = [
            *_SETUP_STEPS,
            SimulatedAttackStep("remielle", "rem_hit", []),
            SimulatedAttackStep("remielle", "ultimate", []),
        ]
        return simulate(
            builds,
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            # Banked points are what let the three teammate anomalies Refringe and
            # store a Voidflare each; without them the Ultimate triggers Luminize
            # against an empty store and the fixture proves nothing.
            initial_lumiflux_points=3,
        )

    def test_luminize_damage_reflects_the_50_percent_res_ignore(self):
        off = self._run(luminize_res_ignore=0)
        on = self._run(luminize_res_ignore=5000)

        lum_off = [e for e in off.events if e.kind == "luminize"]
        lum_on = [e for e in on.events if e.kind == "luminize"]
        assert lum_off, "fixture broken: no Luminize fired"
        assert len(lum_on) == len(lum_off)

        # RESArea = 1 - enemy_res + res_ignore. Each Voidflare is scored against
        # its OWN stored element's RES, so the ratio differs per instance —
        # assert the shift per event rather than a single global factor.
        for before, after in zip(lum_off, lum_on, strict=True):
            assert after.detail["res_mult"] == before.detail["res_mult"] + 5000, (
                f"Luminize ({before.element}) RESArea did not move: "
                f"{before.detail['res_mult']} -> {after.detail['res_mult']}"
            )
            assert after.damage > before.damage

    def test_no_other_damage_in_the_same_rotation_moves(self):
        """The S1-A assertion itself. Every non-Luminize event in the identical
        rotation must be byte-identical — that is the leak, and it stays shut."""
        off = self._run(luminize_res_ignore=0)
        on = self._run(luminize_res_ignore=5000)

        def _non_luminize(res):
            return [(e.t, e.kind, e.agent_id, e.element, e.damage) for e in res.events
                    if e.kind != "luminize"]

        # The guard needs a live subject or it proves nothing. M1's row is
        # `target: self`, so teammate damage could not move under any wiring --
        # comparing only teammate events would pass a bucket wired straight
        # into the generic `res_ignore` path, which is S1-A itself. Assert the
        # rotation actually contains Remielle-owned, RES-sensitive,
        # non-Luminize damage BEFORE asserting it did not move.
        def _remielle_non_luminize(res):
            return sum(
                e.damage or 0
                for e in res.events
                if e.kind != "luminize" and e.agent_id == "remielle" and e.damage
            )

        assert _remielle_non_luminize(off) > 0, (
            "fixture broken: no Remielle-owned non-Luminize damage in the rotation, "
            "so the leak-side assertion below is vacuous"
        )

        assert _non_luminize(on) == _non_luminize(off)
        # And the totals move by exactly the Luminize delta, nothing else.
        lum_delta = sum(e.damage or 0 for e in on.events if e.kind == "luminize") - sum(
            e.damage or 0 for e in off.events if e.kind == "luminize"
        )
        assert lum_delta > 0
        assert on.totals["total"] - off.totals["total"] == lum_delta
