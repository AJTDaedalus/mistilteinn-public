"""Unit tests for `ChannelSpec` — the channel (hold-to-drain) move annotation.

Task 6 of docs/TASKS_channeled_moves.md, DESIGN_channeled_moves.md §4.2/§4.3.

The loader is DB-free by design (same contract as the agent-binding checks in
test_loader_agent_binding.py): it validates the *internal coherence* of a channel
block, never whether `roles` keys name real `attacks.param_name` rows for this
agent. That DB-backed check is harness level LCH (Task 13).
"""

import json
from pathlib import Path

import pytest

from app.data.loaders.moves import ChannelSpec, load_agent_moves
from app.models.enums import HitMode


def _move_file(directory: Path, channel: dict) -> Path:
    data = {
        "agent_id": "019e4c7e-6982-7711-a389-2c3d04c41097",
        "agent_name": "Alice",
        "moves": {"Basic Attack: Starshine Waltz": {"scope": "basic", "channel": channel}},
    }
    (directory / "alice.json").write_text(json.dumps(data))
    return directory


_PER_SECOND = {
    "max_s": 4.0,
    "default_s": 2.0,
    "tick_s": 0.5,
    "tick_mv_basis": "per_second",
    "roles": {"Spray DMG Multiplier Per Sec": "tick", "Blast DMG Multiplier": "release"},
}

_WHOLE_CHANNEL = {
    "max_s": 4.0,
    "default_s": 2.0,
    "tick_s": 0.5,
    "tick_mv_basis": "whole_channel",
    "nominal_s": 2.5,
    "roles": {"Continuous Spray DMG Multiplier": "tick", "Fire Blast DMG Multiplier": "release"},
}


def test_hit_mode_has_channel_member() -> None:
    assert HitMode("channel") is HitMode.CHANNEL


def test_per_second_spec_loads(tmp_path: Path) -> None:
    specs = load_agent_moves(_move_file(tmp_path, _PER_SECOND))
    ch = specs["alice"].moves["Basic Attack: Starshine Waltz"].channel
    assert ch is not None
    assert ch.tick_mv_basis == "per_second"
    assert ch.nominal_s is None


def test_whole_channel_spec_loads(tmp_path: Path) -> None:
    specs = load_agent_moves(_move_file(tmp_path, _WHOLE_CHANNEL))
    ch = specs["alice"].moves["Basic Attack: Starshine Waltz"].channel
    assert ch is not None
    assert ch.nominal_s == 2.5


def test_whole_channel_without_nominal_s_defaults_to_max_s(tmp_path: Path) -> None:
    """Owner ruling D-CH2: a whole-duration MV is the total at MAXIMUM hold.

    Holding is how you *collect* the listed multiplier and cannot exceed it, so `nominal_s`
    is `max_s` unless a move genuinely disagrees. Assigned rather than left `None` so every
    consumer reads one field instead of re-deriving the default, possibly differently.
    """
    spec = {**_WHOLE_CHANNEL}
    del spec["nominal_s"]
    specs = load_agent_moves(_move_file(tmp_path, spec))
    ch = specs["alice"].moves["Basic Attack: Starshine Waltz"].channel
    assert ch is not None
    assert ch.nominal_s == ch.max_s


def test_an_explicit_nominal_s_still_wins(tmp_path: Path) -> None:
    """D-CH2 is a default, not a hard collapse — a move that really differs can say so."""
    specs = load_agent_moves(_move_file(tmp_path, {**_WHOLE_CHANNEL, "nominal_s": 1.25}))
    ch = specs["alice"].moves["Basic Attack: Starshine Waltz"].channel
    assert ch is not None
    assert ch.nominal_s == 1.25


def test_per_second_with_nominal_s_raises(tmp_path: Path) -> None:
    """A per_second row is already a rate; a nominal_s would be silently ignored, and a
    field that looks load-bearing but is not is exactly how a 2x hides."""
    with pytest.raises(ValueError, match="nominal_s"):
        load_agent_moves(_move_file(tmp_path, {**_PER_SECOND, "nominal_s": 2.5}))


def test_unknown_role_raises(tmp_path: Path) -> None:
    bad = {**_PER_SECOND, "roles": {"Spray DMG Multiplier Per Sec": "sustain"}}
    with pytest.raises(ValueError, match="unknown channel roles"):
        load_agent_moves(_move_file(tmp_path, bad))


def test_no_tick_row_raises(tmp_path: Path) -> None:
    """A channel with nothing to scale is not a channel."""
    bad = {**_PER_SECOND, "roles": {"Blast DMG Multiplier": "release"}}
    with pytest.raises(ValueError, match="tick"):
        load_agent_moves(_move_file(tmp_path, bad))


def test_unknown_basis_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tick_mv_basis"):
        load_agent_moves(_move_file(tmp_path, {**_PER_SECOND, "tick_mv_basis": "per_minute"}))


def test_default_outside_bounds_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="default_s"):
        load_agent_moves(_move_file(tmp_path, {**_PER_SECOND, "default_s": 9.0}))


def test_non_positive_tick_s_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tick_s"):
        load_agent_moves(_move_file(tmp_path, {**_PER_SECOND, "tick_s": 0.0}))


def test_drain_cost_key_requires_the_other_two(tmp_path: Path) -> None:
    """Cost keys are bound as a set: a drain with no activation would bill a channel as
    free to start, which is never the real mechanic (DESIGN §4.5)."""
    bad = {**_PER_SECOND, "drain_cost_key": "X_Property_ExSpecial_SpCostValue_02"}
    with pytest.raises(ValueError, match="entry_cost_key"):
        load_agent_moves(_move_file(tmp_path, bad))


def test_shipped_files_still_load_unchanged() -> None:
    """Only Burnice's two EX modes set `channel`; every other file is untouched.

    Was "no committed move file sets `channel`" while Task 6 was schema-only. Task 12
    authored the first two, so the assertion becomes a ledger of which moves opted in —
    the same shape as `test_no_shipped_move_binds_a_cost_yet`, and for the same reason:
    a channel appearing without a decision should fail a test, not pass one.
    """
    specs = load_agent_moves()
    assert len(specs) == 27
    channelled = {
        f"{stem}:{name}"
        for stem, spec in specs.items()
        for name, m in spec.moves.items()
        if m.channel is not None
    }
    assert channelled == {
        "burnice:EX Special Attack: Intense Heat Stirring Method",
        "burnice:EX Special Attack: Intense Heat Stirring Method - Double Shot",
        "norma:EX Special Attack: En-Nah Barrage",
        "trigger:Basic Attack: Silenced Shot",
        "yixuan:EX Special Attack: Cloud-Shaper",
    }


def test_channel_spec_constructs_directly() -> None:
    """Tests build these in memory as simulator fixtures, same as AgentMovesSpec."""
    ch = ChannelSpec(tick_s=0.5, max_s=4.0, default_s=2.0, roles={"A": "tick"})
    assert ch.tick_mv_basis == "per_second"
    assert ch.min_s == 0.0
