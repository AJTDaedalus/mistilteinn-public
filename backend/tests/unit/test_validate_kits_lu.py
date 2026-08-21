"""Unit tests for `validate_kits` LU — unseeded upstream damage rows (issue #180).

L6 watches the multipliers a kit has already hand-copied. LU watches the population those
copies were drawn from: damage-bearing `AvatarSkillTemplateTb` rows that nanoka never
publishes, so no `attacks` row exists and no DB-backed level can see them. 126 of them
exist today across 41 agents.

What these tests pin is that LU **fires**. A level that returns nothing passes a
"shipped corpus is clean" test whether or not it can see anything, and the defect class
here is invisibility, so every test below asserts a specific finding on a specific
fabricated defect. The class tests are the sharpest ones: class authorization is only
safe because LU re-derives the membership predicate, and these assert that it does rather
than trusting the id list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.validate_kits import (
    MalformedUnseededLedgerError,
    check_confidence,
    check_lu,
    load_unseeded_ledger,
    unseeded_confidence_caps,
)

PIN = "475dd0195645afcdbb200fd020edd6cd64d19425"


def _row(**overrides: Any) -> dict[str, Any]:
    row = {
        "avatar_id": 1581,
        "agent_name": "Remielle",
        "bucket": "inert",
        "damage_base": 72520,
        "damage_growth": 6600,
        "stun_base": 0,
        "stun_growth": 0,
        "energy_gain": 0,
        "anomaly_buildup": 0,
        "in_skill_list_id_space": True,
        "referenced_by_ability": None,
    }
    row.update(overrides)
    return row


def _snapshot(rows: dict[str, Any] | None = None, sha: str = PIN) -> dict[str, Any]:
    return {
        "_meta": {"pinned_sha": sha},
        "rows": rows if rows is not None else {"1581001": _row()},
    }


def _entry(**overrides: Any) -> dict[str, Any]:
    entry = {
        "kind": "row",
        "skill_id": 1581001,
        "avatar_id": 1581,
        "agent_name": "Remielle",
        "bucket": "inert",
        "disposition": "not_a_move",
        "reason": "no Daze, no energy, no buildup (RESEARCH §3)",
        "recorded_by": "test",
        "authorized_by": "owner",
        "date": "2026-08-14",
    }
    entry.update(overrides)
    return entry


def _run(snapshot: dict[str, Any] | None, entries: list[dict[str, Any]]) -> list[str]:
    with (
        patch("scripts.validate_kits._load_unseeded_snapshot", return_value=snapshot),
        patch("scripts.validate_kits.load_unseeded_ledger", return_value=entries),
        patch(
            "scripts.validate_kits.DIMBREATH_PROVENANCE_PATH",
            _FakePath(json.dumps({"pinned_commit_sha": PIN})),
        ),
    ):
        return [f.code for f in check_lu([])]


class _FakePath:
    """Minimal stand-in for the provenance path — LU only ever reads its text."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read_text(self) -> str:
        return self._text


# ── the load-bearing finding ───────────────────────────────────────────────
def test_an_unledgered_row_fails() -> None:
    """The whole point of the level: a row nobody has judged must not pass quietly."""
    assert _run(_snapshot(), []) == ["unseeded_row_unledgered"]


def test_a_ledgered_and_authorized_row_passes() -> None:
    assert _run(_snapshot(), [_entry()]) == []


def test_a_recorded_but_unauthorized_row_still_fails() -> None:
    """A curator records; only the owner authorizes. The ledger is a review queue."""
    assert _run(_snapshot(), [_entry(authorized_by=None)]) == ["unseeded_row_unauthorized"]


def test_a_new_upstream_row_fails_even_when_every_other_row_is_ledgered() -> None:
    rows = {"1581001": _row(), "1581026": _row(bucket="novel_signature", stun_base=500)}
    assert _run(_snapshot(rows), [_entry()]) == ["unseeded_row_unledgered"]


# ── ledger hygiene ─────────────────────────────────────────────────────────
def test_an_entry_for_a_row_that_no_longer_exists_fails() -> None:
    """Covers both stale entries and typo'd ids — a typo must authorize nothing."""
    codes = _run(_snapshot(), [_entry(skill_id=1581999)])
    assert "unseeded_row_stale_ledger" in codes
    assert "unseeded_row_unledgered" in codes  # the real row is still unjudged


def test_an_entry_filed_under_the_wrong_avatar_fails() -> None:
    assert "unseeded_row_entity_mismatch" in _run(_snapshot(), [_entry(avatar_id=1311)])


def test_a_missing_snapshot_is_a_finding_not_a_skip() -> None:
    """LU reads committed files only, so 'could not check' can never be 'checked'."""
    assert _run(None, [_entry()]) == ["unseeded_snapshot_missing"]


def test_a_snapshot_built_at_a_different_pin_fails() -> None:
    codes = _run(_snapshot(sha="0ldpin0ldpin"), [_entry()])
    assert "unseeded_snapshot_stale_pin" in codes


# ── class authorization: the predicate is re-derived, never trusted ────────
def _class(**overrides: Any) -> dict[str, Any]:
    entry = {
        "kind": "class",
        "class_id": "inert-instances",
        "skill_ids": [1581001],
        "disposition": "not_a_move",
        "reason": "all carry damage and nothing else",
        "recorded_by": "test",
        "authorized_by": "owner",
        "date": "2026-08-14",
    }
    entry.update(overrides)
    return entry


def test_a_class_covers_its_members() -> None:
    assert _run(_snapshot(), [_class()]) == []


def test_an_inert_class_member_that_gains_a_side_channel_falls_out() -> None:
    """The predicate IS the evidence: a row with Daze is not an inert row any more."""
    rows = {"1581001": _row(stun_base=4030)}
    assert _run(_snapshot(rows), [_class()]) == ["unseeded_class_predicate_violated"]


def test_a_duplicate_class_member_whose_twin_drifts_falls_out() -> None:
    rows = {
        "1341024": _row(
            avatar_id=1341,
            agent_name="Zhao",
            bucket="exact_dup_of_seeded",
            damage_base=43750,
            damage_growth=3980,
            stun_base=4030,
            stun_growth=190,
            anomaly_buildup=3670,
            twin_skill_id=1341023,
            twin_values={
                "damage_base": 43751,  # the twin moved by one
                "damage_growth": 3980,
                "stun_base": 4030,
                "stun_growth": 190,
                "energy_gain": 0,
                "anomaly_buildup": 3670,
            },
        )
    }
    entry = _class(
        class_id="alt-ids",
        disposition="duplicate_of_modelled",
        skill_ids=[1341024],
        avatar_id=1341,
    )
    assert _run(_snapshot(rows), [entry]) == ["unseeded_class_predicate_violated"]


def test_a_duplicate_class_member_with_no_twin_at_all_falls_out() -> None:
    rows = {"1581001": _row(bucket="novel_signature", stun_base=1)}
    entry = _class(disposition="duplicate_of_modelled", skill_ids=[1581001])
    assert _run(_snapshot(rows), [entry]) == ["unseeded_class_predicate_violated"]


def test_no_implicit_membership_a_matching_row_must_still_be_listed() -> None:
    """A new row that happens to satisfy an authorized class's predicate is NOT covered.

    This is the guard that keeps class authorization from re-opening #180's hole: the
    membership list is explicit, so joining a class is always a decision someone made.
    """
    rows = {"1581001": _row(), "1581025": _row()}  # both inert; only one is listed
    assert _run(_snapshot(rows), [_class(skill_ids=[1581001])]) == ["unseeded_row_unledgered"]


# ── loader validation ──────────────────────────────────────────────────────
def _load(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    doc = json.dumps({"entries": entries})
    with patch("scripts.validate_kits.UNSEEDED_LEDGER_PATH", _LedgerPath(doc)):
        return load_unseeded_ledger()


class _LedgerPath(_FakePath):
    def is_file(self) -> bool:
        return True


def test_a_well_formed_ledger_loads() -> None:
    assert len(_load([_entry(), _class(skill_ids=[1581025])])) == 2


@pytest.mark.parametrize(
    ("entry", "match"),
    [
        (_entry(kind="klass"), "is not 'row' or 'class'"),
        ({k: v for k, v in _entry().items() if k != "reason"}, "missing"),
        ({k: v for k, v in _entry().items() if k != "authorized_by"}, "missing"),
        (_entry(disposition="probably_fine"), "is not one of"),
        (_entry(disposition="duplicate_of_modelled"), "must also carry"),
        (_entry(disposition="undetermined"), "must also carry"),
        ({k: v for k, v in _entry().items() if k != "skill_id"}, "needs a skill_id"),
        (_class(skill_ids=[]), "non-empty skill_ids"),
    ],
)
def test_malformed_entries_raise_rather_than_parse_leniently(
    entry: dict[str, Any], match: str
) -> None:
    with pytest.raises(MalformedUnseededLedgerError, match=match):
        _load([entry])


def test_a_class_may_not_carry_a_per_row_disposition() -> None:
    """`undetermined` and `real_move_unmodelled` are stories; a class would not tell them."""
    with pytest.raises(MalformedUnseededLedgerError, match="may not be bundled as a class"):
        _load([_class(disposition="undetermined", issue=None)])


def test_two_entries_may_not_claim_the_same_row() -> None:
    with pytest.raises(MalformedUnseededLedgerError, match="already covered by"):
        _load([_entry(), _class(skill_ids=[1581001])])


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"ceiling": "audited", "retire_when": "never", "decision": "D-KV30"}, "missing"),
        (
            {
                "ceiling": "sparkle",
                "retire_when": "never",
                "decision": "D-KV30",
                "authorized_by": "owner",
            },
            "not a rung",
        ),
        (
            {
                "ceiling": "verified",
                "retire_when": "never",
                "decision": "D-KV30",
                "authorized_by": "owner",
            },
            "may not be 'verified'",
        ),
    ],
)
def test_malformed_ceiling_overrides_raise(override: dict[str, Any], match: str) -> None:
    entry = _entry(disposition="undetermined", issue=None, ceiling_override=override)
    with pytest.raises(MalformedUnseededLedgerError, match=match):
        _load([entry])


# ── LC: the confidence cap ─────────────────────────────────────────────────
def _undetermined(**overrides: Any) -> dict[str, Any]:
    return _entry(disposition="undetermined", issue=None, **overrides)


def _lc(kit_confidence: str, entries: list[dict[str, Any]]) -> list[str]:
    kit = {
        "source_name": "Remielle",
        "source_type": "agent",
        "source_id": "1581",
        "confidence": kit_confidence,
    }
    with patch("scripts.validate_kits.load_unseeded_ledger", return_value=entries):
        return [f.code for f in check_confidence([(Path("agents/remielle.json"), kit)])]


def test_an_undetermined_row_caps_its_agents_kit_at_draft() -> None:
    assert _lc("audited", [_undetermined()]) == ["unseeded_undetermined_caps_confidence"]


def test_a_draft_kit_with_an_undetermined_row_is_fine() -> None:
    assert _lc("draft", [_undetermined()]) == []


def test_an_authorized_ceiling_override_lifts_the_cap() -> None:
    """Remielle's case: nothing accessible upstream names the row, and the kit is as high
    confidence as it can be. The override records that rather than hiding it."""
    override = {
        "ceiling": "audited",
        "retire_when": "never — no accessible upstream source names these rows",
        "decision": "D-KV30",
        "authorized_by": "owner",
    }
    assert _lc("audited", [_undetermined(ceiling_override=override)]) == []


def test_an_unauthorized_ceiling_override_does_not_lift_the_cap() -> None:
    override = {
        "ceiling": "audited",
        "retire_when": "never",
        "decision": "D-KV30",
        "authorized_by": None,
    }
    assert _lc("audited", [_undetermined(ceiling_override=override)]) == [
        "unseeded_undetermined_caps_confidence"
    ]


def test_other_dispositions_do_not_cap() -> None:
    assert _lc("audited", [_entry()]) == []


def test_the_cap_takes_the_lowest_ceiling_when_an_agent_has_several_rows() -> None:
    override = {
        "ceiling": "audited",
        "retire_when": "never",
        "decision": "D-KV30",
        "authorized_by": "owner",
    }
    entries = [
        _undetermined(skill_id=1581001, ceiling_override=override),
        _undetermined(skill_id=1581025),  # no override → draft
    ]
    with patch("scripts.validate_kits.load_unseeded_ledger", return_value=entries):
        assert unseeded_confidence_caps() == {"1581": "draft"}


# ── modelled_in_kit: the claim is re-derived against live kit content ──────
def _modelled(**overrides: Any) -> dict[str, Any]:
    fields = {
        "disposition": "modelled_in_kit",
        "kit": "agents/vivian.json",
        "multiplier_bp": 5500,
    }
    fields.update(overrides)
    return _entry(**fields)


def _with_kit(kit: dict[str, Any], entries: list[dict[str, Any]]) -> list[str]:
    with (
        patch("scripts.validate_kits._load_unseeded_snapshot", return_value=_snapshot()),
        patch("scripts.validate_kits.load_unseeded_ledger", return_value=entries),
        patch(
            "scripts.validate_kits.DIMBREATH_PROVENANCE_PATH",
            _FakePath(json.dumps({"pinned_commit_sha": PIN})),
        ),
    ):
        return [f.code for f in check_lu([(Path("agents/vivian.json"), kit)])]


def test_a_row_the_kit_still_models_passes() -> None:
    """Vivian 1331020: her Prophecy instance is already carried by formulas[0]."""
    kit = {
        "formulas": [{"name": "core_prophecy_dmg", "multiplier": {"op": "const", "value": 5500}}]
    }
    assert _with_kit(kit, [_modelled()]) == []


def test_a_kit_that_stops_carrying_the_multiplier_fails() -> None:
    """The claim rots silently otherwise: the row goes unmodelled while the ledger says
    it is handled. LU re-derives the pairing rather than trusting the entry."""
    kit = {
        "formulas": [{"name": "core_prophecy_dmg", "multiplier": {"op": "const", "value": 5501}}]
    }
    assert _with_kit(kit, [_modelled()]) == ["unseeded_row_modelling_lost"]


def test_an_entry_naming_a_kit_that_does_not_exist_fails() -> None:
    kit = {"formulas": [{"multiplier": {"value": 5500}}]}
    assert _with_kit(kit, [_modelled(kit="agents/nobody.json")]) == ["unseeded_row_modelling_lost"]


def test_hand_copied_upstream_tuples_count_as_modelling() -> None:
    """Remielle's flight attacks live in `lumiflux.flight_attack_mv_bp`, not in a formula."""
    kit = {"lumiflux": {"flight_attack_mv_bp": [16270, 40670, 32530]}}
    assert _with_kit(kit, [_modelled(multiplier_bp=40670)]) == []


def test_a_percentage_bonus_is_not_a_damage_multiplier() -> None:
    """Ye Shunguang 1431036 and Cissia 1521021 both look explained under a naive whole-file
    scan — `1000` there is '+10% DMG', not '1000% of ATK'. Only damage-shaped positions count."""
    kit = {"modifiers": [{"stat": "dmg_bonus", "value": 5500}]}
    assert _with_kit(kit, [_modelled()]) == ["unseeded_row_modelling_lost"]


def test_modelled_in_kit_may_not_be_bundled_as_a_class() -> None:
    with pytest.raises(MalformedUnseededLedgerError, match="may not be bundled as a class"):
        _load(
            [_class(disposition="modelled_in_kit", kit="agents/vivian.json", multiplier_bp=5500)]
        )


def test_modelled_in_kit_must_name_its_kit_and_value() -> None:
    with pytest.raises(MalformedUnseededLedgerError, match="must also carry"):
        _load([_entry(disposition="modelled_in_kit")])


# ── not_described_anywhere: the predicate reads committed prose ────────────
def _described_class(**overrides: Any) -> dict[str, Any]:
    fields = {"disposition": "not_described_anywhere", "skill_ids": [1581001]}
    fields.update(overrides)
    return _class(**fields)


def _with_prose(prose: str, entries: list[dict[str, Any]], rows: dict[str, Any] | None = None):
    doc = {"agents": {"1581": {"name": "Remielle", "skills": prose}}} if prose is not None else {}
    with (
        patch("scripts.validate_kits._load_kit_descriptions", return_value=doc),
        patch("scripts.validate_kits._load_unseeded_snapshot", return_value=_snapshot(rows)),
        patch("scripts.validate_kits.load_unseeded_ledger", return_value=entries),
        patch(
            "scripts.validate_kits.DIMBREATH_PROVENANCE_PATH",
            _FakePath(json.dumps({"pinned_commit_sha": PIN})),
        ),
    ):
        return [f.code for f in check_lu([])]


def test_an_undescribed_row_stays_in_the_class() -> None:
    assert _with_prose("deals Ether DMG and applies a debuff", [_described_class()]) == []


def test_a_row_whose_value_appears_in_prose_falls_out() -> None:
    """If a patch adds prose stating the value, the class's premise stops holding for it —
    and a described damage instance is the shape all three confirmed unmodelled moves had."""
    prose = "launches an extra attack dealing DMG equal to 725.2% of ATK"
    assert _with_prose(prose, [_described_class()]) == ["unseeded_class_predicate_violated"]


def test_the_match_is_boundary_checked() -> None:
    """`725.2%` must not match inside `1,725.2%` — the trap that made Jane's row look
    identified when the text actually said 1,600% of Anomaly Proficiency."""
    prose = "deals DMG equal to 1,725.2% of Anomaly Proficiency"
    assert _with_prose(prose, [_described_class()]) == []


def test_a_higher_skill_level_value_also_counts_as_described() -> None:
    """1581001 is 72520 +6600/level, so Lv.2 is 791.2% — prose may quote any level."""
    assert _with_prose("dealing 791.2% of ATK", [_described_class()]) == [
        "unseeded_class_predicate_violated"
    ]


def test_an_agent_missing_from_the_description_corpus_violates_rather_than_passes() -> None:
    """An unevaluable predicate is not a satisfied one — the harness's standing rule."""
    with (
        patch("scripts.validate_kits._load_kit_descriptions", return_value={"agents": {}}),
        patch("scripts.validate_kits._load_unseeded_snapshot", return_value=_snapshot()),
        patch("scripts.validate_kits.load_unseeded_ledger", return_value=[_described_class()]),
        patch(
            "scripts.validate_kits.DIMBREATH_PROVENANCE_PATH",
            _FakePath(json.dumps({"pinned_commit_sha": PIN})),
        ),
    ):
        assert [f.code for f in check_lu([])] == ["unseeded_class_predicate_violated"]


def test_not_described_anywhere_does_not_cap_confidence() -> None:
    """Owner ruling, 2026-08-16: it is affirmative evidence, not an admission of ignorance,
    so unlike `undetermined` it leaves the kit's rung alone."""
    entry = _entry(disposition="not_described_anywhere")
    assert _lc("audited", [entry]) == []
