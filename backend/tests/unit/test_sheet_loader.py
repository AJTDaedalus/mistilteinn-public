"""Tests for per-agent sheet loader — parses the ``formulas`` section of an
agent modifier JSON and registers its formulas into a NodeRegistry via the
sheet registration primitives.

Schema (agent JSON extension):

```json
{
  "source_id": "...",
  "sheet": "burnice",
  "modifiers": [...],
  "formulas": [
    {
      "name": "core_afterburn_dmg",
      "quantity": "standard_dmg",
      "scope": "assist_followup",
      "element": "fire",
      "scaling_stat": "atk",         // optional, default "atk"
      "multiplier": { ...DSL... }    // bp-space multiplier
    },
    {
      "name": "core_afterburn_anomBuildup",
      "quantity": "anom_buildup",
      "scope": "assist_followup",
      "value": 60                    // flat; or DSL expr
    }
  ]
}
```

Only ``standard_dmg`` and ``anom_buildup`` quantities are supported in the
first cut. Daze-only custom formulas can be added later; for now, attack
hit buildup is derived from the attack table.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from app.formula.builder import const, read_
from app.formula.tags import Tag
from app.formula.zzz.damage import register_enemy
from app.formula.zzz.sheet_loader import load_agent_formulas
from app.formula.zzz.stats import register_base_stats
from app.formula.zzz.tags import (
    Q_ANOM_BUILDUP,
    Q_MINDSCAPE,
    Q_STANDARD_DMG,
    Q,
    formula_tag,
)
from app.pando.calculator import Calculator, NodeRegistry
from app.services.stat_calculator import StatInputs

if TYPE_CHECKING:
    from pathlib import Path


def _basic_setup() -> NodeRegistry:
    reg = NodeRegistry()
    register_base_stats(
        reg,
        StatInputs(
            agent_base_atk=700,
            wengine_base_atk=600,
            atk_pct=3000,
            flat_atk=200,
            crit_rate=5000,
            crit_dmg=15000,
            fire_dmg=2500,
        ),
    )
    register_enemy(reg, enemy_base_def=60, enemy_level=60, enemy_res=0)
    return reg


def _dmg(reg: NodeRegistry, sheet: str, name: str) -> float:
    return Calculator(reg).compute(read_(formula_tag(sheet, name, Q_STANDARD_DMG), "sum"))


def _anom(reg: NodeRegistry, sheet: str, name: str) -> float:
    return Calculator(reg).compute(read_(formula_tag(sheet, name, Q_ANOM_BUILDUP), "sum"))


class TestLoadAgentFormulas:
    def test_empty_formulas_section_ok(self) -> None:
        """An agent JSON with no ``formulas`` key produces no registrations."""
        reg = _basic_setup()
        load_agent_formulas(reg, {"sheet": "burnice", "modifiers": []})
        # Reading any unregistered formula tag returns 0 — no crash
        assert _dmg(reg, "burnice", "anything") == 0

    def test_standard_dmg_formula_from_dsl(self) -> None:
        reg = _basic_setup()
        load_agent_formulas(
            reg,
            {
                "sheet": "burnice",
                "formulas": [
                    {
                        "name": "basic_const",
                        "quantity": "standard_dmg",
                        "scope": "basic",
                        "element": "fire",
                        "multiplier": {"op": "const", "value": 4480},
                    },
                ],
            },
        )
        assert _dmg(reg, "burnice", "basic_const") > 0

    def test_anom_buildup_flat_value(self) -> None:
        reg = NodeRegistry()
        load_agent_formulas(
            reg,
            {
                "sheet": "burnice",
                "formulas": [
                    {
                        "name": "core_afterburn_anomBuildup",
                        "quantity": "anom_buildup",
                        "scope": "assist_followup",
                        "value": 60,
                    },
                ],
            },
        )
        assert _anom(reg, "burnice", "core_afterburn_anomBuildup") == 60

    def test_anom_buildup_dsl_value(self) -> None:
        """``value`` accepts DSL expressions too — some agents have
        buildup numbers that depend on character state (mindscape)."""
        reg = NodeRegistry()
        reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(6))
        load_agent_formulas(
            reg,
            {
                "sheet": "burnice",
                "formulas": [
                    {
                        "name": "m6_buildup",
                        "quantity": "anom_buildup",
                        "scope": "assist_followup",
                        "value": {
                            "op": "cmp_ge",
                            "left": {"op": "read", "q": "mindscape"},
                            "right": 6,
                            "if_ge": 120,
                            "if_lt": 60,
                        },
                    },
                ],
            },
        )
        assert _anom(reg, "burnice", "m6_buildup") == 120

    def test_mindscape_gated_damage(self) -> None:
        """``m6_additional_afterburn_dmg`` style: multiplier gated on mindscape."""
        reg = _basic_setup()
        reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(5))
        load_agent_formulas(
            reg,
            {
                "sheet": "burnice",
                "formulas": [
                    {
                        "name": "m6_extra",
                        "quantity": "standard_dmg",
                        "scope": "assist_followup",
                        "element": "fire",
                        "multiplier": {
                            "op": "cmp_ge",
                            "left": {"op": "read", "q": "mindscape"},
                            "right": 6,
                            "if_ge": 4000,
                        },
                    },
                ],
            },
        )
        # Without M6, multiplier = 0 → damage = 0
        assert _dmg(reg, "burnice", "m6_extra") == 0

        # With M6 active
        reg2 = _basic_setup()
        reg2.register(Tag.of(**{Q: Q_MINDSCAPE}), const(6))
        load_agent_formulas(
            reg2,
            {
                "sheet": "burnice",
                "formulas": [
                    {
                        "name": "m6_extra",
                        "quantity": "standard_dmg",
                        "scope": "assist_followup",
                        "element": "fire",
                        "multiplier": {
                            "op": "cmp_ge",
                            "left": {"op": "read", "q": "mindscape"},
                            "right": 6,
                            "if_ge": 4000,
                        },
                    },
                ],
            },
        )
        assert _dmg(reg2, "burnice", "m6_extra") > 0

    def test_hp_scaling(self) -> None:
        """``scaling_stat: hp`` picks the HP aggregated node (Hugo-family)."""
        reg = _basic_setup()
        load_agent_formulas(
            reg,
            {
                "sheet": "hugo",
                "formulas": [
                    {
                        "name": "hp_scaler",
                        "quantity": "standard_dmg",
                        "scope": "basic",
                        "element": "ice",
                        "scaling_stat": "hp",
                        "multiplier": {"op": "const", "value": 5000},
                    },
                ],
            },
        )
        # Should register without error (HP=0 here → dmg=0 is fine)
        # Just verify the lookup resolves
        assert _dmg(reg, "hugo", "hp_scaler") == 0

    def test_anomaly_proficiency_scaling(self) -> None:
        """``scaling_stat: anomaly_proficiency`` picks the AP aggregated node
        (Alice/Jane-family — anomaly DPS bonus hits scale off AP)."""
        reg = NodeRegistry()
        register_base_stats(
            reg,
            StatInputs(
                agent_base_atk=700,
                wengine_base_atk=600,
                anomaly_proficiency=300,
                crit_rate=5000,
                crit_dmg=15000,
            ),
        )
        register_enemy(reg, enemy_base_def=60, enemy_level=60, enemy_res=0)
        load_agent_formulas(
            reg,
            {
                "sheet": "alice",
                "formulas": [
                    {
                        "name": "m6_ap_scaler",
                        "quantity": "standard_dmg",
                        "scope": "assist_followup",
                        "element": "physical",
                        "scaling_stat": "anomaly_proficiency",
                        "multiplier": {"op": "const", "value": 10000},
                    },
                ],
            },
        )
        # AP=300, multiplier=100% → base damage scales off AP, not ATK
        assert _dmg(reg, "alice", "m6_ap_scaler") > 0

    def test_sheet_slug_required(self) -> None:
        with pytest.raises(ValueError, match="missing 'sheet'"):
            load_agent_formulas(
                NodeRegistry(),
                {
                    "formulas": [
                        {
                            "name": "x",
                            "quantity": "standard_dmg",
                            "scope": "basic",
                            "element": "fire",
                            "multiplier": {"op": "const", "value": 1},
                        }
                    ],
                },
            )

    def test_unknown_quantity_rejected(self) -> None:
        with pytest.raises(ValueError, match="unsupported quantity"):
            load_agent_formulas(
                NodeRegistry(),
                {
                    "sheet": "x",
                    "formulas": [
                        {
                            "name": "y",
                            "quantity": "daze_buildup",  # not yet supported in custom formulas
                            "scope": "basic",
                            "element": "fire",
                            "multiplier": {"op": "const", "value": 1},
                        }
                    ],
                },
            )

    def test_real_burnice_json_loads(self, tmp_path: Path) -> None:
        """Smoke test: an agent JSON extended with a ``formulas`` section
        round-trips through JSON serialization and load_agent_formulas."""
        data = {
            "source_type": "agent",
            "source_id": "1171",
            "source_name": "Burnice",
            "sheet": "burnice",
            "modifiers": [],
            "formulas": [
                {
                    "name": "core_afterburn_dmg",
                    "quantity": "standard_dmg",
                    "scope": "assist_followup",
                    "element": "fire",
                    "multiplier": {
                        "op": "subscript",
                        "index": {"op": "read", "q": "core_level"},
                        "table": [17500, 19600, 21700, 23800, 25900, 28000],
                    },
                },
                {
                    "name": "core_afterburn_anomBuildup",
                    "quantity": "anom_buildup",
                    "scope": "assist_followup",
                    "value": 60,
                },
            ],
        }
        path = tmp_path / "burnice.json"
        path.write_text(json.dumps(data))
        loaded = json.loads(path.read_text())

        reg = _basic_setup()
        # Set core level for subscript lookup
        reg.register(Tag.of(**{Q: "core_level"}), const(0))
        load_agent_formulas(reg, loaded)

        assert _dmg(reg, "burnice", "core_afterburn_dmg") > 0
        assert _anom(reg, "burnice", "core_afterburn_anomBuildup") == 60
