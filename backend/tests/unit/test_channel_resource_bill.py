"""Task 11 — the three-branch resource bill (DESIGN_channeled_moves.md §4.5/§4.6).

`if scope == EX_SPECIAL: spend Agent.ex_energy_cost` is one scalar for one mode. It
over-bills Burnice's Tossing Method (10, billed as 40) and cannot express a per-second
drain at all. The dispatch becomes:

    channel spec      -> entry + drain_per_s * channel_s + release
    plain cost key    -> that mode's own cost
    neither           -> Agent.ex_energy_cost   (unchanged, ~50 agents)
"""

from __future__ import annotations

import pytest

from app.data.loaders.moves import ChannelSpec, MoveBuildupSpec
from app.services.resource_banks import ResourceBanks
from app.services.resource_bill import ResourceBill, bill_for_move, clamp_channel_to_bank

BURNICE_COSTS = {
    "Burnice_Property_ExSpecial_01_SpCostValue_01": (40.0, False, "Energy"),
    "Burnice_Property_ExSpecial_01_SpCostValue_02": (12.5, True, "Energy"),
    "Burnice_Property_ExSpecial_01_SpCostValue_03": (5.0, False, "Energy"),
    "Burnice_Property_ExSpecial_02_SpCostValue_01": (10.0, False, "Energy"),
}


def _costs(mapping=None) -> dict[str, tuple[float, bool, str]]:
    return dict(BURNICE_COSTS if mapping is None else mapping)


def _channel_move(**over) -> MoveBuildupSpec:
    spec = ChannelSpec(
        min_s=0.0,
        max_s=4.0,
        default_s=2.0,
        tick_s=0.5,
        tick_mv_basis="whole_channel",
        nominal_s=2.5,
        roles={"Continuous Spray DMG Multiplier": "tick"},
        entry_cost_key="Burnice_Property_ExSpecial_01_SpCostValue_01",
        drain_cost_key="Burnice_Property_ExSpecial_01_SpCostValue_02",
        release_cost_key="Burnice_Property_ExSpecial_01_SpCostValue_03",
        **over,
    )
    return MoveBuildupSpec(duration_s=1.2, channel=spec)


# ---- branch 1: a channel bills entry + drain x hold + release ---------------


def test_burnice_two_second_spray_bills_seventy() -> None:
    """The acceptance number: 40 + 12.5x2 + 5 = 70."""
    bill = bill_for_move(_channel_move(), _costs(), channel_s=2.0, ex_energy_cost=40)
    assert bill.amount == pytest.approx(70.0)
    assert bill.resource == "Energy"


def test_a_longer_hold_costs_more() -> None:
    short = bill_for_move(_channel_move(), _costs(), channel_s=1.0, ex_energy_cost=40)
    long = bill_for_move(_channel_move(), _costs(), channel_s=3.0, ex_energy_cost=40)
    assert long.amount - short.amount == pytest.approx(25.0)


def test_a_zero_length_hold_still_pays_entry_and_release() -> None:
    """Tapping the button is not free -- you pay to open and to close the channel."""
    bill = bill_for_move(_channel_move(), _costs(), channel_s=0.0, ex_energy_cost=40)
    assert bill.amount == pytest.approx(45.0)


def test_a_channel_with_no_cost_keys_bills_nothing() -> None:
    """Promeia and Pryce channel with no resource drain at all -- that is a real mechanic."""
    move = MoveBuildupSpec(
        channel=ChannelSpec(
            max_s=4.0, default_s=2.0, tick_s=0.5, roles={"X Per Sec": "tick"}
        )
    )
    bill = bill_for_move(move, _costs(), channel_s=3.0, ex_energy_cost=40)
    assert bill.amount == 0.0


def test_a_missing_cost_key_warns_rather_than_billing_zero() -> None:
    """An unresolved key is a data gap. Billing 0 silently makes the move free."""
    bill = bill_for_move(
        _channel_move(), {}, channel_s=2.0, ex_energy_cost=40, move_name="EX"
    )
    assert bill.amount == 0.0
    assert bill.warnings
    assert any("SpCostValue_01" in w for w in bill.warnings)


# ---- branch 2: a plain cost key ------------------------------------------


def test_a_non_channel_move_bills_its_own_key_not_the_scalar() -> None:
    """Burnice's Tossing Method costs 10, not the 40 `ex_energy_cost` reports."""
    move = MoveBuildupSpec(cost_key="Burnice_Property_ExSpecial_02_SpCostValue_01")
    bill = bill_for_move(move, _costs(), channel_s=None, ex_energy_cost=40)
    assert bill.amount == pytest.approx(10.0)


def test_a_named_bank_key_bills_that_bank() -> None:
    move = MoveBuildupSpec(cost_key="Velina_Property_FengHuaCostValue_01")
    costs = {"Velina_Property_FengHuaCostValue_01": (90.0, False, "Windbloom")}
    bill = bill_for_move(move, costs, channel_s=None, ex_energy_cost=45)
    assert bill.amount == pytest.approx(90.0)
    assert bill.resource == "Windbloom"


# ---- branch 3: the unchanged majority ------------------------------------


def test_a_move_with_no_binding_bills_the_scalar() -> None:
    """~50 single-mode agents. This branch must not move."""
    bill = bill_for_move(MoveBuildupSpec(), _costs(), channel_s=None, ex_energy_cost=60)
    assert bill.amount == pytest.approx(60.0)
    assert bill.resource == "Energy"


def test_no_move_spec_at_all_bills_the_scalar() -> None:
    bill = bill_for_move(None, _costs(), channel_s=None, ex_energy_cost=60)
    assert bill.amount == pytest.approx(60.0)


def test_a_null_scalar_falls_back_and_warns() -> None:
    """Preserved verbatim: ex_energy_cost is NULL on a migrated-but-not-re-seeded DB."""
    bill = bill_for_move(None, _costs(), channel_s=None, ex_energy_cost=None)
    assert bill.amount == pytest.approx(60.0)
    assert any("NULL" in w for w in bill.warnings)


# ---- §4.6: the bank bounds the hold --------------------------------------


def test_a_short_bank_clamps_the_hold() -> None:
    """(30 - 40 - 5) is negative: the bank cannot even open this channel."""
    banks = ResourceBanks({"dps": 30.0}, {"dps": {}})
    effective, warning = clamp_channel_to_bank(
        _channel_move().channel, _costs(), banks, "dps", requested_s=4.0, move_name="EX"
    )
    assert effective == 0.0
    assert warning is not None


def test_a_partial_bank_buys_a_partial_hold() -> None:
    """(75 - 40 - 5) / 12.5 = 2.4s affordable against a 4s request."""
    banks = ResourceBanks({"dps": 75.0}, {"dps": {}})
    effective, warning = clamp_channel_to_bank(
        _channel_move().channel, _costs(), banks, "dps", requested_s=4.0, move_name="EX"
    )
    assert effective == pytest.approx(2.4)
    assert warning is not None
    assert "4.0" in warning


def test_a_full_bank_grants_the_whole_request_silently() -> None:
    banks = ResourceBanks({"dps": 200.0}, {"dps": {}})
    effective, warning = clamp_channel_to_bank(
        _channel_move().channel, _costs(), banks, "dps", requested_s=4.0, move_name="EX"
    )
    assert effective == pytest.approx(4.0)
    assert warning is None


def test_the_clamp_never_exceeds_the_spec_max() -> None:
    """A rich bank does not buy a longer hold than the move allows."""
    banks = ResourceBanks({"dps": 10_000.0}, {"dps": {}})
    effective, _ = clamp_channel_to_bank(
        _channel_move().channel, _costs(), banks, "dps", requested_s=99.0, move_name="EX"
    )
    assert effective == pytest.approx(4.0)


def test_a_drainless_channel_is_never_clamped() -> None:
    """No drain means the bank cannot bound it -- dividing by zero would be the bug here."""
    move = MoveBuildupSpec(
        channel=ChannelSpec(
            max_s=4.0, default_s=2.0, tick_s=0.5, roles={"X Per Sec": "tick"}
        )
    )
    banks = ResourceBanks({"dps": 0.0}, {"dps": {}})
    effective, warning = clamp_channel_to_bank(
        move.channel, _costs(), banks, "dps", requested_s=4.0, move_name="EX"
    )
    assert effective == pytest.approx(4.0)
    assert warning is None


def test_bill_is_a_value_object_not_a_mutation() -> None:
    """`bill_for_move` decides; the caller debits. Keeps the decision testable in isolation."""
    bill = bill_for_move(_channel_move(), _costs(), channel_s=2.0, ex_energy_cost=40)
    assert isinstance(bill, ResourceBill)


# ---- the roster regression: nothing bills differently than it did ----------


def test_no_shipped_move_binds_a_cost_yet() -> None:
    """Task 11's regression assert, as a ledger rather than a vibe.

    Every agent with no channel and no cost-key binding must bill exactly what it billed
    before this task, and the only way to be sure of that across ~26 files is to enumerate
    the moves that *do* bind. A binding that appears without touching this test is a binding
    nobody decided on.

    Task 12 (2026-08-19) added the first two entries: Burnice's paired EX channels. Every
    other move still takes the `ex_energy_cost` branch and no number moved for them.
    """
    from app.data.loaders.moves import load_agent_moves

    bound = {
        f"{stem}:{name}"
        for stem, spec in load_agent_moves().items()
        for name, move in spec.moves.items()
        if move.channel is not None or move.cost_key
    }
    assert bound == {
        "burnice:EX Special Attack: Intense Heat Stirring Method",
        "burnice:EX Special Attack: Intense Heat Stirring Method - Double Shot",
        "norma:EX Special Attack: En-Nah Barrage",
        "trigger:Basic Attack: Silenced Shot",
        "yixuan:EX Special Attack: Cloud-Shaper",
    }


def test_an_empty_cost_table_bills_the_scalar() -> None:
    """A migrated-but-not-re-seeded DB has no rows. It must degrade to today's behaviour...

    ...not to free moves. `resource_costs` empty means "bill the scalar", which is exactly
    what the simulator did before this task existed.
    """
    bill = bill_for_move(MoveBuildupSpec(), {}, channel_s=None, ex_energy_cost=60)
    assert bill.amount == pytest.approx(60.0)
    assert bill.warnings == []


# ---- the lazy-load hazard -------------------------------------------------


def test_unloaded_relationship_reads_as_empty_without_touching_the_attribute() -> None:
    """A lazy `resource_costs` must never be *accessed* while building a snapshot.

    Under asyncpg a lazy load from sync code is not slow, it is a hard `MissingGreenlet`.
    `getattr(agent, "resource_costs", None)` does NOT protect against it — the attribute
    exists, so the descriptor fires anyway. This is a regression pin: the whole abloom
    crossval suite went red on exactly that, and the fixtures are what caught it.
    """
    from app.services.snapshot_builder import _resource_costs_of

    class _Exploding:
        @property
        def resource_costs(self):
            raise AssertionError("attribute was accessed — a real ORM instance would emit IO")

    assert _resource_costs_of(_Exploding()) == {}


def test_loaded_relationship_is_read_from_dict() -> None:
    from app.services.snapshot_builder import _resource_costs_of

    class _Row:
        cost_key, value, per_sec, resource = "K", 12.5, True, "Energy"

    class _Agent:
        pass

    agent = _Agent()
    agent.__dict__["resource_costs"] = [_Row()]
    assert _resource_costs_of(agent) == {"K": (12.5, True, "Energy")}
