"""Tests for the single-shot Pando Calculator.

Evaluates hand-built DAGs against expected values. Each op has at least one
test. Register/read plumbing is tested via the ``NodeRegistry`` interface.

Covers (maps to calc.ts switch):
    const, sum, prod, min, max, sumfrac,
    thres, match, lookup, subscript,
    tag, vtag, read, custom, reread (via registry)
"""

from __future__ import annotations

import math

import pytest

from app.formula.builder import (
    const,
    custom,
    lookup,
    match_,
    max_,
    min_,
    prod_,
    read_,
    subscript,
    sum_,
    sumfrac,
    tag_,
    threshold,
    vtag,
)
from app.formula.nodes import ReRead
from app.formula.tags import Tag
from app.pando.calculator import Calculator, NodeRegistry


def _calc(registry: NodeRegistry | None = None) -> Calculator:
    return Calculator(registry or NodeRegistry())


class TestConst:
    def test_number(self) -> None:
        assert _calc().compute(const(42)) == 42

    def test_string(self) -> None:
        assert _calc().compute(const("hello")) == "hello"


class TestArithmetic:
    def test_sum(self) -> None:
        assert _calc().compute(sum_(1, 2, 3)) == 6

    def test_sum_empty_is_zero(self) -> None:
        assert _calc().compute(sum_()) == 0

    def test_prod(self) -> None:
        assert _calc().compute(prod_(2, 3, 4)) == 24

    def test_prod_empty_is_one(self) -> None:
        assert _calc().compute(prod_()) == 1

    def test_min(self) -> None:
        assert _calc().compute(min_(5, 2, 8, 3)) == 2

    def test_max(self) -> None:
        assert _calc().compute(max_(5, 2, 8, 3)) == 8

    def test_sumfrac(self) -> None:
        # 10 / (10 + 40) = 0.2
        assert _calc().compute(sumfrac(10, 40)) == pytest.approx(0.2)

    def test_sumfrac_zero_numerator(self) -> None:
        assert _calc().compute(sumfrac(0, 10)) == 0

    def test_sumfrac_zero_denominator(self) -> None:
        """``0 / (0 + 0)`` → defined as 0 to avoid NaN in pruning."""
        assert _calc().compute(sumfrac(0, 0)) == 0


class TestBranching:
    def test_threshold_ge(self) -> None:
        # 5 >= 3 → "hi"
        assert _calc().compute(threshold(5, 3, "hi", "lo")) == "hi"

    def test_threshold_lt(self) -> None:
        # 1 >= 3 → "lo"
        assert _calc().compute(threshold(1, 3, "hi", "lo")) == "lo"

    def test_match_eq(self) -> None:
        assert _calc().compute(match_("a", "a", 1, 0)) == 1

    def test_match_ne(self) -> None:
        assert _calc().compute(match_("a", "b", 1, 0)) == 0

    def test_lookup_hit(self) -> None:
        n = lookup(
            const("fire"),
            {"fire": const(100), "ice": const(200)},
            default=const(0),
        )
        assert _calc().compute(n) == 100

    def test_lookup_miss_uses_default(self) -> None:
        n = lookup(
            const("lightning"),
            {"fire": const(100), "ice": const(200)},
            default=const(0),
        )
        assert _calc().compute(n) == 0

    def test_subscript(self) -> None:
        # defLevelFactor-style: level 60 -> table[60]
        table = tuple(range(1000))
        assert _calc().compute(subscript(60, table)) == 60


class TestTagNodes:
    def test_tag_override_pushes_context(self) -> None:
        # Inner reads 'src' from tag; outer override sets it
        inner = vtag("src")
        n = tag_(inner, Tag.of(src="Anby"))
        assert _calc().compute(n) == "Anby"

    def test_vtag_missing_returns_empty_string(self) -> None:
        assert _calc().compute(vtag("src")) == ""

    def test_nested_tag_overrides_last_wins(self) -> None:
        # Outer {src: Anby}, inner {src: Lucy} → Lucy wins for the read
        inner = tag_(vtag("src"), Tag.of(src="Lucy"))
        outer = tag_(inner, Tag.of(src="Anby"))
        assert _calc().compute(outer) == "Lucy"

    def test_tag_merge_preserves_unrelated_categories(self) -> None:
        # Outer sets src=Anby; inner sets q=atk_; read inside inner sees both
        inner = tag_(vtag("src"), Tag.of(q="atk_"))
        outer = tag_(inner, Tag.of(src="Anby"))
        assert _calc().compute(outer) == "Anby"


class TestRead:
    def test_read_single_registered_node(self) -> None:
        reg = NodeRegistry()
        reg.register(Tag.of(q="atk_"), const(100))
        calc = _calc(reg)
        assert calc.compute(read_(Tag.of(q="atk_"), "sum")) == 100

    def test_read_sum_accumulator(self) -> None:
        reg = NodeRegistry()
        reg.register(Tag.of(q="atk_"), const(100))
        reg.register(Tag.of(q="atk_"), const(50))
        reg.register(Tag.of(q="atk_"), const(25))
        calc = _calc(reg)
        assert calc.compute(read_(Tag.of(q="atk_"), "sum")) == 175

    def test_read_max_accumulator(self) -> None:
        reg = NodeRegistry()
        reg.register(Tag.of(q="atk_"), const(10))
        reg.register(Tag.of(q="atk_"), const(50))
        reg.register(Tag.of(q="atk_"), const(25))
        calc = _calc(reg)
        assert calc.compute(read_(Tag.of(q="atk_"), "max")) == 50

    def test_read_is_scoped_by_tag(self) -> None:
        """Nodes with wrong tag don't contribute."""
        reg = NodeRegistry()
        reg.register(Tag.of(q="atk_"), const(100))
        reg.register(Tag.of(q="hp_"), const(500))
        calc = _calc(reg)
        assert calc.compute(read_(Tag.of(q="atk_"), "sum")) == 100

    def test_read_is_filtered_by_current_tag_context(self) -> None:
        """Read gathers nodes whose registration tag is subset of current merged with read.tag."""
        reg = NodeRegistry()
        # Only Anby's ATK% should be picked up.
        reg.register(Tag.of(src="Anby", q="atk_"), const(30))
        reg.register(Tag.of(src="Lucy", q="atk_"), const(60))
        calc = _calc(reg)
        # Push src=Anby into context, then read q=atk_.
        n = tag_(read_(Tag.of(q="atk_"), "sum"), Tag.of(src="Anby"))
        assert calc.compute(n) == 30

    def test_read_empty_unique_raises(self) -> None:
        calc = _calc()
        with pytest.raises(ValueError, match="no match"):
            calc.compute(read_(Tag.of(q="nonexistent"), "unique"))

    def test_read_unique_returns_single_value(self) -> None:
        reg = NodeRegistry()
        reg.register(Tag.of(q="atk_base"), const(100))
        calc = _calc(reg)
        assert calc.compute(read_(Tag.of(q="atk_base"), "unique")) == 100

    def test_reread_forwards(self) -> None:
        """A ``ReRead`` registered at a tag reroutes ``read`` to gather its target tag."""
        reg = NodeRegistry()
        # A read at {alias} should pull from {original} via ReRead.
        reg.register(Tag.of(q="alias"), ReRead(tag=Tag.of(q="original")))
        reg.register(Tag.of(q="original"), const(42))
        calc = _calc(reg)
        assert calc.compute(read_(Tag.of(q="alias"), "sum")) == 42


class TestCustom:
    def test_custom_floor(self) -> None:
        """``floor`` is used by DEF level factor for discretization."""
        calc = _calc()
        assert calc.compute(custom("floor", 3.7)) == 3

    def test_custom_unknown_raises(self) -> None:
        with pytest.raises(KeyError, match="not_a_real_op"):
            _calc().compute(custom("not_a_real_op", 1))


class TestIntegration:
    """End-to-end: build an ATK-like formula as a DAG and evaluate."""

    def test_atk_formula(self) -> None:
        """ATK = ((base + wengine) * (1 + atk_pct) + flat) * (1 + final_pct) + final_flat."""
        reg = NodeRegistry()
        reg.register(Tag.of(q="atk_base"), const(600))  # agent
        reg.register(Tag.of(q="atk_base"), const(400))  # w-engine
        reg.register(Tag.of(q="atk_"), const(0.3))  # 30% from disc set
        reg.register(Tag.of(q="atk_flat"), const(100))  # flat atk from discs

        base_sum = read_(Tag.of(q="atk_base"), "sum")  # 1000
        pct_sum = read_(Tag.of(q="atk_"), "sum")  # 0.3
        flat_sum = read_(Tag.of(q="atk_flat"), "sum")  # 100
        atk = sum_(prod_(base_sum, sum_(1.0, pct_sum)), flat_sum)

        calc = _calc(reg)
        # (1000 * 1.30) + 100 = 1400
        assert calc.compute(atk) == pytest.approx(1400)

    def test_def_multiplier_via_sumfrac_and_subscript(self) -> None:
        level_factor_table = tuple(
            math.floor(0.1551 * min(60, lvl) ** 2 + 3.141 * min(60, lvl) + 47.2039)
            for lvl in range(61)
        )
        atk_lvl = const(60)
        enemy_def = const(794)  # crafted so DEFArea = 0.5
        lf = subscript(atk_lvl, level_factor_table)
        def_area = sumfrac(lf, enemy_def)

        assert _calc().compute(def_area) == pytest.approx(0.5, rel=1e-3)
