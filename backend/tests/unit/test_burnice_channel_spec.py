"""Burnice's authored channel spec (Task 12) — the first move in the corpus to bind one.

These assert the *authored numbers*, not the engine: the expansion arithmetic is covered by
`test_channel_plan.py` and the billing by `test_channel_resource_bill.py`. What can only be
checked here is that the spec Burnice actually ships says what the owner rulings say it should,
because every spray number in the game scales linearly with `nominal_s` and nothing downstream
can notice if it drifts.
"""

from __future__ import annotations

import pytest

from app.data.loaders.moves import load_agent_moves
from app.services.channel_plan import build_channel_plan, channel_tick_plan

_STIRRING = "EX Special Attack: Intense Heat Stirring Method"
_DOUBLE = "EX Special Attack: Intense Heat Stirring Method - Double Shot"


def _burnice():
    return load_agent_moves()["burnice"].moves


@pytest.mark.parametrize("move_name", [_STIRRING, _DOUBLE])
def test_both_ex_modes_are_channels(move_name: str) -> None:
    """Both EX modes hold-to-drain; only these two moves in the file do."""
    moves = _burnice()
    assert moves[move_name].channel is not None
    others = [n for n, m in moves.items() if m.channel is not None]
    assert sorted(others) == sorted([_STIRRING, _DOUBLE])


@pytest.mark.parametrize("move_name", [_STIRRING, _DOUBLE])
def test_max_s_is_two_seconds(move_name: str) -> None:
    """Owner ruling D-CH4. A wrong `max_s` rescales every spray number by a constant."""
    assert _burnice()[move_name].channel.max_s == pytest.approx(2.0)


@pytest.mark.parametrize("move_name", [_STIRRING, _DOUBLE])
def test_nominal_s_is_authored_explicitly_not_defaulted(move_name: str) -> None:
    """D-CH2's `nominal_s == max_s` is M0-scoped: M4 raises Double Shot's cap to 3.0s.

    The two fields are distinct concepts that coincide only at M0, so the file must state
    both. Leaning on the default would silently rebase every number the day `max_s` moves.
    """
    channel = _burnice()[move_name].channel
    assert channel.nominal_s == pytest.approx(2.0)
    assert "nominal_s" in channel.notes
    assert "M4" in channel.notes


@pytest.mark.parametrize("move_name", [_STIRRING, _DOUBLE])
def test_basis_is_whole_channel_per_the_era_rule(move_name: str) -> None:
    """D-CH1: Burnice is 1171, inside the <=1371 whole-duration cohort."""
    assert _burnice()[move_name].channel.tick_mv_basis == "whole_channel"


@pytest.mark.parametrize("move_name", [_STIRRING, _DOUBLE])
def test_roles_map_the_two_real_param_names(move_name: str) -> None:
    """Verified against the seeded DB: spray ticks, blast releases."""
    assert _burnice()[move_name].channel.roles == {
        "Continuous Spray DMG Multiplier": "tick",
        "Fire Blast DMG Multiplier": "release",
    }


@pytest.mark.parametrize(
    ("move_name", "prefix"), [(_STIRRING, "01"), (_DOUBLE, "02")]
)
def test_cost_keys_follow_the_textmap_numbering(move_name: str, prefix: str) -> None:
    """The TextMap numbering is self-consistent and is what `agent_resource_costs` is keyed by.

    The ability graph's animator states run the OTHER way (`Attack_ExSpecial_01` is Double
    Shot). Pinned here so a future curator who meets that inversion does not "fix" these keys
    into a swap — which would be 2x in drain and 2x in MV in the same direction, leaving the
    totals plausible.
    """
    channel = _burnice()[move_name].channel
    stem = f"Burnice_Property_ExSpecial_{prefix}_SpCostValue_"
    assert channel.entry_cost_key == stem + "01"
    assert channel.drain_cost_key == stem + "02"
    assert channel.release_cost_key == stem + "03"


@pytest.mark.parametrize("move_name", [_STIRRING, _DOUBLE])
def test_a_full_hold_recovers_exactly_the_authored_multiplier(move_name: str) -> None:
    """The property that makes `tick_s` a free choice: the tick scales sum to 1.0 at max hold."""
    channel = _burnice()[move_name].channel
    n_ticks, mv_scale = channel_tick_plan(channel, channel.max_s)
    assert n_ticks == 4
    assert n_ticks * mv_scale == pytest.approx(1.0)


@pytest.mark.parametrize("move_name", [_STIRRING, _DOUBLE])
def test_tick_s_divides_max_s_evenly(move_name: str) -> None:
    """Otherwise `round(channel_s / tick_s)` quantizes the total away from the authored figure."""
    channel = _burnice()[move_name].channel
    assert (channel.max_s / channel.tick_s) == pytest.approx(
        round(channel.max_s / channel.tick_s)
    )


@pytest.mark.parametrize("move_name", [_STIRRING, _DOUBLE])
def test_default_s_reproduces_the_authored_figure(move_name: str) -> None:
    """A step that names no `channel_s` must not silently under-report the move."""
    channel = _burnice()[move_name].channel
    assert channel.default_s == pytest.approx(channel.nominal_s)


@pytest.mark.parametrize(
    ("move_name", "expected_tail"), [(_STIRRING, 0.5), (_DOUBLE, 1.5)]
)
def test_duration_s_is_the_non_held_tail(move_name: str, expected_tail: float) -> None:
    """On a channel `duration_s` means the entry+release animation, not the whole move.

    Chosen so `default_s + duration_s` equals the whole-move estimate the file carried before
    the re-tag (2.5s and 3.5s), keeping the default path's clock unchanged.
    """
    move = _burnice()[move_name]
    assert move.duration_s == pytest.approx(expected_tail)
    assert move.channel.default_s + move.duration_s == pytest.approx(
        {0.5: 2.5, 1.5: 3.5}[expected_tail]
    )


def test_a_full_hold_expands_to_four_ticks_and_one_release() -> None:
    """End-to-end over the real spec, using stand-in rows carrying the real param names."""

    class _Row:
        def __init__(self, param_name: str, hit_index: int) -> None:
            self.param_name = param_name
            self.hit_index = hit_index

    channel = _burnice()[_STIRRING].channel
    rows = [_Row("Continuous Spray DMG Multiplier", 0), _Row("Fire Blast DMG Multiplier", 1)]
    plan = build_channel_plan(rows, channel, channel.default_s, move_name=_STIRRING)

    assert plan.warnings == []
    assert [h.role for h in plan.hits] == ["tick", "tick", "tick", "tick", "release"]
    assert sum(h.mv_scale for h in plan.hits if h.role == "tick") == pytest.approx(1.0)
    assert [h.mv_scale for h in plan.hits if h.role == "release"] == [1.0]


# ---- Yixuan (Task 18) — the cohort's confirmation case ---------------------


def _yixuan():
    return load_agent_moves()["yixuan"].moves["EX Special Attack: Cloud-Shaper"]


def test_yixuan_max_s_is_cited_not_measured() -> None:
    """Unusually for this cohort the game states the cap outright.

    `YiXuan_Skill_ExSpecial_02_Desc`: "Continuously charge up ... up to a max of 2s". So this
    spec needs no owner measurement, unlike Burnice's, whose cap is an AnimatorController
    constant. Pinned so nobody later "corrects" it toward Burnice's provenance.
    """
    channel = _yixuan().channel
    assert channel.max_s == pytest.approx(2.0)
    assert channel.nominal_s == pytest.approx(2.0)
    assert "UP TO A MAX OF 2s" in channel.notes


def test_yixuan_confirms_the_era_rule_rather_than_assuming_it() -> None:
    """Her row's own `param_name` says "Total ... During Charge" — the label, not an inference.

    D-CH1 predicts `whole_channel` for avatar_id 1371 from release order alone; this move is
    where the prediction is independently corroborated by upstream text.
    """
    channel = _yixuan().channel
    assert channel.tick_mv_basis == "whole_channel"
    assert channel.roles == {"Total DMG Multiplier During Charge": "tick"}


def test_yixuan_has_no_release_cost_because_the_finisher_is_a_separate_move() -> None:
    """`Ashen Ink Becomes Shadows` carries its own rows and buildup.

    Binding a release cost here would bill her finisher twice — once on this channel's
    release and once when the separate move runs.
    """
    channel = _yixuan().channel
    assert channel.release_cost_key is None
    assert channel.entry_cost_key == "YiXuan_Property_ExSpecial_02_SpCostValue_02"
    assert channel.drain_cost_key == "YiXuan_Property_ExSpecial_02_SpCostValue_04"


def test_yixuan_cost_keys_are_the_value_keys_not_the_label_keys() -> None:
    """Her `SpCostValue_NN` series alternates label and value; Burnice's does not.

    `_01` = 'Initial Consumption', `_02` = 20, `_03` = 'Consumption Per Second', `_04` = 20.
    Binding `_01`/`_03` — the arithmetically obvious choice, and the one that matches
    Burnice's shape — would point at strings. Two agents, two conventions, one key shape.
    """
    channel = _yixuan().channel
    assert channel.entry_cost_key.endswith("_02")
    assert channel.drain_cost_key.endswith("_04")
