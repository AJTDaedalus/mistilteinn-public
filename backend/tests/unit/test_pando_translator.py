"""Tests for the Modifier → DAG translator.

The translator writes three kinds of entries into the NodeRegistry:

1. **Condition indicators** — one ``Const(1)`` per active condition
   registered at ``{q: cond_active, cond: <name>}``. Inactive conditions
   are *not* registered, so the indicator read yields 0 via the ``sum``
   accumulator on empty match.

2. **Stack counts** — one ``Const(n)`` per ``source_label`` in
   ``stack_counts``, registered at ``{q: stack, label: <label>}``.

3. **Stat contributions** — one node per modifier, registered at the
   stat tag, gated by a ``Threshold`` on the product of its condition
   indicators. Stackable modifiers multiply the value by the stack read.

Parity gate: for any ``(modifiers, conditions, scope)`` triple, the sum
of the translated stat entries equals the bucketed output of the
existing ``resolve_modifiers`` function. That's the test that matters;
internal structure is an implementation detail.
"""

from __future__ import annotations

from app.formula.builder import read_
from app.formula.tags import Tag
from app.formula.zzz.tags import (
    cond_tag,
    stack_tag,
    stat_tag,
)
from app.pando.calculator import Calculator, NodeRegistry
from app.pando.translator import translate_modifiers
from app.services.buff_resolver import resolve_modifiers
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


def _active(*conds: Condition) -> ActiveConditions:
    return ActiveConditions(active=set(conds) | {Condition.ALWAYS})


def _stat_total(calc: Calculator, _registry: NodeRegistry, stat: str) -> int:
    """Sum all registered values for ``stat`` via a ``read(sum)``."""
    return int(calc.compute(read_(stat_tag(stat), "sum")))


def _read_sum(calc: Calculator, tag: Tag) -> int:
    return int(calc.compute(read_(tag, "sum")))


class TestConditionIndicators:
    def test_active_condition_writes_indicator(self) -> None:
        reg = NodeRegistry()
        translate_modifiers(reg, [], _active(Condition.STUN_IN_TEAM))
        assert _read_sum(Calculator(reg), cond_tag(Condition.STUN_IN_TEAM.value)) == 1

    def test_inactive_condition_has_no_indicator(self) -> None:
        reg = NodeRegistry()
        translate_modifiers(reg, [], _active())  # only ALWAYS
        assert _read_sum(Calculator(reg), cond_tag(Condition.STUN_IN_TEAM.value)) == 0

    def test_always_is_always_active(self) -> None:
        reg = NodeRegistry()
        translate_modifiers(reg, [], _active())
        assert _read_sum(Calculator(reg), cond_tag(Condition.ALWAYS.value)) == 1


class TestStackCounts:
    def test_stack_count_writes_to_registry(self) -> None:
        reg = NodeRegistry()
        conds = ActiveConditions(
            active={Condition.ALWAYS},
            stack_counts={"MyMod": 3},
        )
        translate_modifiers(reg, [], conds)
        assert _read_sum(Calculator(reg), stack_tag("MyMod")) == 3

    def test_missing_stack_count_reads_zero(self) -> None:
        reg = NodeRegistry()
        translate_modifiers(reg, [], _active())
        assert _read_sum(Calculator(reg), stack_tag("NoSuchMod")) == 0


class TestUnconditionalModifier:
    def test_writes_stat_contribution(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=3000,
                source=ModifierSource.DISC_SET_2PC,
                conditions=(Condition.ALWAYS,),
                scopes=(AttackScope.ALL,),
            ),
        ]
        translate_modifiers(reg, mods, _active())
        calc = Calculator(reg)
        assert _stat_total(calc, reg, "atk_pct") == 3000

    def test_multiple_unconditional_sum(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(stat="atk_pct", value=1000, source=ModifierSource.CORE_SKILL),
            Modifier(stat="atk_pct", value=2500, source=ModifierSource.DISC_SET_2PC),
            Modifier(stat="atk_pct", value=500, source=ModifierSource.WENGINE_PASSIVE),
        ]
        translate_modifiers(reg, mods, _active())
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 4000


class TestConditionalModifier:
    def test_inactive_condition_gate_returns_zero(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=5000,
                source=ModifierSource.CORE_SKILL,
                conditions=(Condition.STUN_IN_TEAM,),
            ),
        ]
        translate_modifiers(reg, mods, _active())  # STUN_IN_TEAM not active
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 0

    def test_active_condition_gate_passes_value(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=5000,
                source=ModifierSource.CORE_SKILL,
                conditions=(Condition.STUN_IN_TEAM,),
            ),
        ]
        translate_modifiers(reg, mods, _active(Condition.STUN_IN_TEAM))
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 5000

    def test_multiple_conditions_all_must_be_active(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=5000,
                source=ModifierSource.CORE_SKILL,
                conditions=(Condition.STUN_IN_TEAM, Condition.ENEMY_STUNNED),
            ),
        ]
        # Only one of two active → gated off
        translate_modifiers(reg, mods, _active(Condition.STUN_IN_TEAM))
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 0

    def test_multiple_conditions_all_active_passes(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=5000,
                source=ModifierSource.CORE_SKILL,
                conditions=(Condition.STUN_IN_TEAM, Condition.ENEMY_STUNNED),
            ),
        ]
        translate_modifiers(
            reg,
            mods,
            _active(Condition.STUN_IN_TEAM, Condition.ENEMY_STUNNED),
        )
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 5000


class TestStackableModifier:
    def test_stack_count_multiplies_value(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=500,
                max_stacks=5,
                source_label="Stackable",
                source=ModifierSource.WENGINE_PASSIVE,
            ),
        ]
        conds = ActiveConditions(
            active={Condition.ALWAYS},
            stack_counts={"Stackable": 3},
        )
        translate_modifiers(reg, mods, conds)
        # 500 * 3 = 1500
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 1500

    def test_stack_count_capped_at_max(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=500,
                max_stacks=5,
                source_label="Stackable",
                source=ModifierSource.WENGINE_PASSIVE,
            ),
        ]
        conds = ActiveConditions(
            active={Condition.ALWAYS},
            stack_counts={"Stackable": 99},  # over max
        )
        translate_modifiers(reg, mods, conds)
        # 500 * 5 = 2500 (capped)
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 2500


class TestScopeFiltering:
    def test_scope_filter_skips_mismatched_scope(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=3000,
                source=ModifierSource.CORE_SKILL,
                scopes=(AttackScope.ULTIMATE,),
            ),
        ]
        translate_modifiers(reg, mods, _active(), attack_scope=AttackScope.BASIC)
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 0

    def test_scope_filter_passes_matching_scope(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=3000,
                source=ModifierSource.CORE_SKILL,
                scopes=(AttackScope.BASIC,),
            ),
        ]
        translate_modifiers(reg, mods, _active(), attack_scope=AttackScope.BASIC)
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 3000

    def test_scope_all_matches_any_scope(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=3000,
                source=ModifierSource.CORE_SKILL,
                scopes=(AttackScope.ALL,),
            ),
        ]
        translate_modifiers(reg, mods, _active(), attack_scope=AttackScope.BASIC)
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 3000


class TestTargetFiltering:
    def test_self_filter_excludes_team_target_by_default(self) -> None:
        """Target filter mirrors buff_resolver: SELF includes team-targeted too."""
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=3000,
                source=ModifierSource.CORE_SKILL,
                target=ModifierTarget.TEAM,
            ),
        ]
        # target_filter=SELF — buff_resolver includes TEAM too (see line 96)
        translate_modifiers(reg, mods, _active(), target_filter=ModifierTarget.SELF)
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 3000

    def test_filter_excludes_non_matching_target(self) -> None:
        reg = NodeRegistry()
        mods = [
            Modifier(
                stat="atk_pct",
                value=3000,
                source=ModifierSource.CORE_SKILL,
                target=ModifierTarget.SUMMON,
            ),
        ]
        translate_modifiers(reg, mods, _active(), target_filter=ModifierTarget.SELF)
        assert _stat_total(Calculator(reg), reg, "atk_pct") == 0


class TestParityWithBuffResolver:
    """For every bucket that buff_resolver tracks, the translated DAG must
    produce the identical numeric contribution sum. This is the gate that
    catches any divergence before we replace the service."""

    def _compare(
        self,
        modifiers: list[Modifier],
        conds: ActiveConditions,
        scope: AttackScope = AttackScope.ALL,
    ) -> None:
        expected = resolve_modifiers(modifiers, conds, attack_scope=scope)
        reg = NodeRegistry()
        translate_modifiers(reg, modifiers, conds, attack_scope=scope)
        calc = Calculator(reg)

        # Every stat bucket
        for stat, value in expected.stat_bonuses.items():
            assert _stat_total(calc, reg, stat) == value, f"stat_bonus {stat}"
        for stat in (
            "hp_pct",
            "atk_pct",
            "def_pct",
            "flat_hp",
            "flat_atk",
            "flat_def",
            "final_hp_pct",
            "final_atk_pct",
            "final_def_pct",
            "final_flat_hp",
            "final_flat_atk",
            "final_flat_def",
            "crit_rate",
            "crit_dmg",
            "anomaly_mastery",
            "anomaly_proficiency",
            "impact",
            "energy_regen",
            "pen_flat",
            "pen_ratio",
            "physical_dmg",
            "fire_dmg",
            "ice_dmg",
            "electric_dmg",
            "ether_dmg",
        ):
            if stat not in expected.stat_bonuses:
                assert _stat_total(calc, reg, stat) == 0, f"empty stat {stat}"

        # dmg_bonus bucket → scope-gated aggregate
        from app.formula.builder import read_

        actual_dmg = int(
            calc.compute(
                # Pull all dmg_bonus entries regardless of scope for total parity.
                read_(Tag.of(q="dmg_bonus"), "sum"),
            ),
        )
        assert actual_dmg == expected.total_dmg_bonus

        # Combat stats
        for stat in (
            "res_reduction",
            "res_ignore",
            "def_ignore",
            "vulnerability",
            "anomaly_dmg_bonus",
        ):
            actual = _stat_total(calc, reg, stat)
            expected_val = expected.combat_bonuses.get(stat, 0)
            assert actual == expected_val, f"combat {stat}: {actual} vs {expected_val}"

    def test_empty_modifiers(self) -> None:
        self._compare([], _active())

    def test_single_unconditional(self) -> None:
        self._compare(
            [Modifier(stat="atk_pct", value=3000, source=ModifierSource.DISC_SET_2PC)],
            _active(),
        )

    def test_mixed_buckets(self) -> None:
        """Stat + dmg_bonus + combat stats all at once."""
        mods = [
            Modifier(stat="atk_pct", value=2500, source=ModifierSource.DISC_SET_2PC),
            Modifier(stat="ice_dmg", value=1500, source=ModifierSource.WENGINE_PASSIVE),
            Modifier(stat="dmg_bonus", value=1000, source=ModifierSource.CORE_SKILL),
            Modifier(stat="basic_dmg_bonus", value=800, source=ModifierSource.CORE_SKILL),
            Modifier(stat="res_reduction", value=2000, source=ModifierSource.TEAM_BUFF),
            Modifier(stat="vulnerability", value=1500, source=ModifierSource.TEAM_BUFF),
        ]
        self._compare(mods, _active())

    def test_conditional_gating(self) -> None:
        mods = [
            Modifier(
                stat="atk_pct",
                value=5000,
                source=ModifierSource.CORE_SKILL,
                conditions=(Condition.STUN_IN_TEAM,),
            ),
            Modifier(
                stat="crit_rate",
                value=1000,
                source=ModifierSource.CORE_SKILL,
                conditions=(Condition.ENEMY_STUNNED,),
            ),
        ]
        self._compare(mods, _active(Condition.STUN_IN_TEAM))

    def test_stackable(self) -> None:
        mods = [
            Modifier(
                stat="atk_pct",
                value=500,
                source=ModifierSource.WENGINE_PASSIVE,
                source_label="Stacks",
                max_stacks=5,
            ),
        ]
        conds = ActiveConditions(active={Condition.ALWAYS}, stack_counts={"Stacks": 4})
        self._compare(mods, conds)

    def test_scope_filtering_basic(self) -> None:
        mods = [
            Modifier(
                stat="dmg_bonus",
                value=3000,
                source=ModifierSource.CORE_SKILL,
                scopes=(AttackScope.BASIC,),
            ),
            Modifier(
                stat="dmg_bonus",
                value=4000,
                source=ModifierSource.CORE_SKILL,
                scopes=(AttackScope.ULTIMATE,),
            ),
        ]
        self._compare(mods, _active(), scope=AttackScope.BASIC)
