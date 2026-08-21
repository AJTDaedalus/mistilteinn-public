"""LC (confidence ladder) validator tests — Task 18, docs/TASKS_kit_validation.md.

DESIGN's "Confidence ladder" says the trust model is only real if it is enforced:
`draft` (curator) -> `audited` (auditor) -> `verified` (harness, machine-only). LC is
the layer that makes `verified` unforgeable — it requires a `verified_stamp` that
matches the kit's current `modifiers[]`/`formulas[]`, and only `promote_kits`
(wired to `--promote`) ever computes one. A hand edit setting `confidence: "verified"`
has no way to also guess the matching stamp, so it fails here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.validate_kits import (
    CONFIDENCE_LADDER,
    _confidence_stamp,
    check_confidence,
    iter_kits,
    promote_kits,
)


def _codes(findings, code: str) -> list:
    return [f for f in findings if f.code == code]


def _kit(confidence: str | None, **extra: Any) -> list[tuple[Path, dict[str, Any]]]:
    """A minimal synthetic kit — clean under L0, invisible to L1/L2 (non-agent)."""
    data: dict[str, Any] = {
        "source_type": "disc_set",
        "source_name": "T",
        "modifiers": [
            {"stat": "crit_rate", "value": 1000, "source": "core_skill", "source_label": "T"}
        ],
    }
    if confidence is not None:
        data["confidence"] = confidence
    data.update(extra)
    return [(Path("disc_sets/_synthetic.json"), data)]


# --------------------------------------------------------------------------
# The ladder itself
# --------------------------------------------------------------------------


def test_ladder_is_exactly_four_rungs_in_order() -> None:
    assert CONFIDENCE_LADDER == ("unverified", "draft", "audited", "verified")


@pytest.mark.parametrize("confidence", ["unverified", "draft", "audited"])
def test_pre_verified_rungs_pass_with_no_stamp(confidence: str) -> None:
    """Nothing below `verified` needs a stamp — only the top rung is machine-only."""
    assert check_confidence(_kit(confidence)) == []


def test_unknown_confidence_value_is_flagged() -> None:
    """Catches typos ('Verified', 'audted') that would otherwise silently sit outside
    the ladder and be invisible to every other check.
    """
    findings = check_confidence(_kit("Verified"))
    assert len(_codes(findings, "invalid_confidence")) == 1


def test_missing_confidence_is_flagged() -> None:
    findings = check_confidence(_kit(None))
    assert len(_codes(findings, "invalid_confidence")) == 1


# --------------------------------------------------------------------------
# `verified` without a valid stamp — the hand-edit case Task 18 exists to kill
# --------------------------------------------------------------------------


def test_hand_edited_verified_with_no_stamp_fails_validation() -> None:
    """The literal Task 18 acceptance criterion: hand-editing a kit to `verified`
    (setting only the field, as a human editing JSON would) fails validation.
    """
    findings = check_confidence(_kit("verified"))
    assert len(_codes(findings, "unstamped_verified")) == 1


def test_verified_with_fabricated_stamp_fails_validation() -> None:
    """Guessing a plausible-looking stamp doesn't help — it has to match the hash."""
    findings = check_confidence(_kit("verified", verified_stamp="sha256:deadbeef"))
    assert len(_codes(findings, "stamp_mismatch")) == 1


def test_verified_with_correct_stamp_passes() -> None:
    kit = _kit("verified")
    kit[0][1]["verified_stamp"] = _confidence_stamp(kit[0][1])
    assert check_confidence(kit) == []


def test_stamp_is_deterministic() -> None:
    kit = _kit("audited")[0][1]
    assert _confidence_stamp(kit) == _confidence_stamp(kit)


def test_stamp_changes_when_a_modifier_value_changes() -> None:
    """The stamp binds to content — editing a modifier after stamping must be
    detectable, or a "verified" kit could drift silently out from under its rating.
    """
    kit = _kit("audited")[0][1]
    original = _confidence_stamp(kit)
    kit["modifiers"][0]["value"] = 2000
    assert _confidence_stamp(kit) != original


def test_stamp_is_unaffected_by_metadata_fields() -> None:
    """Editing `notes` (a legitimate, harmless edit — e.g. fixing a typo) must not
    invalidate an existing stamp; only `modifiers[]`/`formulas[]` are load-bearing.
    """
    kit = _kit("audited")[0][1]
    before = _confidence_stamp(kit)
    kit["notes"] = "typo fix, no data change"
    kit["version"] = "2"
    assert _confidence_stamp(kit) == before


# --------------------------------------------------------------------------
# promote_kits — the only legitimate writer of `verified`
# --------------------------------------------------------------------------


def test_promote_stamps_a_clean_audited_kit() -> None:
    kits = _kit("audited")
    promoted = promote_kits(kits)

    assert promoted == ["disc_sets/_synthetic.json"]
    _, kit = kits[0]
    assert kit["confidence"] == "verified"
    assert kit["verified_stamp"] == _confidence_stamp(kit)
    assert check_confidence(kits) == []  # the harness's own output re-validates clean


def test_promote_skips_a_kit_with_an_l0_defect() -> None:
    """Otherwise `verified` would mean less than `audited` — a kit that can't even
    reach the calc has no business at the top of the ladder.
    """
    kits = _kit("audited")
    kits[0][1]["modifiers"][0]["stat"] = "not_a_real_stat"  # L0 unresolvable_stat

    promoted = promote_kits(kits)

    assert promoted == []
    assert kits[0][1]["confidence"] == "audited"
    assert "verified_stamp" not in kits[0][1]


@pytest.mark.parametrize("confidence", ["unverified", "draft"])
def test_promote_only_advances_audited_kits(confidence: str) -> None:
    kits = _kit(confidence)
    assert promote_kits(kits) == []
    assert kits[0][1]["confidence"] == confidence


# --------------------------------------------------------------------------
# Corpus — the real repo, as a regression guard
# --------------------------------------------------------------------------


def test_no_kit_in_the_corpus_claims_verified_without_a_valid_stamp() -> None:
    """As of Task 18, nothing has been promoted yet (Task 17 left everything at
    `audited` or below) — this is both the corpus's current truth and the guard
    against a future hand edit slipping `verified` into a JSON file directly.
    """
    findings = check_confidence(iter_kits())
    assert _codes(findings, "unstamped_verified") == []
    assert _codes(findings, "stamp_mismatch") == []
    assert _codes(findings, "invalid_confidence") == []
