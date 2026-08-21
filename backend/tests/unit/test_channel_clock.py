"""Task 10a — a channel occupies real clock, and its ticks land at `tick_s` cadence.

The defect this closes is #83's, in a different mode: a 4s Burnice spray applied its whole
fire gauge in one instant, so anomaly decay, the 3s per-attribute re-trigger CD, buff
windows and passive energy accrual all read off a clock the move never actually occupied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.data.loaders.moves import ChannelSpec, MoveBuildupSpec
from app.models.enums import HitMode
from app.services.anomaly_simulator import _step_duration_s
from app.services.combo_types import ComboStep
from app.services.modifiers import AttackScope


@dataclass
class _Row:
    hit_mode: Any = HitMode.CHANNEL
    hit_index: int = 0


@dataclass
class _Step:
    attacks: list[Any]
    channel_s: float | None = None


def _spec(**over) -> MoveBuildupSpec:
    channel = ChannelSpec(
        min_s=0.0,
        max_s=4.0,
        default_s=2.0,
        tick_s=0.5,
        tick_mv_basis="whole_channel",
        nominal_s=2.5,
        roles={"Continuous Spray DMG Multiplier": "tick"},
    )
    base = {"duration_s": 1.2, "hits": 2, "channel": channel}
    base.update(over)
    return MoveBuildupSpec(**base)


# ---- _step_duration_s -----------------------------------------------------


def test_channel_clock_is_hold_plus_the_non_held_tail() -> None:
    """`duration_s` on a channel move is the tail (entry + release), not the whole move."""
    assert _step_duration_s(_Step([_Row()], channel_s=2.0), _spec()) == pytest.approx(3.2)


def test_a_longer_hold_costs_more_clock() -> None:
    spec = _spec()
    short = _step_duration_s(_Step([_Row()], channel_s=1.0), spec)
    long = _step_duration_s(_Step([_Row()], channel_s=4.0), spec)
    assert long - short == pytest.approx(3.0)


def test_channel_without_a_requested_length_falls_back_to_default_s() -> None:
    """A step carrying no channel_s must not silently become a zero-length hold."""
    assert _step_duration_s(_Step([_Row()], channel_s=None), _spec()) == pytest.approx(3.2)


def test_zero_length_hold_is_the_tail_alone() -> None:
    assert _step_duration_s(_Step([_Row()], channel_s=0.0), _spec()) == pytest.approx(1.2)


def test_an_out_of_range_hold_is_clamped_on_the_clock_too() -> None:
    """The clock must agree with the resolver, which clamps rather than 404s."""
    assert _step_duration_s(_Step([_Row()], channel_s=99.0), _spec()) == pytest.approx(5.2)


def test_a_non_channel_move_is_untouched() -> None:
    spec = MoveBuildupSpec(duration_s=1.8, hits=6)
    assert _step_duration_s(_Step([_Row(hit_mode=HitMode.ATOMIC)]), spec) == pytest.approx(1.8)


def test_a_channel_spec_with_no_channel_s_field_on_the_step_is_untouched() -> None:
    """The direct paths build steps that predate the field; they must not crash or change."""

    @dataclass
    class _OldStep:
        attacks: list[Any]

    assert _step_duration_s(_OldStep([_Row()]), _spec()) == pytest.approx(3.2)


# ---- ComboStep.duration_s -------------------------------------------------


def test_combo_step_duration_defaults_to_none() -> None:
    """Every existing caller builds ComboSteps without it and must be unaffected."""
    step = ComboStep(
        label="x",
        attack_id="a",
        attack_name="n",
        scope=AttackScope.BASIC,
        multiplier=1000,
    )
    assert step.duration_s is None


# ---- the two paths must agree ---------------------------------------------


@pytest.mark.asyncio
async def test_expanded_steps_sum_to_the_direct_paths_clock(monkeypatch) -> None:
    """The combo path's per-step slices must total what `_step_duration_s` returns.

    Two encodings of one rotation producing different clocks is the #83 defect. The combo
    path charges `_StepMoveSpec.duration_s` per emitted step; the direct path charges
    `_step_duration_s` once for the whole move. This pins them together.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.services import combo_step_resolver as csr
    from app.services.combo_step_resolver import resolve_combo_sequence

    move_name = "EX Special Attack: Intense Heat Stirring Method"
    move = _spec(duration_s=1.2)
    monkeypatch.setattr(csr, "_channel_move_for", lambda agent_id, name: move)

    def _row(idx: int, param: str) -> MagicMock:
        a = MagicMock()
        a.id, a.hit_index, a.name = f"att-{idx}", idx, move_name
        a.skill_key, a.hit_mode, a.variant_label = "EXSpecial", HitMode.CHANNEL, None
        a.param_name, a.element = param, "fire"
        a.damage_base = a.damage_growth = a.stun_base = a.stun_growth = 0
        a.energy_gain = a.anomaly_buildup = 0
        return a

    rows = [
        _row(0, "Continuous Spray DMG Multiplier"),
        _row(1, "Fire Blast DMG Multiplier"),
    ]
    move.channel.roles["Fire Blast DMG Multiplier"] = "release"

    build = MagicMock()
    build.potential_rank, build.agent_id = 5, "agent-1"
    build.skill_levels = "12,12,12,12,12"
    repo = AsyncMock()
    repo.get_by_agent_and_name.return_value = rows

    steps = await resolve_combo_sequence(
        [{"move_name": move_name, "label": "EX", "channel_s": 2.0}],
        build=build,
        attack_repo=repo,
    )
    combo_clock = sum(s.duration_s or 0.0 for s in steps)
    direct_clock = _step_duration_s(_Step(rows, channel_s=2.0), move)
    assert combo_clock == pytest.approx(direct_clock)
    assert combo_clock == pytest.approx(3.2)
