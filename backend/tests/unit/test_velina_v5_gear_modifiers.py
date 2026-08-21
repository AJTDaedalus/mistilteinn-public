"""Modifier-reach tests for Velina's V5 disc set JSON.

Covers the disc set authored in Task V5: Wuthering Salon (id 33900).

The W-Engine half of this file ("Poem of the Empty Feather Return", claiming
id 14158) was removed by the 14158-collision hotfix
(docs/TASKS_wengine_id_collision.md, Task H1): that JSON was misattributed —
id 14158 is Remielle's "Ode of Resurrected Wings" — and its values were
fabricated `unverified` ones. Velina's real signature engine gets re-authored
from a verified id on the `feat/new-agents` salvage backlog.

Verifies each buff routes to the correct ResolvedBuffs bucket and produces a
non-zero effect with the expected stack scaling. Numeric kit cross-reference
(rotation-level) is out of scope — this only proves the modifiers *reach*
the calc.
"""

from __future__ import annotations

from app.services.buff_resolver import resolve_modifiers
from app.services.modifier_loader import load_disc_set_modifiers
from app.services.modifiers import ActiveConditions, Condition, ModifierTarget

DISC_SET_ID = "33900"  # Wuthering Salon

# source_label used for per-stack lookup (must match the JSON exactly).
_DISC_AP_LABEL = "4pc: AP (EX Special stacks)"


def _resolve_disc(
    *,
    ap_stacks: int = 0,
    extra_conditions: set[Condition] | None = None,
):
    mods = load_disc_set_modifiers(DISC_SET_ID)
    active = {Condition.ALWAYS} | (extra_conditions or set())
    ac = ActiveConditions(active=active, stack_counts={_DISC_AP_LABEL: ap_stacks})
    return resolve_modifiers(mods, ac, target_filter=ModifierTarget.SELF)


class TestDiscSetLoads:
    def test_loads_three_modifiers(self):
        mods = load_disc_set_modifiers(DISC_SET_ID)
        assert len(mods) == 3

    def test_no_unknown_conditions(self):
        mods = load_disc_set_modifiers(DISC_SET_ID)
        for mod in mods:
            assert Condition.UNKNOWN not in mod.conditions, (
                f"Unknown condition in modifier '{mod.source_label}'"
            )


class TestDiscSet2pc:
    """2pc — Wind DMG +10%, always on."""

    def test_wind_dmg_reaches_stat_bonuses(self):
        buffs = _resolve_disc()
        assert buffs.stat_bonuses.get("wind_dmg") == 1000


class TestDiscSet4pcAP:
    """4pc — AP +25 per EX Special use, max 2 stacks."""

    def test_inactive_without_ex_special(self):
        """No ex_special_used condition → AP buff absent even with stacks set."""
        buffs = _resolve_disc(ap_stacks=2)
        assert buffs.stat_bonuses.get("anomaly_proficiency_flat", 0) == 0

    def test_inactive_without_stacks(self):
        """Condition met but zero stacks → no contribution."""
        buffs = _resolve_disc(ap_stacks=0, extra_conditions={Condition.EX_SPECIAL_USED})
        assert buffs.stat_bonuses.get("anomaly_proficiency_flat", 0) == 0

    def test_full_stacks(self):
        """ex_special_used + 2 stacks → 25 × 2 = 50 AP."""
        buffs = _resolve_disc(ap_stacks=2, extra_conditions={Condition.EX_SPECIAL_USED})
        assert buffs.stat_bonuses.get("anomaly_proficiency_flat") == 50

    def test_stacks_capped_at_max(self):
        """Requesting more than max_stacks (2) is capped at 2."""
        buffs = _resolve_disc(ap_stacks=5, extra_conditions={Condition.EX_SPECIAL_USED})
        assert buffs.stat_bonuses.get("anomaly_proficiency_flat") == 50


class TestDiscSet4pcWindswept:
    """4pc — DMG +18% (Windswept trigger), modeled as always per curation policy."""

    def test_dmg_bonus_reaches_dmg_pool(self):
        """Generic dmg_bonus routes to the additive dmg_bonuses pool, not a stat."""
        buffs = _resolve_disc()
        assert 1800 in buffs.dmg_bonuses
