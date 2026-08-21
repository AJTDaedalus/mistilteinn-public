"""Tasks 29/30 — `assemble_lumiflux_inputs` (DESIGN_remielle.md §13.2/§13.3).

The assembler is the single producer of `simulate()`'s two Lumiflux kwargs, so
what matters here is that it is (a) correct for the Lumiflux team, (b) a cheap
no-op for every other team, and (c) *loud* rather than silent when a Lumiflux
agent has no spec — that specific silence is how the subsystem shipped inert.
"""

from __future__ import annotations

import logging

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import (
    SimulatedAttackStep,
    _SyntheticAttack,
    simulate,
    walk_step_timeline,
)
from app.services.build_damage_service import BuildSnapshot
from app.services.lumiflux_assembly import assemble_lumiflux_inputs
from app.services.modifiers import AttackScope

REMIELLE_ID = "1581"


class _MoveStub:
    def __init__(self, *, duration_s: float = 1.0, phase_flow_entry: bool = False) -> None:
        self.duration_s = duration_s
        self.phase_flow_entry = phase_flow_entry


class _SimMoveSpec:
    """A move spec rich enough for `simulate()` to resolve a real hit from."""

    def __init__(
        self,
        *,
        duration_s: float = 1.0,
        hits: int = 1,
        element: str = "fire",
        scope=None,
        buildup: int = 0,
        phase_flow_entry: bool = False,
    ) -> None:
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.buildup = buildup
        self.consolidated = False
        self.phase_flow_entry = phase_flow_entry


class _AgentMovesStub:
    def __init__(self, moves: dict) -> None:
        self.moves = moves


def _remielle(**kwargs) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Remielle",
        agent_element="lumiflux",
        agent_source_id=kwargs.pop("agent_source_id", REMIELLE_ID),
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=200,
        **kwargs,
    )


def _teammate(name: str = "Ally", element: str = "fire") -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element=element,
        agent_level=60,
        agent_base_atk=1000,
    )


def _step(agent_id: str, move_name: str) -> SimulatedAttackStep:
    return SimulatedAttackStep(agent_id=agent_id, move_name=move_name, attacks=[])


class TestSpecs:
    def test_team_without_a_lumiflux_agent_yields_no_specs(self) -> None:
        builds = {"a": _teammate("A"), "b": _teammate("B", "ice")}
        inputs = assemble_lumiflux_inputs(builds, [], {})
        assert inputs.specs == {}
        assert inputs.is_empty

    def test_non_lumiflux_team_does_no_kit_io(self, monkeypatch) -> None:
        calls: list[str] = []

        def _record(source_id: str) -> None:
            calls.append(source_id)

        monkeypatch.setattr("app.services.lumiflux_assembly.load_lumiflux_spec", _record)
        assemble_lumiflux_inputs({"a": _teammate("A")}, [], {})
        assert calls == []

    def test_lumiflux_agent_yields_exactly_one_entry_keyed_by_agent_id(self) -> None:
        builds = {"rem": _remielle(), "ally": _teammate()}
        inputs = assemble_lumiflux_inputs(builds, [], {})
        assert set(inputs.specs) == {"rem"}
        assert inputs.specs["rem"].point_cap == 4

    def test_spec_is_the_one_the_loader_returns(self) -> None:
        from app.services.lumiflux_loader import load_lumiflux_spec

        inputs = assemble_lumiflux_inputs({"rem": _remielle()}, [], {})
        assert inputs.specs["rem"] == load_lumiflux_spec(REMIELLE_ID)

    def test_lumiflux_agent_with_no_source_id_warns_and_is_skipped(self, caplog) -> None:
        builds = {"rem": _remielle(agent_source_id="")}
        with caplog.at_level(logging.WARNING):
            inputs = assemble_lumiflux_inputs(builds, [], {})
        assert inputs.specs == {}
        assert "no loadable" in caplog.text
        assert "Remielle" in caplog.text

    def test_lumiflux_agent_with_an_unknown_source_id_warns_rather_than_raising(
        self, caplog
    ) -> None:
        builds = {"rem": _remielle(agent_source_id="99999")}
        with caplog.at_level(logging.WARNING):
            inputs = assemble_lumiflux_inputs(builds, [], {})
        assert inputs.specs == {}
        assert "validate_kits" in caplog.text

    def test_two_lumiflux_agents_each_get_their_own_entry(self) -> None:
        builds = {"rem": _remielle(), "rem2": _remielle()}
        inputs = assemble_lumiflux_inputs(builds, [], {})
        assert set(inputs.specs) == {"rem", "rem2"}


class TestPhaseFlowWindows:
    """DESIGN §13.3 — entry on the swap-out *after* an arming move, exit at
    `min(entry + phase_flow_duration_s, next time she acts)`."""

    def _moves(self) -> dict:
        return {
            "remielle": _AgentMovesStub(
                {
                    "EX Special Attack: Ode to Dawn": _MoveStub(
                        duration_s=1.8, phase_flow_entry=True
                    ),
                    "Basic Attack: Leap": _MoveStub(duration_s=1.2),
                }
            ),
            "ally": _AgentMovesStub({"Hit": _MoveStub(duration_s=2.0)}),
        }

    def _builds(self) -> dict:
        return {"rem": _remielle(), "ally": _teammate()}

    def test_arm_then_swap_out_opens_one_full_length_window(self) -> None:
        steps = [
            _step("rem", "EX Special Attack: Ode to Dawn"),
            _step("ally", "Hit"),
            _step("ally", "Hit"),
        ]
        inputs = assemble_lumiflux_inputs(self._builds(), steps, self._moves())
        assert list(inputs.phase_flow_windows) == ["rem"]
        (start, end) = inputs.phase_flow_windows["rem"][0]
        # She acts from t=0 for 1.8s, then the implicit switch to the ally
        # charges 1.0s: the window opens when she stops acting.
        assert start == pytest.approx(1.8)
        assert end == pytest.approx(1.8 + 40.0)

    def test_never_swapping_away_produces_no_window(self) -> None:
        steps = [
            _step("rem", "EX Special Attack: Ode to Dawn"),
            _step("rem", "Basic Attack: Leap"),
        ]
        inputs = assemble_lumiflux_inputs(self._builds(), steps, self._moves())
        assert inputs.phase_flow_windows == {}

    def test_no_arming_move_produces_no_window(self) -> None:
        steps = [_step("rem", "Basic Attack: Leap"), _step("ally", "Hit")]
        inputs = assemble_lumiflux_inputs(self._builds(), steps, self._moves())
        assert inputs.phase_flow_windows == {}

    def test_window_closes_early_when_she_acts_again(self) -> None:
        steps = [
            _step("rem", "EX Special Attack: Ode to Dawn"),
            _step("ally", "Hit"),
            _step("rem", "Basic Attack: Leap"),
        ]
        inputs = assemble_lumiflux_inputs(self._builds(), steps, self._moves())
        (start, end) = inputs.phase_flow_windows["rem"][0]
        # ally acts at 1.8 (+1.0 switch charge) for 2.0s → she re-enters at 4.8,
        # well short of the 40s natural expiry.
        assert start == pytest.approx(1.8)
        assert end == pytest.approx(4.8)
        assert end - start < 40.0

    def test_two_cycles_produce_two_non_overlapping_windows(self) -> None:
        steps = [
            _step("rem", "EX Special Attack: Ode to Dawn"),
            _step("ally", "Hit"),
            _step("rem", "EX Special Attack: Ode to Dawn"),
            _step("ally", "Hit"),
            _step("ally", "Hit"),
        ]
        inputs = assemble_lumiflux_inputs(self._builds(), steps, self._moves())
        windows = inputs.phase_flow_windows["rem"]
        assert len(windows) == 2
        assert windows[0][1] <= windows[1][0]

    def test_every_window_has_positive_width(self) -> None:
        steps = [
            _step("rem", "EX Special Attack: Ode to Dawn"),
            _step("ally", "Hit"),
            _step("rem", "Basic Attack: Leap"),
            _step("rem", "EX Special Attack: Ode to Dawn"),
            _step("ally", "Hit"),
        ]
        inputs = assemble_lumiflux_inputs(self._builds(), steps, self._moves())
        for start, end in inputs.phase_flow_windows["rem"]:
            assert end > start

    def test_explicit_switch_step_arms_the_same_window(self) -> None:
        steps = [
            _step("rem", "EX Special Attack: Ode to Dawn"),
            _step("ally", "switch"),
            _step("ally", "Hit"),
        ]
        inputs = assemble_lumiflux_inputs(self._builds(), steps, self._moves())
        assert inputs.phase_flow_windows["rem"][0][0] == pytest.approx(1.8)

    def test_a_teammate_arming_move_does_not_open_her_window(self) -> None:
        moves = self._moves()
        moves["ally"] = _AgentMovesStub({"Hit": _MoveStub(duration_s=2.0, phase_flow_entry=True)})
        steps = [_step("ally", "Hit"), _step("rem", "Basic Attack: Leap")]
        inputs = assemble_lumiflux_inputs(self._builds(), steps, moves)
        assert inputs.phase_flow_windows == {}

    def test_no_windows_without_a_spec(self, caplog) -> None:
        """A Lumiflux agent skipped for a missing spec must not still get
        windows — `simulate()` reads `lumiflux_specs[agent_id]` for the tick."""
        builds = {"rem": _remielle(agent_source_id=""), "ally": _teammate()}
        steps = [
            _step("rem", "EX Special Attack: Ode to Dawn"),
            _step("ally", "Hit"),
        ]
        with caplog.at_level(logging.WARNING):
            inputs = assemble_lumiflux_inputs(builds, steps, self._moves())
        assert inputs.phase_flow_windows == {}


class TestTimelineAgreesWithSimulate:
    """`walk_step_timeline` mirrors `simulate()`'s clock. This is the assertion
    that makes the mirror safe: the two live in one module, and any drift in the
    step loop's timing rules fails here rather than silently mis-scheduling
    Phase Flow ticks against windows derived from the other clock.
    """

    def _enemy(self):
        return EnemyProfile(
            name="Clock Target",
            level=60,
            defense=50,
            anomaly_duration_default=10.0,
        )

    def _attack(self, name: str):
        return _SyntheticAttack(id=None, name=name, element="fire", skill_key="Basic")

    def _fixture(self):
        builds = {
            "rem": _remielle(),
            "ally": _teammate(),
        }
        moves_db = {
            "remielle": _AgentMovesStub(
                {
                    "EX Special Attack: Ode to Dawn": _SimMoveSpec(
                        duration_s=1.8, element="lumiflux", scope=AttackScope.EX_SPECIAL
                    ),
                    "Basic Attack: Leap": _SimMoveSpec(
                        duration_s=1.2, hits=4, element="lumiflux", scope=AttackScope.BASIC
                    ),
                }
            ),
            "ally": _AgentMovesStub(
                {"Hit": _SimMoveSpec(duration_s=2.0, element="fire", scope=AttackScope.BASIC)}
            ),
        }
        steps = [
            SimulatedAttackStep("rem", "EX Special Attack: Ode to Dawn", [self._attack("ex")]),
            SimulatedAttackStep("ally", "Hit", [self._attack("hit")]),
            SimulatedAttackStep("ally", "switch", []),
            SimulatedAttackStep("rem", "Basic Attack: Leap", [self._attack("leap")]),
            SimulatedAttackStep("ally", "Hit", [self._attack("hit")]),
        ]
        return builds, steps, moves_db

    def test_switch_event_times_match_the_walk(self) -> None:
        builds, steps, moves_db = self._fixture()
        result = simulate(builds, steps, self._enemy(), moves_db)
        simulated = [e.t for e in result.events if e.kind == "switch"]
        walked = [
            timing.t_switch
            for timing in walk_step_timeline(builds, steps, moves_db)
            if timing.t_switch is not None
        ]
        assert simulated == pytest.approx(walked)

    def test_last_hit_lands_at_the_last_steps_end(self) -> None:
        # `t_hit = t_start + (i+1) * duration_s/hits`, so the final hit of the
        # final step lands exactly on that step's `t_end`.
        builds, steps, moves_db = self._fixture()
        result = simulate(builds, steps, self._enemy(), moves_db)
        last_hit = max(e.t for e in result.events if e.kind == "hit")
        timings = walk_step_timeline(builds, steps, moves_db)
        assert last_hit == pytest.approx(timings[-1].t_end)

    def test_redundant_switch_advances_neither_clock(self) -> None:
        builds, _, moves_db = self._fixture()
        steps = [
            SimulatedAttackStep("rem", "Basic Attack: Leap", [self._attack("leap")]),
            SimulatedAttackStep("rem", "switch", []),  # already active
            SimulatedAttackStep("rem", "Basic Attack: Leap", [self._attack("leap")]),
        ]
        result = simulate(builds, steps, self._enemy(), moves_db)
        timings = walk_step_timeline(builds, steps, moves_db)
        # Only the initial None->rem switch, which charges no time. The explicit
        # redundant one emits nothing at all, in both clocks.
        assert [e.t for e in result.events if e.kind == "switch"] == [0.0]
        assert [t.t_switch for t in timings if t.t_switch is not None] == [0.0]
        assert timings[1].t_end == timings[1].t_start  # the redundant switch
        assert timings[-1].t_end == pytest.approx(2.4)
        assert max(e.t for e in result.events if e.kind == "hit") == pytest.approx(2.4)

    def test_marker_steps_advance_neither_clock(self) -> None:
        builds, _, moves_db = self._fixture()
        steps = [
            SimulatedAttackStep("rem", "Basic Attack: Leap", [self._attack("leap")]),
            SimulatedAttackStep("rem", "stun_trigger", []),
            SimulatedAttackStep("rem", "stun_end", []),
            SimulatedAttackStep("rem", "Basic Attack: Leap", [self._attack("leap")]),
        ]
        result = simulate(builds, steps, self._enemy(), moves_db)
        timings = walk_step_timeline(builds, steps, moves_db)
        assert timings[-1].t_end == pytest.approx(2.4)
        assert max(e.t for e in result.events if e.kind == "hit") == pytest.approx(2.4)

    def test_unknown_move_uses_the_same_one_second_fallback(self) -> None:
        builds, _, moves_db = self._fixture()
        steps = [SimulatedAttackStep("rem", "Not In The Moves DB", [self._attack("x")])]
        result = simulate(builds, steps, self._enemy(), moves_db)
        timings = walk_step_timeline(builds, steps, moves_db)
        assert timings[-1].t_end == pytest.approx(1.0)
        assert max(e.t for e in result.events if e.kind == "hit") == pytest.approx(1.0)

    def test_windows_line_up_with_the_ticks_they_schedule(self) -> None:
        """End-to-end for the clock: windows derived by the assembler, fed
        straight back into `simulate()`, put ticks inside the interval when she
        is genuinely off field."""
        builds, steps, moves_db = self._fixture()
        moves_db["remielle"].moves["EX Special Attack: Ode to Dawn"].phase_flow_entry = True
        inputs = assemble_lumiflux_inputs(builds, steps, moves_db)
        assert inputs.phase_flow_windows["rem"]
        result = simulate(
            builds,
            steps,
            self._enemy(),
            moves_db,
            lumiflux_specs=inputs.specs,
            phase_flow_windows=inputs.phase_flow_windows,
        )
        ticks = [e.t for e in result.events if e.kind == "phase_flow_tick"]
        for tick in ticks:
            assert any(start < tick < end for start, end in inputs.phase_flow_windows["rem"])


class TestMisconfiguredElementWarnsLoudly:
    """Pipeline finding P-F3 / hardening Task 16.

    An agent with a `lumiflux` kit block but a non-lumiflux DB element has its
    whole Lumiflux subsystem skipped silently by the element predicate. That is
    production's current state -- `alembic upgrade` does not change an agent's
    element, only a re-seed does -- and silence on exactly that condition is
    escalation E-5's failure mode.
    """

    def _build(self, element: str):
        from app.services.build_damage_service import BuildSnapshot

        return BuildSnapshot(
            agent_name="Remielle",
            agent_element=element,
            agent_source_id="1581",  # real shipped kit, so a spec loads
            agent_level=60,
            agent_base_atk=1000,
        )

    def _assemble(self, element: str):
        from app.services.lumiflux_assembly import assemble_lumiflux_inputs

        return assemble_lumiflux_inputs({"rem": self._build(element)}, [], {})

    def _reset_warn_state(self):
        from app.services import lumiflux_assembly

        lumiflux_assembly._warned_element_mismatch.clear()

    def test_warns_once_naming_the_agent_both_elements_and_the_fix(self, caplog):
        self._reset_warn_state()
        with caplog.at_level("WARNING"):
            self._assemble("physical")

        messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert len(messages) == 1, messages
        message = messages[0]
        assert "Remielle" in message
        assert "physical" in message  # the wrong element it actually has
        assert "lumiflux" in message  # the element it should have
        assert "seed_db" in message  # the fix

    def test_warns_only_once_per_process(self, caplog):
        self._reset_warn_state()
        with caplog.at_level("WARNING"):
            self._assemble("physical")
            self._assemble("physical")
            self._assemble("physical")
        assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1

    def test_silent_when_the_element_is_correct(self, caplog):
        self._reset_warn_state()
        with caplog.at_level("WARNING"):
            inputs = self._assemble("lumiflux")
        assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == []
        assert "rem" in inputs.specs

    def test_silent_for_an_ordinary_agent_with_no_lumiflux_block(self, caplog):
        """Control: the warning keys off having a loadable block, not merely
        off being non-lumiflux -- otherwise every agent in the game trips it."""
        from app.services.build_damage_service import BuildSnapshot
        from app.services.lumiflux_assembly import assemble_lumiflux_inputs

        self._reset_warn_state()
        ordinary = BuildSnapshot(
            agent_name="Ellen",
            agent_element="ice",
            agent_source_id="1191",
            agent_level=60,
            agent_base_atk=1000,
        )
        with caplog.at_level("WARNING"):
            assemble_lumiflux_inputs({"ellen": ordinary}, [], {})
        assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == []


class TestAssemblerResolvesTheFlux:
    """P-F1 / hardening Task 17: the assembler is where the flux is resolved,
    so all three `simulate()` call sites get it without any of them
    remembering to -- the same reason the assembler exists at all (E-5)."""

    def _build(self, element, source_id=""):
        from app.services.build_damage_service import BuildSnapshot

        return BuildSnapshot(
            agent_name=element.title(),
            agent_element=element,
            agent_source_id=source_id,
            agent_level=60,
            agent_base_atk=1000,
        )

    def _inputs(self, builds):
        from app.services.lumiflux_assembly import assemble_lumiflux_inputs

        return assemble_lumiflux_inputs(builds, [], {})

    def test_flux_is_the_next_slot_cyclic(self):
        # Slot order: rem -> jane -> lucy -> (wraps to rem). Remielle's flux is
        # the NEXT slot's element, i.e. Jane's physical.
        builds = {
            "rem": self._build("lumiflux", "1581"),
            "jane": self._build("physical"),
            "lucy": self._build("fire"),
        }
        assert self._inputs(builds).fluxed_elements == {"rem": "physical"}

    def test_last_slot_wraps_to_the_first(self):
        builds = {
            "jane": self._build("physical"),
            "lucy": self._build("fire"),
            "rem": self._build("lumiflux", "1581"),
        }
        assert self._inputs(builds).fluxed_elements == {"rem": "physical"}

    def test_assembler_flux_matches_the_primitive(self):
        """Pins the assumption the assembler makes -- that `builds`' iteration
        order IS team-slot order -- against `resolve_fluxed_element` itself."""
        from app.services.lumiflux import AgentRef, resolve_fluxed_element

        builds = {
            "rem": self._build("lumiflux", "1581"),
            "jane": self._build("physical"),
            "lucy": self._build("fire"),
        }
        ordered = [
            AgentRef(build_id=aid, element=b.agent_element) for aid, b in builds.items()
        ]
        expected = resolve_fluxed_element(ordered, ordered[0])
        assert self._inputs(builds).fluxed_elements["rem"] == expected

    def test_solo_lumiflux_has_no_flux(self):
        assert self._inputs({"rem": self._build("lumiflux", "1581")}).fluxed_elements == {}

    def test_non_lumiflux_agents_never_get_a_flux(self):
        builds = {
            "jane": self._build("physical"),
            "lucy": self._build("fire"),
        }
        assert self._inputs(builds).fluxed_elements == {}


class TestFluxOverrideBeatsTheDerivedValue:
    """Review follow-up to hardening Task 17.

    Task 17 resolved the flux in the assembler so all three `simulate()` call
    sites got it. But the API *separately* resolves override-or-derived for its
    `fluxed_element` response field -- so an assembler that only ever derived
    would put the echoed value and the used value back out of step the moment a
    caller supplied an override. That is the narrow form of P-F1 itself: a
    response claiming an element the calc did not use.

    DESIGN §5.3: an explicit override always wins.
    """

    def _build(self, element, source_id=""):
        from app.services.build_damage_service import BuildSnapshot

        return BuildSnapshot(
            agent_name=element.title(),
            agent_element=element,
            agent_source_id=source_id,
            agent_level=60,
            agent_base_atk=1000,
        )

    def _builds(self):
        return {
            "rem": self._build("lumiflux", "1581"),
            "jane": self._build("physical"),
            "lucy": self._build("fire"),
        }

    def _flux(self, overrides):
        from app.services.lumiflux_assembly import assemble_lumiflux_inputs

        return assemble_lumiflux_inputs(
            self._builds(), [], {}, fluxed_overrides=overrides
        ).fluxed_elements

    def test_derived_value_when_no_override(self):
        assert self._flux(None) == {"rem": "physical"}

    def test_override_wins_over_the_derived_value(self):
        assert self._flux({"rem": "ice"}) == {"rem": "ice"}

    def test_override_for_a_non_lumiflux_agent_is_ignored(self):
        """Only agents with a loaded spec get a flux at all, so an override
        aimed at a teammate cannot invent one for them."""
        assert self._flux({"jane": "ice"}) == {"rem": "physical"}

    def test_an_override_of_lumiflux_itself_falls_back_to_derived(self):
        """There is no `lumiflux_dmg` bucket by design, so fluxing *to*
        Lumiflux is meaningless -- the schema rejects it at the API, and the
        assembler refuses to honour it if it ever arrives another way."""
        assert self._flux({"rem": "lumiflux"}) == {"rem": "physical"}
