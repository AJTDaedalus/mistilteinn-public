"""Task 19a — the `per_tick` basis: a tick worth exactly its authored row.

Neither existing basis can express a **per-shot** multiplier. `per_second` treats the row as a
rate and multiplies by `tick_s`; `whole_channel` treats it as a total and divides by `nominal_s`.
Trigger's `Shot DMG Multiplier` is neither — it is what one shot does, and holding fires more of
them (D-CH1a).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.data.loaders.moves import ChannelSpec
from app.services.channel_plan import build_channel_plan, channel_tick_plan


def _spec(**over: object) -> ChannelSpec:
    base: dict[str, object] = {
        "min_s": 0.0,
        "max_s": 3.0,
        "default_s": 3.0,
        "tick_s": 0.5,
        "tick_mv_basis": "per_tick",
        "roles": {"Shot DMG Multiplier": "tick", "Finishing Move DMG Multiplier": "release"},
    }
    base.update(over)
    return ChannelSpec(**base)  # type: ignore[arg-type]


class _Row:
    def __init__(self, param_name: str, hit_index: int, damage_base: int = 0) -> None:
        self.param_name = param_name
        self.hit_index = hit_index
        self.damage_base = damage_base
        self.anomaly_buildup = 0


def test_a_tick_is_worth_exactly_its_row() -> None:
    """The whole point. `mv_scale` is 1.0 — not `tick_s`, not `tick_s / nominal_s`."""
    n_ticks, mv_scale = channel_tick_plan(_spec(), channel_s=3.0)
    assert n_ticks == 6
    assert mv_scale == 1.0


@pytest.mark.parametrize("tick_s", [0.25, 0.5, 1.0])
def test_the_scale_does_not_depend_on_tick_s(tick_s: float) -> None:
    """Unlike `per_second`, where the scale IS `tick_s`.

    On this basis `tick_s` decides *how many* shots a hold produces, never what one is worth.
    """
    _, mv_scale = channel_tick_plan(_spec(tick_s=tick_s), channel_s=2.0)
    assert mv_scale == 1.0


def test_holding_longer_fires_more_shots_linearly() -> None:
    """Twice the hold, twice the shots, each still worth a full row."""
    short_n, _ = channel_tick_plan(_spec(), channel_s=1.0)
    long_n, _ = channel_tick_plan(_spec(), channel_s=2.0)
    assert long_n == 2 * short_n


def test_nominal_s_is_forbidden_exactly_as_on_per_second() -> None:
    """A field that looks load-bearing but is ignored is how a silent 2x hides.

    `per_tick` has nothing to divide by, so authoring `nominal_s` alongside it is the same
    mistake the loader already rejects for `per_second`.
    """
    with pytest.raises(ValidationError, match="nominal_s"):
        _spec(nominal_s=3.0)


def test_the_default_basis_is_still_per_second() -> None:
    """Adding a member must not move the default out from under the corpus."""
    spec = ChannelSpec(max_s=2.0, default_s=2.0, tick_s=0.5, roles={"A": "tick"})
    assert spec.tick_mv_basis == "per_second"


def test_an_unknown_basis_still_fails() -> None:
    with pytest.raises(ValidationError, match="tick_mv_basis"):
        _spec(tick_mv_basis="per_fortnight")


def test_expansion_gives_every_shot_a_full_multiplier() -> None:
    """End to end through the shared plan, in Trigger's shape."""
    rows = [_Row("Shot DMG Multiplier", 0, 4760), _Row("Finishing Move DMG Multiplier", 1, 13120)]
    plan = build_channel_plan(
        rows, _spec(), channel_s=1.5, move_name="Basic Attack: Silenced Shot"
    )

    assert plan.warnings == []
    ticks = [h for h in plan.hits if h.role == "tick"]
    assert len(ticks) == 3
    assert all(h.mv_scale == 1.0 for h in ticks)
    # Three shots at the authored multiplier, not one shot spread across three.
    assert sum(round(h.row.damage_base * h.mv_scale) for h in ticks) == 3 * 4760
