"""Parametrized parity test for batch-ported agent formula sheets.

For each agent in :data:`AGENT_FORMULAS` we:

1. Load the agent's JSON modifier file via :func:`load_agent_formulas`
2. Compute the named formula's standard_dmg via the DAG
3. Compare against :func:`calculate_standard_damage` with the same scaling
   stat + bp multiplier — internal consistency check.
4. For mindscape-gated formulas, also assert dmg=0 below the gate.

This is the lightweight pair to ``test_burnice_sheet.py`` — Burnice gets
its own file because it has multiple formulas and ZO cross-reference
constants. The agents listed here all reduce to a single (or two)
formula(s) of the standard "ATK x bp multiplier, optionally gated on
mindscape" shape, so a single parametrized scaffold is sufficient.

Each entry's ``bp`` value comes from the corresponding
``mappedStats`` lookup in
``/tmp/genshin-optimizer/libs/zzz/formula/src/data/char/sheets/<Agent>.ts``,
converted from raw fraction → bp via ``bp = round(value * 10000)``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.formula.builder import const, read_
from app.formula.tags import Tag
from app.formula.zzz.damage import register_enemy
from app.formula.zzz.sheet_loader import load_agent_formulas
from app.formula.zzz.stats import register_base_stats
from app.formula.zzz.tags import (
    Q_CORE_LEVEL,
    Q_MINDSCAPE,
    Q_STANDARD_DMG,
    Q,
    formula_tag,
)
from app.pando.calculator import Calculator, NodeRegistry
from app.services.damage_calculator import calculate_standard_damage
from app.services.stat_calculator import StatInputs, compute_total_stats

MODIFIERS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "app" / "data" / "modifiers" / "agents"
)


@dataclass(frozen=True)
class FormulaCase:
    """One agent / formula-name pair to validate."""

    json_file: str  # e.g. "vivian.json"
    sheet: str  # e.g. "vivian"
    formula_name: str  # e.g. "core_prophecy_dmg"
    expected_bp: int  # multiplier in bp-space (10000 = 100%)
    element: str  # for elem_dmg lookup in parity calc
    mindscape_required: int = 0  # 0 = always-on; ≥1 = gated formula
    scaling: str = "atk"  # "atk" | "anomaly_proficiency" | "def"
    elem_dmg_bp: int = 2500  # default elem dmg bonus on the test rig
    core_level: int = 6  # max core (G) — drives subscript tables
    inputs: dict[str, Any] = field(
        default_factory=lambda: {
            "agent_base_atk": 700,
            "wengine_base_atk": 600,
            "atk_pct": 3000,
            "flat_atk": 200,
            "crit_rate": 5000,
            "crit_dmg": 15000,
        }
    )


# Per-agent formula registry. Add new entries here as agents are ported.
# Source-of-truth for `expected_bp` is the corresponding ZO
# `mappedStats[char.<key>]` x 10000.
AGENT_FORMULAS: tuple[FormulaCase, ...] = (
    # Vivian — Core Prophecy: 55% ATK ether dmg (always on).
    # ZO: customDmg('core_prophecy_dmg', prod(own.final.atk, percent(0.55))).
    FormulaCase(
        json_file="vivian.json",
        sheet="vivian",
        formula_name="core_prophecy_dmg",
        expected_bp=5500,
        element="ether",
    ),
    # Ben — M2: 300% DEF dmg (gated on M2), split by Block Counter scope:
    # Special Attack: Fiscal Fist is physical, EX Special Attack: Cashflow
    # Counter is fire (Task 17 Batch 9 re-curation).
    # ZO: customDmg('m2_dmg', cmpGE(char.mindscape,2, prod(own.final.def, percent(3)))).
    FormulaCase(
        json_file="ben.json",
        sheet="ben",
        formula_name="m2_dmg_special",
        expected_bp=30000,
        element="physical",
        scaling="def",
        mindscape_required=2,
        inputs={
            "agent_base_atk": 700,
            "wengine_base_atk": 600,
            "agent_base_def": 600,
            "def_pct": 3000,
            "flat_def": 100,
            "crit_rate": 5000,
            "crit_dmg": 15000,
        },
    ),
    FormulaCase(
        json_file="ben.json",
        sheet="ben",
        formula_name="m2_dmg_ex_special",
        expected_bp=30000,
        element="fire",
        scaling="def",
        mindscape_required=2,
        inputs={
            "agent_base_atk": 700,
            "wengine_base_atk": 600,
            "agent_base_def": 600,
            "def_pct": 3000,
            "flat_def": 100,
            "crit_rate": 5000,
            "crit_dmg": 15000,
        },
    ),
    # Evelyn — M6 chain follow-up: 375% ATK fire (gated on M6).
    FormulaCase(
        json_file="evelyn.json",
        sheet="evelyn",
        formula_name="m6_follow_up_dmg_",
        expected_bp=37500,
        element="fire",
        mindscape_required=6,
    ),
    # Harumasa — M6 "electromagnetic explosion" has no FormulaCase: Task 17
    # Batch 6's re-audit found the mechanic genuinely unrepresentable (a
    # 1-in-12-hits cadence on Ha-Oto no Ya, not a per-hit formula — the
    # kit_formulas.py grammar has no counter/cadence read target) and it
    # was correctly omitted from harumasa.json; this case previously tested
    # a stale/buggy shape (scope="ex_special" instead of "basic", plus an
    # unconditional-per-hit ~12x over-credit) that the redraft confirmed no
    # longer matches the corrected, drafted JSON. See docs/LOG_kit_curation.md
    # Harumasa — Task 17 Batch 6 draft.
    # Miyabi — core Frostburn Break: subscript by core level.
    # At core=6 (G) → 1500% ATK ice dmg, always-on.
    FormulaCase(
        json_file="miyabi.json",
        sheet="miyabi",
        formula_name="core_frostburnBreak_dmg",
        expected_bp=150000,
        element="ice",
        core_level=6,
    ),
    # Lucy — M6: 300% ATK fire (explicit gate, ZO relies on UI).
    FormulaCase(
        json_file="lucy.json",
        sheet="lucy",
        formula_name="m6_dmg",
        expected_bp=30000,
        element="fire",
        mindscape_required=6,
    ),
    # Koleda — M6: 360% ATK fire, fires on EX Special/Chain/Ultimate explosion
    # hits alike (DB M6 text names all three; ZO's single customDmg call is
    # shared across the three move contexts, split into 3 formulas here since
    # KitFormula carries one scope per entry).
    FormulaCase(
        json_file="koleda.json",
        sheet="koleda",
        formula_name="m6_dmg_ex_special",
        expected_bp=36000,
        element="fire",
        mindscape_required=6,
    ),
    FormulaCase(
        json_file="koleda.json",
        sheet="koleda",
        formula_name="m6_dmg_chain",
        expected_bp=36000,
        element="fire",
        mindscape_required=6,
    ),
    FormulaCase(
        json_file="koleda.json",
        sheet="koleda",
        formula_name="m6_dmg_ultimate",
        expected_bp=36000,
        element="fire",
        mindscape_required=6,
    ),
    # JuFufu — M6: 160% ATK fire chain (gated on M6).
    FormulaCase(
        json_file="ju_fufu.json",
        sheet="ju_fufu",
        formula_name="m6_popcorn_dmg",
        expected_bp=16000,
        element="fire",
        mindscape_required=6,
    ),
    # Jane — M6: 1600% anomaly-prof physical (gated on M6). Scales off AP.
    FormulaCase(
        json_file="jane.json",
        sheet="jane",
        formula_name="m6_additional_dmg",
        expected_bp=160000,
        element="physical",
        scaling="anomaly_proficiency",
        mindscape_required=6,
        inputs={
            "agent_base_atk": 700,
            "wengine_base_atk": 600,
            "anomaly_proficiency": 300,
            "crit_rate": 5000,
            "crit_dmg": 15000,
        },
    ),
    # Alice — M6: 3300% anomaly-prof physical (gated on M6). Scales off AP.
    FormulaCase(
        json_file="alice.json",
        sheet="alice",
        formula_name="m6_dmg",
        expected_bp=330000,
        element="physical",
        scaling="anomaly_proficiency",
        mindscape_required=6,
        inputs={
            "agent_base_atk": 700,
            "wengine_base_atk": 600,
            "anomaly_proficiency": 300,
            "crit_rate": 5000,
            "crit_dmg": 15000,
        },
    ),
    # Orphie & Magus — M6: 250% ATK fire, Ultimate-trigger portion (gated on
    # M6). The EX Special (Heat Charge-only) trigger is escalated (see
    # orphie_magus.json notes) since 3 of 4 EXSpecial-category moves don't
    # fire this proc.
    FormulaCase(
        json_file="orphie_magus.json",
        sheet="orphie_magus",
        formula_name="m6_dmg_ultimate",
        expected_bp=25000,
        element="fire",
        mindscape_required=6,
    ),
    # Seed — M6's laser-beam volley (mindscapeParams[5][1]=3 beams x
    # mindscapeParams[5][2]=1.65 = 495% ATK electric) has no FormulaCase: the
    # Task 17 Batch 8 re-audit found the DB-correct total is 49500bp (3x the
    # stale 16500bp this case previously pinned, which matched only ZO's own
    # un-multiplied single-instance registration), but even at the corrected
    # total, scope="basic" over-credits Seed's non-triggering sibling basic
    # moves (Chrysanthemum Wheel Dance, Falling Petals - Downfall) by
    # ~1.75-2.5x — independently over the D-KV17 ceiling regardless of the
    # beam-count fix, with no schema field to scope a formula to one specific
    # move within a category. Per the established precedent for over-ceiling
    # category-grain findings this batch (drop, don't ship at a lesser
    # value), the formula was removed from seed.json's formulas[] entirely
    # rather than repinned at 49500bp. See docs/LOG_kit_curation.md Task 17
    # Batch 8 — Seed (kit-auditor) and (curator fix, F1-F3 + M6).
    # Seth — M6: 500% ATK electric (gated on M6).
    FormulaCase(
        json_file="seth.json",
        sheet="seth",
        formula_name="m6_dmg",
        expected_bp=50000,
        element="electric",
        mindscape_required=6,
    ),
    # Soldier 0 - Anby's M6 (1000% ATK electric aftershock vortex) is NOT a
    # formulas[] entry — Task 17 Batch 7 re-audit found the real trigger is a
    # 6-instance White-Thunder proc counter, not an attack-scope gate, so it
    # moved to moves/agents/soldier_0_anby.json's aftershock block
    # (wt_vortex_mv_bp/wt_vortex_tally_cap/wt_vortex_requires_mindscape) —
    # see test_aftershock_p2_wt_cascade.py::test_anby_m6_vortex_after_6_wt_at_mindscape_6.
    # Yuzuha — M6: 300% ATK physical, Assist Follow-Up powerful-shell extra
    # hits (gated on M6). DB text confirms 300%, not the previously-tested
    # 400% (a prior draft's fabricated value).
    FormulaCase(
        json_file="yuzuha.json",
        sheet="yuzuha",
        formula_name="m6_dmg",
        expected_bp=30000,
        element="physical",
        mindscape_required=6,
    ),
    # Zhu Yuan — M6: 880% ATK ether afterglow (4 bullets x 220% each, gated on
    # M6). Corrected from a stale un-multiplied 220% (single-bullet) value —
    # the DB text is explicit that the Ether Buckshot fires 4 bullets, each
    # dealing 220% ATK; see docs/LOG_kit_curation.md Task 17 Batch 8.
    FormulaCase(
        json_file="zhu_yuan.json",
        sheet="zhu_yuan",
        formula_name="m6_ether_afterglow",
        expected_bp=88000,
        element="ether",
        mindscape_required=6,
    ),
    # Trigger — M6: 1200% ATK base + M6's own +50% self dmg_bonus term = 1800%
    # ATK electric Armor Break Rounds (gated on M6). M4 Disconnect has no
    # FormulaCase: Task 17 Batch 2 audit found it genuinely unrepresentable
    # (a "fires once per state-entry window" trigger shape, not a per-hit
    # formula — see docs/LOG_kit_curation.md) and it was correctly omitted
    # from trigger.json; this case previously tested a stale/buggy shape
    # (scope="chain" instead of "basic", and an under-counted 120000bp that
    # silently dropped the M6 self-buff term) that Task 32 Batch 32b's
    # re-audit confirmed no longer matches the corrected, audited JSON.
    FormulaCase(
        json_file="trigger.json",
        sheet="trigger",
        formula_name="m6_armor_break_rounds_dmg",
        expected_bp=180000,
        element="electric",
        mindscape_required=6,
    ),
)


def _load_json(json_file: str) -> dict[str, Any]:
    with (MODIFIERS_DIR / json_file).open() as f:
        return json.load(f)


def _setup_registry(case: FormulaCase, mindscape: int) -> NodeRegistry:
    reg = NodeRegistry()
    inputs = StatInputs(
        **case.inputs,
        **{f"{case.element}_dmg": case.elem_dmg_bp},
    )
    register_base_stats(reg, inputs)
    register_enemy(reg, enemy_base_def=60, enemy_level=60, enemy_res=0)
    reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(mindscape))
    reg.register(Tag.of(**{Q: Q_CORE_LEVEL}), const(case.core_level))
    load_agent_formulas(reg, _load_json(case.json_file))
    return reg


def _compute_dmg(reg: NodeRegistry, sheet: str, name: str) -> float:
    return Calculator(reg).compute(
        read_(formula_tag(sheet, name, Q_STANDARD_DMG), "sum"),
    )


def _scaling_value(case: FormulaCase) -> float:
    """Resolve the scaling stat value the procedural calculator should use,
    mirroring what the DAG sees."""
    totals = compute_total_stats(StatInputs(**case.inputs))
    if case.scaling == "atk":
        return float(totals.atk)
    if case.scaling in ("def", "defense"):
        return float(totals.defense)
    if case.scaling == "hp":
        return float(totals.hp)
    if case.scaling in ("anomaly_proficiency", "anom_prof"):
        return float(case.inputs.get("anomaly_proficiency", 0))
    raise ValueError(f"unknown scaling stat {case.scaling!r}")


@pytest.mark.parametrize("case", AGENT_FORMULAS, ids=lambda c: c.sheet + "/" + c.formula_name)
class TestAgentSheetBatch:
    def test_loads_and_produces_positive_dmg(self, case: FormulaCase) -> None:
        """At a satisfying mindscape, the formula yields a positive number."""
        reg = _setup_registry(case, mindscape=case.mindscape_required or 0)
        dag_value = _compute_dmg(reg, case.sheet, case.formula_name)
        assert dag_value > 0, (
            f"{case.sheet}/{case.formula_name} produced zero damage at "
            f"mindscape={case.mindscape_required}"
        )

    def test_parity_with_procedural_calculator(self, case: FormulaCase) -> None:
        """DAG output matches calculate_standard_damage with same scaling
        stat + bp multiplier (1% tolerance for bp round-trip)."""
        reg = _setup_registry(case, mindscape=case.mindscape_required or 0)
        dag_value = _compute_dmg(reg, case.sheet, case.formula_name)

        proc = calculate_standard_damage(
            scaling_stat=_scaling_value(case),
            multiplier=case.expected_bp,
            dmg_bonuses=[case.elem_dmg_bp],
            crit_rate=case.inputs.get("crit_rate", 0),
            crit_dmg=case.inputs.get("crit_dmg", 0),
            enemy_base_def=60,
            enemy_level=60,
        )
        assert dag_value == pytest.approx(proc.total, rel=0.01)

    def test_mindscape_gate_inactive_below_threshold(self, case: FormulaCase) -> None:
        """Mindscape-gated formulas should yield zero damage when the user's
        mindscape is below the gate. Always-on formulas skip this check."""
        if case.mindscape_required == 0:
            pytest.skip("formula is not mindscape-gated")
        reg = _setup_registry(case, mindscape=case.mindscape_required - 1)
        dag_value = _compute_dmg(reg, case.sheet, case.formula_name)
        assert dag_value == 0
