"""Task 10c — one expansion, three paths.

`combo_step_resolver` expands a channel into N ComboSteps; `api/v1/simulate` and
`optimizer_pipeline` each build one SimulatedAttackStep holding every row. Two encodings of
one rotation producing different anomaly counts is the #83 defect, so both now derive from
the same `build_channel_plan` rather than from two copies of the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.data.loaders.moves import ChannelSpec
from app.services.channel_plan import build_channel_plan


@dataclass
class _Row:
    hit_index: int
    param_name: str | None
    variant_label: str | None = None


def _spec(**over) -> ChannelSpec:
    base = {
        "min_s": 0.0,
        "max_s": 4.0,
        "default_s": 2.0,
        "tick_s": 0.5,
        "tick_mv_basis": "whole_channel",
        "nominal_s": 2.5,
        "roles": {
            "Ignition DMG Multiplier": "entry",
            "Continuous Spray DMG Multiplier": "tick",
            "Fire Blast DMG Multiplier": "release",
        },
    }
    base.update(over)
    return ChannelSpec(**base)


def _rows() -> list[_Row]:
    return [
        _Row(0, "Ignition DMG Multiplier"),
        _Row(1, "Continuous Spray DMG Multiplier"),
        _Row(2, "Fire Blast DMG Multiplier"),
    ]


def test_plan_orders_entry_then_ticks_then_release() -> None:
    plan = build_channel_plan(_rows(), _spec(), channel_s=2.0, tail_s=1.2)
    assert [h.role for h in plan.hits] == ["entry", *["tick"] * 4, "release"]


def test_tick_hits_carry_the_scale_and_the_others_do_not() -> None:
    plan = build_channel_plan(_rows(), _spec(), channel_s=2.0, tail_s=1.2)
    scales = {h.role: h.mv_scale for h in plan.hits}
    assert scales["tick"] == pytest.approx(0.5 / 2.5)
    assert scales["entry"] == 1.0
    assert scales["release"] == 1.0


def test_durations_sum_to_hold_plus_tail() -> None:
    """The clock the combo path charges must equal what `_step_duration_s` returns."""
    plan = build_channel_plan(_rows(), _spec(), channel_s=2.0, tail_s=1.2)
    assert sum(h.duration_s for h in plan.hits) == pytest.approx(3.2)


def test_zero_length_hold_keeps_entry_and_release_only() -> None:
    plan = build_channel_plan(_rows(), _spec(), channel_s=0.0, tail_s=1.2)
    assert [h.role for h in plan.hits] == ["entry", "release"]


def test_per_second_basis_scales_by_tick_length() -> None:
    spec = _spec(tick_mv_basis="per_second", nominal_s=None, tick_s=1.0, max_s=6.0)
    plan = build_channel_plan(_rows(), spec, channel_s=3.0, tail_s=0.0)
    ticks = [h for h in plan.hits if h.role == "tick"]
    assert len(ticks) == 3
    assert all(h.mv_scale == pytest.approx(1.0) for h in ticks)


def test_an_unmapped_row_fires_once_unscaled_and_warns() -> None:
    rows = [*_rows(), _Row(3, "Mystery DMG Multiplier")]
    plan = build_channel_plan(rows, _spec(), channel_s=1.0, tail_s=0.0)
    mystery = [h for h in plan.hits if h.row.param_name == "Mystery DMG Multiplier"]
    assert len(mystery) == 1
    assert mystery[0].mv_scale == 1.0
    assert any("Mystery" in w for w in plan.warnings)


def test_rows_are_ordered_by_hit_index_not_input_order() -> None:
    rows = list(reversed(_rows()))
    plan = build_channel_plan(rows, _spec(), channel_s=0.0, tail_s=0.0)
    assert [h.row.hit_index for h in plan.hits] == [0, 2]


def test_the_tail_is_split_across_multiple_release_rows() -> None:
    rows = [
        _Row(0, "Continuous Spray DMG Multiplier"),
        _Row(1, "Fire Blast DMG Multiplier"),
        _Row(2, "Fire Blast DMG Multiplier"),
    ]
    plan = build_channel_plan(rows, _spec(), channel_s=0.0, tail_s=1.2)
    releases = [h for h in plan.hits if h.role == "release"]
    assert len(releases) == 2
    assert sum(h.duration_s for h in releases) == pytest.approx(1.2)


def test_a_channel_with_no_release_row_still_spends_the_tail() -> None:
    """The tail is animation, not a property of the release row; losing it shortens the step."""
    rows = [_Row(0, "Continuous Spray DMG Multiplier")]
    plan = build_channel_plan(rows, _spec(), channel_s=1.0, tail_s=1.2)
    assert sum(h.duration_s for h in plan.hits) == pytest.approx(2.2)


# ---- the three paths agree ------------------------------------------------


def test_all_three_paths_call_the_same_expansion() -> None:
    """The structural guarantee 10c buys, asserted rather than assumed.

    `_resolve_channel` (saved combos), `_resolve_channel_rows` (/simulate) and
    `optimizer_pipeline`'s channel branch must all reach `build_channel_plan`. A fourth
    copy of the arithmetic appearing anywhere is the #83 defect waiting to happen, and the
    cheapest guard against it is to pin that the three known call sites are the only ones.
    """
    import inspect

    from app.api.v1 import simulate as simulate_api
    from app.services import combo_step_resolver, optimizer_pipeline

    for module in (combo_step_resolver, simulate_api, optimizer_pipeline):
        source = inspect.getsource(module)
        assert "build_channel_plan(" in source, f"{module.__name__} does not use the shared plan"


def test_scales_and_rows_stay_positionally_aligned() -> None:
    """`attack_scales[i]` must describe `attacks[i]` — the direct paths index them in parallel."""
    plan = build_channel_plan(_rows(), _spec(), channel_s=2.0, tail_s=1.2)
    rows = [h.row for h in plan.hits]
    scales = [h.mv_scale for h in plan.hits]
    assert len(rows) == len(scales)
    for row, scale in zip(rows, scales, strict=True):
        expected = 0.5 / 2.5 if row.param_name == "Continuous Spray DMG Multiplier" else 1.0
        assert scale == pytest.approx(expected)


def test_every_call_site_passes_the_non_held_tail() -> None:
    """All three paths must feed `tail_s`, not just the combo one.

    They did not. `_resolve_channel_rows` and `optimizer_pipeline` called
    `build_channel_plan` without `tail_s`, so for the identical rotation the release hit
    landed one tail earlier than the combo path put it. Totals matched, which is why
    nothing caught it — but hit TIMES are what the 3s per-attribute re-trigger CD and the
    anomaly decay clock read, so the two encodings could disagree on proc count. That is
    #83 in its timing form, and Task 10c's single-expansion rule is not satisfied by
    sharing the function while diverging on its arguments.

    Pinned by source inspection for the same reason the sibling test above is: the
    alternative is a DB-backed round trip per path, which is exactly the kind of check that
    stops running the first time someone's Postgres is down.
    """
    import inspect
    import re

    from app.api.v1 import simulate as simulate_api
    from app.services import combo_step_resolver, optimizer_pipeline

    for module in (combo_step_resolver, simulate_api, optimizer_pipeline):
        source = inspect.getsource(module)
        for call in re.findall(r"build_channel_plan\(.*?\)", source, re.DOTALL):
            assert "tail_s" in call, (
                f"{module.__name__} calls build_channel_plan without tail_s — its release "
                "hit will land one non-held tail earlier than the other paths place it"
            )
