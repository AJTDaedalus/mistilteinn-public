"""LD (ledger consistency) validator tests — issue #88, items 3-4.

LD asks the two questions about `confidence` that the kits themselves cannot answer.
*Why is this kit still `draft`?* — Task 32 closed with four draft kits carrying four
unrelated blockers (a ZO stub sheet, a schema gap, a D-KV17 approximation ceiling, an
unanswered policy question), each recorded only inside its own kit's `notes`, with nothing
reporting that state. And *is this kit above `draft` while carrying a known defect?* —
D-KV22 caps a waived kit at `draft`, which until now was convention rather than a check,
and is the general form of #88's complaint that `audited` guarantees nothing.

Three kinds of test, extending the L0 file's split:

* **Corpus tests** pin the real ledger against the real corpus — every draft kit is
  documented, no entry outlives its blocker, and no kit above `draft` carries a waiver.
* **Rule tests** drive the checks with synthetic kits, so they stay covered no matter
  which kits happen to be draft on any given day.
* **CLI tests** drive `main()` itself, because a check the CLI never calls is a check
  nobody has — the failure mode `project_scaling_stat_gaps` records for the calc.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_kits import (
    DRAFT_BLOCKER_CLASSES,
    KNOWN_ISSUES_PATH,
    Finding,
    MalformedDraftBlockerError,
    _rel,
    check_confidence_caps,
    check_draft_blockers,
    format_draft_report,
    iter_kits,
    load_draft_blockers,
    main,
    stale_draft_blockers,
)


@pytest.fixture(scope="module")
def corpus() -> list[tuple[Path, dict[str, Any]]]:
    return iter_kits()


@pytest.fixture(scope="module")
def blockers() -> dict[str, dict[str, Any]]:
    return load_draft_blockers()


def _kits(*confidences: str) -> list[tuple[Path, dict[str, Any]]]:
    """Synthetic kits named `agents/k0.json`, `agents/k1.json`, ... one per confidence."""
    return [
        (Path(f"agents/k{i}.json"), {"source_name": f"K{i}", "confidence": conf})
        for i, conf in enumerate(confidences)
    ]


def _entry(**overrides: Any) -> dict[str, Any]:
    base = {
        "key": "agents/k0.json#blocked",
        "kit": "agents/k0.json",
        "class": "schema_gap",
        "reason": "r",
        "retire_when": "w",
    }
    return base | overrides


# --------------------------------------------------------------------------
# Corpus — the shipped ledger against the shipped kits
# --------------------------------------------------------------------------


def test_every_draft_kit_is_documented(corpus, blockers) -> None:
    """A draft kit with no ledger entry is the exact state issue #88 was filed about."""
    findings = check_draft_blockers(corpus, blockers)
    assert findings == [], f"undocumented draft kits: {[f.source_file for f in findings]}"


def test_no_stale_draft_blockers(corpus, blockers) -> None:
    """An entry for a kit that is no longer draft must be deleted, not left to rot."""
    stale = stale_draft_blockers(corpus, blockers)
    assert stale == [], f"stale draft blockers (the kit moved on — remove them): {stale}"


def test_only_draft_kits_are_checked(corpus, blockers) -> None:
    """The 117 `unverified` W-Engine/disc-set kits are out of scope, not undocumented.

    `unverified` is Task 15's demotion default — never audited, not *stuck*. Folding it in
    would bury the four real blockers under a wall of entries that say nothing.
    """
    listed = {entry["kit"] for entry in blockers.values()}
    for path, kit in corpus:
        if kit.get("confidence") != "draft":
            assert _rel(path) not in listed


def test_every_blocker_explains_itself_and_names_what_retires_it(blockers) -> None:
    """`load_draft_blockers` enforces the fields; this pins what it cannot.

    That every entry points at the derivation rather than restating a conclusion, and that
    each class is actually in use as intended — `curation_pending` names a task because
    someone can do it, everything else names an external condition because nobody can.
    """
    assert blockers, "the ledger has no draft_blockers entries at all"
    for key, entry in blockers.items():
        assert entry["class"] in DRAFT_BLOCKER_CLASSES, key
        assert len(entry["reason"]) > 80, f"blocker reason too thin to be a record: {key}"
        if entry["class"] == "curation_pending":
            assert "Task" in entry["owner_task"], f"owner_task names no task: {key}"
        else:
            assert entry["retire_when"], key
        assert key.startswith(entry["kit"] + "#"), f"key must be <kit>#<slug>: {key}"


def test_draft_blocker_keys_match_the_documented_format() -> None:
    """`_meta` documents the two key formats; a drifted key silently breaks grouping."""
    raw = json.loads(KNOWN_ISSUES_PATH.read_text())
    assert "draft_blockers" in raw["_meta"]["key_format"]
    assert set(raw["_meta"]["draft_blocker_classes"]) == set(DRAFT_BLOCKER_CLASSES)


# --------------------------------------------------------------------------
# Rules — synthetic kits, independent of which kits are draft today
# --------------------------------------------------------------------------


def test_undocumented_draft_fires() -> None:
    findings = check_draft_blockers(_kits("draft"), {})
    assert [(f.level, f.code) for f in findings] == [("LD", "undocumented_draft")]
    assert "agents/k0.json" in findings[0].message


def test_documented_draft_is_clean() -> None:
    assert check_draft_blockers(_kits("draft"), {"k": _entry()}) == []


@pytest.mark.parametrize("confidence", ["unverified", "audited", "verified"])
def test_non_draft_kits_never_fire(confidence: str) -> None:
    assert check_draft_blockers(_kits(confidence), {}) == []


def test_one_kit_may_carry_several_blockers() -> None:
    """Nekomata is stuck for two unrelated reasons; one entry per kit would lose one."""
    entries = {
        "a": _entry(key="agents/k0.json#a"),
        "b": _entry(key="agents/k0.json#b", **{"class": "upstream_blocked"}, decision="D-KV22"),
    }
    assert check_draft_blockers(_kits("draft"), entries) == []
    assert stale_draft_blockers(_kits("draft"), entries) == []


def test_stale_blocker_when_kit_is_promoted() -> None:
    entries = {"a": _entry(key="agents/k0.json#a")}
    assert stale_draft_blockers(_kits("audited"), entries) == ["a"]


def test_stale_blocker_when_kit_no_longer_exists() -> None:
    assert stale_draft_blockers([], {"a": _entry()}) == ["a"]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (_entry(key=None), "has no `key`"),
        (_entry(**{"class": None}), "expected one of"),
        (_entry(**{"class": "typo"}), "expected one of"),
        (_entry(**{"class": "curation_pending"}), "must carry: owner_task"),
        (_entry(**{"class": "upstream_blocked"}), "must carry: decision"),
        (
            _entry(**{"class": "approximation_ceiling"}, retire_when=None),
            "must carry: retire_when",
        ),
        ({"key": "k", "class": "schema_gap", "retire_when": "w"}, "must carry: kit, reason"),
    ],
)
def test_malformed_blocker_is_rejected(entry: dict, expected: str, tmp_path, monkeypatch) -> None:
    """An entry that does not say what retires it silences the check while explaining nothing.

    That is strictly worse than the kit not being listed: the report would show a blocker
    with no exit condition, which reads as tracked when it is not.
    """
    entry = {k: v for k, v in entry.items() if v is not None}
    ledger = tmp_path / "known_issues.json"
    ledger.write_text(json.dumps({"draft_blockers": [entry]}))
    monkeypatch.setattr("scripts.validate_kits.KNOWN_ISSUES_PATH", ledger)

    with pytest.raises(MalformedDraftBlockerError, match=expected):
        load_draft_blockers()


def test_duplicate_blocker_key_is_rejected(tmp_path, monkeypatch) -> None:
    """A duplicate would shadow the first entry — and shadowing is what keying by
    `<kit>#<slug>` instead of by kit exists to prevent."""
    ledger = tmp_path / "known_issues.json"
    ledger.write_text(json.dumps({"draft_blockers": [_entry(), _entry()]}))
    monkeypatch.setattr("scripts.validate_kits.KNOWN_ISSUES_PATH", ledger)

    with pytest.raises(MalformedDraftBlockerError, match="duplicate draft blocker key"):
        load_draft_blockers()


def test_missing_ledger_file_is_not_an_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("scripts.validate_kits.KNOWN_ISSUES_PATH", tmp_path / "nope.json")
    assert load_draft_blockers() == {}


# --------------------------------------------------------------------------
# Confidence caps — `audited` must mean "no known defects" (D-KV22)
# --------------------------------------------------------------------------


def _waived(source_file: str = "agents/k0.json") -> Finding:
    return Finding(
        level="L2",
        code="no_zo_citation",
        source_file=source_file,
        source_name="K0",
        index=3,
        label="row",
        message="m",
    )


def test_corpus_has_no_kit_above_draft_carrying_an_open_waiver(corpus) -> None:
    """The general form of issue #88's headline complaint, pinned against real data."""
    from scripts.validate_kits import LEVELS, load_waivers

    waivers = load_waivers()
    fired = [f for level in LEVELS.values() for f in level(corpus) if f.key in waivers]
    findings = check_confidence_caps(corpus, fired)
    offenders = [f.source_file for f in findings]
    assert findings == [], f"waived findings on kits above draft: {offenders}"


@pytest.mark.parametrize(("confidence", "fires"), [("audited", True), ("verified", True)])
def test_open_waiver_above_draft_fires(confidence: str, fires: bool) -> None:
    findings = check_confidence_caps(_kits(confidence), [_waived()])
    assert [f.code for f in findings] == ["waived_finding_above_draft"]
    assert confidence in findings[0].message


@pytest.mark.parametrize("confidence", ["draft", "unverified"])
def test_open_waiver_at_or_below_draft_is_fine(confidence: str) -> None:
    """`draft` is where D-KV22 caps a waived kit — that is the correct state, not a defect.

    `unverified` is below it and equally fine: a kit nobody has audited is not claiming
    anything a waiver could contradict.
    """
    assert check_confidence_caps(_kits(confidence), [_waived()]) == []


def test_unrecognised_confidence_is_left_to_lc() -> None:
    """LC already reports a typo'd rung; reporting it twice reads as two defects."""
    kits = [(Path("agents/k0.json"), {"source_name": "K0", "confidence": "audted"})]
    assert check_confidence_caps(kits, [_waived()]) == []


def test_unwaived_findings_do_not_cap_confidence() -> None:
    """Only *waived* findings reach this check — an unwaived one already fails on its own."""
    assert check_confidence_caps(_kits("audited"), []) == []


# --------------------------------------------------------------------------
# The report itself (issue #88, item 4) — the state, without opening four JSONs
# --------------------------------------------------------------------------


def test_report_lists_every_draft_kit_with_its_class_and_exit_condition(corpus, blockers) -> None:
    report = "\n".join(format_draft_report(corpus, blockers))
    for path, kit in corpus:
        if kit.get("confidence") == "draft":
            assert _rel(path) in report
    for entry in blockers.values():
        assert entry["class"] in report
        assert (entry.get("owner_task") or entry["retire_when"])[:40] in report


def test_report_flags_a_kit_with_no_entry() -> None:
    report = "\n".join(format_draft_report(_kits("draft"), {}))
    assert "no ledger entry" in report


def test_report_says_so_when_nothing_is_draft() -> None:
    assert format_draft_report(_kits("audited"), {}) == ["No kits at `confidence: draft`."]


# --------------------------------------------------------------------------
# main() wiring — every test above calls the checks directly, which proves
# nothing about whether the CLI runs them (project_scaling_stat_gaps: a pure
# check that never reaches the caller is a check nobody has)
# --------------------------------------------------------------------------


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """main() driven against a synthetic corpus and a throwaway ledger.

    `--level l0` keeps L1/L2/L4 (fixture, ZO constants, DB) out of it; L0 passes the
    modifier below cleanly, so anything the run reports came from LD.
    """

    def run(confidence: str, ledger: dict, *argv: str) -> tuple[int, str]:
        kit = {
            "source_name": "K0",
            "confidence": confidence,
            "modifiers": [
                {"stat": "crit_rate", "value": 1000, "source": "core_skill", "source_label": "T"}
            ],
        }
        path = tmp_path / "known_issues.json"
        path.write_text(json.dumps(ledger))
        monkeypatch.setattr("scripts.validate_kits.KNOWN_ISSUES_PATH", path)
        monkeypatch.setattr(
            "scripts.validate_kits.iter_kits", lambda: [(Path("agents/k0.json"), kit)]
        )
        monkeypatch.setattr("sys.argv", ["validate_kits", "--level", "l0", *argv])
        return main()

    return run


def test_cli_fails_on_an_undocumented_draft(cli, capsys) -> None:
    assert cli("draft", {}) == 1
    out = capsys.readouterr().out
    assert "undocumented_draft" in out
    assert "Draft kits (1)" in out


def test_cli_passes_on_a_documented_draft(cli, capsys) -> None:
    assert cli("draft", {"draft_blockers": [_entry()]}) == 0
    assert "delusion" not in capsys.readouterr().out  # the real ledger is not consulted


def test_cli_fails_on_a_stale_blocker(cli, capsys) -> None:
    assert cli("audited", {"draft_blockers": [_entry()]}) == 1
    assert "STALE DRAFT BLOCKER" in capsys.readouterr().err


def test_cli_reports_drafts_in_json_mode(cli, capsys) -> None:
    assert cli("draft", {"draft_blockers": [_entry()]}, "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["draft_kits"] == ["agents/k0.json"]
    assert payload["stale_draft_blockers"] == []
    assert len(payload["draft_blockers"]) == 1
