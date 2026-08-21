"""Modifier-reach tests for Velina's kit JSON.

Verifies that each buff in modifiers/agents/velina.json routes to the
correct bucket in ResolvedBuffs and produces a non-zero calc effect.
Does not validate numeric cross-reference (those belong in V6 rotation test).

V7+V8 update (2026-06-22):
  - AA +10% Windswept/Vortex moved to target=team; now only visible under team filter.
  - Core +150% Vortex added, gated on windbite_consumed (Condition.WINDBITE_CONSUMED).

Task 32 Batch 32c update (2026-07-xx): the AA's +10% Windswept/Vortex DMG and M2's
further +15% on the same effect were REMOVED from velina.json. Both are gated in-game
on "another squad member is Anomaly or shares Velina's [Wind] attribute", and no
owner-relative union condition exists yet for "shares element OR shares specialty"
(see the SAME_ATTRIBUTE_OR_SPECIALTY_IN_TEAM schema ask in velina.json's modifier[0]
notes). Approximating with conditions=['always'] would misrepresent an always-on buff
as gated, so the rows were dropped rather than mis-authored — this file's AA/M2 tests
were updated accordingly; re-add them once that Condition lands.
"""

from __future__ import annotations

from app.services.buff_resolver import resolve_modifiers
from app.services.modifier_loader import load_agent_modifiers
from app.services.modifiers import ActiveConditions, Condition, ModifierTarget

VELINA_HAKUSHIN_ID = "1561"


def _resolve(
    extra_conditions: set[Condition] | None = None,
    target_filter: ModifierTarget = ModifierTarget.SELF,
):
    mods = load_agent_modifiers(VELINA_HAKUSHIN_ID)
    active = {Condition.ALWAYS}
    if extra_conditions:
        active |= extra_conditions
    return resolve_modifiers(mods, ActiveConditions(active=active), target_filter=target_filter)


class TestVelinaModifiersLoad:
    def test_loads_without_error(self):
        mods = load_agent_modifiers(VELINA_HAKUSHIN_ID)
        assert len(mods) > 0

    def test_no_unknown_conditions(self):
        """All condition strings in the JSON must resolve to known Condition values."""
        mods = load_agent_modifiers(VELINA_HAKUSHIN_ID)
        for mod in mods:
            assert Condition.UNKNOWN not in mod.conditions, (
                f"Unknown condition in modifier '{mod.source_label}'"
            )


class TestAAWindsweptVortexBonus:
    """AA +10% Windswept/Vortex DMG — removed pending a schema gate (Task 32c).

    See the module docstring: the effect is gated in-game on an owner-relative
    union condition ("Anomaly or shares element") that doesn't exist yet, so the
    rows were dropped from velina.json rather than mis-authored. These guard that
    the buckets stay at 0 until the rows come back.
    """

    def test_aa_windswept_absent_under_team_filter(self):
        """No AA row → combat_bonuses['anomaly_dmg_bonus'] stays 0 under team filter."""
        buffs = _resolve(target_filter=ModifierTarget.TEAM)
        assert buffs.combat_bonuses.get("anomaly_dmg_bonus", 0) == 0

    def test_aa_vortex_absent_under_team_filter(self):
        """No AA row → combat_bonuses['vortex_dmg_bonus'] stays 0 under team filter."""
        buffs = _resolve(target_filter=ModifierTarget.TEAM)
        assert buffs.combat_bonuses.get("vortex_dmg_bonus", 0) == 0

    def test_aa_windswept_absent_in_self_filter(self):
        """No AA/M2 row → anomaly_dmg_bonus stays 0 under self filter."""
        buffs = _resolve()
        assert buffs.combat_bonuses.get("anomaly_dmg_bonus", 0) == 0

    def test_aa_vortex_absent_in_self_filter(self):
        """No AA/M2 row → vortex_dmg_bonus stays 0 under self filter (windbite off)."""
        buffs = _resolve()
        assert buffs.combat_bonuses.get("vortex_dmg_bonus", 0) == 0


class TestCoreVortexBonus150:
    """Core Passive +150% Vortex DMG gated on windbite_consumed.

    AA/M2's Windswept/Vortex bonuses are currently absent from the kit (see
    TestAAWindsweptVortexBonus), so vortex_dmg_bonus has no baseline contribution
    from them — Core's own row is the only source.
    """

    def test_core_150_vortex_inactive_by_default(self):
        """Core +150% must not apply without windbite_consumed active."""
        buffs = _resolve()
        assert buffs.combat_bonuses.get("vortex_dmg_bonus", 0) == 0

    def test_core_150_vortex_active_with_windbite_consumed(self):
        """Core +150% sets vortex_dmg_bonus to 15000 when windbite_consumed is on."""
        buffs = _resolve(extra_conditions={Condition.WINDBITE_CONSUMED})
        assert buffs.combat_bonuses.get("vortex_dmg_bonus", 0) == 15000

    def test_windbite_consumed_condition_exists(self):
        """Condition.WINDBITE_CONSUMED must be a known (non-UNKNOWN) enum member."""
        assert Condition.WINDBITE_CONSUMED != Condition.UNKNOWN
        assert Condition.WINDBITE_CONSUMED.value == "windbite_consumed"


class TestM1ResIgnore:
    def test_self_res_ignore_reaches_combat(self):
        """M1 self RES ignore 20% → combat_bonuses['res_ignore'] ≥ 2000."""
        buffs = _resolve()
        assert buffs.combat_bonuses.get("res_ignore", 0) >= 2000

    def test_team_res_ignore_visible_to_team_filter(self):
        """M1 team modifier must reach DPS via team target filter."""
        mods = load_agent_modifiers(VELINA_HAKUSHIN_ID)
        team_buffs = resolve_modifiers(
            mods,
            ActiveConditions(active={Condition.ALWAYS}),
            target_filter=ModifierTarget.TEAM,
        )
        assert team_buffs.combat_bonuses.get("res_ignore", 0) >= 2000


class TestM2WindsweptVortexBonus:
    """M2's further +15% on AA's Windswept/Vortex DMG — same removal as the AA rows.

    See TestAAWindsweptVortexBonus / the module docstring: both are gated on the
    same not-yet-implemented union condition, so neither row exists in the kit today.
    """

    def test_m2_anomaly_dmg_bonus_absent(self):
        """No AA/M2 row → combat_bonuses['anomaly_dmg_bonus'] stays 0 under self filter."""
        buffs = _resolve()
        assert buffs.combat_bonuses.get("anomaly_dmg_bonus", 0) == 0

    def test_m2_vortex_dmg_bonus_absent(self):
        """No AA/M2 row → vortex_dmg_bonus stays 0 under self filter (no windbite)."""
        buffs = _resolve()
        assert buffs.combat_bonuses.get("vortex_dmg_bonus", 0) == 0


class TestM4ATKBonus:
    def test_m4_inactive_without_condition(self):
        """M4 ATK% must not apply when ex_special_used is off."""
        buffs = _resolve()
        assert buffs.stat_bonuses.get("final_atk_pct", 0) == 0

    def test_m4_active_with_ex_special_used(self):
        """M4 ATK +15% → stat_bonuses['final_atk_pct'] = 1500 when EX used."""
        buffs = _resolve(extra_conditions={Condition.EX_SPECIAL_USED})
        assert buffs.stat_bonuses.get("final_atk_pct", 0) == 1500


class TestM6WindBuildup:
    def test_m6_wind_buildup_inactive_without_condition(self):
        """M6 Wind Buildup must not apply without enemy_has_anomaly."""
        buffs = _resolve()
        assert buffs.combat_bonuses.get("wind_anomaly_buildup", 0) == 0

    def test_m6_wind_buildup_reaches_combat(self):
        """M6 Wind Buildup +20% → combat_bonuses['wind_anomaly_buildup'] = 2000."""
        buffs = _resolve(extra_conditions={Condition.ENEMY_HAS_ANOMALY})
        assert buffs.combat_bonuses.get("wind_anomaly_buildup", 0) == 2000
