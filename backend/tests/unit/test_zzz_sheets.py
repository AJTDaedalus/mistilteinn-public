"""Tests for per-agent formula sheet registration primitives.

``register_attack_hit`` registers three DAG nodes under a single
``(sheet, name)`` pair — one per damage/daze/anom quantity. Each test
verifies both the value (parity against the procedural damage calc) and
the tag structure (formulas are discoverable by sheet+name+quantity read).
"""

from __future__ import annotations

import pytest

from app.formula.builder import const, read_
from app.formula.zzz.sheets import (
    register_attack_hit,
    register_custom_anom_buildup,
    register_custom_standard_dmg,
)
from app.formula.zzz.stats import register_base_stats
from app.formula.zzz.tags import (
    Q_ANOM_BUILDUP,
    Q_DAZE_BUILDUP,
    Q_STANDARD_DMG,
    formula_tag,
)
from app.pando.calculator import Calculator, NodeRegistry

from app.formula.zzz.damage import register_enemy  # isort: skip
from app.services.damage_calculator import (  # isort: skip
    calculate_standard_damage,
)
from app.services.stat_calculator import StatInputs  # isort: skip


def _dmg(reg: NodeRegistry, sheet: str, name: str) -> float:
    return Calculator(reg).compute(read_(formula_tag(sheet, name, Q_STANDARD_DMG), "sum"))


def _daze(reg: NodeRegistry, sheet: str, name: str) -> float:
    return Calculator(reg).compute(read_(formula_tag(sheet, name, Q_DAZE_BUILDUP), "sum"))


def _anom(reg: NodeRegistry, sheet: str, name: str) -> float:
    return Calculator(reg).compute(read_(formula_tag(sheet, name, Q_ANOM_BUILDUP), "sum"))


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


class TestRegisterAttackHit:
    def test_registers_all_three_quantities(self) -> None:
        reg = _basic_setup()
        register_attack_hit(
            reg,
            sheet="burnice",
            name="basic_0",
            scope="basic",
            element="fire",
            damage_mult_bp=4480,
            daze_mult_bp=1000,
            anom_buildup_bp=500,
        )
        # All three reads resolve without raising
        assert _dmg(reg, "burnice", "basic_0") > 0
        assert _daze(reg, "burnice", "basic_0") > 0
        assert _anom(reg, "burnice", "basic_0") > 0

    def test_damage_parity_with_procedural(self) -> None:
        reg = _basic_setup()
        register_attack_hit(
            reg,
            sheet="burnice",
            name="basic_0",
            scope="basic",
            element="fire",
            damage_mult_bp=4480,
        )
        dag_value = _dmg(reg, "burnice", "basic_0")

        from app.services.stat_calculator import compute_total_stats

        stats = compute_total_stats(
            StatInputs(
                agent_base_atk=700,
                wengine_base_atk=600,
                atk_pct=3000,
                flat_atk=200,
                crit_rate=5000,
                crit_dmg=15000,
                fire_dmg=2500,
            )
        )
        proc = calculate_standard_damage(
            scaling_stat=stats.atk,
            multiplier=4480,
            dmg_bonuses=[2500],
            crit_rate=5000,
            crit_dmg=15000,
            enemy_base_def=60,
            enemy_level=60,
        )
        assert dag_value == pytest.approx(proc.total, rel=0.01)

    def test_daze_is_scaling_times_mult(self) -> None:
        reg = _basic_setup()
        register_attack_hit(
            reg,
            sheet="burnice",
            name="basic_0",
            scope="basic",
            element="fire",
            damage_mult_bp=4480,
            daze_mult_bp=1000,
        )
        # daze = ATK * 1000bp = ATK * 0.1
        from app.services.stat_calculator import compute_total_stats

        atk = compute_total_stats(
            StatInputs(
                agent_base_atk=700,
                wengine_base_atk=600,
                atk_pct=3000,
                flat_atk=200,
            )
        ).atk
        assert _daze(reg, "burnice", "basic_0") == pytest.approx(atk * 0.1)

    def test_anom_buildup_default_zero(self) -> None:
        reg = _basic_setup()
        register_attack_hit(
            reg,
            sheet="burnice",
            name="basic_0",
            scope="basic",
            element="fire",
            damage_mult_bp=4480,  # daze & anom omitted → 0
        )
        assert _daze(reg, "burnice", "basic_0") == 0.0
        assert _anom(reg, "burnice", "basic_0") == 0.0

    def test_scope_gated_modifier_applies(self) -> None:
        """An EX Special attack picks up a crit-rate modifier registered at
        ``{q: crit_rate, scope: ex_special}`` — scope tag is pushed by the
        attack's ``tag_`` wrapper so the inner reads see the bonus."""
        from app.formula.tags import Tag
        from app.formula.zzz.tags import Q_CRIT_RATE, SCOPE, Q

        reg = _basic_setup()
        reg.register(
            Tag.of(**{Q: Q_CRIT_RATE, SCOPE: "ex_special"}),
            const(3000),  # +30% crit on EX Special only
        )

        register_attack_hit(
            reg,
            sheet="burnice",
            name="ex_0",
            scope="ex_special",
            element="fire",
            damage_mult_bp=6660,
        )
        register_attack_hit(
            reg,
            sheet="burnice",
            name="basic_0",
            scope="basic",
            element="fire",
            damage_mult_bp=6660,
        )
        # Same multiplier, same scaling, different scopes → EX larger (crit boost applies)
        assert _dmg(reg, "burnice", "ex_0") > _dmg(reg, "burnice", "basic_0")

    def test_unknown_scaling_stat_rejected(self) -> None:
        reg = NodeRegistry()
        with pytest.raises(ValueError, match="unknown scaling_stat"):
            register_attack_hit(
                reg,
                sheet="x",
                name="y",
                scope="basic",
                element="fire",
                scaling_stat="mana",  # invalid
                damage_mult_bp=1000,
            )

    def test_different_sheets_do_not_collide(self) -> None:
        """Two sheets registering the same ``name`` stay separate thanks to
        the sheet tag — verifies the per-agent namespacing works."""
        reg = _basic_setup()
        register_attack_hit(
            reg,
            sheet="burnice",
            name="basic_0",
            scope="basic",
            element="fire",
            damage_mult_bp=4480,
        )
        register_attack_hit(
            reg,
            sheet="ellen",
            name="basic_0",
            scope="basic",
            element="ice",
            damage_mult_bp=8000,
        )
        a = _dmg(reg, "burnice", "basic_0")
        b = _dmg(reg, "ellen", "basic_0")
        assert a > 0
        assert b > 0
        assert a != b


class TestRegisterCustomStandardDmg:
    def test_constant_multiplier_equivalent_to_attack_hit_dmg(self) -> None:
        """A custom formula with a ``const(4480)`` multiplier matches the
        damage output of ``register_attack_hit(damage_mult_bp=4480)`` —
        confirms the custom path and the standard path compose identically
        through the damage zones."""
        reg = _basic_setup()
        register_attack_hit(
            reg,
            sheet="burnice",
            name="basic_0",
            scope="basic",
            element="fire",
            damage_mult_bp=4480,
        )
        register_custom_standard_dmg(
            reg,
            sheet="burnice",
            name="custom_equiv",
            scope="basic",
            element="fire",
            multiplier=const(4480),
        )
        assert _dmg(reg, "burnice", "basic_0") == pytest.approx(
            _dmg(reg, "burnice", "custom_equiv"),
            rel=1e-9,
        )


class TestRegisterCustomAnomBuildup:
    def test_constant_value_registers_directly(self) -> None:
        """Burnice's ``core_afterburn_anomBuildup = 60`` is a flat gauge
        value — no scaling stat product, no multiplier zones."""
        reg = NodeRegistry()
        register_custom_anom_buildup(
            reg,
            sheet="burnice",
            name="core_afterburn",
            scope="assist_followup",
            value=60,
        )
        assert _anom(reg, "burnice", "core_afterburn") == 60
