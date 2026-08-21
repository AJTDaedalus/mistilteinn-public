"""Task 27 — the structured `lumiflux` block on a Lumiflux agent's kit JSON
(issue #84, DESIGN_remielle.md §13.1).

Before this task every `LumifluxSpec` coefficient existed only as English prose
in `remielle.json`'s `notes` and as a hand-built fixture inside the unit tests.
Nothing could load them, which is half of why the subsystem shipped inert
(escalation E-5). These tests pin three things:

1. the shipped block is complete and matches `LumifluxSpec`'s field list;
2. the two mirror maps (`refringe_flat_bonuses`, `luminize_multipliers`) agree
   with the files that *are* the source of truth for those numbers — the
   modifier rows and `moves/agents/remielle.json` respectively, so the
   duplication is a checked invariant rather than a drift hazard;
3. the L0 harness rejects a missing key, an unknown key, and a missing block.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.lumiflux import LumifluxSpec
from scripts.validate_kits import check_l0, lumiflux_spec_keys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REMIELLE_KIT = BACKEND_ROOT / "app" / "data" / "modifiers" / "agents" / "remielle.json"
REMIELLE_MOVES = BACKEND_ROOT / "app" / "data" / "moves" / "agents" / "remielle.json"


def _kit() -> dict:
    return json.loads(REMIELLE_KIT.read_text())


def _block() -> dict:
    return _kit()["lumiflux"]


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


class TestShippedBlock:
    """The committed block is loadable and complete."""

    def test_block_exists_and_is_an_object(self) -> None:
        assert isinstance(_block(), dict)

    def test_block_covers_every_lumiflux_spec_field(self) -> None:
        assert lumiflux_spec_keys() <= set(_block())

    def test_block_carries_no_key_lumiflux_spec_cannot_read(self) -> None:
        # `notes` is the one permitted extra — prose, deliberately not loaded.
        assert set(_block()) - lumiflux_spec_keys() == {"notes"}

    def test_block_constructs_a_lumiflux_spec(self) -> None:
        block = {k: v for k, v in _block().items() if k != "notes"}
        for key in ("flight_attack_points", "flight_attack_mv_bp", "flight_attack_daze_bp"):
            block[key] = tuple(block[key])
        spec = LumifluxSpec(**block)
        assert spec.point_cap == 4
        assert spec.voidflare_cap == 3
        # 0.02%/AP. db(core_skills) — flat across levels 1-7, so the max-level
        # convention is a no-op for this one.
        assert spec.refringe_ap_ratio_bp == 2
        # 0.2%/AP. db(core_skills, level 7) — the authored point per D-KV4's
        # max-level convention. The DB curve runs 0.1/0.12/0.14/0.15/0.16/0.18/0.2%
        # over core levels 1-7; authoring the level-1 end of it was audit finding
        # S1-B, fixed in hardening Task 1.
        assert spec.luminize_ap_bonus_bp == 20
        assert spec.phase_flow_tick_s == 5.0  # guide line 90

    def test_phase_flow_duration_is_the_floating_radiance_cap_over_its_drain_rate(self) -> None:
        # guide line 88 (cap 120) / guide line 90 ("lose 3 Floating Radiance per
        # second"). Explicitly NOT the 60s team DMG buff on the Special Attack row.
        assert _block()["phase_flow_duration_s"] == pytest.approx(120 / 3)

    def test_flight_attack_tuples_are_slot_aligned(self) -> None:
        block = _block()
        lengths = {
            len(block["flight_attack_points"]),
            len(block["flight_attack_mv_bp"]),
            len(block["flight_attack_daze_bp"]),
        }
        assert lengths == {3}


class TestMirrorsStayInStep:
    """Neither map is a source of truth; both must agree with the file that is."""

    def test_refringe_flat_bonuses_mirror_the_modifier_rows(self) -> None:
        """Bound BY KEY, not by value-set (tests-review finding T-M3b).

        The old assertion compared `{row values} == {block values}`, i.e.
        `{1000, 2000} == {1000, 2000}`. That passes just as happily if the two
        entries are swapped -- the +10%-at-3-Anomaly core term labelled `m2`
        and the M2 term labelled `anomaly_count_3_in_team` -- which is exactly
        the drift this mirror exists to catch.
        """
        rows = [
            mod
            for mod in _kit()["modifiers"]
            if mod.get("stat") == "refringe_flat_bonus_bp"
        ]
        # A row's mirror key is its gating condition, or `m<N>` when the gate
        # is a mindscape tier rather than a condition.
        authored = {}
        for mod in rows:
            conditions = mod.get("conditions") or ["always"]
            gate = next((c for c in conditions if c != "always"), None)
            key = gate if gate is not None else f"m{mod.get('min_mindscape', 0)}"
            authored[key] = mod["value"]

        assert authored == _block()["refringe_flat_bonuses"]

    def test_luminize_multipliers_mirror_the_move_entries(self) -> None:
        moves = json.loads(REMIELLE_MOVES.read_text())["moves"]
        authored = {
            name: move["luminize_mult_bp"]
            for name, move in moves.items()
            if move.get("triggers_luminize")
        }
        assert _block()["luminize_multipliers"] == authored


class TestHarnessRejectsBadBlocks:
    """L0 is the CI-time defense; Task 28's loader is the runtime one."""

    def _run(self, kit: dict) -> set[str]:
        # `_is_lumiflux_agent` keys off the moves file, so use the real path.
        return _codes(check_l0([(REMIELLE_KIT, kit)]))

    def test_shipped_kit_is_clean(self) -> None:
        assert self._run(_kit()) == set()

    def test_missing_key_is_a_finding_naming_the_key(self) -> None:
        kit = _kit()
        del kit["lumiflux"]["voidflare_cap"]
        findings = check_l0([(REMIELLE_KIT, kit)])
        assert "incomplete_lumiflux_block" in _codes(findings)
        assert any("voidflare_cap" in f.message for f in findings)

    def test_misspelled_key_reports_both_the_absence_and_the_stray(self) -> None:
        kit = _kit()
        kit["lumiflux"]["voidflare_capp"] = kit["lumiflux"].pop("voidflare_cap")
        findings = check_l0([(REMIELLE_KIT, kit)])
        assert {"incomplete_lumiflux_block", "unknown_lumiflux_key"} <= _codes(findings)
        assert any("voidflare_capp" in f.message for f in findings)

    def test_unknown_key_is_a_finding(self) -> None:
        kit = _kit()
        kit["lumiflux"]["refringe_ap_ratio"] = 2  # plausible, and read by nothing
        findings = check_l0([(REMIELLE_KIT, kit)])
        assert "unknown_lumiflux_key" in _codes(findings)
        assert any("refringe_ap_ratio'" in f.message for f in findings)

    def test_null_value_is_a_finding(self) -> None:
        kit = _kit()
        kit["lumiflux"]["point_cap"] = None
        assert "incomplete_lumiflux_block" in self._run(kit)

    def test_missing_block_on_a_lumiflux_agent_is_a_finding(self) -> None:
        kit = _kit()
        del kit["lumiflux"]
        assert "missing_lumiflux_block" in self._run(kit)

    def test_missing_block_on_a_non_lumiflux_agent_is_not(self) -> None:
        kit = _kit()
        del kit["lumiflux"]
        other = REMIELLE_KIT.parent / "lucy.json"
        assert _codes(check_l0([(other, kit)])) == set()

    def test_slot_misaligned_flight_tuples_are_a_finding(self) -> None:
        kit = _kit()
        kit["lumiflux"]["flight_attack_daze_bp"] = [27500, 37820]
        assert "incoherent_lumiflux_block" in self._run(kit)


class TestWholeCorpusStillClean:
    def test_no_shipped_kit_regresses(self) -> None:
        from scripts.validate_kits import iter_kits

        assert [f for f in check_l0(iter_kits()) if "lumiflux" in f.code] == []
