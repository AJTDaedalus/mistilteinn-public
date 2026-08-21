"""Task 28 — `lumiflux_loader.load_lumiflux_spec` (DESIGN_remielle.md §13.1).

The contract worth pinning is the three-way split of outcomes:

* a Lumiflux agent's kit → a spec whose every field equals the JSON;
* any other agent (or an unknown id) → ``None``, quietly, because that is the
  ordinary case for the whole roster;
* a *present but incomplete* block → **raise**. Never a zero. A Refringe
  coefficient that silently defaults to 0 deletes the agent's kit while looking
  like a working build, which is the class of failure this whole phase exists
  to close.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.build_damage_service import BuildSnapshot
from app.services.lumiflux import LumifluxSpec
from app.services.lumiflux_loader import (
    LumifluxBlockError,
    _LumifluxBlock,
    load_lumiflux_spec,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REMIELLE_KIT = BACKEND_ROOT / "app" / "data" / "modifiers" / "agents" / "remielle.json"
REMIELLE_ID = "1581"


def _block() -> dict:
    return json.loads(REMIELLE_KIT.read_text())["lumiflux"]


class TestLoadsTheRealKit:
    def test_returns_a_spec_for_remielle(self) -> None:
        assert isinstance(load_lumiflux_spec(REMIELLE_ID), LumifluxSpec)

    def test_every_field_equals_the_json(self) -> None:
        spec = load_lumiflux_spec(REMIELLE_ID)
        assert spec is not None
        block = _block()
        assert spec.point_cap == block["point_cap"]
        assert spec.voidflare_cap == block["voidflare_cap"]
        assert spec.refringe_ap_ratio_bp == block["refringe_ap_ratio_bp"]
        assert spec.luminize_ap_bonus_bp == block["luminize_ap_bonus_bp"]
        assert spec.refringe_flat_bonuses == block["refringe_flat_bonuses"]
        assert spec.luminize_multipliers == block["luminize_multipliers"]
        assert spec.phase_flow_tick_s == block["phase_flow_tick_s"]
        assert spec.phase_flow_duration_s == block["phase_flow_duration_s"]
        assert spec.flight_attack_points == tuple(block["flight_attack_points"])
        assert spec.flight_attack_mv_bp == tuple(block["flight_attack_mv_bp"])
        assert spec.flight_attack_daze_bp == tuple(block["flight_attack_daze_bp"])

    def test_tuple_fields_are_tuples_not_lists(self) -> None:
        # `LumifluxSpec` is frozen and the tuples are read slot-wise; a list here
        # would be a mutable field on a "frozen" dataclass.
        spec = load_lumiflux_spec(REMIELLE_ID)
        assert spec is not None
        assert isinstance(spec.flight_attack_points, tuple)
        assert isinstance(spec.flight_attack_mv_bp, tuple)
        assert isinstance(spec.flight_attack_daze_bp, tuple)

    def test_notes_are_not_loaded_onto_the_spec(self) -> None:
        assert not hasattr(load_lumiflux_spec(REMIELLE_ID), "notes")


class TestNoneCases:
    def test_non_lumiflux_agent_returns_none(self) -> None:
        # Lucy — a real, shipped kit with no `lumiflux` block.
        lucy = json.loads((REMIELLE_KIT.parent / "lucy.json").read_text())
        assert load_lumiflux_spec(lucy["source_id"]) is None

    def test_unknown_source_id_returns_none(self) -> None:
        assert load_lumiflux_spec("nosuchagent") is None

    def test_empty_source_id_returns_none(self) -> None:
        # The `BuildSnapshot.agent_source_id` default. Hand-built snapshots in
        # tests carry it and must not blow up the assembler.
        assert load_lumiflux_spec("") is None


class TestIncompleteBlockRaises:
    """`_LumifluxBlock` is the parse seam; exercising it directly keeps these
    tests off the filesystem while testing the same model the loader uses."""

    def test_missing_coefficient_raises(self) -> None:
        block = _block()
        del block["voidflare_cap"]
        with pytest.raises(ValidationError) as exc:
            _LumifluxBlock.model_validate(block)
        assert "voidflare_cap" in str(exc.value)

    def test_unknown_key_raises_rather_than_being_dropped(self) -> None:
        block = _block()
        block["refringe_ap_ratio"] = 2  # plausible misspelling of a real field
        with pytest.raises(ValidationError) as exc:
            _LumifluxBlock.model_validate(block)
        assert "refringe_ap_ratio" in str(exc.value)

    def test_loader_wraps_a_broken_block_in_lumiflux_block_error(
        self, tmp_path, monkeypatch
    ) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        block = _block()
        del block["point_cap"]
        (agents / "broken.json").write_text(
            json.dumps({"source_type": "agent", "source_id": "9999", "lumiflux": block})
        )
        monkeypatch.setattr("app.services.lumiflux_loader._DATA_DIR", tmp_path)
        load_lumiflux_spec.cache_clear()
        try:
            with pytest.raises(LumifluxBlockError) as exc:
                load_lumiflux_spec("9999")
            assert "point_cap" in str(exc.value)
            assert "must not become a zero" in str(exc.value)
        finally:
            load_lumiflux_spec.cache_clear()


class TestCaching:
    def test_second_call_is_a_cache_hit(self) -> None:
        load_lumiflux_spec.cache_clear()
        try:
            load_lumiflux_spec(REMIELLE_ID)
            before = load_lumiflux_spec.cache_info().hits
            load_lumiflux_spec(REMIELLE_ID)
            assert load_lumiflux_spec.cache_info().hits == before + 1
        finally:
            load_lumiflux_spec.cache_clear()

    def test_none_results_are_cached_too(self) -> None:
        # The optimizer asks per non-Lumiflux teammate; a cache that only held
        # hits would rescan the kit directory on every miss.
        load_lumiflux_spec.cache_clear()
        try:
            load_lumiflux_spec("nosuchagent")
            misses = load_lumiflux_spec.cache_info().misses
            load_lumiflux_spec("nosuchagent")
            assert load_lumiflux_spec.cache_info().misses == misses
        finally:
            load_lumiflux_spec.cache_clear()


class TestBuildSnapshotIdentityField:
    def test_default_is_empty_so_hand_built_snapshots_stay_valid(self) -> None:
        assert BuildSnapshot(agent_name="X").agent_source_id == ""

    def test_field_round_trips(self) -> None:
        snap = BuildSnapshot(agent_name="Remielle", agent_source_id=REMIELLE_ID)
        assert load_lumiflux_spec(snap.agent_source_id) is not None
