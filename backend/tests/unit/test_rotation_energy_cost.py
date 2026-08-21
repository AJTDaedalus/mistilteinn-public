"""Task 15 — derive the rotation's Energy bill instead of asking the caller for it.

`rotation_energy_cost` is a number the server already knows: it is the sum of the
per-step bills `resource_bill` computes. Asking the caller to supply it invites the two to
disagree, and on a channel the caller *cannot* compute it — the bill depends on how long
each press is held.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.data.loaders.moves import ChannelSpec, MoveBuildupSpec
from app.services.rotation_cost import derive_rotation_energy_cost


@dataclass
class _Step:
    move_name: str
    agent_id: str = "dps"
    channel_s: float | None = None
    attacks: list[Any] = field(default_factory=list)


@dataclass
class _Snap:
    ex_energy_cost: float | None = 40
    resource_costs: dict = field(default_factory=dict)


BURNICE_COSTS = {
    "entry": (40.0, False, "Energy"),
    "drain": (12.5, True, "Energy"),
    "release": (5.0, False, "Energy"),
    "toss": (10.0, False, "Energy"),
}


def _channel_move() -> MoveBuildupSpec:
    return MoveBuildupSpec(
        duration_s=1.2,
        channel=ChannelSpec(
            max_s=4.0,
            default_s=2.0,
            tick_s=0.5,
            tick_mv_basis="whole_channel",
            nominal_s=2.5,
            roles={"Spray": "tick"},
            entry_cost_key="entry",
            drain_cost_key="drain",
            release_cost_key="release",
        ),
    )


def _moves(**over) -> dict[str, MoveBuildupSpec]:
    base = {"EX Spray": _channel_move(), "EX Toss": MoveBuildupSpec(cost_key="toss")}
    base.update(over)
    return base


def test_a_channel_step_contributes_its_held_bill() -> None:
    """40 + 12.5x2 + 5 = 70 -- the number the caller could not have computed."""
    total = derive_rotation_energy_cost(
        [_Step("EX Spray", channel_s=2.0)],
        {"dps": _Snap(resource_costs=BURNICE_COSTS)},
        {"dps": _moves()},
    )
    assert total == pytest.approx(70.0)


def test_a_longer_hold_raises_the_rotation_cost() -> None:
    """The whole reason to derive rather than ask: the bill moves with the hold."""
    short = derive_rotation_energy_cost(
        [_Step("EX Spray", channel_s=1.0)],
        {"dps": _Snap(resource_costs=BURNICE_COSTS)},
        {"dps": _moves()},
    )
    long = derive_rotation_energy_cost(
        [_Step("EX Spray", channel_s=4.0)],
        {"dps": _Snap(resource_costs=BURNICE_COSTS)},
        {"dps": _moves()},
    )
    assert long - short == pytest.approx(37.5)


def test_a_cost_key_step_bills_its_own_mode() -> None:
    total = derive_rotation_energy_cost(
        [_Step("EX Toss")],
        {"dps": _Snap(resource_costs=BURNICE_COSTS)},
        {"dps": _moves()},
    )
    assert total == pytest.approx(10.0)


def test_steps_sum_across_the_rotation() -> None:
    total = derive_rotation_energy_cost(
        [_Step("EX Spray", channel_s=2.0), _Step("EX Toss")],
        {"dps": _Snap(resource_costs=BURNICE_COSTS)},
        {"dps": _moves()},
    )
    assert total == pytest.approx(80.0)


def test_only_the_scored_owner_is_billed() -> None:
    """The gate credits the DPS build's EX damage; a support's spend is not its constraint."""
    total = derive_rotation_energy_cost(
        [_Step("EX Spray", channel_s=2.0), _Step("EX Toss", agent_id="support1")],
        {"dps": _Snap(resource_costs=BURNICE_COSTS), "support1": _Snap()},
        {"dps": _moves(), "support1": _moves()},
        owner_id="dps",
    )
    assert total == pytest.approx(70.0)


def test_a_move_with_no_binding_contributes_nothing_without_an_ex_scope() -> None:
    """A Basic Attack costs no Energy; only EX presses bill the scalar.

    `None`, not `0.0`, for the same reason an empty rotation is None: nothing was billed, and
    `0.0` would read as a computed answer while switching the gate off.
    """
    total = derive_rotation_energy_cost(
        [_Step("Basic Attack: Whatever")],
        {"dps": _Snap(resource_costs=BURNICE_COSTS)},
        {"dps": _moves()},
    )
    assert total is None


def test_markers_are_not_billed() -> None:
    total = derive_rotation_energy_cost(
        [_Step("stun_trigger"), _Step("switch"), _Step("aftershock"), _Step("stun_end")],
        {"dps": _Snap(resource_costs=BURNICE_COSTS)},
        {"dps": _moves()},
    )
    assert total is None


def test_an_empty_rotation_derives_none_not_zero() -> None:
    """Zero would switch the gate OFF (`cost > 0`); None says "nothing to derive" out loud."""
    assert derive_rotation_energy_cost([], {"dps": _Snap()}, {"dps": _moves()}) is None


def test_an_unknown_agent_is_skipped_rather_than_crashing() -> None:
    total = derive_rotation_energy_cost(
        [_Step("EX Spray", agent_id="ghost", channel_s=2.0)],
        {"dps": _Snap(resource_costs=BURNICE_COSTS)},
        {"dps": _moves()},
        owner_id="ghost",
    )
    assert total is None
