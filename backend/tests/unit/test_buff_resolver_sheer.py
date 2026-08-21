"""Unit tests for sheer-specific stats in the buff resolver."""

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


def _mod(
    stat: str,
    value: int,
    target: ModifierTarget = ModifierTarget.SELF,
) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.MINDSCAPE,
        source_label="test",
        target=target,
        conditions=(Condition.ALWAYS,),
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


class TestSheerDmgBonusStat:
    def test_sheer_dmg_bonus_routes_to_combat_bonuses(self):
        mods = [_mod("sheer_dmg_bonus", 2000)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.combat_bonuses.get("sheer_dmg_bonus") == 2000

    def test_sheer_dmg_bonus_property_reads_from_combat_bonuses(self):
        buffs = ResolvedBuffs(combat_bonuses={"sheer_dmg_bonus": 2000})
        assert buffs.sheer_dmg_bonus == 2000

    def test_sheer_dmg_bonus_property_zero_when_absent(self):
        buffs = ResolvedBuffs()
        assert buffs.sheer_dmg_bonus == 0

    def test_multiple_sheer_dmg_bonus_mods_sum(self):
        mods = [
            _mod("sheer_dmg_bonus", 2000),
            _mod("sheer_dmg_bonus", 1000),
        ]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.sheer_dmg_bonus == 3000


class TestSheerForceFlatStat:
    def test_sheer_force_flat_routes_to_combat_bonuses(self):
        mods = [_mod("sheer_force_flat", 400)]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.combat_bonuses.get("sheer_force_flat") == 400

    def test_sheer_force_flat_property_reads_from_combat_bonuses(self):
        buffs = ResolvedBuffs(combat_bonuses={"sheer_force_flat": 400})
        assert buffs.sheer_force_flat == 400

    def test_sheer_force_flat_property_zero_when_absent(self):
        buffs = ResolvedBuffs()
        assert buffs.sheer_force_flat == 0

    def test_sheer_force_flat_multiple_sources_sum(self):
        # Lucia + Pan Yinhu both grant flat Sheer Force — they should stack
        mods = [
            _mod("sheer_force_flat", 300),
            _mod("sheer_force_flat", 250),
        ]
        result = resolve_modifiers(mods, ActiveConditions())
        assert result.sheer_force_flat == 550

    def test_sheer_force_flat_team_target_reaches_resolver(self):
        # A TEAM-targeted modifier (e.g. from Lucia support) should pass
        # through resolve_modifiers when target_filter=SELF (default includes TEAM).
        mods = [_mod("sheer_force_flat", 400, target=ModifierTarget.TEAM)]
        result = resolve_modifiers(mods, ActiveConditions(), target_filter=ModifierTarget.SELF)
        assert result.sheer_force_flat == 400
