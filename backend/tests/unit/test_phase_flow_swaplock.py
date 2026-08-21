"""Task 16 — Phase Flow swap-lock/unlock (DESIGN_remielle.md §7.3 P4b).

"Prefer the cheap option": the lock is a rotation-validation *warning*, not
a hard block on the swap itself (per the task brief).
"""

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.combo_step_resolver import is_phase_flow_swap_legal
from app.services.lumiflux import LumifluxSpec


def _spec():
    return LumifluxSpec(
        point_cap=4,
        voidflare_cap=3,
        refringe_ap_ratio_bp=2,
        refringe_flat_bonuses={},
        luminize_multipliers={},
        luminize_ap_bonus_bp=10,
        phase_flow_tick_s=5.0,
        phase_flow_duration_s=40.0,
        flight_attack_points=(0, 1, 2),
        flight_attack_mv_bp=(8130, 20320, 16250),
        flight_attack_daze_bp=(27500, 37820, 37820),
    )


class _MoveSpec:
    def __init__(
        self,
        buildup=0,
        duration_s=1.0,
        hits=1,
        element=None,
        scope="basic",
        multiplier_bp=0,
        phase_flow_entry=False,
    ):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.multiplier_bp = multiplier_bp
        self.phase_flow_entry = phase_flow_entry


class _AgentMoves:
    def __init__(self, moves):
        self.moves = moves


def _remielle_build():
    return BuildSnapshot(
        agent_name="Remielle",
        agent_element="lumiflux",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=200,
    )


def _dps_build():
    return BuildSnapshot(
        agent_name="DpsGuy",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )


def _enemy():
    return EnemyProfile(
        name="Swaplock Target",
        level=60,
        defense=50,
        fire_res=0,
        ice_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_ice=100,
        anomaly_duration_default=10.0,
    )


def _moves_db(*, unlock_multiplier_bp=0):
    moves = {
        "dpsguy": _AgentMoves(
            {
                "fire_hit": _MoveSpec(15000, 4.0, 1, "fire"),
                "ice_hit": _MoveSpec(15000, 4.0, 1, "ice"),
            }
        ),
    }
    if unlock_multiplier_bp:
        moves["remielle"] = _AgentMoves(
            {"phase_flow_unlock_assist": _MoveSpec(multiplier_bp=unlock_multiplier_bp)}
        )
    return moves


def _trigger_steps(n):
    """n alternating fire/ice triggers by dps -- each a genuinely new anomaly
    (different element than whatever's currently active), each eligible to
    Refringe if the pool has a point."""
    elements = ["fire_hit", "ice_hit"]
    return [SimulatedAttackStep("dps", elements[i % 2], []) for i in range(n)]


def _builds():
    return {"remielle": _remielle_build(), "dps": _dps_build()}


class TestSwapLockWarning:
    """Unit tests of the lock's inner logic, on SYNTHETIC `(0.0, 30.0)` windows.

    Read the caveat before trusting these: `lumiflux_assembly` cannot produce
    a window shaped like this, because it closes every window at exactly the
    instant the agent is swapped back to. These fixtures therefore exercise
    the legality predicate, the unlock assist, and the Chain-Attack bypass --
    but NOT the boundary condition production actually hits. Their passing
    while the lock was entirely dead on real windows is engine finding E-F2.

    `TestSwapLockOnRealAssemblerWindows` below covers the production
    boundary. Kept rather than deleted because the scenarios here (2 vs 3
    Refringes, once-per-window unlock) are still worth pinning directly; the
    class docstring is the honest label the fixtures previously lacked.
    """

    def test_swap_at_two_refringes_is_flagged(self):
        steps = [
            *_trigger_steps(2),
            SimulatedAttackStep("remielle", "switch", []),
        ]
        result = simulate(
            _builds(),
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=4,
            phase_flow_windows={"remielle": [(0.0, 30.0)]},
        )

        refringe_events = [e for e in result.events if e.kind == "refringe"]
        assert len(refringe_events) == 2

        illegal_warnings = [w for w in result.warnings if "Illegal Phase Flow swap-in" in w]
        assert len(illegal_warnings) == 1
        assert "2 Refringe" in illegal_warnings[0]

        # The swap is NOT blocked -- it's a warning, not a hard gate. (Two
        # switch events total: the implicit initial switch to "dps" plus
        # the explicit swap to "remielle".)
        switch_events = [e for e in result.events if e.kind == "switch"]
        assert len(switch_events) == 2
        assert switch_events[-1].agent_id == "remielle"

    def test_swap_at_three_refringes_is_legal_and_unlock_assist_fires(self):
        steps = [
            *_trigger_steps(3),
            SimulatedAttackStep("remielle", "switch", []),
        ]
        result = simulate(
            _builds(),
            steps,
            _enemy(),
            _moves_db(unlock_multiplier_bp=20_000),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=4,
            phase_flow_windows={"remielle": [(0.0, 30.0)]},
        )

        refringe_events = [e for e in result.events if e.kind == "refringe"]
        assert len(refringe_events) == 3

        illegal_warnings = [w for w in result.warnings if "Illegal Phase Flow swap-in" in w]
        assert illegal_warnings == []

        unlock_events = [e for e in result.events if e.kind == "phase_flow_unlock_assist"]
        assert len(unlock_events) == 1
        assert unlock_events[0].agent_id == "remielle"
        assert unlock_events[0].damage > 0

    def test_unlock_assist_fires_at_most_once_per_phase_flow(self):
        """Two legal swaps within the SAME Phase Flow window (swap out then
        back in) must only auto-fire the unlock Assist once."""
        steps = [
            *_trigger_steps(3),
            SimulatedAttackStep("remielle", "switch", []),
            SimulatedAttackStep("dps", "switch", []),
            SimulatedAttackStep("remielle", "switch", []),
        ]
        result = simulate(
            _builds(),
            steps,
            _enemy(),
            _moves_db(unlock_multiplier_bp=20_000),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=4,
            phase_flow_windows={"remielle": [(0.0, 30.0)]},
        )

        unlock_events = [e for e in result.events if e.kind == "phase_flow_unlock_assist"]
        assert len(unlock_events) == 1

    def test_chain_attack_swap_bypasses_the_lock(self):
        steps = [
            *_trigger_steps(1),  # only 1 Refringe -- would normally be illegal
            SimulatedAttackStep(
                "remielle", "switch", [], conditions=["chain_attack_swap"]
            ),
        ]
        result = simulate(
            _builds(),
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=4,
            phase_flow_windows={"remielle": [(0.0, 30.0)]},
        )

        assert [w for w in result.warnings if "Illegal Phase Flow swap-in" in w] == []
        assert [e for e in result.events if e.kind == "phase_flow_unlock_assist"] == []
        # Two switch events total: the implicit initial switch to "dps" (whoever
        # acts first) plus the explicit chain-attack swap to "remielle".
        switch_events = [e for e in result.events if e.kind == "switch"]
        assert len(switch_events) == 2
        assert switch_events[-1].agent_id == "remielle"

    def test_swap_outside_any_phase_flow_window_is_unaffected(self):
        steps = [
            *_trigger_steps(1),
            SimulatedAttackStep("remielle", "switch", []),
        ]
        result = simulate(
            _builds(),
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=4,
            # No phase_flow_windows entry for remielle at all.
        )

        assert [w for w in result.warnings if "Illegal Phase Flow swap-in" in w] == []


class TestIsPhaseFlowSwapLegalPredicate:
    def test_three_refringes_is_legal(self):
        assert is_phase_flow_swap_legal(3) is True

    def test_two_refringes_is_illegal(self):
        assert is_phase_flow_swap_legal(2) is False

    def test_zero_refringes_is_illegal(self):
        assert is_phase_flow_swap_legal(0) is False

    def test_more_than_three_is_still_legal(self):
        assert is_phase_flow_swap_legal(5) is True


class TestSwapLockOnRealAssemblerWindows:
    """Engine finding E-F2 / hardening Task 12.

    Every test above feeds `simulate()` a hand-built `(0.0, 30.0)` window.
    Production never produces one: `lumiflux_assembly` closes a window at
    *exactly the instant she is swapped back to*, so a real window's `end` and
    the swap-in under test share a timestamp. The lock's window lookup used
    `w_start <= t < w_end`, which excludes that instant -- so on every window
    the assembler can actually build, the lock was dead code.

    The second half of E-F2: the lock lived inside the explicit-`switch`
    branch, but most authored rotations swap implicitly, by simply having a
    different agent act.

    These tests build their windows *through the assembler*, so they exercise
    the boundary production really produces.
    """

    def _remielle(self):
        return BuildSnapshot(
            agent_name="Remielle",
            agent_element="lumiflux",
            agent_source_id="1581",  # loads the real shipped `lumiflux` block
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=200,
        )

    def _moves_db(self):
        return {
            "remielle": _AgentMoves(
                {
                    "EX Special Attack: Ode to Dawn": _MoveSpec(
                        0, 1.8, 1, "lumiflux", scope="ex_special", phase_flow_entry=True
                    ),
                    "idle": _MoveSpec(0, 1.0, 1, "lumiflux"),
                }
            ),
            "dpsguy": _AgentMoves({"fire_hit": _MoveSpec(15000, 4.0, 1, "fire")}),
        }

    _STEPS = None  # built per-test below

    def _steps(self):
        return [
            # Arms Phase Flow while she is on field.
            SimulatedAttackStep("remielle", "EX Special Attack: Ode to Dawn", []),
            # Swapping away opens the window at her last t_end.
            SimulatedAttackStep("dps", "fire_hit", []),
            # Swapping back CLOSES the window at exactly this instant, and is
            # the swap the lock has to judge. Implicit -- no "switch" step.
            SimulatedAttackStep("remielle", "idle", []),
        ]

    def _assembled(self):
        from app.services.lumiflux_assembly import assemble_lumiflux_inputs

        builds = {"remielle": self._remielle(), "dps": _dps_build()}
        return builds, assemble_lumiflux_inputs(builds, self._steps(), self._moves_db())

    def test_the_assembler_really_closes_the_window_at_the_swap_in(self):
        """Establishes the premise the rest of the class rests on, so a change
        in assembler convention shows up here rather than as a silent pass."""
        _, inputs = self._assembled()
        windows = inputs.phase_flow_windows["remielle"]
        assert len(windows) == 1
        w_start, w_end = windows[0]
        # The window is closed by the swap-back, not by the 40s duration.
        assert w_end < w_start + inputs.specs["remielle"].phase_flow_duration_s

    def test_illegal_swap_in_at_the_window_boundary_is_flagged(self):
        """Red pre-fix: with `t < w_end` no window matched at the swap-in, so
        no warning was ever emitted on an assembler-produced window."""
        builds, inputs = self._assembled()
        result = simulate(
            builds,
            self._steps(),
            _enemy(),
            self._moves_db(),
            lumiflux_specs=inputs.specs,
            phase_flow_windows=inputs.phase_flow_windows,
            initial_lumiflux_points=0,
        )
        assert any("Illegal Phase Flow swap-in" in w for w in result.warnings), (
            f"expected a swap-lock warning; got {result.warnings}"
        )

    def test_chain_attack_swap_still_bypasses_at_the_boundary(self):
        """The bypass has to survive the boundary change -- otherwise the fix
        would turn a legal Chain Attack swap into a spurious warning."""
        builds, inputs = self._assembled()
        steps = self._steps()
        steps[-1] = SimulatedAttackStep(
            "remielle", "idle", [], conditions=["chain_attack_swap"]
        )
        result = simulate(
            builds,
            steps,
            _enemy(),
            self._moves_db(),
            lumiflux_specs=inputs.specs,
            phase_flow_windows=inputs.phase_flow_windows,
            initial_lumiflux_points=0,
        )
        assert not any("Illegal Phase Flow swap-in" in w for w in result.warnings)
