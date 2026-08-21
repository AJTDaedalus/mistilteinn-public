"""Tasks 1 & 2 — resource_costs.json curation and regen-stability."""

from __future__ import annotations

import json
from pathlib import Path

EXTRACT_PATH = (
    Path(__file__).parent.parent.parent
    / "app/data/dimbreath/schema/resource_costs.json"
)

AMBIGUOUS_AGENTS = [
    "banyue",
    "burnice",
    "caesar",
    "corin",
    "lighter",
    "lycaon",
    "nicole",
    "norma",
    "qingyi",
    "seed",
    "soukaku",
    "yixuan",
]


def _load() -> dict:
    return json.loads(EXTRACT_PATH.read_text())


def test_all_ambiguous_agents_have_provenance():
    """Every historically-ambiguous agent carries a non-empty provenance note."""
    data = _load()
    agents = data["agents"]
    for name in AMBIGUOUS_AGENTS:
        assert name in agents, f"{name} missing from extract"
        note = agents[name].get("provenance", "")
        assert note, f"{name} has empty provenance"


def test_all_ambiguous_agents_have_numeric_ex_energy_cost():
    """Every historically-ambiguous agent has a numeric (non-null) ex_energy_cost."""
    data = _load()
    agents = data["agents"]
    for name in AMBIGUOUS_AGENTS:
        cost = agents[name].get("ex_energy_cost")
        assert cost is not None, f"{name} ex_energy_cost is None"
        assert isinstance(cost, (int, float)), f"{name} ex_energy_cost is not numeric: {cost!r}"
        assert cost > 0, f"{name} ex_energy_cost is not positive: {cost}"


def test_nicole_primary_corrected_to_60():
    """Nicole's on-press EX activation is 60 (Bombard), not 20 (which is a per-sec drain)."""
    data = _load()
    assert data["agents"]["nicole"]["ex_energy_cost"] == 60.0


def test_nicole_hold_drain_marked_per_sec():
    """Nicole's 20 Energy/sec hold drain must be flagged per_sec=True."""
    data = _load()
    hold_drain = next(
        c for c in data["agents"]["nicole"]["costs"]
        if c["key"] == "Nostradamus_Property_ExSpecial_SpCostValue_01"
    )
    assert hold_drain["per_sec"] is True, "Nicole hold-drain entry should have per_sec=True"
    assert hold_drain["value"] == 20.0


# --- Task 2: extract integrity (regen-stable) ---

VALID_COST_SOURCES = {"textmap_property", "manual_override"}


def test_extract_has_56_agents():
    """Committed extract covers the full 56-agent roster."""
    data = _load()
    assert data["roster"] == 56
    assert len(data["agents"]) == 56


def test_every_agent_has_avatar_id():
    """Every agent entry carries a numeric avatar_id for DB join."""
    data = _load()
    for name, agent in data["agents"].items():
        assert "avatar_id" in agent, f"{name} missing avatar_id"
        assert isinstance(agent["avatar_id"], int), f"{name} avatar_id not int"


def test_every_agent_cost_source_is_valid():
    """cost_source is one of the two expected values."""
    data = _load()
    for name, agent in data["agents"].items():
        src = agent.get("cost_source")
        assert src in VALID_COST_SOURCES, (
            f"{name} cost_source={src!r} not in {VALID_COST_SOURCES}"
        )


def test_every_agent_ex_energy_cost_is_numeric_or_null():
    """ex_energy_cost is a number (int/float) or null — never absent."""
    data = _load()
    for name, agent in data["agents"].items():
        cost = agent.get("ex_energy_cost", "ABSENT")
        assert cost != "ABSENT", f"{name} missing ex_energy_cost key"
        if cost is not None:
            assert isinstance(cost, (int, float)), (
                f"{name} ex_energy_cost has unexpected type {type(cost)}"
            )


def test_no_preview_banner():
    """_preview key must be absent — the extract is committed, not a draft."""
    data = _load()
    assert "_preview" not in data, "_preview banner still present; remove before committing"
