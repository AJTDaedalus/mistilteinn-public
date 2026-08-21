"""Task 5 — the generic resource-bank helper, extracted from the aftershock path.

`anomaly_simulator` already maintained named banks, but only inside the aftershock
gate/consume pair. The channel bill (Task 11) needs the same arithmetic against the same
dicts, and a second copy of "which dict holds this resource, and how do I clamp it" is
exactly how two callers end up disagreeing about an agent's balance.
"""

from __future__ import annotations

import pytest

from app.services.resource_banks import ResourceBanks


def _banks(energy=None, named=None) -> tuple[ResourceBanks, dict, dict]:
    energy = energy if energy is not None else {"dps": 100.0}
    named = named if named is not None else {"dps": {}}
    return ResourceBanks(energy=energy, named=named), energy, named


# ---- Energy is not a bank like the others ---------------------------------


def test_energy_reads_the_energy_dict() -> None:
    banks, _, _ = _banks(energy={"dps": 72.0})
    assert banks.balance("dps", "energy") == pytest.approx(72.0)


def test_energy_is_matched_case_insensitively() -> None:
    """Aftershock specs say "energy"; agent_resource_costs rows say "Energy".

    A capitalised row falling through to the named-bank path would invent a second, empty
    Energy pool -- every EX would read as unaffordable while the real bank sat full.
    """
    banks, _, named = _banks(energy={"dps": 72.0})
    assert banks.balance("dps", "Energy") == pytest.approx(72.0)
    banks.debit("dps", "Energy", 12.0)
    assert banks.balance("dps", "energy") == pytest.approx(60.0)
    assert named["dps"] == {}


def test_debiting_energy_mutates_the_caller_s_dict() -> None:
    """The simulator mutates `energy` in a dozen other places; the helper must share it."""
    banks, energy, _ = _banks(energy={"dps": 100.0})
    banks.debit("dps", "energy", 40.0)
    assert energy["dps"] == pytest.approx(60.0)


# ---- named banks ----------------------------------------------------------


def test_named_bank_starts_empty_and_credits() -> None:
    banks, _, named = _banks()
    assert banks.balance("dps", "Windbloom") == 0.0
    banks.credit("dps", "Windbloom", 90.0)
    assert banks.balance("dps", "Windbloom") == pytest.approx(90.0)
    assert named["dps"]["Windbloom"] == pytest.approx(90.0)


def test_named_banks_are_per_agent() -> None:
    banks, _, _ = _banks(energy={"dps": 0.0, "support1": 0.0}, named={"dps": {}, "support1": {}})
    banks.credit("dps", "Heat", 100.0)
    assert banks.balance("support1", "Heat") == 0.0


def test_an_unknown_agent_reads_zero_rather_than_raising() -> None:
    """A step for an agent with no bank must not take the request down."""
    banks, _, _ = _banks()
    assert banks.balance("nobody", "Heat") == 0.0


# ---- clamping is the behaviour being preserved ----------------------------


def test_debit_clamps_at_zero() -> None:
    """Preserved verbatim from `_aftershock_consume`: a bank never goes negative."""
    banks, energy, _ = _banks(energy={"dps": 10.0})
    banks.debit("dps", "energy", 40.0)
    assert energy["dps"] == 0.0


def test_debit_returns_what_was_actually_spent() -> None:
    """The caller needs the truth to warn on a short bank, not the amount it asked for."""
    banks, _, _ = _banks(energy={"dps": 10.0})
    assert banks.debit("dps", "energy", 40.0) == pytest.approx(10.0)
    assert banks.debit("dps", "energy", 5.0) == 0.0


def test_credit_respects_a_cap() -> None:
    banks, _, _ = _banks()
    banks.credit("dps", "Heat", 80.0, cap=100.0)
    banks.credit("dps", "Heat", 80.0, cap=100.0)
    assert banks.balance("dps", "Heat") == pytest.approx(100.0)


def test_credit_without_a_cap_is_unbounded() -> None:
    banks, _, _ = _banks()
    banks.credit("dps", "Heat", 80.0)
    banks.credit("dps", "Heat", 80.0)
    assert banks.balance("dps", "Heat") == pytest.approx(160.0)


def test_can_afford_uses_a_floor_distinct_from_the_cost() -> None:
    """Orphie needs >=60 Energy but spends 30 -- availability floor, not cost (aftershock rule)."""
    banks, _, _ = _banks(energy={"dps": 45.0})
    assert banks.can_afford("dps", "energy", 30.0) is True
    assert banks.can_afford("dps", "energy", 30.0, floor=60.0) is False


def test_a_zero_cost_is_always_affordable() -> None:
    banks, _, _ = _banks(energy={"dps": 0.0})
    assert banks.can_afford("dps", "energy", 0.0) is True


def test_no_resource_named_is_always_affordable() -> None:
    """A spec with no `resource` is ungated -- the aftershock path's existing behaviour."""
    banks, _, _ = _banks(energy={"dps": 0.0})
    assert banks.can_afford("dps", None, 30.0) is True
