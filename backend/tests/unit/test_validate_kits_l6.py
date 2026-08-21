"""Unit tests for `validate_kits` L6 — upstream multiplier cross-check (issue #165).

L6 exists because the two levels that check move data against ground truth, L4 and L5,
both resolve a key against DB `attacks` rows — and some damage-bearing skills have no
such row at all. nanoka publishes only the moves the in-game skill panel lists, so
Remielle's Phase Flow flight attacks (upstream 1581022-24) are seeded nowhere, and the
three multipliers her Phase Flow damage channel is built on are a hand-copy that the
whole gate reported green without ever inspecting.

What these tests pin, therefore, is not "does the shipped kit pass" — a level that
returns no findings passes that test whether or not it can see anything. It is that L6
**fires**: on a drifted value, on a citation the snapshot cannot answer, on a
hand-copy-shaped key that nobody enrolled, and on a snapshot built at a SHA the toolkit
no longer pins.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.validate_kits import (
    L6_CODES,
    LEVELS,
    _hand_copy_paths,
    check_l6,
    iter_kits,
)

_SNAPSHOT = {
    "_meta": {"pinned_sha": "deadbeef", "table": "AvatarSkillTemplateTb"},
    "skills": {
        # base 8130 (+740/level) → Lv.12 = 8130 + 740*11 = 16270
        "1581022": {"damage_base": 8130, "damage_growth": 740,
                    "stun_base": 27500, "stun_growth": 1250},
        # base 20320 (+1850/level) → Lv.12 = 40670
        "1581023": {"damage_base": 20320, "damage_growth": 1850,
                    "stun_base": 37820, "stun_growth": 1720},
    },
}


def _kit(**overrides: Any) -> list[tuple[Path, dict[str, Any]]]:
    kit: dict[str, Any] = {
        "source_name": "Testmon",
        "lumiflux": {"flight_attack_mv_bp": [16270, 40670]},
        "upstream_mv_checks": [
            {
                "path": "lumiflux.flight_attack_mv_bp",
                "skill_ids": [1581022, 1581023],
                "quantity": "damage",
                "skill_level": 12,
            }
        ],
    }
    kit.update(overrides)
    return [(Path("agents/testmon.json"), kit)]


def _run(kits: list[tuple[Path, dict[str, Any]]], snapshot: Any = _SNAPSHOT) -> list[str]:
    with (
        patch("scripts.validate_kits._load_upstream_snapshot", return_value=snapshot),
        patch("scripts.validate_kits._snapshot_findings", return_value=[]),
    ):
        return [f.code for f in check_l6(kits)]


def test_matching_tuple_passes() -> None:
    assert _run(_kit()) == []


def test_drifted_value_is_caught() -> None:
    """The defect the level exists for: the copy stops matching what it was copied from."""
    kits = _kit(lumiflux={"flight_attack_mv_bp": [16270, 40671]})
    assert _run(kits) == ["upstream_mv_mismatch"]


def test_lv1_values_where_lv12_was_intended_are_caught() -> None:
    """The real slip this shape has already produced once (remielle hardening Task 2:
    the tuple shipped Lv.1 bases against a Lv.12 convention)."""
    kits = _kit(lumiflux={"flight_attack_mv_bp": [8130, 20320]})
    assert _run(kits) == ["upstream_mv_mismatch", "upstream_mv_mismatch"]


def test_daze_quantity_reads_the_stun_columns() -> None:
    kits = _kit(
        lumiflux={"flight_attack_daze_bp": [41250, 56740]},
        upstream_mv_checks=[
            {
                "path": "lumiflux.flight_attack_daze_bp",
                "skill_ids": [1581022, 1581023],
                "quantity": "daze",
                "skill_level": 12,
            }
        ],
    )
    assert _run(kits) == []


def test_skill_id_absent_from_snapshot_blocks_rather_than_passes() -> None:
    """"Could not check" is not "checked and clean" — the harness's standing rule."""
    kits = _kit(
        upstream_mv_checks=[
            {
                "path": "lumiflux.flight_attack_mv_bp",
                "skill_ids": [1581022, 9999999],
                "quantity": "damage",
                "skill_level": 12,
            }
        ]
    )
    assert _run(kits) == ["upstream_mv_unknown_skill"]


@pytest.mark.parametrize(
    "check",
    [
        {"skill_ids": [1581022], "quantity": "damage", "skill_level": 12},  # no path
        {"path": "lumiflux.flight_attack_mv_bp", "skill_ids": [1581022],
         "quantity": "sparkle", "skill_level": 12},
        {"path": "lumiflux.flight_attack_mv_bp", "skill_ids": [1581022],
         "quantity": "damage", "skill_level": 0},
        {"path": "lumiflux.nope", "skill_ids": [1581022],
         "quantity": "damage", "skill_level": 12},
        # two values, one cited id — positional alignment is the whole contract
        {"path": "lumiflux.flight_attack_mv_bp", "skill_ids": [1581022],
         "quantity": "damage", "skill_level": 12},
    ],
)
def test_malformed_declarations_are_rejected(check: dict[str, Any]) -> None:
    # A declaration that names no path (or the wrong one) also leaves the real key
    # unenrolled, so `upstream_mv_undeclared` legitimately rides along on those two
    # cases — both signals are true, and both name something a curator must fix.
    assert "upstream_mv_bad_declaration" in _run(_kit(upstream_mv_checks=[check]))


def test_hand_copy_key_with_no_declaration_is_flagged() -> None:
    """Otherwise L6 can only ever check what someone remembered to enrol."""
    kits = _kit(
        lumiflux={"flight_attack_mv_bp": [16270, 40670], "surprise_daze_bp": [1, 2]},
    )
    assert _run(kits) == ["upstream_mv_undeclared"]


def test_missing_snapshot_is_a_finding_not_a_skip() -> None:
    """L6 reads a committed artifact, so — unlike L4/L5 — it has no way to skip."""
    assert _run(_kit(), snapshot=None) == ["upstream_mv_snapshot_missing"]


def test_hand_copy_paths_walks_nested_blocks() -> None:
    found = _hand_copy_paths(
        {"a": {"b": {"x_mv_bp": [1]}}, "y_daze_bp": [2], "z_mv_bp": "not-a-list"}
    )
    assert sorted(found) == ["a.b.x_mv_bp", "y_daze_bp"]


def test_stale_snapshot_sha_fails() -> None:
    """A pin bump without a regenerate leaves L6 diffing against yesterday's upstream."""
    with (
        patch("scripts.validate_kits._load_upstream_snapshot", return_value=_SNAPSHOT),
        patch(
            "scripts.validate_kits.DIMBREATH_PROVENANCE_PATH",
            _FakePath(json.dumps({"pinned_commit_sha": "0ther5ha"})),
        ),
    ):
        codes = [f.code for f in check_l6(_kit())]
    assert codes == ["upstream_mv_snapshot_stale"]


class _FakePath:
    """Minimal stand-in for the provenance Path (read_text only)."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read_text(self) -> str:
        return self._text


def test_every_emitted_code_is_registered() -> None:
    """`L6_CODES` is what the ledger and any future skip-exemption key off."""
    emitted = {
        code
        for kits, snap in (
            (_kit(lumiflux={"flight_attack_mv_bp": [1, 2]}), _SNAPSHOT),
            (_kit(upstream_mv_checks=[{"path": "x", "quantity": "damage",
                                       "skill_level": 12, "skill_ids": []}]), _SNAPSHOT),
            (_kit(lumiflux={"flight_attack_mv_bp": [16270, 40670],
                            "extra_mv_bp": [1]}), _SNAPSHOT),
            (_kit(upstream_mv_checks=[{"path": "lumiflux.flight_attack_mv_bp",
                                       "skill_ids": [1, 2], "quantity": "damage",
                                       "skill_level": 12}]), _SNAPSHOT),
            (_kit(), None),
        )
        for code in _run(kits, snap)
    }
    assert emitted <= L6_CODES
    assert "l6" in LEVELS


def test_shipped_corpus_is_clean() -> None:
    """The real kits, the real snapshot — the assertion the gate makes on every run."""
    assert [f.message for f in check_l6(iter_kits())] == []
