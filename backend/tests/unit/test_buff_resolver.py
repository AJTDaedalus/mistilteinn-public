"""Unit tests for buff resolution (buff_resolver.py)."""

from __future__ import annotations

from app.services.buff_resolver import ResolvedBuffs, resolve_modifiers
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.stat_calculator import StatInputs


def _mod_with_source(
    stat: str = "atk_pct",
    value: int = 1000,
    source: ModifierSource = ModifierSource.CORE_SKILL,
    source_label: str = "Core F",
    owner_name: str | None = None,
    notes: str | None = None,
) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=source,
        source_label=source_label,
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
        owner_name=owner_name,
        notes=notes,
    )


def _mod(
    stat: str = "atk_pct",
    value: int = 1000,
    conditions: tuple[Condition, ...] = (Condition.ALWAYS,),
    scopes: tuple[AttackScope, ...] = (AttackScope.ALL,),
    target: ModifierTarget = ModifierTarget.SELF,
    max_stacks: int = 1,
    source_label: str = "test",
    element_scope: tuple[str, ...] | None = None,
) -> Modifier:
    """Helper to create a test modifier with minimal boilerplate."""
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.CORE_SKILL,
        source_label=source_label,
        target=target,
        conditions=conditions,
        scopes=scopes,
        max_stacks=max_stacks,
        element_scope=element_scope,
    )


class TestResolveModifiers:
    def test_always_active(self):
        mods = [_mod(stat="atk_pct", value=3000)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.stat_bonuses["atk_pct"] == 3000

    def test_inactive_condition_excluded(self):
        mods = [_mod(conditions=(Condition.ENEMY_STUNNED,))]
        result = resolve_modifiers(mods, ActiveConditions())
        assert len(result.stat_bonuses) == 0

    def test_active_condition_included(self):
        mods = [_mod(conditions=(Condition.ENEMY_STUNNED,))]
        conds = ActiveConditions(active={Condition.ALWAYS, Condition.ENEMY_STUNNED})
        result = resolve_modifiers(mods, conds)
        assert result.stat_bonuses["atk_pct"] == 1000

    def test_and_conditions_all_required(self):
        mods = [_mod(conditions=(Condition.ENEMY_STUNNED, Condition.SAME_ELEMENT_IN_TEAM))]
        # Only one condition met
        conds = ActiveConditions(active={Condition.ALWAYS, Condition.ENEMY_STUNNED})
        result = resolve_modifiers(mods, conds)
        assert len(result.stat_bonuses) == 0

        # Both met
        conds = ActiveConditions(
            active={Condition.ALWAYS, Condition.ENEMY_STUNNED, Condition.SAME_ELEMENT_IN_TEAM}
        )
        result = resolve_modifiers(mods, conds)
        assert result.stat_bonuses["atk_pct"] == 1000

    def test_scope_filtering(self):
        mods = [_mod(scopes=(AttackScope.DASH, AttackScope.CHAIN))]
        # Matching scope
        result = resolve_modifiers(mods, ActiveConditions(), attack_scope=AttackScope.DASH)
        assert result.stat_bonuses["atk_pct"] == 1000

        # Non-matching scope
        result = resolve_modifiers(mods, ActiveConditions(), attack_scope=AttackScope.BASIC)
        assert len(result.stat_bonuses) == 0

    def test_all_scope_matches_everything(self):
        mods = [_mod(scopes=(AttackScope.ALL,))]
        result = resolve_modifiers(mods, ActiveConditions(), attack_scope=AttackScope.EX_SPECIAL)
        assert result.stat_bonuses["atk_pct"] == 1000

    def test_scope_all_query_includes_scoped_mods(self):
        """When attack_scope=ALL, scoped modifiers are still included."""
        mods = [_mod(scopes=(AttackScope.DASH,))]
        result = resolve_modifiers(mods, ActiveConditions(), attack_scope=AttackScope.ALL)
        assert result.stat_bonuses["atk_pct"] == 1000

    def test_stacking(self):
        mods = [_mod(value=300, max_stacks=10, source_label="ice_stack")]
        conds = ActiveConditions(stack_counts={"ice_stack": 7})
        result = resolve_modifiers(mods, conds)
        assert result.stat_bonuses["atk_pct"] == 2100  # 300 * 7

    def test_stacking_capped_at_max(self):
        mods = [_mod(value=300, max_stacks=5, source_label="stack")]
        conds = ActiveConditions(stack_counts={"stack": 10})
        result = resolve_modifiers(mods, conds)
        assert result.stat_bonuses["atk_pct"] == 1500  # 300 * 5

    def test_unset_stacks_default_to_max(self):
        """An enabled stackable buff with no explicit count is fully stacked."""
        mods = [_mod(value=300, max_stacks=10, source_label="stack")]
        conds = ActiveConditions(stack_counts={})
        result = resolve_modifiers(mods, conds)
        assert result.stat_bonuses["atk_pct"] == 3000  # 300 * 10

    def test_stacking_zero_stacks(self):
        """An explicit 0 means the user modeled the buff as not yet stacked."""
        mods = [_mod(value=300, max_stacks=10, source_label="stack")]
        conds = ActiveConditions(stack_counts={"stack": 0})
        result = resolve_modifiers(mods, conds)
        # Zero-valued contributions are dropped to keep attribution
        # lists clean — callers default to 0 when the key is absent.
        assert result.stat_bonuses.get("atk_pct", 0) == 0

    def test_multiple_modifiers_sum(self):
        mods = [
            _mod(stat="crit_rate", value=1000),
            _mod(stat="crit_rate", value=500),
        ]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.stat_bonuses["crit_rate"] == 1500

    def test_dmg_bonus_stat(self):
        mods = [_mod(stat="dmg_bonus", value=2500)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.total_dmg_bonus == 2500

    def test_combat_stats(self):
        mods = [
            _mod(stat="res_reduction", value=2000),
            _mod(stat="vulnerability", value=1500),
            _mod(stat="def_ignore", value=1000),
        ]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.res_reduction == 2000
        assert result.vulnerability == 1500
        assert result.def_ignore == 1000

    def test_target_filter(self):
        mods = [
            _mod(target=ModifierTarget.SELF, value=1000),
            _mod(target=ModifierTarget.TEAM, value=500),
        ]
        result = resolve_modifiers(mods, ActiveConditions(), target_filter=ModifierTarget.SELF)
        # SELF mod included, TEAM mod also included (team buffs apply to everyone)
        assert result.stat_bonuses["atk_pct"] == 1500

    def test_target_filter_excludes_other(self):
        mods = [_mod(target=ModifierTarget.SUMMON)]
        result = resolve_modifiers(mods, ActiveConditions(), target_filter=ModifierTarget.SELF)
        assert len(result.stat_bonuses) == 0


class TestElementScope:
    """C7 / D-KV16: `element_scope` restricts res_reduction/res_ignore rows to
    specific damage elements — the Lycaon fix (25% Ice-only + 30% non-Ice-only
    instead of 55% on every element)."""

    def test_scoped_row_included_when_element_matches(self):
        mods = [_mod(stat="res_reduction", value=2500, element_scope=("ice",))]
        result = resolve_modifiers(mods, ActiveConditions(), damage_element="ice")
        assert result.res_reduction == 2500

    def test_scoped_row_excluded_when_element_does_not_match(self):
        mods = [_mod(stat="res_reduction", value=2500, element_scope=("ice",))]
        result = resolve_modifiers(mods, ActiveConditions(), damage_element="fire")
        assert result.res_reduction == 0

    def test_unscoped_row_applies_to_every_element(self):
        mods = [_mod(stat="res_reduction", value=1000)]
        for element in ("ice", "fire", "physical"):
            result = resolve_modifiers(mods, ActiveConditions(), damage_element=element)
            assert result.res_reduction == 1000

    def test_lycaon_split_sums_correctly_per_element(self):
        """The two-row Lycaon shape: Ice-only 25% + non-Ice-only 30%, never both."""
        mods = [
            _mod(stat="res_reduction", value=2500, element_scope=("ice",), source_label="ice-row"),
            _mod(
                stat="res_reduction",
                value=3000,
                element_scope=("physical", "fire", "electric", "ether"),
                source_label="non-ice-row",
            ),
        ]
        ice_result = resolve_modifiers(mods, ActiveConditions(), damage_element="ice")
        assert ice_result.res_reduction == 2500

        fire_result = resolve_modifiers(mods, ActiveConditions(), damage_element="fire")
        assert fire_result.res_reduction == 3000

    def test_no_damage_element_context_keeps_scoped_row_unfiltered(self):
        """Callers that don't thread an element (buff roster / DAG parity path,
        pre-C7 behaviour) still see the row — only callers that pass
        `damage_element` get the filter."""
        mods = [_mod(stat="res_reduction", value=2500, element_scope=("ice",))]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.res_reduction == 2500

    def test_element_scope_ignored_on_unhonored_stat(self):
        """element_scope is only wired for res_reduction/res_ignore; a stat
        outside that set is unaffected by the filter (L0 is what stops this
        from shipping — see test_validate_kits_l0.py)."""
        mods = [_mod(stat="dmg_bonus", value=1000, element_scope=("ice",))]
        result = resolve_modifiers(mods, ActiveConditions(), damage_element="fire")
        assert result.total_dmg_bonus == 1000


class TestResolvedBuffs:
    def test_apply_to_stat_inputs(self):
        result = ResolvedBuffs()
        result.stat_bonuses = {"atk_pct": 3000, "crit_rate": 1200}
        inputs = StatInputs(atk_pct=1000, crit_rate=500)
        result.apply_to_stat_inputs(inputs)
        assert inputs.atk_pct == 4000  # 1000 + 3000
        assert inputs.crit_rate == 1700  # 500 + 1200

    def test_empty_combat_stats_default_zero(self):
        result = ResolvedBuffs()
        assert result.res_reduction == 0
        assert result.res_ignore == 0
        assert result.def_ignore == 0
        assert result.vulnerability == 0
        assert result.anomaly_dmg_bonus == 0
        assert result.stun_dmg_mult_bonus == 0


class TestStunDmgMultBonus:
    """T-A4: stun_dmg_mult_bonus routes through combat_bonuses."""

    def test_routed_to_combat_bonuses(self):
        mods = [_mod(stat="stun_dmg_mult_bonus", value=5000)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.stun_dmg_mult_bonus == 5000

    def test_conditional_on_enemy_stunned(self):
        mods = [
            _mod(stat="stun_dmg_mult_bonus", value=5000, conditions=(Condition.ENEMY_STUNNED,))
        ]
        assert resolve_modifiers(mods, ActiveConditions()).stun_dmg_mult_bonus == 0
        on = ActiveConditions(active={Condition.ALWAYS, Condition.ENEMY_STUNNED})
        assert resolve_modifiers(mods, on).stun_dmg_mult_bonus == 5000

    def test_multiple_sources_stack_additively(self):
        mods = [
            _mod(stat="stun_dmg_mult_bonus", value=3000, source_label="src1"),
            _mod(stat="stun_dmg_mult_bonus", value=2000, source_label="src2"),
        ]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.stun_dmg_mult_bonus == 5000


class TestContributionEnrichment:
    """Verify resolve_modifiers populates source_category, source_kind, owner_agent_name."""

    def test_agent_core_skill_contribution(self):
        mod = _mod_with_source(
            source=ModifierSource.CORE_SKILL,
            source_label="Core Passive",
            owner_name="Ellen Joe",
        )
        result = resolve_modifiers([mod], ActiveConditions())
        contribs = result.stat_attributions["atk_pct"]
        assert len(contribs) == 1
        c = contribs[0]
        assert c.source_category == "agent"
        assert c.source_kind == "core_skill"
        assert c.owner_agent_name == "Ellen Joe"
        assert c.description is None

    def test_wengine_contribution(self):
        mod = _mod_with_source(
            source=ModifierSource.WENGINE_PASSIVE,
            source_label="Deep Sea Visitor R1",
            owner_name="Ellen Joe",
        )
        result = resolve_modifiers([mod], ActiveConditions())
        contribs = result.stat_attributions["atk_pct"]
        assert contribs[0].source_category == "wengine"
        assert contribs[0].source_kind == "wengine_passive"
        assert contribs[0].owner_agent_name == "Ellen Joe"

    def test_disc_set_contribution(self):
        mod = _mod_with_source(
            source=ModifierSource.DISC_SET_4PC,
            source_label="Polar Metal 4pc",
        )
        result = resolve_modifiers([mod], ActiveConditions())
        contribs = result.stat_attributions["atk_pct"]
        assert contribs[0].source_category == "disc_set"
        assert contribs[0].source_kind == "disc_set_4pc"
        assert contribs[0].owner_agent_name is None

    def test_external_contribution(self):
        mod = _mod_with_source(source=ModifierSource.EXTERNAL, source_label="Food Buff")
        result = resolve_modifiers([mod], ActiveConditions())
        contribs = result.stat_attributions["atk_pct"]
        assert contribs[0].source_category == "external"

    def test_untagged_modifier_category_derived_from_source_enum(self):
        mod = Modifier(
            stat="atk_pct",
            value=500,
            source=ModifierSource.CORE_SKILL,
            source_label="Old mod",
        )
        result = resolve_modifiers([mod], ActiveConditions())
        c = result.stat_attributions["atk_pct"][0]
        assert c.source_category == "agent"
        assert c.owner_agent_name is None

    def test_notes_threaded_from_modifier(self):
        mod = _mod_with_source(notes="Cross-referenced with ZO commit abc1234.")
        result = resolve_modifiers([mod], ActiveConditions())
        c = result.stat_attributions["atk_pct"][0]
        assert c.notes == "Cross-referenced with ZO commit abc1234."

    def test_notes_absent_is_none(self):
        mod = _mod_with_source()
        result = resolve_modifiers([mod], ActiveConditions())
        c = result.stat_attributions["atk_pct"][0]
        assert c.notes is None


class TestStunAreaOverride:
    def test_routed_to_combat_bonuses(self):
        mods = [_mod(stat="stun_area_override", value=11000)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.stun_area_override == 11000

    def test_max_across_multiple_sources(self):
        mods = [
            _mod(stat="stun_area_override", value=10000, source_label="src1"),
            _mod(stat="stun_area_override", value=11000, source_label="src2"),
            _mod(stat="stun_area_override", value=9000, source_label="src3"),
        ]
        result = resolve_modifiers(mods, ActiveConditions())
        # Should take the max (11000) rather than summing
        assert result.stun_area_override == 11000

    def test_empty_override_defaults_to_zero(self):
        result = ResolvedBuffs()
        assert result.stun_area_override == 0


class TestGraceShockDmgBonus:
    """H3: Grace M4 uses shock_dmg_bonus — routes to combat_bonuses, not anomaly_dmg_bonus."""

    def test_shock_dmg_bonus_routes_to_combat_bonuses(self):
        mods = [_mod(stat="shock_dmg_bonus", value=2000)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.shock_dmg_bonus == 2000

    def test_shock_dmg_bonus_does_not_inflate_anomaly_dmg_bonus(self):
        mods = [_mod(stat="shock_dmg_bonus", value=2000)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.anomaly_dmg_bonus == 0

    def test_shock_dmg_bonus_empty_defaults_zero(self):
        result = ResolvedBuffs()
        assert result.shock_dmg_bonus == 0


class TestAnomalyMasteryRouting:
    """Task 1.6b — anomaly_mastery_flat and anomaly_mastery_pct must route correctly."""

    def test_anomaly_mastery_flat_routes_to_flat_accumulator(self):
        # W-Engine passives use stat="anomaly_mastery_flat" — must land in inputs.anomaly_mastery
        mods = [_mod(stat="anomaly_mastery_flat", value=60)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.stat_bonuses.get("anomaly_mastery_flat") == 60
        # apply_to_stat_inputs must write it to the "anomaly_mastery" field
        inputs = StatInputs()
        result.apply_to_stat_inputs(inputs)
        assert inputs.anomaly_mastery == 60

    def test_anomaly_mastery_pct_routes_to_am_pct(self):
        # Phaethon's Melody 2pc / W-Engine secondary — must land in inputs.am_pct
        mods = [_mod(stat="anomaly_mastery_pct", value=800)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.stat_bonuses.get("anomaly_mastery_pct") == 800
        inputs = StatInputs()
        result.apply_to_stat_inputs(inputs)
        assert inputs.am_pct == 800


class TestNotesFromChainedAPBuff:
    """A6 — Notes from the Chained 4pc: AP+48 on AFTER_ABLOOM_TRIGGER.

    stat='anomaly_proficiency_flat' must route to anomaly_proficiency field via
    _STAT_TO_INPUT (same pattern as anomaly_mastery_flat → anomaly_mastery).
    """

    def test_ap_flat_routes_when_condition_active(self):
        mods = [
            _mod(
                stat="anomaly_proficiency_flat",
                value=48,
                conditions=(Condition.AFTER_ABLOOM_TRIGGER,),
            )
        ]
        on = ActiveConditions(active={Condition.ALWAYS, Condition.AFTER_ABLOOM_TRIGGER})
        result = resolve_modifiers(mods, on)
        assert result.stat_bonuses.get("anomaly_proficiency_flat") == 48
        inputs = StatInputs(anomaly_proficiency=100)
        result.apply_to_stat_inputs(inputs)
        assert inputs.anomaly_proficiency == 148

    def test_ap_flat_absent_before_trigger(self):
        mods = [
            _mod(
                stat="anomaly_proficiency_flat",
                value=48,
                conditions=(Condition.AFTER_ABLOOM_TRIGGER,),
            )
        ]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.stat_bonuses.get("anomaly_proficiency_flat", 0) == 0


class TestFrostfallSickleAbloomDmgBonus:
    """A6 — Frostfall Sickle abloom_dmg_bonus routes to combat_bonuses, not anomaly_dmg_bonus."""

    def test_abloom_dmg_bonus_routes_to_combat_bonuses(self):
        mods = [_mod(stat="abloom_dmg_bonus", value=4000)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.abloom_dmg_bonus == 4000

    def test_abloom_dmg_bonus_does_not_inflate_anomaly_dmg_bonus(self):
        mods = [_mod(stat="abloom_dmg_bonus", value=4000)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.anomaly_dmg_bonus == 0


class TestYanagiGessouBuildup:
    """H3: Yanagi Gessou +45% electric_anomaly_buildup is gated on gessou_active."""

    def test_gessou_buildup_applies_when_active(self):
        mods = [
            _mod(
                stat="electric_anomaly_buildup", value=4500, conditions=(Condition.GESSOU_ACTIVE,)
            )
        ]
        on = ActiveConditions(active={Condition.ALWAYS, Condition.GESSOU_ACTIVE})
        result = resolve_modifiers(mods, on)
        assert result.combat_bonuses.get("electric_anomaly_buildup", 0) == 4500

    def test_gessou_buildup_absent_when_inactive(self):
        mods = [
            _mod(
                stat="electric_anomaly_buildup", value=4500, conditions=(Condition.GESSOU_ACTIVE,)
            )
        ]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.combat_bonuses.get("electric_anomaly_buildup", 0) == 0
