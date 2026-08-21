"""LR — roster coverage (DESIGN_kit_accuracy_gate.md D7, TASKS Track D, Tasks D1/D2).

Every other harness level iterates the kit JSONs that exist, so an entity with *no*
file is invisible to all of them by construction. LR closes that: the DB roster is
the universe, and every uncovered entity must be either curated or deliberately,
owner-authorizedly ledgered. These tests exercise the pure diff
(`_roster_findings`) with synthetic rosters — the same DB-free split every DB-backed
level here uses — plus the skip contract and registry wiring.

The motivating gap is pinned as the shape of the synthetic data: an S-rank engine
that is the signature of an already-curated agent (the Norma/Pyrois case) must
outrank every other finding.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.validate_kits import (
    LEVELS,
    LR_CODES,
    LR_STATUS,
    MalformedCoverageLedgerError,
    _roster_findings,
    _unrunnable_waiver_codes,
    load_coverage_ledger,
    load_signature_map,
    unrunnable_levels,
)


def _roster() -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "agent": {
            "1551": {"name": "Pyrois", "rarity": "S", "specialty": ""},
            "1591": {"name": "Sigrid", "rarity": "S", "specialty": ""},
        },
        "w_engine": {
            "14155": {"name": "Sol Exuvia", "rarity": "S", "specialty": "attack"},
            "13018": {"name": "Boisterous Echoes", "rarity": "A", "specialty": "anomaly"},
            "14000": {"name": "Covered Engine", "rarity": "S", "specialty": "attack"},
        },
        "disc_set": {"34000": {"name": "The Sky Ablaze", "rarity": "", "specialty": ""}},
    }


def _corpus() -> dict[str, set[str]]:
    # Pyrois is curated; his signature engine is not — the exact motivating gap.
    return {"agent": {"1551"}, "w_engine": {"14000"}, "disc_set": set()}


_SIGMAP = {"14155": {"agent_source_id": "1551", "agent_name": "Pyrois", "evidence": "test"}}


def _ledger_entry(**overrides: Any) -> dict[str, Any]:
    entry = {
        "entity_type": "w_engine",
        "source_id": "13018",
        "name": "Boisterous Echoes",
        "reason": "A-rank, no combat-relevant passive worth curating",
        "recorded_by": "test-curator",
        "authorized_by": "owner",
        "date": "2026-08-08",
    }
    entry.update(overrides)
    return entry


class TestUncovered:
    def test_every_unledgered_gap_is_a_finding(self) -> None:
        findings = _roster_findings(_roster(), _corpus(), [], {})
        keys = {(f.code, f.source_file) for f in findings}
        assert ("roster_uncovered", "agents/1591") in keys
        assert ("roster_uncovered", "w_engines/14155") in keys
        assert ("roster_uncovered", "w_engines/13018") in keys
        assert ("roster_uncovered", "disc_sets/34000") in keys

    def test_a_covered_entity_is_not_a_finding(self) -> None:
        findings = _roster_findings(_roster(), _corpus(), [], {})
        assert not any(f.source_file == "w_engines/14000" for f in findings)
        assert not any(f.source_file == "agents/1551" for f in findings)

    def test_a_sig_engine_of_a_curated_agent_ranks_first(self) -> None:
        """The Norma/Pyrois case: the gap most likely to matter is the one a user of a
        curated agent hits immediately — it must lead the report, not hide in it."""
        findings = _roster_findings(_roster(), _corpus(), [], _SIGMAP)
        assert findings[0].source_file == "w_engines/14155"
        assert "SIGNATURE ENGINE of curated agent Pyrois" in findings[0].message

    def test_s_rank_gaps_outrank_a_rank_gaps(self) -> None:
        findings = _roster_findings(_roster(), _corpus(), [], {})
        order = [f.source_file for f in findings if f.code == "roster_uncovered"]
        assert order.index("agents/1591") < order.index("w_engines/13018")

    def test_all_emitted_codes_are_registered(self) -> None:
        """Every code the pure function can emit must be in LR_CODES, or the
        stale-waiver exclusion would miss it — the drift L5_CODES exists to prevent."""
        ledger = [
            _ledger_entry(authorized_by=None),
            _ledger_entry(source_id="14000", name="Covered Engine"),
            _ledger_entry(source_id="99999", name="Ghost"),
        ]
        sigmap = dict(_SIGMAP, **{"88888": {"agent_source_id": "77777", "agent_name": "X"}})
        findings = _roster_findings(_roster(), _corpus(), ledger, sigmap)
        assert {f.code for f in findings} <= LR_CODES


class TestLedger:
    def test_an_authorized_entry_suppresses_the_gap(self) -> None:
        findings = _roster_findings(_roster(), _corpus(), [_ledger_entry()], {})
        assert not any(f.source_file == "w_engines/13018" for f in findings)

    def test_a_recorded_but_unauthorized_entry_still_fails(self) -> None:
        """A curator records; only the owner authorizes — `authorized_by: null` is a
        review queue, not a suppression (same rule as omissions[])."""
        findings = _roster_findings(_roster(), _corpus(), [_ledger_entry(authorized_by=None)], {})
        (f,) = [f for f in findings if f.source_file == "w_engines/13018"]
        assert f.code == "roster_unauthorized_ledger"

    def test_an_entry_whose_entity_gained_a_kit_is_stale(self) -> None:
        ledger = [_ledger_entry(source_id="14000", name="Covered Engine")]
        findings = _roster_findings(_roster(), _corpus(), ledger, {})
        assert any(
            f.code == "roster_stale_ledger" and f.source_file == "w_engines/14000"
            for f in findings
        )

    def test_an_entry_naming_no_db_row_fails(self) -> None:
        """A typo'd id must not silently authorize nothing."""
        ledger = [_ledger_entry(source_id="99999", name="Ghost Engine")]
        findings = _roster_findings(_roster(), _corpus(), ledger, {})
        assert any(f.code == "roster_ledger_unknown_entity" for f in findings)

    def test_the_committed_ledger_parses(self) -> None:
        load_coverage_ledger()  # raises MalformedCoverageLedgerError on a bad entry

    def test_a_malformed_entry_raises(self, tmp_path, monkeypatch) -> None:
        import scripts.validate_kits as vk

        bad = tmp_path / "coverage_ledger.json"
        bad.write_text('{"entries": [{"entity_type": "w_engine"}]}')
        monkeypatch.setattr(vk, "COVERAGE_LEDGER_PATH", bad)
        with pytest.raises(MalformedCoverageLedgerError):
            vk.load_coverage_ledger()


class TestSignatureMap:
    def test_an_unresolvable_map_entry_fails(self) -> None:
        sigmap = {"88888": {"agent_source_id": "77777", "agent_name": "Nobody"}}
        findings = _roster_findings(_roster(), _corpus(), [], sigmap)
        (f,) = [f for f in findings if f.code == "roster_sigmap_error"]
        assert "88888" in f.message
        assert "77777" in f.message

    def test_the_committed_map_entries_carry_evidence(self) -> None:
        """Every committed mapping must say where it came from — the field the
        poem_of_the_empty_feather_return misattribution (PR #103) was missing."""
        for eng_id, sig in load_signature_map().items():
            assert sig.get("evidence"), f"signature_map entry {eng_id} has no evidence"
            assert sig.get("agent_source_id"), f"signature_map entry {eng_id} names no agent"


class TestRegistryAndSkip:
    def test_lr_is_a_registered_level(self) -> None:
        assert "lr" in LEVELS

    def test_an_unreachable_db_makes_lr_unrunnable(self, monkeypatch) -> None:
        monkeypatch.setitem(LR_STATUS, "db_reachable", False)
        assert "lr" in unrunnable_levels(["lr"])
        assert _unrunnable_waiver_codes(["lr"]) >= LR_CODES

    def test_a_reachable_db_makes_lr_runnable(self, monkeypatch) -> None:
        monkeypatch.setitem(LR_STATUS, "db_reachable", True)
        assert "lr" not in unrunnable_levels(["lr"])
