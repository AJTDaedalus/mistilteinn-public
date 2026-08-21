"""L1 (description cross-check) validator tests — Task 9, docs/TASKS_kit_validation.md.

L1 asks: does every number a modifier asserts actually appear in that modifier's own
in-game description text? It is a **containment** check, never a parse of game grammar —
it kills values that came from nowhere (fabrications, off-by-10x, transcription slips)
and is deliberately blind to a right number wired to the wrong stat (D-KV6).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import scripts.validate_kits as vk
from scripts.validate_kits import (
    MAX_SKILL_LEVEL,
    _safe_arith,
    check_l1,
    expand_cal,
    iter_kits,
    load_stat_units,
    load_waivers,
)


@pytest.fixture(scope="module")
def findings():
    return check_l1(iter_kits())


def _by(findings, code: str):
    return [f for f in findings if f.code == code]


def _agent_kit(*modifiers: dict[str, Any], source_id: str = "1311") -> list:
    """A synthetic kit pinned to a real agent's description text (default: Astra Yao)."""
    return [
        (
            Path("agents/_synthetic.json"),
            {
                "source_type": "agent",
                "source_id": source_id,
                "source_name": "Synthetic",
                "modifiers": list(modifiers),
            },
        )
    ]


# --------------------------------------------------------------------------
# CAL templates — descriptions state level-scaled values as formulas, not numbers
# --------------------------------------------------------------------------


def test_expand_cal_resolves_astras_team_buffs() -> None:
    """`{CAL:0.08+AvatarSkillLevel(1)*0.01,100,2}` → 20.00 at max skill level.

    This is why L1 can check level-scaled buffs at all. Astra's team DMG% (20%) and CRIT
    DMG (25%) appear in the text *only* as templates; without expansion, both correct
    modifiers would be reported as fabrications.
    """
    assert MAX_SKILL_LEVEL == 12
    assert expand_cal("DMG by {CAL:0.08+AvatarSkillLevel(1)*0.01,100,2}%") == "DMG by 20.00%"
    assert expand_cal("CRIT DMG by {CAL:0.07+AvatarSkillLevel(1)*0.015,100,2}%") == (
        "CRIT DMG by 25.00%"
    )


def test_expand_cal_leaves_unparseable_templates_visible() -> None:
    """An unknown template stays in the text rather than silently becoming a number."""
    assert expand_cal("{CAL:__import__('os'),1,2}") == "{CAL:__import__('os'),1,2}"


def test_safe_arith_evaluates_arithmetic_only() -> None:
    """The CAL evaluator is an AST walk, not eval() — no names, calls or attributes."""
    assert _safe_arith("0.08+12*0.01") == pytest.approx(0.20)
    assert _safe_arith("-50+12*250") == pytest.approx(2950)
    assert _safe_arith("__import__('os').system('rm -rf /')") is None
    assert _safe_arith("open('/etc/passwd')") is None


def test_stat_units_are_read_from_frontend_stat_meta() -> None:
    units = load_stat_units()
    assert units["crit_rate"] == "bp"
    assert units["flat_atk"] == "raw"
    assert units["sheer_force_flat"] == "raw"


# --------------------------------------------------------------------------
# The fabrication class — what L1 exists to catch
# --------------------------------------------------------------------------


def test_starlight_billy_numbers_are_retired(findings) -> None:
    """Starlight - Billy's kit used to disagree with his own description, in four places.

    Description: EX Special hits "ignore **18%** Physical RES"; Special Attack stacks give
    "+**8%** CRIT DMG"; M2 "increases the DMG dealt ... by **50%**". The kit said 15%, 12%
    and 40%. Caught with no ZO involvement at all — the agent's own text was enough.

    Retired by Task 17 Batch 10's re-audit: the kit was fully re-derived from DB text and
    ZO's raw param-path arrays (`StarlightBilly.ts` is an unimplemented ZO stub), correcting
    all three values plus splitting the conflated M2 DMG/CRIT DMG mechanics.
    """
    assert {f.label for f in findings if f.source_name == "Starlight - Billy"} == set()


def test_flags_the_mindscape_multiplier_class(findings) -> None:
    """Qingyi/Vivian/Caesar M2 each *scaled an existing buff*, and the kit added a flat row.

    The text said the buff was raised "to 135% / 130% of its original value" — so the
    literal 35% / 30% the kit asserted appeared nowhere. Same shape gap as Astra's M2
    (DESIGN Finding 4, D-KV2).

    All three members of this class are now retired. Caesar first: Task 14 (C2) landed the
    mindscape-variant schema and re-authored his core buff as 1000 | 1500 gated rows.
    Qingyi and Vivian could not follow him at the time, and that was the interesting part —
    the schema was never the whole blocker. Qingyi's core per-stack Stun multiplier and
    Vivian's core AP-scaled Abloom family were *absent from their kits entirely*, so there
    was no base buff for the x1.35 / x1.3 to multiply. Authoring one was curation, not
    schema — both landed during Task 17's re-audit passes (Qingyi: Batch 32a; Vivian:
    Batch 5), which is why this class is now empty.
    """
    flagged = {f.source_name for f in _by(findings, "value_not_in_description")}
    assert not {"Qingyi", "Vivian", "Caesar"} & flagged


def test_corpus_findings_are_exactly_the_known_set(findings) -> None:
    """If this fails, L1 found something new — read it, don't silence it."""
    # 9 before Task 14 retired Caesar's phantom +500 M2 row. 8 before Task 17's re-audit
    # passes retired Qingyi's and Vivian's mindscape-multiplier findings (see
    # test_flags_the_mindscape_multiplier_class), leaving Pan Yinhu (1 row, Batch 9)
    # and Starlight - Billy (3 rows, Batch 10). 4 before Batch 9 re-derived pan_yinhu.json
    # from scratch and audited it clean, retiring its 1 stale row and waiver, leaving only
    # Starlight - Billy's 3 rows pending Batch 10. 0 since Batch 10's re-audit fixed all
    # three of Starlight - Billy's values (see test_starlight_billy_numbers_are_retired) —
    # L1 finds nothing new anywhere in the corpus.
    assert len(_by(findings, "value_not_in_description")) == 0
    # 0 since Task 23: HakushinCoreDescriptionPatchImporter backfilled Velina's (and
    # Norma's) blank core_skills text from the zzz-hakushin-data mirror.
    assert len(_by(findings, "no_description_text")) == 0
    assert {f.code for f in findings} == set()


def test_every_l1_finding_is_in_the_ledger(findings) -> None:
    waivers = load_waivers()
    unwaived = [f.key for f in findings if f.key not in waivers]
    assert unwaived == [], f"unwaived L1 findings: {unwaived}"


# --------------------------------------------------------------------------
# Seeding gaps are not curation errors
# --------------------------------------------------------------------------


def test_missing_description_text_is_reported_as_a_seeding_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A core description that is blank in the DB is reported once, as a seeding gap —
    never as N "value not in description" findings blaming a curator for a hole in the
    seed data.

    Regression test for Task 23: Velina's (and Norma's) `core_skills` rows were
    literally `" | "` in the DB — nanoka.cc served an empty Core Passive/Additional
    Ability description for both. That's since been backfilled from the
    zzz-hakushin-data mirror (`HakushinCoreDescriptionPatchImporter`), so the real
    corpus no longer exercises this path — this test keeps the mechanism covered with
    a synthetic fixture instead of depending on a live agent staying broken.
    """
    fixture = {
        "agents": {
            "9001": {
                "name": "Synthetic Blank",
                "slug": "syntheticblank",
                "skills": [],
                "core_skills": {"1": [{"name": "Core Passive: X", "description": " | "}]},
                "mindscapes": {},
            }
        }
    }
    fixture_path = tmp_path / "kit_descriptions.json"
    fixture_path.write_text(json.dumps(fixture))
    monkeypatch.setattr(vk, "KIT_DESCRIPTIONS_PATH", fixture_path)

    kits = _agent_kit(
        {"stat": "anomaly_dmg_bonus", "value": 1000, "source": "core_skill", "label": "AA: X"},
        source_id="9001",
    )
    synthetic_findings = vk.check_l1(kits)

    gaps = _by(synthetic_findings, "no_description_text")
    assert [(f.source_name, f.label) for f in gaps] == [("Synthetic", "core_skill")]
    others = [f for f in synthetic_findings if f.code != "no_description_text"]
    assert others == []


# --------------------------------------------------------------------------
# Astra — the DESIGN's acceptance case, and the limitation it actually reveals
# --------------------------------------------------------------------------


def test_astras_corrected_core_passes(findings) -> None:
    """Every modifier Task 2 authored for Astra is justified by her description text.

    cap 1,200 and ratio 35% are both stated in the core text; the 20%/25% team buffs come
    out of the Special skill's CAL templates.
    """
    assert [f for f in findings if f.source_name == "Astra Yao"] == []


def test_l1_cannot_catch_astras_original_bug_and_that_is_by_design() -> None:
    """**The DESIGN's stated Task 9 acceptance is not achievable, and this proves why.**

    TASKS says: "Astra's pre-Task-2 `final_atk_pct 3500` fails against a description saying
    'up to 1,200'". It does not fail, and it *cannot*: the description reads "The increase
    is equal to **35%** of Astra Yao's initial ATK, up to a maximum of 1,200", so the
    number 35 is right there in the text. L1 goes green.

    The bug in that row was never its number — it was its **shape**: `final_atk_pct` applied
    an uncapped 35% ATK bonus to the *recipient*, instead of flat ATK = min(1200, 35% of
    *Astra's* ATK). A containment check cannot see the difference, and neither can L2
    (D-KV6). Shape is the auditor's job. Encoded here as a test so the blind spot is a
    known, asserted property of the harness rather than a comfortable assumption.
    """
    old_astra_core = {
        "stat": "final_atk_pct",
        "value": 3500,
        "source": "core_skill",
        "source_label": "Core: Team ATK",
    }
    assert check_l1(_agent_kit(old_astra_core)) == []


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


def test_value_present_in_description_passes() -> None:
    """Astra's core cap (1,200) and ATK ratio (35%) are both in her text."""
    modifier = {
        "stat": "flat_atk",
        "value": 1200,
        "atk_scale_ratio": 3500,
        "source": "core_skill",
        "source_label": "Core",
    }
    assert check_l1(_agent_kit(modifier)) == []


def test_fabricated_value_is_flagged() -> None:
    modifier = {
        "stat": "crit_rate",
        "value": 7777,
        "source": "core_skill",
        "source_label": "Core",
    }
    findings = check_l1(_agent_kit(modifier))
    assert [f.code for f in findings] == ["value_not_in_description"]


def test_override_reason_is_an_escape_hatch() -> None:
    modifier = {
        "stat": "crit_rate",
        "value": 7777,
        "source": "core_skill",
        "source_label": "Core",
        "override_reason": "derived from ZO; the in-game text rounds it",
    }
    assert check_l1(_agent_kit(modifier)) == []


def test_unknown_source_id_is_reported() -> None:
    findings = check_l1(_agent_kit({"stat": "crit_rate", "value": 1}, source_id="999999"))
    assert [f.code for f in findings] == ["no_description_source"]
