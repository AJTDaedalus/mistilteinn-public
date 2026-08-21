"""One press of a `sequential` move costs one press worth of clock (issue #83).

`duration_s` and `buildup` are both authored as whole-**move** totals
(`MODIFIER_AUTHORING.md`), so both need the same divisor when a step is one button
press of a multi-press move. #79 gave the gauge its divisor and left the clock alone,
so a single-tap press charged the entire chain's animation: Jane's 6-row Dancing Blades
took 1.8s *per press*, and a 6-press cycle spanned 10.8s instead of 1.8s. Every combo
and every optimizer rotation resolves sequential moves single-tap, so that was the
production path, not a corner case.

The consequence is not cosmetic. Anomaly decay, the 3s per-attribute re-trigger
cooldown, buff windows and passive energy accrual are all read off this clock, so the
*same rotation* produced a different anomaly proc count depending only on how its steps
were encoded — which is exactly the class of error the crossval harness could not see
while it bundled every row into one step.

The load-bearing assertion here is therefore not a duration number: it is that the two
encodings of one rotation agree. A harness that can only run one shape cannot notice
when they stop agreeing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.models.enums import HitMode
from app.services.anomaly_simulator import (
    SimulatedAttackStep,
    _is_sequential_slice,
    _step_duration_s,
    simulate,
)
from app.services.build_damage_service import BuildSnapshot


@dataclass
class _Spec:
    buildup: int | None = 60000
    duration_s: float = 1.8
    hits: int = 6
    element: str = "physical"
    scope: str = "basic"


class _Moves:
    def __init__(self, moves: dict) -> None:
        self.moves = moves


@dataclass
class _Row:
    """Enough of an `Attack` row for the step loop."""

    hit_mode: str
    hit_index: int
    name: str = "Basic Attack: Test Chain"
    skill_key: str = "Basic"
    damage_base: int = 3000
    damage_growth: int = 300
    stun_base: int = 0
    stun_growth: int = 0
    energy_gain: int = 0
    anomaly_buildup: int = 0
    element: str = "physical"
    variant_label: str | None = None
    param_name: str | None = None


class _Enemy:
    name = "Dummy"
    level = 60
    defense = 500
    physical_res = 0
    fire_res = 0
    ice_res = 0
    electric_res = 0
    ether_res = 0
    stun_dmg_taken_ratio = 5000
    anomaly_capacity_physical = 300
    anomaly_res_physical = 0
    anomaly_duration_default = 10.0


_MOVE = "Basic Attack: Test Chain"
_SEQ_ROWS = [_Row(hit_mode=HitMode.SEQUENTIAL, hit_index=i) for i in range(6)]
_ATOMIC_ROWS = [_Row(hit_mode=HitMode.ATOMIC, hit_index=i) for i in range(6)]


def _build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Tester",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=115,
        modifiers=[],
    )


def _run(steps: list[SimulatedAttackStep]):
    return simulate(
        builds={"dps": _build()},
        steps=steps,
        enemy=_Enemy(),
        moves_db={"tester": _Moves({_MOVE: _Spec()})},
    )


def _bundled(cycles: int) -> list[SimulatedAttackStep]:
    return [
        SimulatedAttackStep(agent_id="dps", move_name=_MOVE, attacks=_SEQ_ROWS, conditions=[])
        for _ in range(cycles)
    ]


def _single_tap(cycles: int) -> list[SimulatedAttackStep]:
    return [
        SimulatedAttackStep(agent_id="dps", move_name=_MOVE, attacks=[row], conditions=[])
        for _ in range(cycles)
        for row in _SEQ_ROWS
    ]


def test_one_press_costs_one_press_of_clock() -> None:
    step = SimulatedAttackStep(agent_id="dps", move_name=_MOVE, attacks=[_SEQ_ROWS[0]])
    assert _is_sequential_slice(step, _Spec())
    assert _step_duration_s(step, _Spec()) == 1.8 / 6


def test_a_bundled_step_still_costs_the_whole_move() -> None:
    step = SimulatedAttackStep(agent_id="dps", move_name=_MOVE, attacks=_SEQ_ROWS)
    assert not _is_sequential_slice(step, _Spec())
    assert _step_duration_s(step, _Spec()) == 1.8


def test_an_atomic_move_is_never_sliced() -> None:
    """An atomic move's authored `hits` is an animation-hit count that legitimately
    exceeds its row count, and every row lands in one step — slicing there would be the
    same defect in the other direction."""
    step = SimulatedAttackStep(agent_id="dps", move_name=_MOVE, attacks=[_ATOMIC_ROWS[0]])
    assert not _is_sequential_slice(step, _Spec())
    assert _step_duration_s(step, _Spec()) == 1.8


def test_no_spec_falls_back_to_one_second() -> None:
    step = SimulatedAttackStep(agent_id="dps", move_name=_MOVE, attacks=[_SEQ_ROWS[0]])
    assert _step_duration_s(step, None) == 1.0


def test_both_encodings_of_the_same_rotation_take_the_same_time() -> None:
    # `approx`: the bundled path computes each hit as `t_start + (i+1)*(d/hits)` while
    # the single-tap path accumulates `d/hits` per step, so they differ in the last bit
    # of a float and in nothing else.
    bundled, single = _run(_bundled(3)), _run(_single_tap(3))
    assert [e.t for e in single.events if e.kind == "hit"] == pytest.approx(
        [e.t for e in bundled.events if e.kind == "hit"]
    )


def test_both_encodings_of_the_same_rotation_deal_the_same_damage() -> None:
    """The invariant the crossval fixtures rest on: their golden values were derived
    against the bundled shape, and the harness now runs the single-tap one."""
    bundled, single = _run(_bundled(3)), _run(_single_tap(3))
    assert dict(single.totals) == dict(bundled.totals)


def test_both_encodings_trigger_the_same_anomalies() -> None:
    """The specific way the un-sliced clock lied: a longer rotation cleared the 3s
    re-trigger cooldown more often, so single-tap invented anomaly procs the identical
    bundled rotation never got."""
    bundled, single = _run(_bundled(3)), _run(_single_tap(3))
    kinds = lambda r: sorted(e.kind for e in r.events)  # noqa: E731
    assert kinds(single) == kinds(bundled)
