"""Cross-file `(source_type, source_id)` uniqueness — the 14158 collision check.

Task H2 of `docs/TASKS_wengine_id_collision.md`. Two kit files claiming one id
means `modifier_loader._find_file_by_source_id` returns whichever the directory
glob yields first — found live when Velina's fabricated
`poem_of_the_empty_feather_return.json` claimed id 14158, which is Remielle's
"Ode of Resurrected Wings", and prod served her invented buffs for a real item.

Same split as the other harness test files: rule tests drive the check with
synthetic kits; a corpus test pins the shipped tree collision-free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.validate_kits import _check_duplicate_source_ids, check_l0, iter_kits


def _kit(rel: str, source_type: str, source_id: str) -> tuple[Path, dict[str, Any]]:
    return (
        Path(rel),
        {
            "source_type": source_type,
            "source_id": source_id,
            "source_name": Path(rel).stem.title(),
            "confidence": "draft",
            "modifiers": [],
        },
    )


@pytest.fixture(scope="module")
def corpus() -> list[tuple[Path, dict[str, Any]]]:
    return iter_kits()


class TestDuplicateSourceIdRule:
    def test_two_kits_sharing_an_id_produce_two_findings(self):
        kits = [
            _kit("w_engines/a.json", "w_engine", "9999"),
            _kit("w_engines/b.json", "w_engine", "9999"),
        ]
        findings = _check_duplicate_source_ids(kits)
        assert len(findings) == 2
        assert {f.code for f in findings} == {"duplicate_source_id"}
        assert {f.source_file for f in findings} == {
            "w_engines/a.json",
            "w_engines/b.json",
        }
        # Each finding names the OTHER members, so the report is actionable
        # from either side.
        by_file = {f.source_file: f for f in findings}
        assert "w_engines/b.json" in by_file["w_engines/a.json"].message
        assert "w_engines/a.json" in by_file["w_engines/b.json"].message

    def test_findings_are_file_level(self):
        kits = [
            _kit("w_engines/a.json", "w_engine", "9999"),
            _kit("w_engines/b.json", "w_engine", "9999"),
        ]
        assert all(f.index == -1 for f in _check_duplicate_source_ids(kits))
        assert all(f.level == "L0" for f in _check_duplicate_source_ids(kits))

    def test_same_id_across_source_types_is_no_collision(self):
        kits = [
            _kit("agents/a.json", "agent", "9999"),
            _kit("w_engines/b.json", "w_engine", "9999"),
        ]
        assert _check_duplicate_source_ids(kits) == []

    def test_distinct_ids_produce_nothing(self):
        kits = [
            _kit("w_engines/a.json", "w_engine", "9998"),
            _kit("w_engines/b.json", "w_engine", "9999"),
        ]
        assert _check_duplicate_source_ids(kits) == []

    def test_three_way_collision_flags_every_member(self):
        kits = [
            _kit("w_engines/a.json", "w_engine", "9999"),
            _kit("w_engines/b.json", "w_engine", "9999"),
            _kit("w_engines/c.json", "w_engine", "9999"),
        ]
        findings = _check_duplicate_source_ids(kits)
        assert len(findings) == 3
        by_file = {f.source_file: f for f in findings}
        assert "w_engines/b.json" in by_file["w_engines/a.json"].message
        assert "w_engines/c.json" in by_file["w_engines/a.json"].message

    def test_check_l0_runs_the_rule(self):
        """The rule must reach `check_l0` — a check the pipeline never calls
        is a check nobody has."""
        kits = [
            _kit("w_engines/a.json", "w_engine", "9999"),
            _kit("w_engines/b.json", "w_engine", "9999"),
        ]
        codes = {f.code for f in check_l0(kits)}
        assert "duplicate_source_id" in codes


class TestShippedCorpus:
    def test_no_collisions_in_the_shipped_tree(self, corpus):
        assert _check_duplicate_source_ids(corpus) == []
