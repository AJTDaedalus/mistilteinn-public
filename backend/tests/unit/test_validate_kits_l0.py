"""L0 (executability) validator tests — Task 8, docs/TASKS_kit_validation.md.

L0 asks one question of every curated modifier: *can this physically reach the damage
calc?* It needs no fixture, no DB and no ZO clone — only the kit JSONs, the snapshot
builder's bake dispatch, and the buff resolver's stat buckets.

Two kinds of test live here:

* **Corpus tests** pin the real defects L0 finds in the shipped data. They are the
  evidence that the layer works, and they fail if someone silently introduces a new
  no-op (or fixes one without retiring its waiver).
* **Rule tests** drive each rule with a synthetic kit, so the rules stay covered even
  after the corpus is cleaned up in Phase C/D.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_kits import _L4_CODE_BY_CLASSIFICATION as _L4_CODES
from scripts.validate_kits import (
    KNOWN_ISSUES_PATH,
    L4_STATUS,
    L5_CODES,
    L5_STATUS,
    LEVELS,
    LR_CODES,
    LR_STATUS,
    RESOLVABLE_STATS,
    WAIVER_CLASSES,
    MalformedWaiverError,
    baked_scaling_stats,
    check_l0,
    iter_kits,
    load_waivers,
)


@pytest.fixture(scope="module")
def corpus() -> list[tuple[Path, dict[str, Any]]]:
    return iter_kits()


@pytest.fixture(scope="module")
def findings(corpus: list[tuple[Path, dict[str, Any]]]):
    return check_l0(corpus)


def _codes(findings, code: str) -> list:
    return [f for f in findings if f.code == code]


def _kit(**modifier: Any) -> list[tuple[Path, dict[str, Any]]]:
    """A one-modifier synthetic kit, for driving a single rule."""
    base = {
        "stat": "crit_rate",
        "value": 1000,
        "source": "core_skill",
        "source_label": "T",
    }
    base.update(modifier)
    return [(Path("agents/_synthetic.json"), {"source_name": "T", "modifiers": [base]})]


# --------------------------------------------------------------------------
# Introspection — L0 derives its answer key from the code, not a hardcoded list
# --------------------------------------------------------------------------


def test_bake_dispatch_is_read_from_snapshot_builder() -> None:
    """The set of scaling_stats the builder actually bakes.

    Task 13 (C1) replaced the hardcoded if-chain with `_SCALING_BAKERS`, which L0 now
    imports directly (it regex-scraped the builder's source until PR #67 review — that
    also matched `mod.scaling_stat == "..."` inside comments, and `sys.exit`ed whenever
    the code shape moved). `def` joined the table there. `hp` deliberately did not: the
    Rupture HP→SheerForce intrinsic is not an ATK buff and is not authored as a modifier
    at all (D-KV9). `pen_ratio` and `impact` joined in Task 27 (C8).
    `anomaly_proficiency_excess` joined in Track C4 — the damage-sim audit found it was
    the *last* missing basis, and the one blocking Jane's Passion ATK gain (+586 at her
    live AP, currently baking to zero) and her M1 AP→DMG% conversion.

    This assertion is the point of the import: adding a basis to the builder must be a
    deliberate, reviewed change here too, not a silent widening of what L0 accepts.
    """
    assert baked_scaling_stats() == {
        "base_atk",
        "def",
        "anomaly_mastery_excess",
        "pen_ratio",
        "impact",
        "anomaly_proficiency_excess",
    }


def test_resolvable_stats_come_from_buff_resolver() -> None:
    assert {"crit_rate", "flat_atk", "dmg_bonus", "def_ignore"} <= RESOLVABLE_STATS
    # Both Impact keys resolve since Task 22 (C4) gave `impact_pct` real semantics —
    # a percentage of base Impact, distinct from the flat `impact`.
    assert {"impact", "impact_pct"} <= RESOLVABLE_STATS


# --------------------------------------------------------------------------
# Corpus — the real defects in the shipped kits
# --------------------------------------------------------------------------


def test_no_unbaked_scaling_stat_survives_in_the_corpus(findings) -> None:
    """Retired by Task 13 (C1). This is the layer's own regression guard.

    L0 originally flagged three: Ben's DEF→ATK core, and Manato's/Yidhari's HP→ATK
    rows. `def` became a real basis in the builder's dispatch table; the two HP rows
    were the wrong *shape* (HP feeds SheerForce, not ATK) and were deleted in favour
    of the intrinsic Rupture path (D-KV9). The rule still bites — see
    `test_rule_unbaked_scaling_stat`, which fires it on a synthetic kit.

    (DESIGN Finding 3 predicted six no-ops here, from a grep that conflated
    `modifiers[]` with `formulas[]`. The Jane/Alice/Ben-second entries it named are
    `formulas[]` rows — dead for a different and worse reason; see below.)
    """
    assert _codes(findings, "unbaked_scaling_stat") == []


def test_no_unresolvable_stat_survives_in_the_corpus(findings) -> None:
    """Retired by Task 22 (C4).

    Shockstar Disco's 2pc granted `impact_pct`, which resolved in no buff_resolver
    bucket — the set's 2pc did nothing. It is now a real percentage of base Impact.
    The rule still bites; see `test_rule_unresolvable_stat`.
    """
    assert _codes(findings, "unresolvable_stat") == []


def test_no_unexecutable_formulas(findings) -> None:
    """Every kit `formulas[]` entry evaluates — the D-KV8 defect is closed.

    This rule used to flag all 21 entries unconditionally: no loader, service, or
    frontend path read the key, so Ben's M2, Alice's and Jane's AP-scaled M6, Miyabi's
    frostburn break and the rest were authored, ZO-cited, and dropped. Task 21 (C3)
    built the consumer, and the rule now runs it — so a finding here means a formula
    names an op, read target, scope, quantity, or scaling stat the engine lacks.
    """
    assert _codes(findings, "unexecutable_formula") == []


def test_no_other_finding_classes_in_the_corpus(findings) -> None:
    """L0 is clean on the corpus. Every rule it has still fires on a synthetic kit below.

    If this fails, L0 found something new — read it, don't silence it.
    """
    assert {f.code for f in findings} == set()


# --------------------------------------------------------------------------
# Waivers — known debt is tracked, and the list cannot rot (D-KV7)
# --------------------------------------------------------------------------


def test_every_current_finding_is_waived(findings) -> None:
    """CI is green on today's corpus: every finding is a tracked, owned open issue."""
    waivers = load_waivers()
    unwaived = [f for f in findings if f.key not in waivers]
    assert unwaived == [], f"unwaived L0 findings: {[f.key for f in unwaived]}"


def test_no_stale_waivers(corpus) -> None:
    """A waiver whose finding no longer fires must be deleted, not left to rot.

    Checked against **every** layer's findings, not just L0's — the ledger is shared, so
    an L0-only view would call every L1 entry stale.

    L4 (docs/TASKS_move_key_resolution.md Task 3) needs the real seeded app DB and this
    file's `corpus` fixture never seeds one — that's deliberate, this lane is DB-free by
    design (see module docstring) and the `backend` CI job runs `pytest tests/unit`
    against no Postgres at all. `check_l4` degrades to `[]` without raising when the DB
    is unreachable, which on its own would make every currently-open L4 waiver look
    "stale" here — wrongly, since "couldn't check" isn't "confirmed gone". Excluding
    L4-coded waivers from this test mirrors the same `L4_STATUS["db_reachable"]` guard
    `scripts.validate_kits.main()` already applies to its own stale-waiver check.

    **L5 (docs/TASKS_sequential_variant.md Task 25) is the same story**, and has one extra
    way to be unable to check: `attacks.param_name` is NULL on every row of a DB that was
    migrated but never re-seeded, which is "cannot check", not "clean". Either condition
    excludes L5-coded waivers here for the same reason.
    """
    fired = {f.key for level in LEVELS.values() for f in level(corpus)}
    ignorable = set(_L4_CODES.values()) if not L4_STATUS["db_reachable"] else set()
    if not (L5_STATUS["db_reachable"] and L5_STATUS["param_name_populated"]):
        ignorable |= L5_CODES
    if not LR_STATUS["db_reachable"]:
        ignorable |= LR_CODES
    stale = [
        key for key in load_waivers() if key not in fired and key.split("|", 1)[0] not in ignorable
    ]
    assert stale == [], f"stale waivers (the defect is gone — remove them): {stale}"


def test_every_waiver_names_who_retires_it() -> None:
    """A waiver is a promise someone owns the fix, not a way to silence a check.

    Which promise depends on the class: `branch_debt` names the task on this branch that
    retires it, `upstream_blocked` names the third-party condition that would and the
    D-KV decision licensing the exception. `load_waivers` enforces the per-class fields;
    this pins the parts it cannot — that both classes are actually in use as intended,
    and that every entry explains itself in prose.
    """
    raw = json.loads(KNOWN_ISSUES_PATH.read_text())
    for waiver in raw["waivers"]:
        assert waiver.get("reason"), f"waiver without reason: {waiver['key']}"
        assert waiver["class"] in WAIVER_CLASSES, f"unknown class: {waiver['key']}"

    # load_waivers is the enforcement point — prove it rejects a malformed entry rather
    # than trusting that the committed ledger happens to be well-formed today.
    assert load_waivers()  # the real ledger parses


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"key": "k", "reason": "r"}, "expected one of"),
        ({"key": "k", "reason": "r", "class": "typo"}, "expected one of"),
        ({"key": "k", "reason": "r", "class": "branch_debt"}, "must carry: owner_task"),
        (
            {"key": "k", "reason": "r", "class": "upstream_blocked", "decision": "D-KV22"},
            "must carry: retire_when",
        ),
    ],
)
def test_malformed_waiver_is_rejected(entry: dict, expected: str, tmp_path, monkeypatch) -> None:
    """An unclassified waiver must not silently suppress its finding.

    It would count toward neither class — escaping the merge gate while still hiding the
    defect, which is strictly worse than not being listed at all.
    """
    ledger = tmp_path / "known_issues.json"
    ledger.write_text(json.dumps({"waivers": [entry]}))
    monkeypatch.setattr("scripts.validate_kits.KNOWN_ISSUES_PATH", ledger)

    with pytest.raises(MalformedWaiverError, match=expected):
        load_waivers()


# --------------------------------------------------------------------------
# Rules — synthetic kits, so coverage survives the corpus being cleaned up
# --------------------------------------------------------------------------


def test_rule_unbaked_scaling_stat() -> None:
    # `crit_rate` is a real stat but not a *basis* — nothing bakes off it. (This used
    # to use `def`, which Task 13 turned into a genuine basis; a rule test must name
    # something the builder truly cannot dispatch on, or it stops testing the rule.)
    findings = check_l0(
        _kit(stat="flat_atk", value=0, scaling_stat="crit_rate", scaling_ratio=8000)
    )
    assert [f.code for f in findings] == ["unbaked_scaling_stat"]


def test_rule_baked_scaling_stat_is_clean() -> None:
    findings = check_l0(
        _kit(stat="flat_atk", value=0, scaling_stat="base_atk", scaling_ratio=4000)
    )
    assert findings == []


def test_rule_unresolvable_stat() -> None:
    # Was `impact_pct` until Task 22 (C4) made it resolve. A rule test must name a stat
    # no consumer reads, or it silently stops testing the rule.
    findings = check_l0(_kit(stat="mood_pct", value=600))
    assert [f.code for f in findings] == ["unresolvable_stat"]


def test_rule_inert_modifier() -> None:
    findings = check_l0(_kit(stat="crit_rate", value=0))
    assert [f.code for f in findings] == ["inert_modifier"]


def test_rule_wengine_refinement_values_are_not_inert() -> None:
    """W-Engine rows carry value_r1/value_r5, not `value` — they are not inert."""
    kit = [
        (
            Path("w_engines/_synthetic.json"),
            {
                "source_name": "W",
                "modifiers": [
                    {
                        "stat": "ice_dmg",
                        "value_r1": 2500,
                        "value_r5": 5000,
                        "source": "w_engine_passive",
                        "source_label": "Ice DMG",
                    }
                ],
            },
        )
    ]
    assert check_l0(kit) == []


def test_rule_base_atk_without_ratio_never_dispatches() -> None:
    """snapshot_builder gates base_atk on `scaling_ratio > 0` — ratio 0 is a no-op."""
    findings = check_l0(_kit(stat="flat_atk", value=100, scaling_stat="base_atk"))
    assert [f.code for f in findings] == ["incoherent_scale"]


def test_rule_scaling_ratio_without_scaling_stat() -> None:
    findings = check_l0(_kit(stat="flat_atk", value=100, scaling_ratio=4000))
    assert [f.code for f in findings] == ["incoherent_scale"]


def test_rule_atk_scale_ratio_needs_a_cap() -> None:
    """With atk_scale_ratio set, `value` is the cap: min(0, ATK*ratio) == 0."""
    findings = check_l0(_kit(stat="flat_atk", value=0, atk_scale_ratio=2260))
    assert [f.code for f in findings] == ["incoherent_scale"]


def test_rule_atk_scaled_modifier_with_cap_is_clean() -> None:
    """Lucy's post-Task-3 shape: cap + ratio."""
    findings = check_l0(_kit(stat="flat_atk", value=600, atk_scale_ratio=2260))
    assert findings == []


def test_rule_flat_addend_without_atk_scale_ratio_is_rejected() -> None:
    """C8 / D-KV20: flat_addend only means anything alongside atk_scale_ratio — on
    its own it would be a second, uncapped way to author a flat buff."""
    findings = check_l0(_kit(stat="flat_atk", value=100, flat_addend=50))
    assert [f.code for f in findings] == ["incoherent_scale"]


def test_rule_flat_addend_with_atk_scale_ratio_is_clean() -> None:
    """Lucy's 'Cheer On!' shape: cap + ratio + flat, all under the shared cap."""
    findings = check_l0(_kit(stat="flat_atk", value=600, atk_scale_ratio=2260, flat_addend=50))
    assert findings == []


def test_rule_hp_scale_fields_must_be_coherent() -> None:
    per_unit_only = check_l0(_kit(stat="dmg_bonus", value=1000, hp_scale_per_unit=1000))
    assert [f.code for f in per_unit_only] == ["incoherent_scale"]

    unit_only = check_l0(_kit(stat="dmg_bonus", value=1000, hp_scale_unit=100))
    assert [f.code for f in unit_only] == ["incoherent_scale"]


def test_rule_element_scope_on_unhonored_stat_is_rejected() -> None:
    """C7 / D-KV16: element_scope only means anything to res_reduction/res_ignore —
    on any other stat it would silently do nothing, the exact no-op class L0 exists
    to catch."""
    findings = check_l0(_kit(stat="dmg_bonus", value=1000, element_scope=["ice"]))
    assert [f.code for f in findings] == ["unhonored_element_scope"]


def test_rule_element_scope_on_honored_stat_is_clean() -> None:
    findings = check_l0(_kit(stat="res_reduction", value=2500, element_scope=["ice"]))
    assert findings == []

    findings = check_l0(_kit(stat="res_ignore", value=2500, element_scope=["ice"]))
    assert findings == []


def test_rule_no_element_scope_is_clean() -> None:
    """Absence of the field is always fine — element_scope is opt-in."""
    assert check_l0(_kit(stat="dmg_bonus", value=1000)) == []


@pytest.mark.parametrize(
    ("inner", "outer"),
    [("atk_pct", "final_atk_pct"), ("hp_pct", "final_hp_pct"), ("def_pct", "final_def_pct")],
)
def test_rule_inner_bracket_on_an_agent_kit_is_rejected(inner: str, outer: str) -> None:
    """Rule 7: kit-sourced ATK/HP/DEF% belongs in the OUTER (combat) bracket.

    Unlike the rest of L0 this is not a no-op class — the inner-bracket value *does*
    reach the calc, it just multiplies the bare base rather than the equipment-inclusive
    total, so every other layer passes it. Pulchra's M2 row made that concrete: fixed in
    8c747da, silently reverted by an uncommitted Batch-5 draft, fixed again in 2c7c1d4.
    """
    findings = check_l0(_kit(stat=inner, value=1000))
    assert [f.code for f in findings] == ["wrong_stat_bracket"]
    assert outer in findings[0].message


def test_rule_outer_bracket_on_an_agent_kit_is_clean() -> None:
    for outer in ("final_atk_pct", "final_hp_pct", "final_def_pct"):
        assert check_l0(_kit(stat=outer, value=1000)) == []


def test_rule_inner_bracket_is_scoped_to_agent_kits() -> None:
    """Disc sets legitimately use both brackets — a 2pc base bonus *is* an Initial
    Stat, a conditional 4pc is not — so the rule must not fire outside `agents/`."""
    for subdir in ("disc_sets", "w_engines"):
        kit = [
            (
                Path(f"{subdir}/_synthetic.json"),
                {
                    "source_name": "T",
                    "modifiers": [
                        {
                            "stat": "atk_pct",
                            "value": 1000,
                            "source": "set_2pc",
                            "source_label": "T",
                        }
                    ],
                },
            )
        ]
        assert check_l0(kit) == []


def test_rule_inner_bracket_survives_a_nested_agents_dir() -> None:
    """`iter_kits` walks with `rglob`, so the scoping test must hold one level down too —
    a `parent.name` check would let `agents/<subdir>/foo.json` slip the rule silently."""
    kit = [
        (
            Path("agents/batch_5/_synthetic.json"),
            {
                "source_name": "T",
                "modifiers": [
                    {
                        "stat": "atk_pct",
                        "value": 1000,
                        "source": "core_skill",
                        "source_label": "T",
                    }
                ],
            },
        )
    ]
    assert [f.code for f in check_l0(kit)] == ["wrong_stat_bracket"]


def test_corpus_has_no_inner_bracket_agent_rows(findings) -> None:
    """The corpus is clean today (8 final_atk_pct + 5 final_hp_pct agent rows, zero
    inner-bracket ones). This is the regression guard the bracket bug never had: it
    fails the moment a fourth revert lands, naming the kit and the row."""
    offenders = _codes(findings, "wrong_stat_bracket")
    assert offenders == [], [f"{f.source_file}[{f.index}] {f.label}" for f in offenders]


def test_no_unhonored_element_scope_survives_in_the_corpus(findings) -> None:
    assert _codes(findings, "unhonored_element_scope") == []


def _formula_kit(formula: dict) -> list[tuple[Path, dict]]:
    return [
        (
            Path("agents/_synthetic.json"),
            {"source_name": "T", "modifiers": [], "formulas": [formula]},
        )
    ]


def test_rule_unexecutable_formula_unknown_op() -> None:
    """An op the evaluator does not implement must fail the build, not return 0."""
    findings = check_l0(
        _formula_kit(
            {
                "name": "m6_dmg",
                "quantity": "standard_dmg",
                "scope": "chain",
                "multiplier": {"op": "prod", "args": []},
            }
        )
    )
    assert [f.code for f in findings] == ["unexecutable_formula"]
    assert "unknown op 'prod'" in findings[0].message


def test_rule_unexecutable_formula_unknown_read_target() -> None:
    findings = check_l0(
        _formula_kit(
            {
                "name": "m6_dmg",
                "quantity": "standard_dmg",
                "scope": "chain",
                "multiplier": {"op": "read", "q": "ascension"},
            }
        )
    )
    assert [f.code for f in findings] == ["unexecutable_formula"]


def test_rule_unexecutable_formula_unknown_scaling_stat() -> None:
    """The formula analogue of `unbaked_scaling_stat`: a stat no damage path can read."""
    findings = check_l0(
        _formula_kit(
            {
                "name": "m6_dmg",
                "quantity": "standard_dmg",
                "scope": "chain",
                "scaling_stat": "impact",
                "multiplier": 10000,
            }
        )
    )
    assert [f.code for f in findings] == ["unexecutable_formula"]


def test_rule_unexecutable_formula_checks_the_untaken_branch() -> None:
    """A bad op in an `if_lt` resolves fine at M6 — the structural walk still catches it."""
    findings = check_l0(
        _formula_kit(
            {
                "name": "m6_dmg",
                "quantity": "standard_dmg",
                "scope": "chain",
                "multiplier": {
                    "op": "cmp_ge",
                    "left": {"op": "read", "q": "mindscape"},
                    "right": 6,
                    "if_ge": 10000,
                    "if_lt": {"op": "prod", "args": []},
                },
            }
        )
    )
    assert [f.code for f in findings] == ["unexecutable_formula"]


def test_rule_unexecutable_formula_passes_a_real_entry() -> None:
    findings = check_l0(
        _formula_kit(
            {
                "name": "m2_dmg",
                "quantity": "standard_dmg",
                "scope": "special",
                "element": "fire",
                "scaling_stat": "def",
                "multiplier": {
                    "op": "cmp_ge",
                    "left": {"op": "read", "q": "mindscape"},
                    "right": 2,
                    "if_ge": 30000,
                },
            }
        )
    )
    assert findings == []
