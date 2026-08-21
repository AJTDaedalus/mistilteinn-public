"""Task 10b — a channel's gauge split, and its cadence on the clock.

Owner ruling **D-CH3** (2026-08-18): gauge and damage in the same row share a basis. So the
per-role split is the DB's own per-row `anomaly_buildup` — for Burnice, spray 41110 and blast
7155, which sum to exactly the authored 48265 — and each tick carries the same fraction of
its row that the tick's multiplier does.

That replaces the uniform per-emitted-hit split the path used before, which gave a 0.5s tick
the same gauge as the Fire Blast.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.data.loaders.moves import ChannelSpec
from app.services.channel_plan import build_channel_plan


@dataclass
class _Row:
    hit_index: int
    param_name: str | None
    anomaly_buildup: int = 0
    variant_label: str | None = None


@dataclass
class _Step:
    attacks: list[Any] = field(default_factory=list)
    attack_scales: list[float] | None = None
    attack_offsets: list[float] | None = None


def _spec(**over) -> ChannelSpec:
    base = {
        "max_s": 6.0,
        "default_s": 2.0,
        "tick_s": 0.5,
        "tick_mv_basis": "whole_channel",
        "roles": {
            "Continuous Spray DMG Multiplier": "tick",
            "Fire Blast DMG Multiplier": "release",
        },
    }
    base.update(over)
    return ChannelSpec(**base)


def _burnice_rows() -> list[_Row]:
    return [
        _Row(0, "Continuous Spray DMG Multiplier", anomaly_buildup=41110),
        _Row(1, "Fire Blast DMG Multiplier", anomaly_buildup=7155),
    ]


def _buildups(plan) -> list[int]:
    return [round(h.row.anomaly_buildup * h.mv_scale) for h in plan.hits]


def test_a_full_hold_recovers_the_authored_move_total() -> None:
    """41110 + 7155 = 48265, which is exactly what burnice.json authors. Under D-CH2 a full
    hold is what collects it, so the sum at max_s must land back on the authored figure."""
    plan = build_channel_plan(_burnice_rows(), _spec(), channel_s=6.0, tail_s=1.2)
    assert sum(_buildups(plan)) == pytest.approx(48265, abs=2)


def test_a_half_hold_collects_half_the_spray_but_all_of_the_blast() -> None:
    """The blast is a release row: it fires once whatever the hold. Only the spray scales."""
    plan = build_channel_plan(_burnice_rows(), _spec(), channel_s=3.0, tail_s=1.2)
    spray = sum(round(h.row.anomaly_buildup * h.mv_scale) for h in plan.hits if h.role == "tick")
    blast = sum(
        round(h.row.anomaly_buildup * h.mv_scale) for h in plan.hits if h.role == "release"
    )
    assert spray == pytest.approx(41110 / 2, abs=2)
    assert blast == 7155


def test_a_tick_does_not_carry_the_blast_s_gauge() -> None:
    """The defect D-CH3 fixes: the uniform split gave a 0.5s tick the Fire Blast's share."""
    plan = build_channel_plan(_burnice_rows(), _spec(), channel_s=6.0, tail_s=1.2)
    per_tick = next(
        round(h.row.anomaly_buildup * h.mv_scale) for h in plan.hits if h.role == "tick"
    )
    uniform = 48265 // len(plan.hits)
    assert per_tick != uniform
    # 41110 * (0.5/6.0) ~= 3426, well under the uniform 48265/13 ~= 3712
    assert per_tick == pytest.approx(41110 * (0.5 / 6.0), abs=2)


def test_gauge_and_damage_scale_by_the_same_factor() -> None:
    """D-CH3 in one assertion: one row, one basis, both columns."""
    plan = build_channel_plan(_burnice_rows(), _spec(), channel_s=2.0, tail_s=1.2)
    for hit in plan.hits:
        assert hit.mv_scale == pytest.approx(0.5 / 6.0 if hit.role == "tick" else 1.0)


def test_a_zero_gauge_row_stays_zero_at_every_hold() -> None:
    """Scaling must not manufacture gauge for a row the DB says carries none."""
    rows = [
        _Row(0, "Continuous Spray DMG Multiplier", anomaly_buildup=0),
        _Row(1, "Fire Blast DMG Multiplier", anomaly_buildup=7155),
    ]
    plan = build_channel_plan(rows, _spec(), channel_s=4.0, tail_s=1.2)
    assert all(
        round(h.row.anomaly_buildup * h.mv_scale) == 0 for h in plan.hits if h.role == "tick"
    )


# ---- cadence on the clock -------------------------------------------------


def test_offsets_place_ticks_at_the_real_tick_cadence() -> None:
    """§4.4's core claim: a spray applies its gauge at `tick_s` cadence, not in one instant.

    Anomaly decay, the 3s per-attribute re-trigger CD, and Shock/Corruption's internal proc
    CDs are all read off these timestamps, so spreading them uniformly across the step is not
    a cosmetic difference.
    """
    from app.services.channel_plan import plan_hit_offsets

    plan = build_channel_plan(_burnice_rows(), _spec(), channel_s=2.0, tail_s=1.2)
    offsets = plan_hit_offsets(plan)
    ticks = [o for o, h in zip(offsets, plan.hits, strict=True) if h.role == "tick"]
    assert ticks == pytest.approx([0.5, 1.0, 1.5, 2.0])


def test_the_release_lands_after_the_last_tick() -> None:
    from app.services.channel_plan import plan_hit_offsets

    plan = build_channel_plan(_burnice_rows(), _spec(), channel_s=2.0, tail_s=1.2)
    offsets = plan_hit_offsets(plan)
    assert offsets[-1] == pytest.approx(3.2)
    assert offsets[-1] > max(
        o for o, h in zip(offsets, plan.hits, strict=True) if h.role == "tick"
    )


def test_offsets_are_monotonic() -> None:
    from app.services.channel_plan import plan_hit_offsets

    plan = build_channel_plan(_burnice_rows(), _spec(), channel_s=4.0, tail_s=1.2)
    offsets = plan_hit_offsets(plan)
    assert offsets == sorted(offsets)
