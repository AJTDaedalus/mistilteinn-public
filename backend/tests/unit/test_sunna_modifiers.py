"""Modifier-reach tests for Sunna's kit JSON (Task 34, D-KV24).

Verifies that the Delusion Reprise team-ATK rider added by Task 34 actually routes into
`ResolvedBuffs` with the right value under the right condition — not merely that the
number sits in a JSON file. That distinction is the whole point here: this row cannot be
cross-checked against ZO (her sheet is an unimplemented stub, hence the `no_zo_citation`
waiver in `known_issues.json`), so the harness verifies its *value* against the DB text
and nothing else. A test that it reaches the calc is the only thing standing between "the
buff is authored" and "the buff is applied" — the failure mode `project_scaling_stat_gaps`
records, where a value lands in a key no consumer reads and stays silently at zero.

Also covers the two pre-existing Ether-Veil-gated rows, since the new row shares their
condition and a regression in the gate would look identical across all three.
"""

from __future__ import annotations

from app.services.buff_resolver import resolve_modifiers
from app.services.modifier_loader import load_agent_modifiers
from app.services.modifiers import ActiveConditions, Condition, ModifierTarget

SUNNA_HAKUSHIN_ID = "1491"

DELUSION_REPRISE_ROW = "EX Special: Delusion Reprise Team ATK"


def _resolve(
    extra_conditions: set[Condition] | None = None,
    target_filter: ModifierTarget = ModifierTarget.TEAM,
):
    mods = load_agent_modifiers(SUNNA_HAKUSHIN_ID)
    active = {Condition.ALWAYS}
    if extra_conditions:
        active |= extra_conditions
    return resolve_modifiers(mods, ActiveConditions(active=active), target_filter=target_filter)


class TestDelusionRepriseTeamATK:
    """DB text: 'While Ether Veil: Delusion Reprise is active, all squad members gain an
    additional 50 ATK for 40s.' Flat, so raw units — 50, not 5000 basis points."""

    def test_row_exists_and_is_flat_atk(self):
        mods = load_agent_modifiers(SUNNA_HAKUSHIN_ID)
        row = [m for m in mods if m.source_label == DELUSION_REPRISE_ROW]
        assert len(row) == 1, "Task 34's row is missing from sunna.json"
        assert row[0].stat == "flat_atk"
        assert row[0].value == 50
        assert row[0].target == ModifierTarget.TEAM

    def test_inactive_without_the_veil(self):
        """The buff is not unconditional — it must be absent with the Veil down."""
        buffs = _resolve()
        assert buffs.stat_bonuses.get("flat_atk", 0) == 0

    def test_reaches_the_calc_under_the_veil(self):
        buffs = _resolve(extra_conditions={Condition.IN_ETHER_VEIL})
        assert buffs.stat_bonuses.get("flat_atk", 0) == 50

    def test_is_modeled_not_merely_loaded(self):
        """`is_modeled=False` is how a buff gets displayed and then ignored by the calc."""
        buffs = _resolve(extra_conditions={Condition.IN_ETHER_VEIL})
        contributions = buffs.stat_attributions["flat_atk"]
        row = [c for c in contributions if c.source == DELUSION_REPRISE_ROW]
        assert len(row) == 1
        assert row[0].is_modeled is True
        assert row[0].value == 50

    def test_applies_to_sunna_herself(self):
        """'All squad members' includes Sunna, so the row must survive the self filter."""
        buffs = _resolve(
            extra_conditions={Condition.IN_ETHER_VEIL}, target_filter=ModifierTarget.SELF
        )
        assert buffs.stat_bonuses.get("flat_atk", 0) == 50


class TestEtherVeilGateSharedWithTheOlderRows:
    def test_m2_team_atk_is_veil_gated_and_outer_bracket(self):
        """M2's +10% team ATK sits in the outer bracket (L0 Rule 7 pins the bracket)."""
        assert _resolve().stat_bonuses.get("final_atk_pct", 0) == 0
        buffs = _resolve(extra_conditions={Condition.IN_ETHER_VEIL})
        assert buffs.stat_bonuses.get("final_atk_pct", 0) == 1000

    def test_core_stun_multiplier_is_veil_gated(self):
        assert _resolve().combat_bonuses.get("stun_dmg_mult_bonus", 0) == 0
        buffs = _resolve(extra_conditions={Condition.IN_ETHER_VEIL})
        assert buffs.combat_bonuses.get("stun_dmg_mult_bonus", 0) == 3000
