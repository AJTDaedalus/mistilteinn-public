"""Tests for the formula mini-DSL compiler.

The DSL lets agent JSONs express conditional multiplier trees that
``register_custom_standard_dmg`` / ``register_custom_anom_buildup`` can
consume. JSON is the source of truth; the compiler lowers it to ``AnyNode``
so the DAG engine evaluates it identically to hand-written builder code.

Operators (JSON ``{"op": <name>, ...}``):
  const, sum, prod, min, max, sumfrac, subscript, cmp_ge, read, stat

Shorthand: bare numbers auto-wrap to ``const``; strings raise (ambiguous).
"""

from __future__ import annotations

import pytest

from app.formula.builder import const, read_
from app.formula.tags import Tag
from app.formula.zzz.formula_dsl import compile_dsl, compile_dsl_optional
from app.formula.zzz.stats import (
    Q_ATK_NODE,
    Q_CRIT_DMG_NODE,
    Q_CRIT_RATE_NODE,
    Q_DEF_NODE,
    Q_HP_NODE,
    register_base_stats,
)
from app.formula.zzz.tags import (
    Q_CORE_LEVEL,
    Q_MINDSCAPE,
    Q,
    formula_tag,
)
from app.pando.calculator import Calculator, NodeRegistry
from app.services.stat_calculator import StatInputs


def _compute(node, reg=None):
    reg = reg or NodeRegistry()
    return Calculator(reg).compute(node)


# ---- Primitive ops --------------------------------------------------------


class TestConstants:
    def test_const_literal_number(self) -> None:
        node = compile_dsl({"op": "const", "value": 42})
        assert _compute(node) == 42

    def test_const_float(self) -> None:
        node = compile_dsl({"op": "const", "value": 3.14})
        assert _compute(node) == pytest.approx(3.14)

    def test_bare_int_auto_wraps(self) -> None:
        """Scalars in nested positions auto-wrap to const for terseness."""
        node = compile_dsl({"op": "sum", "args": [1, 2, 3]})
        assert _compute(node) == 6

    def test_bare_float_auto_wraps(self) -> None:
        node = compile_dsl({"op": "prod", "args": [2.0, 0.5]})
        assert _compute(node) == pytest.approx(1.0)


class TestArithmetic:
    def test_sum(self) -> None:
        node = compile_dsl(
            {
                "op": "sum",
                "args": [{"op": "const", "value": 10}, 20, 30],
            }
        )
        assert _compute(node) == 60

    def test_prod(self) -> None:
        node = compile_dsl(
            {
                "op": "prod",
                "args": [2, 3, 4],
            }
        )
        assert _compute(node) == 24

    def test_min(self) -> None:
        node = compile_dsl({"op": "min", "args": [5, 2, 8]})
        assert _compute(node) == 2

    def test_max(self) -> None:
        node = compile_dsl({"op": "max", "args": [5, 2, 8]})
        assert _compute(node) == 8

    def test_sumfrac(self) -> None:
        # a / (a + b) — classic DEF-area shape
        node = compile_dsl({"op": "sumfrac", "numer": 100, "denom_extra": 300})
        assert _compute(node) == pytest.approx(0.25)


class TestSubscript:
    def test_subscript_by_index(self) -> None:
        """Burnice's core levels pick from a per-level table at char.core."""
        reg = NodeRegistry()
        reg.register(Tag.of(**{Q: Q_CORE_LEVEL}), const(3))
        node = compile_dsl(
            {
                "op": "subscript",
                "index": {"op": "read", "q": "core_level"},
                "table": [100, 110, 120, 130, 140, 150],
            }
        )
        assert _compute(node, reg) == 130

    def test_subscript_literal_index(self) -> None:
        node = compile_dsl(
            {
                "op": "subscript",
                "index": 2,
                "table": [10, 20, 30, 40],
            }
        )
        assert _compute(node) == 30


class TestCmpGe:
    def test_cmp_ge_true_branch(self) -> None:
        reg = NodeRegistry()
        reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(6))
        node = compile_dsl(
            {
                "op": "cmp_ge",
                "left": {"op": "read", "q": "mindscape"},
                "right": 6,
                "if_ge": 999,
            }
        )
        assert _compute(node, reg) == 999

    def test_cmp_ge_false_branch_default_zero(self) -> None:
        reg = NodeRegistry()
        reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(2))
        node = compile_dsl(
            {
                "op": "cmp_ge",
                "left": {"op": "read", "q": "mindscape"},
                "right": 6,
                "if_ge": 999,
            }
        )
        assert _compute(node, reg) == 0

    def test_cmp_ge_false_branch_explicit(self) -> None:
        reg = NodeRegistry()
        reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(2))
        node = compile_dsl(
            {
                "op": "cmp_ge",
                "left": {"op": "read", "q": "mindscape"},
                "right": 6,
                "if_ge": 999,
                "if_lt": 111,
            }
        )
        assert _compute(node, reg) == 111


class TestRead:
    def test_read_state_quantity(self) -> None:
        reg = NodeRegistry()
        reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(4))
        node = compile_dsl({"op": "read", "q": "mindscape"})
        assert _compute(node, reg) == 4

    def test_read_empty_defaults_zero(self) -> None:
        """Unregistered tag sums to zero — no NameError."""
        node = compile_dsl({"op": "read", "q": "mindscape"})
        assert _compute(node) == 0


class TestStatAlias:
    @pytest.fixture
    def reg_with_stats(self) -> NodeRegistry:
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
                agent_base_hp=5000,
                agent_base_def=100,
            ),
        )
        return reg

    def test_atk_resolves_to_q_atk_node(self, reg_with_stats: NodeRegistry) -> None:
        node = compile_dsl({"op": "stat", "name": "atk"})
        # Should compute the same as the pre-built node
        assert _compute(node, reg_with_stats) == _compute(Q_ATK_NODE, reg_with_stats)

    def test_hp_resolves_to_q_hp_node(self, reg_with_stats: NodeRegistry) -> None:
        node = compile_dsl({"op": "stat", "name": "hp"})
        assert _compute(node, reg_with_stats) == _compute(Q_HP_NODE, reg_with_stats)

    def test_def_resolves_to_q_def_node(self, reg_with_stats: NodeRegistry) -> None:
        node = compile_dsl({"op": "stat", "name": "def"})
        assert _compute(node, reg_with_stats) == _compute(Q_DEF_NODE, reg_with_stats)

    def test_crit_rate(self, reg_with_stats: NodeRegistry) -> None:
        node = compile_dsl({"op": "stat", "name": "crit_rate"})
        assert _compute(node, reg_with_stats) == _compute(Q_CRIT_RATE_NODE, reg_with_stats)

    def test_crit_dmg(self, reg_with_stats: NodeRegistry) -> None:
        node = compile_dsl({"op": "stat", "name": "crit_dmg"})
        assert _compute(node, reg_with_stats) == _compute(Q_CRIT_DMG_NODE, reg_with_stats)

    def test_unknown_stat_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown stat"):
            compile_dsl({"op": "stat", "name": "mana"})


# ---- Validation + errors --------------------------------------------------


class TestValidation:
    def test_unknown_op_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown op"):
            compile_dsl({"op": "divide", "args": [1, 2]})

    def test_missing_op_rejected(self) -> None:
        with pytest.raises(ValueError, match="missing 'op'"):
            compile_dsl({"value": 5})

    def test_non_dict_non_number_rejected(self) -> None:
        with pytest.raises(TypeError, match="DSL expression must be"):
            compile_dsl("some string")  # type: ignore[arg-type]

    def test_compile_dsl_optional_none(self) -> None:
        assert compile_dsl_optional(None) is None

    def test_compile_dsl_optional_passthrough(self) -> None:
        node = compile_dsl_optional({"op": "const", "value": 7})
        assert node is not None
        assert _compute(node) == 7


# ---- Composed: real-world Burnice shapes ----------------------------------


class TestBurniceShapes:
    """Representative shapes drawn from ZO's Burnice.ts — confirms the DSL
    can express the conditionals that appear in actual agent sheets."""

    def test_core_afterburn_multiplier_shape(self) -> None:
        """Burnice core: ``subscript(char.core, table) + cmpGE(M1, M1_bonus)``
        expressed purely in JSON.
        """
        reg = NodeRegistry()
        reg.register(Tag.of(**{Q: Q_CORE_LEVEL}), const(2))
        reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(1))

        # sum(subscript(core, [100,110,120,130,140,150]),
        #     cmp_ge(mindscape, 1, 50))
        multiplier = compile_dsl(
            {
                "op": "sum",
                "args": [
                    {
                        "op": "subscript",
                        "index": {"op": "read", "q": "core_level"},
                        "table": [100, 110, 120, 130, 140, 150],
                    },
                    {
                        "op": "cmp_ge",
                        "left": {"op": "read", "q": "mindscape"},
                        "right": 1,
                        "if_ge": 50,
                    },
                ],
            }
        )
        # core=2 → 120; mindscape=1 → +50; total = 170
        assert _compute(multiplier, reg) == 170

    def test_m6_gated_damage(self) -> None:
        """M6 additional afterburn: ``cmp_ge(mindscape, 6, atk * percent)``
        — mirrors ZO's mindscape-gated extra damage pattern.
        """
        reg = NodeRegistry()
        register_base_stats(
            reg,
            StatInputs(agent_base_atk=1000, wengine_base_atk=500),
        )

        # no mindscape → 0
        reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(5))
        node = compile_dsl(
            {
                "op": "cmp_ge",
                "left": {"op": "read", "q": "mindscape"},
                "right": 6,
                "if_ge": {
                    "op": "prod",
                    "args": [{"op": "stat", "name": "atk"}, 1.5],
                },
            }
        )
        assert _compute(node, reg) == 0

        # with M6 → atk * 1.5
        reg2 = NodeRegistry()
        register_base_stats(
            reg2,
            StatInputs(agent_base_atk=1000, wengine_base_atk=500),
        )
        reg2.register(Tag.of(**{Q: Q_MINDSCAPE}), const(6))
        atk = _compute(Q_ATK_NODE, reg2)
        assert _compute(node, reg2) == pytest.approx(atk * 1.5)


# ---- Integration with register_custom_standard_dmg ------------------------


class TestIntegrationWithSheetRegistration:
    """The DSL's primary consumer: feeding a compiled multiplier into
    ``register_custom_standard_dmg`` so agent JSONs can declare bespoke
    formulas without touching Python."""

    def test_dsl_multiplier_registers_as_standard_dmg(self) -> None:
        from app.formula.zzz.damage import register_enemy
        from app.formula.zzz.sheets import register_custom_standard_dmg
        from app.formula.zzz.tags import Q_STANDARD_DMG

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
        reg.register(Tag.of(**{Q: Q_MINDSCAPE}), const(1))

        # "basic_0 multiplier" expressed in DSL: const 4480 bp + M1 extra 500
        multiplier = compile_dsl(
            {
                "op": "sum",
                "args": [
                    4480,
                    {
                        "op": "cmp_ge",
                        "left": {"op": "read", "q": "mindscape"},
                        "right": 1,
                        "if_ge": 500,
                    },
                ],
            }
        )
        register_custom_standard_dmg(
            reg,
            sheet="burnice",
            name="basic_m1",
            scope="basic",
            element="fire",
            multiplier=multiplier,
        )
        value = Calculator(reg).compute(
            read_(formula_tag("burnice", "basic_m1", Q_STANDARD_DMG), "sum"),
        )
        assert value > 0
