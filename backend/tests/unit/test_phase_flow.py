"""Task 15 — Phase Flow expected-value scheduler (DESIGN_remielle.md §7.3).
"""

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.lumiflux import LumifluxSpec, PhaseFlowState
from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget


# NOTE: the flight-attack tuples below are *synthetic scheduler fixtures*, not
# the shipped kit values -- they are the Lv.1 bases, kept because the arithmetic
# in this file's assertions is written against them. The shipped Lv.12 tuples
# and the tick's absolute damage are pinned in `test_phase_flow_tick_pin.py`;
# do not treat these as a source of truth for Remielle's real multipliers.
def _spec(*, tick_s=5.0, point_cap=4, mv=(8130, 20320, 16250), points=(0, 1, 2)):
    return LumifluxSpec(
        point_cap=point_cap,
        voidflare_cap=3,
        refringe_ap_ratio_bp=2,
        refringe_flat_bonuses={},
        luminize_multipliers={},
        luminize_ap_bonus_bp=10,
        phase_flow_tick_s=tick_s,
        phase_flow_duration_s=40.0,
        flight_attack_points=points,
        flight_attack_mv_bp=mv,
        flight_attack_daze_bp=(27500, 37820, 37820),
    )


def _remielle_build(modifiers=None):
    return BuildSnapshot(
        agent_name="Remielle",
        agent_element="lumiflux",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=200,
        modifiers=modifiers or [],
    )


def _enemy():
    return EnemyProfile(
        name="Phase Flow Target",
        level=60,
        defense=50,
        anomaly_duration_default=10.0,
    )


class _MoveSpec:
    def __init__(self, buildup=0, duration_s=1.0, hits=1, element=None, scope="basic"):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope


class _AgentMoves:
    def __init__(self, moves):
        self.moves = moves


def _no_op_step():
    return [SimulatedAttackStep("remielle", "noop", [])]


def _no_op_moves_db():
    return {"remielle": _AgentMoves({"noop": _MoveSpec(0, 0.1, 1, None)})}


def _ticks(result):
    return [e for e in result.events if e.kind == "phase_flow_tick"]


class TestPhaseFlowTicksAreDeterministic:
    def test_ticks_land_at_exactly_5_10_15s(self):
        builds = {"remielle": _remielle_build()}
        result = simulate(
            builds,
            _no_op_step(),
            _enemy(),
            _no_op_moves_db(),
            lumiflux_specs={"remielle": _spec()},
            phase_flow_windows={"remielle": [(0.0, 16.0)]},
        )
        ticks = _ticks(result)
        assert [t.t for t in ticks] == [5.0, 10.0, 15.0]

    def test_deterministic_across_repeated_runs(self):
        builds = {"remielle": _remielle_build()}
        results = [
            simulate(
                builds,
                _no_op_step(),
                _enemy(),
                _no_op_moves_db(),
                lumiflux_specs={"remielle": _spec()},
                phase_flow_windows={"remielle": [(0.0, 16.0)]},
            )
            for _ in range(3)
        ]
        damages = [[t.damage for t in _ticks(r)] for r in results]
        assert damages[0] == damages[1] == damages[2]
        assert all(d > 0 for d in damages[0])

    def test_no_ticks_without_a_phase_flow_window(self):
        builds = {"remielle": _remielle_build()}
        result = simulate(
            builds,
            _no_op_step(),
            _enemy(),
            _no_op_moves_db(),
            lumiflux_specs={"remielle": _spec()},
        )
        assert _ticks(result) == []

    def test_no_ticks_without_a_registered_spec(self):
        builds = {"remielle": _remielle_build()}
        result = simulate(
            builds,
            _no_op_step(),
            _enemy(),
            _no_op_moves_db(),
            phase_flow_windows={"remielle": [(0.0, 16.0)]},
        )
        assert _ticks(result) == []


class TestPhaseFlowEVIsTheMeanOfTheThreeFlightAttacks:
    def test_ev_mv_is_the_rounded_mean(self):
        builds = {"remielle": _remielle_build()}
        result = simulate(
            builds,
            _no_op_step(),
            _enemy(),
            _no_op_moves_db(),
            lumiflux_specs={"remielle": _spec(mv=(8130, 20320, 16250))},
            phase_flow_windows={"remielle": [(0.0, 6.0)]},
        )
        ticks = _ticks(result)
        assert len(ticks) == 1
        # mean(8130, 20320, 16250) = 14900.0 -> round -> 14900
        assert ticks[0].detail["ev_mv_bp"] == 14900

    def test_ev_points_accumulate_and_cap(self):
        """E[points] = mean(0, 1, 2) = 1 per tick (guide's own worked
        example); three ticks against a point_cap of 2 must cap, not
        overflow to 3."""
        builds = {"remielle": _remielle_build()}
        result = simulate(
            builds,
            _no_op_step(),
            _enemy(),
            _no_op_moves_db(),
            lumiflux_specs={"remielle": _spec(point_cap=2)},
            phase_flow_windows={"remielle": [(0.0, 16.0)]},
        )
        ticks = _ticks(result)
        assert len(ticks) == 3
        assert all(t.detail["ev_points"] == 1 for t in ticks)
        assert result.final_lumiflux_points == 2

        point_events = [e for e in result.events if e.kind == "lumiflux_point"]
        assert [e.detail["points"] for e in point_events] == [1, 2, 2]


class TestPhaseFlowDamageResolvesOffField:
    def test_teammates_team_modifier_applies_teammates_active_modifier_does_not(self):
        teammate = BuildSnapshot(
            agent_name="Support",
            agent_element="fire",
            agent_level=60,
            agent_base_atk=1000,
            modifiers=[
                Modifier(
                    stat="dmg_bonus",
                    value=3000,
                    source=ModifierSource.CORE_SKILL,
                    source_label="Team DMG buff",
                    target=ModifierTarget.TEAM,
                ),
                Modifier(
                    stat="dmg_bonus",
                    value=9000,
                    source=ModifierSource.CORE_SKILL,
                    source_label="Active-only DMG buff",
                    target=ModifierTarget.ACTIVE,
                ),
            ],
        )
        builds_plain = {"remielle": _remielle_build()}
        builds_with_team = {"remielle": _remielle_build(), "support": teammate}

        plain = simulate(
            builds_plain,
            _no_op_step(),
            _enemy(),
            _no_op_moves_db(),
            lumiflux_specs={"remielle": _spec()},
            phase_flow_windows={"remielle": [(0.0, 6.0)]},
        )
        with_team = simulate(
            builds_with_team,
            _no_op_step(),
            _enemy(),
            _no_op_moves_db(),
            lumiflux_specs={"remielle": _spec()},
            phase_flow_windows={"remielle": [(0.0, 6.0)]},
        )

        plain_dmg = _ticks(plain)[0].damage
        team_dmg = _ticks(with_team)[0].damage
        # +30% TEAM dmg_bonus applied, +90% ACTIVE dmg_bonus was NOT --
        # a 90%-inflated result would be far larger than a 30%-inflated one.
        assert team_dmg == round(plain_dmg * 1.3)


class TestPhaseFlowState:
    def test_energy_regen_is_on_field(self):
        assert PhaseFlowState().is_on_field_for("energy_regen") is True

    def test_feathered_fate_persistence_is_off_field(self):
        assert PhaseFlowState().is_on_field_for("feathered_fate_persistence") is False

    def test_modifier_merge_is_off_field(self):
        assert PhaseFlowState().is_on_field_for("modifier_merge") is False

    def test_flight_attack_scope_is_special(self):
        assert PhaseFlowState().flight_attack_scope == "special"

    def test_unknown_system_raises(self):
        with pytest.raises(ValueError, match="no classification"):
            PhaseFlowState().is_on_field_for("some_future_system")


class TestPhaseFlowTicksSeePhaseFlowGatedBuffs:
    """Engine finding E-F5(c) / hardening Task 13.

    Ticks resolved under a bare `{ALWAYS}` condition set, so every
    PHASE_FLOW_ACTIVE-gated buff was invisible to the very damage that only
    exists because Phase Flow is active. That silently excluded Remielle's own
    modifier [4] (+18% squad DMG on Phase Flow entry) and hardening Task 5's
    M1 team Attribute-Anomaly-DMG row from her flight-attack damage.
    """

    def _phase_flow_gated_buff(self, value):
        return Modifier(
            stat="dmg_bonus",
            value=value,
            source=ModifierSource.CORE_SKILL,
            source_label="Phase Flow squad DMG",
            target=ModifierTarget.TEAM,
            conditions=(Condition.PHASE_FLOW_ACTIVE,),
        )

    def _tick_damage(self, modifiers):
        result = simulate(
            {"remielle": _remielle_build(modifiers)},
            _no_op_step(),
            _enemy(),
            _no_op_moves_db(),
            lumiflux_specs={"remielle": _spec()},
            phase_flow_windows={"remielle": [(0.0, 6.0)]},
        )
        ticks = _ticks(result)
        assert len(ticks) == 1
        return ticks[0].damage

    def test_a_phase_flow_gated_buff_reaches_tick_damage(self):
        plain = self._tick_damage([])
        buffed = self._tick_damage([self._phase_flow_gated_buff(1800)])
        # +18% -- the real value of her modifier [4] at skill level 12.
        assert buffed == round(plain * 1.18)

    def test_an_unrelated_gate_still_does_not_reach_tick_damage(self):
        """Control: the fix adds PHASE_FLOW_ACTIVE specifically, not a blanket
        'resolve everything' -- a buff gated on something else stays out."""
        gated_elsewhere = Modifier(
            stat="dmg_bonus",
            value=9000,
            source=ModifierSource.CORE_SKILL,
            source_label="Stun-only DMG buff",
            target=ModifierTarget.TEAM,
            conditions=(Condition.ENEMY_STUNNED,),
        )
        assert self._tick_damage([gated_elsewhere]) == self._tick_damage([])
