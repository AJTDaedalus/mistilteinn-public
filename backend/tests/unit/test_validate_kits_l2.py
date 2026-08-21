"""L2 (ZO citation check) validator tests — Task 10, docs/TASKS_kit_validation.md.

L2 asks whether the ZO symbol a modifier *cites* actually exists for that agent. It is the
layer that kills the fabrication class: a citation naming a symbol ZO does not have is a
hard failure, no matter how confident the prose around it sounds.

It is deliberately blind to formula *shape* (D-KV6). `test_l2_passes_nicoles_miswired_ability`
asserts that blind spot rather than assuming it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_kits import (
    ZO_CONSTANTS_PATH,
    _norm_slug,
    check_l2,
    iter_kits,
    load_waivers,
)


@pytest.fixture(scope="module")
def findings():
    return check_l2(iter_kits())


@pytest.fixture(scope="module")
def zo():
    return json.loads(ZO_CONSTANTS_PATH.read_text())["agents"]


def _by(findings, code: str):
    return [f for f in findings if f.code == code]


def _nicole_kit(*modifiers: dict[str, Any]) -> list:
    return [
        (
            Path("agents/nicole.json"),
            {
                "source_type": "agent",
                "source_id": "1141",
                "source_name": "Nicole",
                "modifiers": list(modifiers),
            },
        )
    ]


def _astra_kit(*modifiers: dict[str, Any]) -> list:
    return [
        (
            Path("agents/astra_yao.json"),
            {
                "source_type": "agent",
                "source_id": "1311",
                "source_name": "Astra Yao",
                "modifiers": list(modifiers),
            },
        )
    ]


# --------------------------------------------------------------------------
# The fixture carries both answer keys a citation can name
# --------------------------------------------------------------------------


def test_zo_fixture_has_buff_names_and_dm_symbols(zo) -> None:
    """A citation may name a sheet buff id or a dm constant — the fixture holds both.

    They are different namespaces: a sheet author invents the buff id
    (`registerBuff('m1_exSpecial_dmg_', ...)`) and feeds it a dm constant
    (`dm.m1.ex_special_dmg_anomBuildup`). Resolving citations against dm symbols alone
    would have called 200+ perfectly good citations fabrications.
    """
    nicole = zo["Nicole"]
    assert "ability_ether_dmg_" in nicole["buff_names"]
    assert nicole["symbols"]["ability.ether_dmg_"] == 0.25
    assert nicole["symbols"]["m1.ex_special_dmg_anomBuildup"] == 0.16


def test_buff_names_are_per_character(zo) -> None:
    """`m1_crit_` is a real Ellen buff and a fabricated Lycaon one. Scope matters."""
    assert "m1_crit_" in zo["Ellen"]["buff_names"]
    assert "m1_crit_" not in zo["Lycaon"]["buff_names"]


def test_slug_normalisation_covers_digit_runs() -> None:
    """`soldier_11` ↔ ZO's `Soldier11`; a naive CamelCase→snake join drops both Soldiers."""
    assert _norm_slug("soldier_11") == _norm_slug("Soldier11")
    assert _norm_slug("soldier_0_anby") == _norm_slug("Soldier0Anby")


# --------------------------------------------------------------------------
# The acceptance case: Nicole's fabricated M1
# --------------------------------------------------------------------------


def test_fabricated_symbol_is_a_hard_failure() -> None:
    """Nicole's pre-Task-1 `m1_defRed_` — the fabrication this whole feature exists for.

    The symbol exists nowhere in ZO's Nicole: not as a registered buff, not as a dm
    constant. The old kit cited it anyway, with a confident note. L2 fails it outright.
    """
    fabricated = {
        "stat": "def_ignore",
        "value": 1600,
        "source": "mindscape",
        "source_label": "M1: DEF Reduction (team)",
        "notes": "ZO: m1_defRed_ = 0.16",
    }
    findings = check_l2(_nicole_kit(fabricated))
    assert [f.code for f in findings] == ["nonexistent_zo_symbol"]
    assert "m1_defRed_" in findings[0].message


def test_real_symbol_resolves() -> None:
    """`ability_ether_dmg_` is a real Nicole buff — L2 passes it."""
    real = {
        "stat": "dmg_bonus",
        "value": 2500,
        "source": "core_skill",
        "source_label": "Ability",
        "notes": "ZO: ability_ether_dmg_ = 0.25",
    }
    assert check_l2(_nicole_kit(real)) == []


def test_l2_passes_nicoles_miswired_ability() -> None:
    """**L2's blind spot, asserted rather than assumed (D-KV6).**

    ZO's `ability_ether_dmg_` is *applied* as `teamBuff.combat.common_dmg_` — generic DMG%,
    every damage type — gated on all three squad slots being Ether or Cunning Hares. A kit
    that encodes it as Ether-only, on the wrong condition, cites a **real** symbol with the
    **right** value: L2 goes green and is right to.

    The number came from somewhere real; the wiring is still wrong. That is what the auditor
    is for, and it is why a green harness is necessary but never sufficient. If anyone later
    proposes dropping the auditor because "CI covers it", this test is the counterexample.
    """
    miswired = {
        "stat": "ether_dmg",  # ZO applies it as common_dmg_ — wrong stat
        "value": 2500,  # right number
        "source": "core_skill",
        "source_label": "Ability: Ether DMG",
        "conditions": ["same_element_in_team"],  # wrong condition
        "notes": "ZO: ability_ether_dmg_ = 0.25",
    }
    assert check_l2(_nicole_kit(miswired)) == []


# --------------------------------------------------------------------------
# Bare, unprefixed buff-id citations (D-KV15)
# --------------------------------------------------------------------------


def test_bare_id_absent_from_recogniser_before_fix_regression_guard(zo) -> None:
    """`common_dmg_` is a real Astra Yao buff id with no core/ability/mN prefix.

    `_CITED_SYMBOL_RE` requires one of those prefixes, so a citation shaped exactly like
    ZO's own `registerBuff('common_dmg_', ...)` call does not match it at all — the
    recogniser is too narrow, not the resolution logic (D-KV15). This pins the fixture
    fact the rest of this section depends on.
    """
    assert "common_dmg_" in zo["AstraYao"]["buff_names"]
    assert "crit_dmg_" in zo["AstraYao"]["buff_names"]


def test_bare_id_present_in_buff_names_resolves() -> None:
    """A citation naming a bare id ZO actually registers for this agent passes L2.

    No `core.`/`ability.`/`m[1-6].` prefix anywhere in the note — the only thing that
    makes this citation valid is that `common_dmg_` is a real entry in Astra's own
    `buff_names`.
    """
    real_bare = {
        "stat": "dmg_bonus",
        "value": 800,
        "source": "core_skill",
        "source_label": "Additional Ability: Team DMG%",
        "notes": "ZO: registerBuff('common_dmg_', teamBuff.combat.common_dmg_.add(...))",
    }
    assert check_l2(_astra_kit(real_bare)) == []


def test_bare_id_absent_from_buff_names_still_fails() -> None:
    """A bare id that is *not* in this agent's `buff_names` stays a failure.

    `made_up_dmg_` is shaped exactly like a real ZO bare buff id but does not exist for
    Astra — fabrication stays caught; the fix must not turn into prefix-free fuzzy
    matching (D-KV15's explicit guardrail).
    """
    fabricated_bare = {
        "stat": "dmg_bonus",
        "value": 800,
        "source": "core_skill",
        "source_label": "Additional Ability: Team DMG%",
        "notes": "ZO: registerBuff('made_up_dmg_', teamBuff.combat.made_up_dmg_.add(...))",
    }
    findings = check_l2(_astra_kit(fabricated_bare))
    assert [f.code for f in findings] == ["no_zo_citation"]


def test_bare_id_is_scoped_to_this_agents_own_buff_names(zo) -> None:
    """No global namespace: a bare id real for *another* agent must not resolve here.

    `basic_electric_dmg_` is a real Yanagi buff (her Jougen-stance Electric DMG row, the
    other D-KV15 headline case) but not an Astra one — it must not resolve just because it
    exists somewhere in the ZO corpus.
    """
    assert "basic_electric_dmg_" in zo["Yanagi"]["buff_names"]
    assert "basic_electric_dmg_" not in zo["AstraYao"]["buff_names"]
    cross_agent_bare = {
        "stat": "electric_dmg",
        "value": 1000,
        "source": "core_skill",
        "source_label": "Core: Electric DMG",
        "notes": "ZO: registerBuff('basic_electric_dmg_', ...)",
    }
    findings = check_l2(_astra_kit(cross_agent_bare))
    assert [f.code for f in findings] == ["no_zo_citation"]


# --------------------------------------------------------------------------
# `db:` citations for fairy-internal stats (D-KV21, Task 28)
# --------------------------------------------------------------------------


def test_db_citation_for_allowlisted_stat_passes() -> None:
    """`frostbite_frost_variant` has no ZO symbol at all — it's a fairy-internal marker.

    A `db:"..."` citation quoting the DB text is the only shape that can justify it;
    L2 must accept that shape instead of flagging it as an uncited fabrication.
    """
    allowlisted = {
        "stat": "frostbite_frost_variant",
        "value": 1,
        "source": "core_skill",
        "source_label": "Core: Frostbite (Frost variant)",
        "notes": 'db:"Frostbite... Frostburn state ends when Frostbite expires"',
    }
    assert check_l2(_astra_kit(allowlisted)) == []


def test_db_citation_for_non_allowlisted_stat_fails() -> None:
    """`db:` is not a general-purpose escape hatch — only allowlisted stats may use it.

    A citation shaped exactly like the accepted form, but naming a stat ZO *does* cover
    (`dmg_bonus`), must still fail: otherwise `db:` reopens the fabrication hole L2 exists
    to close for every stat, not just the fairy-internal ones (D-KV21's explicit guardrail).
    """
    not_allowlisted = {
        "stat": "dmg_bonus",
        "value": 2500,
        "source": "core_skill",
        "source_label": "Ability",
        "notes": 'db:"increases DMG by 25%"',
    }
    findings = check_l2(_astra_kit(not_allowlisted))
    assert [f.code for f in findings] == ["db_citation_not_allowlisted"]
    assert "dmg_bonus" in findings[0].message


def test_db_citation_does_not_leak_into_bare_or_symbol_recognisers() -> None:
    """A `db:` fragment must not accidentally satisfy L2 via some other recogniser.

    Confirms the acceptance case end to end: an allowlisted `db:` citation with no ZO
    symbol, no param path, and no bare buff id anywhere in `notes` still resolves cleanly.
    """
    allowlisted_only = {
        "stat": "frostbite_frost_variant",
        "value": 1,
        "source": "core_skill",
        "source_label": "Core: Frostbite (Frost variant)",
        "notes": 'db:"Frostburn state ends when Frostbite expires"',
    }
    assert check_l2(_nicole_kit(allowlisted_only)) == []


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


def test_flags_the_unverifiable_citations(findings) -> None:
    """0 citations name a ZO symbol that does not exist for that agent.

    Was 7 agents (Grace, Jane, Lycaon, Miyabi, Yixuan, Zhu Yuan, Ye Shunguang) before
    Task 17's re-audit passes fixed the citations on Grace/Jane/Lycaon/Miyabi (earlier
    batches) and Zhu Yuan/Ye Shunguang (Batch 8) — each was a genuine misattribution with
    real consequences, e.g. Grace's `m4_shock_dmg_` for a team Shock DMG buff when ZO's
    Grace M4 is actually *energy regen* (her Shock DMG comes from the ability). Yixuan
    (Batch 10) was last: her prior file's citations were re-derived and corrected against
    the live ZO sheet, retiring the class entirely.
    """
    flagged = {f.source_name for f in _by(findings, "nonexistent_zo_symbol")}
    assert flagged == set()


def test_flags_uncited_modifiers(findings) -> None:
    """3 modifiers cite no ZO symbol at all — their values trace to nothing.

    Was 70 before Task 13 deleted Manato's and Yidhari's mis-shaped HP→ATK rows,
    which were uncited precisely because there was no ZO symbol to cite (D-KV9).
    Was 66 before Task 25 (D-KV15): Astra Yao's Team DMG%/Team CRIT DMG rows already
    cited `common_dmg_`/`crit_dmg_` in `_comment`, a real bare ZO buff id the old
    core/ability/mN-prefixed recogniser could never match — the citation was always
    there, the recogniser was just too narrow to see it. Was 22 as Task 17's re-audit
    passes cited or removed the rest, leaving Cissia 2, Pan Yinhu 2, Starlight - Billy 6,
    Yixuan 4, Zhao 8 as pre-existing `known_issues.json` waivers on kits not yet
    re-audited. Was 12 after Batch 9 (this session) re-derived pan_yinhu.json and
    zhao.json from scratch and audited both clean — their ZO stub sheets (Zhao.ts)
    forced raw `coreParams[N]`/`mindscapeParams[N]` index-path citations instead of
    named symbols, but every value now has one, retiring both kits' 2+8=10 rows and
    waivers. Down to 2: Batch 10 fully re-derived Starlight - Billy (also a ZO stub,
    param-path citations throughout) and Yixuan (a real ZO sheet), retiring both kits'
    findings and waivers. Cissia's 2 remain — a pre-existing, out-of-scope ZO-stub gap
    (D-KV22) not covered by Batch 10's Rupture scope. Back up to 3 with Task 34: Sunna's
    `flat_atk` team rider is the same ZO-stub gap on a different agent, and D-KV24 settled
    that it takes a waiver rather than a `db:` citation — so the row is authored, flagged,
    and tracked rather than left out of the kit entirely, which is what "under-credit
    silently" looked like before.
    """
    assert len(_by(findings, "no_zo_citation")) == 3


def test_every_agent_kit_maps_to_a_zo_character(findings) -> None:
    """ZO covers all 54 agents, so `no_zo_reference` should never fire (DESIGN)."""
    assert _by(findings, "no_zo_reference") == []


def test_corpus_findings_are_exactly_the_known_set(findings) -> None:
    assert {f.code for f in findings} == {"no_zo_citation"}


def test_every_l2_finding_is_in_the_ledger(findings) -> None:
    waivers = load_waivers()
    unwaived = {f.key for f in findings if f.key not in waivers}
    assert unwaived == set(), f"unwaived L2 findings: {sorted(unwaived)}"


# --------------------------------------------------------------------------
# Index-path citations — the off-by-one class (DESIGN Finding 4)
# --------------------------------------------------------------------------


def test_index_path_citation_with_the_wrong_value_is_flagged() -> None:
    """`coreParams[0][6]` is 0.35 for Astra. Citing it as 0.32 reads the wrong level.

    This is DESIGN Finding 4's off-by-one, made mechanical: 0.32 is index 5.
    """
    kit = [
        (
            Path("agents/astra_yao.json"),
            {
                "source_type": "agent",
                "source_id": "1311",
                "source_name": "Astra Yao",
                "modifiers": [
                    {
                        "stat": "flat_atk",
                        "value": 1200,
                        "source": "core_skill",
                        "source_label": "Core",
                        "notes": "coreParams[0][6] = 0.32",
                    }
                ],
            },
        )
    ]
    findings = check_l2(kit)
    assert [f.code for f in findings] == ["zo_value_mismatch"]
    assert "0.35" in findings[0].message
