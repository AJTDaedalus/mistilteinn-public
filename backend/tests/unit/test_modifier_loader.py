"""Unit tests for modifier JSON loader."""

from __future__ import annotations

import pytest

from app.services.modifier_loader import (
    _parse_conditions,
    _parse_scopes,
    _raw_mod_to_modifier,
    load_agent_modifiers,
    load_disc_set_modifiers,
    load_wengine_modifiers,
    wengine_value_at_refinement,
)
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    ModifierSource,
    ModifierTarget,
)


class TestParseConditions:
    def test_known_condition_maps_correctly(self):
        result = _parse_conditions(["always"])
        assert result == (Condition.ALWAYS,)

    def test_unknown_condition_maps_to_unknown_not_always(self):
        result = _parse_conditions(["totally_unknown_condition_xyz"])
        assert Condition.UNKNOWN in result
        assert Condition.ALWAYS not in result

    def test_unknown_condition_modifier_inactive(self):
        """A modifier with an unknown condition must never be active."""
        result = _parse_conditions(["totally_unknown_condition_xyz"])
        active = ActiveConditions(active={Condition.ALWAYS})
        assert not active.is_met(result)

    def test_empty_list_defaults_to_always(self):
        result = _parse_conditions([])
        assert result == (Condition.ALWAYS,)

    def test_mixed_known_unknown(self):
        result = _parse_conditions(["always", "not_a_real_condition"])
        assert Condition.ALWAYS in result
        assert Condition.UNKNOWN in result


class TestParseScopes:
    def test_dash_scope_parses(self):
        assert _parse_scopes(["dash"]) == (AttackScope.DASH,)

    def test_default_all(self):
        assert _parse_scopes(["all"]) == (AttackScope.ALL,)


class TestWengineValueAtRefinement:
    def test_r1(self):
        assert wengine_value_at_refinement(2000, 4000, 1) == 2000

    def test_r5(self):
        assert wengine_value_at_refinement(2000, 4000, 5) == 4000

    def test_r3_interpolation(self):
        # Linear interp: 2000 + (4000-2000) * (3-1) / (5-1) = 2000 + 1000 = 3000
        assert wengine_value_at_refinement(2000, 4000, 3) == 3000

    def test_r2(self):
        # 2000 + (4000-2000) * (2-1) / (5-1) = 2000 + 500 = 2500
        assert wengine_value_at_refinement(2000, 4000, 2) == 2500

    def test_r4(self):
        # 2000 + (4000-2000) * (3) / (4) = 2000 + 1500 = 3500
        assert wengine_value_at_refinement(2000, 4000, 4) == 3500


class TestLoadAgentModifiers:
    def test_loads_ellen(self):
        mods = load_agent_modifiers("1191")
        assert len(mods) > 0
        # First mod should be Ellen's core CRIT DMG
        assert mods[0].stat == "crit_dmg"
        assert mods[0].value == 10000
        assert mods[0].source == ModifierSource.CORE_SKILL

    def test_conditions_parsed(self):
        mods = load_agent_modifiers("1191")
        # Ellen's core CRIT DMG requires flash_freeze_consumed
        assert Condition.FLASH_FREEZE_CONSUMED in mods[0].conditions

    def test_scopes_parsed(self):
        mods = load_agent_modifiers("1191")
        # Ellen's core CRIT DMG (chain/ult row) is scoped, not the "all" default
        assert any(AttackScope.CHAIN in m.scopes for m in mods)

    def test_target_parsed(self):
        mods = load_agent_modifiers("1191")
        assert mods[0].target == ModifierTarget.SELF

    def test_mindscape_modifiers_included(self):
        mods = load_agent_modifiers("1191")
        mindscape_mods = [m for m in mods if m.source == ModifierSource.MINDSCAPE]
        assert len(mindscape_mods) > 0

    def test_max_stacks(self):
        mods = load_agent_modifiers("1191")
        # Ellen M1: 6 stacks, M2: 3 stacks, Ice DMG: 10 stacks
        stacking_mods = [m for m in mods if m.max_stacks > 1]
        assert len(stacking_mods) > 0

    def test_nonexistent_agent_returns_empty(self):
        mods = load_agent_modifiers("9999999")
        assert mods == []


class TestLoadDiscSetModifiers:
    def test_loads_woodpecker(self):
        mods = load_disc_set_modifiers("31000")
        assert len(mods) > 0

    def test_2pc_source(self):
        mods = load_disc_set_modifiers("31000")
        two_pc = [m for m in mods if m.source == ModifierSource.DISC_SET_2PC]
        assert len(two_pc) > 0
        # Woodpecker 2pc: CRIT Rate +8%
        assert two_pc[0].stat == "crit_rate"
        assert two_pc[0].value == 800

    def test_4pc_source(self):
        mods = load_disc_set_modifiers("31000")
        four_pc = [m for m in mods if m.source == ModifierSource.DISC_SET_4PC]
        assert len(four_pc) > 0

    def test_nonexistent_set_returns_empty(self):
        mods = load_disc_set_modifiers("9999999")
        assert mods == []


class TestLoadWengineModifiers:
    def test_loads_at_r1(self):
        # Steel Cushion (14102)
        mods = load_wengine_modifiers("14102", refinement=1)
        assert len(mods) > 0

    def test_r1_value(self):
        mods = load_wengine_modifiers("14102", refinement=1)
        phys = [m for m in mods if m.stat == "physical_dmg"]
        assert len(phys) == 1
        assert phys[0].value == 2000

    def test_r5_value(self):
        mods = load_wengine_modifiers("14102", refinement=5)
        phys = [m for m in mods if m.stat == "physical_dmg"]
        assert len(phys) == 1
        assert phys[0].value == 4000

    def test_r3_interpolated(self):
        mods = load_wengine_modifiers("14102", refinement=3)
        phys = [m for m in mods if m.stat == "physical_dmg"]
        assert len(phys) == 1
        assert phys[0].value == 3000

    def test_source_is_wengine_passive(self):
        mods = load_wengine_modifiers("14102", refinement=1)
        assert all(m.source == ModifierSource.WENGINE_PASSIVE for m in mods)

    def test_empty_modifiers_wengine(self):
        # Hellfire Gears (14110) has no offensive modifiers
        mods = load_wengine_modifiers("14110", refinement=1)
        assert mods == []

    def test_nonexistent_wengine_returns_empty(self):
        mods = load_wengine_modifiers("9999999", refinement=1)
        assert mods == []


class TestHpScalingFields:
    """hp_scale_* fields on Modifier (`_bake_hp_scaled_modifier`'s
    stepped-and-capped bake). Exercised via a synthetic raw dict rather than
    a pinned agent's kit content, which drifts as kits get re-curated — see
    docs/LOG_kit_curation.md Task 17 Batch 9 (zhao.json's prior "HP-scaled
    Team DMG" row this test used to pin against turned out to be a
    fabrication, conflating two unrelated ZO param entries; the real,
    representable use of this mechanism is zhao.json's Additional Ability
    escalation (3), still unauthored pending its union-gate schema gap)."""

    def _raw(self, **overrides) -> dict:
        raw = {
            "stat": "dmg_bonus",
            "value": 4000,
            "source": "core_skill",
            "source_label": "Additional: Team DMG (HP-scaled)",
            "target": "team",
            "conditions": ["always"],
            "hp_scale_base": 1000,
            "hp_scale_threshold": 15000,
            "hp_scale_per_unit": 400,
            "hp_scale_unit": 100,
        }
        raw.update(overrides)
        return raw

    def test_hp_scale_fields_thread_to_modifier(self):
        core_dmg = _raw_mod_to_modifier(self._raw())
        assert core_dmg.hp_scale_base == 1000
        assert core_dmg.hp_scale_threshold == 15000
        assert core_dmg.hp_scale_per_unit == 400
        assert core_dmg.hp_scale_unit == 100

    def test_hp_scaled_modifier_target_is_team(self):
        core_dmg = _raw_mod_to_modifier(self._raw())
        assert core_dmg.target == ModifierTarget.TEAM

    def test_hp_scaled_modifier_value_is_cap(self):
        core_dmg = _raw_mod_to_modifier(self._raw())
        assert core_dmg.value == 4000

    def test_non_scaled_modifier_has_zero_hp_fields(self):
        raw = self._raw(
            source_label="Core: Flat ATK",
            hp_scale_base=0,
            hp_scale_threshold=0,
            hp_scale_per_unit=0,
            hp_scale_unit=0,
        )
        flat_atk = _raw_mod_to_modifier(raw)
        assert flat_atk.hp_scale_per_unit == 0


class TestNotesField:
    """Task A4: per-modifier `notes` (curation citation) threads to Modifier.notes."""

    def _raw(self, **overrides) -> dict:
        raw = {
            "stat": "crit_dmg",
            "value": 1000,
            "source": "core_skill",
            "source_label": "Core F",
            "target": "self",
            "conditions": ["always"],
        }
        raw.update(overrides)
        return raw

    def test_notes_present_surfaces_on_modifier(self):
        mod = _raw_mod_to_modifier(
            self._raw(notes="Cross-referenced with ZO commit abc1234.")
        )
        assert mod.notes == "Cross-referenced with ZO commit abc1234."

    def test_notes_absent_is_none(self):
        mod = _raw_mod_to_modifier(self._raw())
        assert mod.notes is None


class TestResolveEquipperConditions:
    def _make_mod(self, conditions: list[str]) -> Modifier:
        from app.services.modifier_loader import _CONDITION_MAP
        from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget

        cond_tuple = tuple(_CONDITION_MAP.get(c, Condition.UNKNOWN) for c in conditions)
        return Modifier(
            stat="dmg_bonus",
            value=1500,
            source=ModifierSource.DISC_SET_4PC,
            source_label="4pc: Team CRIT DMG",
            target=ModifierTarget.TEAM,
            conditions=cond_tuple,
        )

    def test_stun_condition_met_strips_it(self):
        from app.services.modifiers import Condition
        from app.services.snapshot_builder import resolve_equipper_conditions

        mod = self._make_mod(["equipper_is_stun", "after_ex_or_chain"])
        result = resolve_equipper_conditions(mod, "stun", "physical")
        assert result is not None
        assert all(c.value != "equipper_is_stun" for c in result.conditions)
        assert Condition.AFTER_EX_OR_CHAIN in result.conditions

    def test_stun_condition_not_met_drops_mod(self):
        from app.services.snapshot_builder import resolve_equipper_conditions

        mod = self._make_mod(["equipper_is_stun", "after_ex_or_chain"])
        result = resolve_equipper_conditions(mod, "defense", "ice")
        assert result is None

    def test_defense_condition_met(self):
        from app.services.snapshot_builder import resolve_equipper_conditions

        mod = self._make_mod(["equipper_is_defense", "after_ex_or_assist"])
        result = resolve_equipper_conditions(mod, "defense", "ice")
        assert result is not None
        assert all(c.value != "equipper_is_defense" for c in result.conditions)

    def test_no_equipper_conditions_returns_unchanged(self):
        from app.services.snapshot_builder import resolve_equipper_conditions

        mod = self._make_mod(["always"])
        result = resolve_equipper_conditions(mod, "stun", "physical")
        assert result is mod  # same object, no copy needed

    def test_only_equipper_conditions_become_always(self):
        from app.services.modifiers import Condition
        from app.services.snapshot_builder import resolve_equipper_conditions

        mod = self._make_mod(["equipper_is_stun"])
        result = resolve_equipper_conditions(mod, "stun", "physical")
        assert result is not None
        assert result.conditions == (Condition.ALWAYS,)


class TestBakeHpScaledModifier:
    def _make_hp_scaled_mod(self) -> Modifier:
        from app.services.modifiers import Modifier, ModifierSource, ModifierTarget

        return Modifier(
            stat="dmg_bonus",
            value=4000,
            source=ModifierSource.CORE_SKILL,
            source_label="Core: DMG",
            target=ModifierTarget.TEAM,
            hp_scale_base=1000,
            hp_scale_threshold=15000,
            hp_scale_per_unit=400,
            hp_scale_unit=100,
        )

    def test_below_threshold_returns_base(self):
        from app.services.snapshot_builder import _bake_hp_scaled_modifier

        mod = self._make_hp_scaled_mod()
        baked = _bake_hp_scaled_modifier(mod, support_hp=10000)
        assert baked.value == 1000

    def test_at_threshold_returns_base(self):
        from app.services.snapshot_builder import _bake_hp_scaled_modifier

        mod = self._make_hp_scaled_mod()
        baked = _bake_hp_scaled_modifier(mod, support_hp=15000)
        assert baked.value == 1000

    def test_scales_correctly_above_threshold(self):
        from app.services.snapshot_builder import _bake_hp_scaled_modifier

        mod = self._make_hp_scaled_mod()
        # HP = 19000 → (19000-15000)/400 = 10 units → 1000+10*100=2000
        baked = _bake_hp_scaled_modifier(mod, support_hp=19000)
        assert baked.value == 2000

    def test_caps_at_value(self):
        from app.services.snapshot_builder import _bake_hp_scaled_modifier

        mod = self._make_hp_scaled_mod()
        # HP = 40000 → would be 1000+(25000/400)*100=7250 → capped at 4000
        baked = _bake_hp_scaled_modifier(mod, support_hp=40000)
        assert baked.value == 4000

    def test_zhao_actual_hp_gives_3000(self):
        from app.services.snapshot_builder import _bake_hp_scaled_modifier

        mod = self._make_hp_scaled_mod()
        # floor((23357-15000)/400)=20 units → 1000+20*100=3000
        baked = _bake_hp_scaled_modifier(mod, support_hp=23357)
        assert baked.value == 3000


class TestCaesarM2AtkUpgrade:
    """Caesar's M2 raises the core team-ATK buff to 150% of its value: 1000 → 1500.

    It does **not** add a separate +500 buff. This class used to assert exactly that
    ("core 1000 + M2 delta 500 = 1500"), which is how the bug survived: the additive
    row summed with the buff it was meant to replace, and its +500 cites no source —
    it is 1500 minus 1000, worked backwards from the answer. Task 14 (C2) re-authored
    it as two mindscape-gated variants of one buff; `mindscape_allows` keeps exactly
    one live. ZO Caesar.ts:101-114: prod(core.atk, cmpGE(mc, 2, m2.atk_increase_, 1)).
    """

    def test_the_two_variants_load_as_one_buff(self):
        mods = [m for m in load_agent_modifiers("1071") if m.stat == "flat_atk"]

        assert len(mods) == 2
        assert {m.value for m in mods} == {1000, 1500}
        # One buff, one toggle: same label, same source. The M2 upgrade is not a
        # mindscape *row* — it is the core buff wearing a different number.
        # Label renamed "Core: Team ATK buff" -> "Core: Shield Bearer ATK" in
        # Task 17 Batch 9 (docs/LOG_kit_curation.md "Caesar (kit-auditor)"):
        # the buff targets the shield bearer specifically (target: active),
        # not the whole team, and the old label overstated its reach.
        assert {m.source_label for m in mods} == {"Core: Shield Bearer ATK"}
        assert {m.source for m in mods} == {ModifierSource.CORE_SKILL}

    @pytest.mark.parametrize(("mc", "expected"), [(0, 1000), (1, 1000), (2, 1500), (6, 1500)])
    def test_exactly_one_variant_is_live_at_each_mindscape(self, mc: int, expected: int):
        from app.services.modifiers import Condition, mindscape_allows

        live = [
            m
            for m in load_agent_modifiers("1071")
            if m.stat == "flat_atk"
            and Condition.SHIELD_ACTIVE in m.conditions
            and mindscape_allows(m, mc)
        ]

        assert len(live) == 1, f"M{mc}: expected one live variant, got {[m.value for m in live]}"
        assert live[0].value == expected


class TestAliceKitModifiers:
    """H3: Alice modifier JSON — M4 buildup present; polarity_disorder in moves JSON."""

    def test_m4_physical_anomaly_buildup_present(self):
        mods = load_agent_modifiers("1401")
        buildup_mods = [
            m
            for m in mods
            if m.stat == "physical_anomaly_buildup" and m.source == ModifierSource.MINDSCAPE
        ]
        assert len(buildup_mods) == 1, "M4 physical_anomaly_buildup modifier missing"
        assert buildup_mods[0].value == 2500
        assert AttackScope.BASIC in buildup_mods[0].scopes

    def test_polarity_disorder_flag_on_moves(self):
        from app.data.loaders.moves import load_agent_moves

        moves = load_agent_moves()
        alice_spec = moves.get("alice")
        assert alice_spec is not None
        polarity_moves = [
            name for name, spec in alice_spec.moves.items() if spec.polarity_disorder
        ]
        assert len(polarity_moves) >= 2, (
            f"Expected ≥2 polarity_disorder moves for Alice, got: {polarity_moves}"
        )

    def test_vivian_featherbloom_wind_mv_pin(self):
        """Featherbloom abloom_mv_by_element must include all 6 elements including wind=32."""
        from app.data.loaders.moves import load_agent_moves

        moves = load_agent_moves()
        vivian = moves.get("vivian")
        assert vivian is not None
        featherbloom = vivian.moves.get("Basic Attack: Featherbloom")
        assert featherbloom is not None, "Featherbloom move missing from vivian.json"
        mv = featherbloom.abloom_mv_by_element
        assert mv is not None, "abloom_mv_by_element missing from Featherbloom"
        assert mv.get("wind") == 32, f"Expected wind MV 32, got {mv.get('wind')}"
        # Verify the full 6-element table is present (no element left blank).
        expected_elements = {"ether", "electric", "fire", "physical", "ice", "wind"}
        assert expected_elements == set(mv.keys()), (
            f"Featherbloom MV table missing elements: {expected_elements - set(mv.keys())}"
        )

    def test_move_keys_are_attack_names_not_scopes(self):
        """Every shipped move file must key `moves` by full DB attacks.name.

        Scope-keyed files ("chain", "ultimate", ...) never match the simulator's
        lookup, so grants_state / grants_full_charge silently no-op — this is how
        Pulchra's Hunter's Gait aftershock chain went dead.
        """
        from app.data.loaders.moves import _RESERVED_MOVE_KEYS, load_agent_moves

        offenders = {
            agent: sorted(_RESERVED_MOVE_KEYS.intersection(spec.moves))
            for agent, spec in load_agent_moves().items()
            if _RESERVED_MOVE_KEYS.intersection(spec.moves)
        }
        assert not offenders, f"Move files keyed by scope instead of attack name: {offenders}"

    def test_scope_keyed_move_file_is_rejected(self, tmp_path):
        """The loader must fail loudly on a scope-keyed file rather than degrade."""
        from app.data.loaders.moves import load_agent_moves

        (tmp_path / "bogus.json").write_text(
            '{"agent_name": "Bogus", "moves": {"ultimate": {"hits": 1, "duration_s": 1.0}}}'
        )
        with pytest.raises(ValueError, match="attack scopes, not attack names"):
            load_agent_moves(tmp_path)
