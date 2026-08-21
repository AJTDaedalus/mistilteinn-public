"""Task 17b — `select_when` evaluated per hit, inside the simulator.

Why per hit rather than at fetch time: `potential` is fixed for a build, so it filters once
in the repository. Stun is not — `is_enemy_stunned` starts from the enemy profile and then
flips on the rotation's own `stun_trigger` / `stun_end` markers — so a row gated on it has to
be re-checked at every hit.

The alignment assertion is the one that matters. `attack_scales` and `attack_offsets` are
positionally aligned with `step.attacks`, so a gated-off row must be skipped **at its own
index**, never pre-filtered out of the list.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.models.enums import RowCondition
from app.services.anomaly_simulator import SimulatedAttackStep, _row_is_live


@dataclass
class _Row:
    hit_index: int = 0
    param_name: str | None = None
    select_when: object | None = None


# ---- the predicate itself --------------------------------------------------


def test_an_ungated_row_always_fires() -> None:
    """NULL means unconditional. This is what makes an un-re-seeded DB degrade to today's
    behaviour rather than to silently-dropped hits."""
    assert _row_is_live(_Row(), is_stunned=True) is True
    assert _row_is_live(_Row(), is_stunned=False) is True


@pytest.mark.parametrize("stunned", [True, False])
def test_enemy_stunned_row_follows_the_state(stunned: bool) -> None:
    row = _Row(select_when=RowCondition.ENEMY_STUNNED)
    assert _row_is_live(row, is_stunned=stunned) is stunned


@pytest.mark.parametrize("stunned", [True, False])
def test_enemy_not_stunned_row_follows_the_inverse(stunned: bool) -> None:
    row = _Row(select_when=RowCondition.ENEMY_NOT_STUNNED)
    assert _row_is_live(row, is_stunned=stunned) is (not stunned)


def test_a_plain_string_is_accepted_as_well_as_the_enum() -> None:
    """Rows come back from asyncpg as strings, not enum members."""
    assert _row_is_live(_Row(select_when="enemy_stunned"), is_stunned=True) is True
    assert _row_is_live(_Row(select_when="enemy_stunned"), is_stunned=False) is False


def test_an_unrecognised_condition_fails_open() -> None:
    """Deliberate: an unknown value fires rather than vanishing.

    The loader rejects unknown conditions at author time, so a value reaching here means the
    DB holds something this build does not know — a downgrade, or a row seeded by a newer
    branch. Failing open keeps the row's damage, which is wrong in a *visible* way; failing
    closed would delete a hit silently, which is the failure this whole column is shaped to
    avoid (NULL = fires).
    """
    assert _row_is_live(_Row(select_when="enemy_is_on_fire"), is_stunned=False) is True


# ---- alignment, the part that would break quietly --------------------------


def test_scales_stay_aligned_when_a_row_is_gated_off() -> None:
    """A skipped row must not shift the arrays that index alongside `attacks`.

    Pre-filtering `step.attacks` would renumber every later row against the wrong scale —
    a channel's third tick would take the release's factor. The failure is silent because
    the output is still a plausible number, which is exactly how the `tail_s` divergence
    survived until Task 14 went looking.
    """
    rows = [
        _Row(0, "Shot"),
        _Row(1, "AP Warhead", RowCondition.ENEMY_NOT_STUNNED),
        _Row(2, "HE Warhead", RowCondition.ENEMY_STUNNED),
    ]
    step = SimulatedAttackStep(
        agent_id="dps",
        move_name="EX Special Attack: Turret",
        attacks=rows,
        attack_scales=[1.0, 0.25, 0.5],
    )
    live = [
        (idx, step.attack_scales[idx])
        for idx, row in enumerate(step.attacks)
        if _row_is_live(row, is_stunned=True)
    ]
    # HE keeps ITS OWN scale (index 2 -> 0.5), not the one it would inherit after a shift.
    assert live == [(0, 1.0), (2, 0.5)]


# ---- end to end, across a stun_trigger marker ------------------------------


@dataclass
class _MoveSpec:
    buildup: int = 0
    duration_s: float = 1.0
    hits: int = 2
    element: str = "fire"
    scope: str = "ex_special"
    channel: object | None = None
    cost_key: str | None = None
    abloom_mv_by_element: dict | None = None


class _MovesSpec:
    def __init__(self, moves: dict) -> None:
        self.moves = moves


@dataclass
class _Attack:
    """The subset of `Attack` the damage loop reads."""

    hit_index: int
    param_name: str
    select_when: object | None = None
    name: str = "EX Special Attack: Turret"
    damage_base: int = 10000
    damage_growth: int = 0
    stun_base: int = 0
    stun_growth: int = 0
    energy_gain: int = 0
    anomaly_buildup: int = 0
    element: str = "fire"
    skill_key: str = "EXSpecial"
    scope: str = "ex_special"


def _turret_rows() -> list[_Attack]:
    """One unconditional row plus the two mutually-exclusive warheads — Norma's shape."""
    return [
        _Attack(0, "Shot"),
        _Attack(1, "AP Warhead", RowCondition.ENEMY_NOT_STUNNED, damage_base=20000),
        _Attack(2, "HE Warhead", RowCondition.ENEMY_STUNNED, damage_base=40000),
    ]


def _run(*, stunned: bool):
    from app.models.build import EnemyProfile
    from app.services.anomaly_simulator import simulate
    from app.services.build_damage_service import BuildSnapshot

    build = BuildSnapshot(
        agent_name="Turret Agent",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )
    enemy = EnemyProfile(
        name="Row Condition Dummy",
        level=60,
        defense=0,
        fire_res=0,
        anomaly_capacity_fire=1000,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )
    steps: list = []
    if stunned:
        steps.append(SimulatedAttackStep("dps", "stun_trigger", []))
    steps.append(
        SimulatedAttackStep("dps", "EX Special Attack: Turret", _turret_rows())
    )
    moves_db = {"dps": _MovesSpec({"EX Special Attack: Turret": _MoveSpec()})}
    return simulate({"dps": build}, steps, enemy, moves_db)


def test_exactly_one_warhead_fires_on_each_side_of_the_marker() -> None:
    """The whole point of D-CH5, end to end.

    Three rows are present in `step.attacks` both times; the state decides which two land.
    Before this, the atomic reading fired all three on every press — that is Norma's live
    over-count, in miniature.
    """
    unstunned = _run(stunned=False)
    stunned = _run(stunned=True)

    def _hits(result) -> int:
        return len([e for e in result.events if e.kind == "hit"])

    assert _hits(unstunned) == 2
    assert _hits(stunned) == 2


def test_the_two_states_do_not_produce_the_same_damage() -> None:
    """A gate that compiles but never changes the answer is the failure mode worth pinning.

    The two warheads carry different multipliers in the real data, so the totals must move
    when the state flips. Equal totals would mean the predicate ran and selected nothing —
    which passes every structural test above.
    """
    a = _run(stunned=False).totals["total"]
    b = _run(stunned=True).totals["total"]
    assert a > 0
    assert b > 0
    assert a != b


# ---- Task 17c: one evaluation point, inherited by all three paths -----------


def test_the_predicate_lives_in_the_consumer_not_the_three_producers() -> None:
    """`select_when` is evaluated once, in `simulate()`, and every path inherits it.

    This is the structural difference from `tail_s`, which Task 14 caught diverging: that
    lived in the three *producers* (`combo_step_resolver`, `/simulate`, `optimizer_pipeline`),
    so keeping them agreeing was a standing obligation and they duly stopped. `select_when`
    is evaluated in the shared *consumer*, which every producer already calls, so agreement
    is structural rather than maintained.

    Pinned because the tempting "optimisation" — pre-filter the gated rows when building the
    step — would quietly undo it, reintroduce three copies of the rule, AND break
    `attack_scales` alignment at the same time.
    """
    import inspect

    from app.api.v1 import simulate as simulate_api
    from app.services import anomaly_simulator, combo_step_resolver, optimizer_pipeline

    assert "_row_is_live" in inspect.getsource(anomaly_simulator)

    for module in (combo_step_resolver, simulate_api, optimizer_pipeline):
        source = inspect.getsource(module)
        assert "_row_is_live" not in source, (
            f"{module.__name__} evaluates the row gate itself — it must not. One evaluation "
            "point in simulate() is what makes the three paths agree by construction."
        )
        assert "select_when" not in source, (
            f"{module.__name__} references select_when — a producer-side filter would break "
            "attack_scales alignment and fork the rule three ways."
        )


def test_a_combo_shaped_step_list_gates_identically_to_a_bundled_one() -> None:
    """The saved-combo path emits one step per row; the direct paths bundle them.

    Two encodings of one rotation must agree on which rows land — the #83 defect in its
    row-gating form.
    """
    from app.models.build import EnemyProfile
    from app.services.anomaly_simulator import simulate
    from app.services.build_damage_service import BuildSnapshot

    build = BuildSnapshot(
        agent_name="Turret Agent",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )
    enemy = EnemyProfile(
        name="Row Condition Dummy",
        level=60,
        defense=0,
        fire_res=0,
        anomaly_capacity_fire=1000,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )
    moves_db = {"dps": _MovesSpec({"EX Special Attack: Turret": _MoveSpec()})}

    bundled = [
        SimulatedAttackStep("dps", "stun_trigger", []),
        SimulatedAttackStep("dps", "EX Special Attack: Turret", _turret_rows()),
    ]
    per_row = [SimulatedAttackStep("dps", "stun_trigger", [])] + [
        SimulatedAttackStep("dps", "EX Special Attack: Turret", [row])
        for row in _turret_rows()
    ]

    a = simulate({"dps": build}, bundled, enemy, moves_db)
    b = simulate({"dps": build}, per_row, enemy, moves_db)

    assert len([e for e in a.events if e.kind == "hit"]) == 2
    assert len([e for e in b.events if e.kind == "hit"]) == 2
