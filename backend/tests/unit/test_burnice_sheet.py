"""End-to-end parity test for Burnice's formula sheet.

Loads ``app/data/modifiers/agents/burnice.json``, registers its custom
formulas into a DAG registry via :func:`load_agent_formulas`, and checks
each formula's numeric output against:

1. Our procedural :func:`calculate_standard_damage` with the same
   scaling stat + multiplier input — internal consistency.
2. ZO's published constants (core afterburn table ``coreParams[6]``,
   M1 afterburn +100%, M6 special afterburn +60%, anom buildup = 60)
   — external cross-reference.

This is the reference sheet. When we batch-port other agents they will
follow this file's structure: numeric constants in bp-space, character
state reads (mindscape / core_level) registered before compute, and
assertions pinned to both procedural and source-of-truth numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.formula.builder import const, read_
from app.formula.tags import Tag
from app.formula.zzz.damage import register_enemy
from app.formula.zzz.sheet_loader import load_agent_formulas
from app.formula.zzz.stats import register_base_stats
from app.formula.zzz.tags import (
    Q_ANOM_BUILDUP,
    Q_CORE_LEVEL,
    Q_MINDSCAPE,
    Q_STANDARD_DMG,
    Q,
    formula_tag,
)
from app.pando.calculator import Calculator, NodeRegistry
from app.services.damage_calculator import calculate_standard_damage
from app.services.stat_calculator import StatInputs, compute_total_stats

BURNICE_JSON = (
    Path(__file__).resolve().parent.parent.parent
    / "app"
    / "data"
    / "modifiers"
    / "agents"
    / "burnice.json"
)

# Burnice's afterburn_dmg values from ZO mappedStats (coreParams[6]) — the
# same table our JSON encodes in basis points. Kept here as fractions so the
# parity math mirrors ZO's `percent(dm.core.afterburn_dmg)` step exactly.
ZO_AFTERBURN_FRACS = (1.75, 2.05, 2.35, 2.62, 2.90, 3.20, 3.50)
ZO_M1_BONUS = 1.0  # m1.afterburn_dmg = 100% flat
ZO_M6_BONUS = 0.60  # m6.special_afterburn_dmg

# ZO's `constant(60)` for core_afterburn_anomBuildup, in ZO's own unit: raw
# AttributeInfliction. Fairy stores that quantity x100 — the DB's
# `attacks.anomaly_buildup` for Burnice's EX hit 0 is 41110 where ZO's
# `AttributeInfliction` is 411.1 — and the simulator tests the gauge against
# `anomaly_capacity_<element> * 100`. So parity here is a *conversion*, not an
# identity, unlike the damage constants above which ZO and fairy both express as
# a fraction of ATK. See docs/DESIGN_kit_accuracy_gate.md Finding 4.
ZO_CORE_BUILDUP = 60
ZO_TO_FAIRY_GAUGE_SCALE = 100


def _load_burnice() -> dict:
    with BURNICE_JSON.open() as f:
        return json.load(f)


def _setup_registry(
    mindscape: int = 0,
    core_level: int = 0,
) -> tuple[NodeRegistry, float]:
    """Spin up a registry with Burnice's sheet loaded. Returns the registry
    and the computed ATK it sees (used by parity calls to the procedural
    damage calculator)."""
    reg = NodeRegistry()
    inputs = StatInputs(
        agent_base_atk=700,
        wengine_base_atk=600,
        atk_pct=3000,
        flat_atk=200,
        crit_rate=5000,
        crit_dmg=15000,
        fire_dmg=2500,
    )
    register_base_stats(reg, inputs)
    register_enemy(reg, enemy_base_def=60, enemy_level=60, enemy_res=0)
    reg.register(Tag.of(**{Q: Q_CORE_LEVEL}), const(core_level))
    reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(mindscape))
    load_agent_formulas(reg, _load_burnice())
    return reg, compute_total_stats(inputs).atk


def _compute_dmg(reg: NodeRegistry, name: str) -> float:
    return Calculator(reg).compute(
        read_(formula_tag("burnice", name, Q_STANDARD_DMG), "sum"),
    )


def _compute_anom(reg: NodeRegistry, name: str) -> float:
    return Calculator(reg).compute(
        read_(formula_tag("burnice", name, Q_ANOM_BUILDUP), "sum"),
    )


class TestBurniceSheetLoads:
    def test_sheet_slug_present(self) -> None:
        data = _load_burnice()
        assert data["sheet"] == "burnice"

    def test_formulas_section_present(self) -> None:
        data = _load_burnice()
        names = {f["name"] for f in data["formulas"]}
        assert names == {
            "core_afterburn_dmg",
            "core_afterburn_anomBuildup",
            "m6_additional_afterburn_dmg",
            # #90: Potential-unlocked-only free Afterburn proc on Mixed Flame Blend.
            # Tagged `potential: "unlocked"`, so a locked build never resolves it.
            "unlocked_mfb_afterburn_dmg",
        }


class TestCoreAfterburnDmg:
    @pytest.mark.parametrize("core_level", list(range(7)))
    def test_parity_no_mindscape(self, core_level: int) -> None:
        """At core level N, afterburn multiplier = ZO_AFTERBURN_FRACS[N] ATK.
        Matches our procedural damage calculator output when the multiplier
        is passed in the same bp form."""
        reg, _ = _setup_registry(mindscape=0, core_level=core_level)
        dag_value = _compute_dmg(reg, "core_afterburn_dmg")

        fraction = ZO_AFTERBURN_FRACS[core_level]
        bp = round(fraction * 10000)
        proc = calculate_standard_damage(
            scaling_stat=compute_total_stats(
                StatInputs(
                    agent_base_atk=700,
                    wengine_base_atk=600,
                    atk_pct=3000,
                    flat_atk=200,
                )
            ).atk,
            multiplier=bp,
            dmg_bonuses=[2500],
            crit_rate=5000,
            crit_dmg=15000,
            enemy_base_def=60,
            enemy_level=60,
        )
        # 1% tolerance — bp round-trip introduces a tiny offset
        assert dag_value == pytest.approx(proc.total, rel=0.01)

    def test_m1_adds_100pct_afterburn(self) -> None:
        """M1 adds a flat +100% (10000 bp) to the core afterburn multiplier.
        Verified by computing the un-scaled ratio (M1 on) / (M1 off)."""
        reg_off, _ = _setup_registry(mindscape=0, core_level=0)
        reg_on, _ = _setup_registry(mindscape=1, core_level=0)
        off = _compute_dmg(reg_off, "core_afterburn_dmg")
        on = _compute_dmg(reg_on, "core_afterburn_dmg")

        base_frac = ZO_AFTERBURN_FRACS[0]  # 1.75 at core 0
        expected_ratio = (base_frac + ZO_M1_BONUS) / base_frac
        assert on / off == pytest.approx(expected_ratio, rel=0.001)


class TestCoreAfterburnBuildup:
    def test_flat_60_converted_to_fairy_gauge_scale(self) -> None:
        """ZO's 60 raw AttributeInfliction is 6 000 on fairy's x100 gauge."""
        reg, _ = _setup_registry()
        assert (
            _compute_anom(reg, "core_afterburn_anomBuildup")
            == ZO_CORE_BUILDUP * ZO_TO_FAIRY_GAUGE_SCALE
        )


class TestM6AdditionalAfterburn:
    def test_zero_without_m6(self) -> None:
        reg, _ = _setup_registry(mindscape=5)
        assert _compute_dmg(reg, "m6_additional_afterburn_dmg") == 0

    def test_active_with_m6_matches_procedural(self) -> None:
        """At M6, multiplier = 60% ATK. Parity against the procedural
        damage calculator with bp=6000."""
        reg, _ = _setup_registry(mindscape=6)
        dag_value = _compute_dmg(reg, "m6_additional_afterburn_dmg")

        proc = calculate_standard_damage(
            scaling_stat=compute_total_stats(
                StatInputs(
                    agent_base_atk=700,
                    wengine_base_atk=600,
                    atk_pct=3000,
                    flat_atk=200,
                )
            ).atk,
            multiplier=int(ZO_M6_BONUS * 10000),  # 6000 bp
            dmg_bonuses=[2500],
            crit_rate=5000,
            crit_dmg=15000,
            enemy_base_def=60,
            enemy_level=60,
        )
        assert dag_value == pytest.approx(proc.total, rel=0.01)
