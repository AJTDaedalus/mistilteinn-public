"""Task 18 — modifiers/agents/remielle.json (DESIGN_remielle.md §6.1, §9.1
test 2).

Verifies the authored kit JSON loads with the expected shape and that the
three-row Additional Ability ATK buff reproduces the guide's 6/12/40% totals
with the ATK kink landing at exactly 4000 (the one tier -- 3-Anomaly --
where the per-row proportional-cap encoding is exact, per DESIGN §6.1).
"""

import json
from pathlib import Path

from app.services.buff_resolver import ActiveConditions, resolve_modifiers
from app.services.modifier_loader import load_agent_modifiers
from app.services.modifiers import (
    Condition,
    ModifierSource,
    ModifierTarget,
    mindscape_allows,
)
from app.services.snapshot_builder import _bake_atk_scaled_modifier

MODIFIERS_PATH = (
    Path(__file__).parents[2] / "app" / "data" / "modifiers" / "agents" / "remielle.json"
)

REMIELLE_HAKUSHIN_ID = "1581"


def _aa_rows():
    mods = load_agent_modifiers(REMIELLE_HAKUSHIN_ID)
    return [m for m in mods if m.source.value == "additional_ability"]


def _aa_row_gated_on(condition_value: str):
    return next(m for m in _aa_rows() if m.conditions[0].value == condition_value)


def _total_atk_buff(atk: int) -> int:
    """Sum the three AA rows' baked flat-ATK contribution at a given ATK,
    as if all three conditions were simultaneously active (a 3-Anomaly
    squad including Remielle -- the tier DESIGN §6.1 says is exact)."""
    return sum(_bake_atk_scaled_modifier(mod, atk).value for mod in _aa_rows())


class TestKitLoadsWithExpectedShape:
    def test_loads_the_expected_modifier_rows(self):
        # 9 rows now, and not the same set the kit shipped with. Hardening
        # Task 4 removed the flattened M1 `res_ignore` row (audit finding
        # S1-A), Task 5 added the missing M1 team Attribute-Anomaly-DMG row
        # (S1-C), and Task 19 put M1's RES ignore back as `luminize_res_ignore`
        # once a Luminize-only bucket existed to hold it. Listing the stats,
        # not just the count, so a swap cannot be silently the same length --
        # which is exactly what a bare `len(mods) == 8` would have been across
        # Task 4 and Task 5, since those cancelled out.
        mods = load_agent_modifiers(REMIELLE_HAKUSHIN_ID)
        assert sorted(m.stat for m in mods) == [
            "anomaly_buildup",
            "anomaly_dmg_bonus",
            "dmg_bonus",
            "flat_atk",
            "flat_atk",
            "flat_atk",
            "luminize_res_ignore",
            "refringe_flat_bonus_bp",
            "refringe_flat_bonus_bp",
        ]

    def test_three_additional_ability_rows_with_expected_ratios_and_caps(self):
        rows = _aa_rows()
        assert len(rows) == 3
        ratios_and_caps = sorted((m.atk_scale_ratio, m.value) for m in rows)
        assert ratios_and_caps == [(600, 240), (600, 240), (2800, 1120)]

    def test_row_1_gates_on_the_aa_activation_boilerplate_not_anomaly_presence(self):
        rows = _aa_rows()
        # Both the 1- and 2-Anomaly-tier rows have atk_scale_ratio=600; the
        # gate is what distinguishes them.
        gates = {m.conditions[0] for m in rows if m.atk_scale_ratio == 600}
        assert Condition.SAME_SPECIALTY_OR_FACTION_IN_TEAM in gates
        assert Condition.ANOMALY_COUNT_2_IN_TEAM in gates
        assert Condition.ANOMALY_IN_TEAM not in gates


class TestATKBuffTotalsAndKink:
    """DESIGN §9.1 test 2: strictly increasing below 4000 ATK, flat at/above,
    reproducing 6/12/40% cumulative totals -- exact at the 3-Anomaly tier."""

    def test_totals_are_6_12_40_percent_below_the_cap(self):
        atk = 1000
        one_anomaly = _aa_row_gated_on("same_specialty_or_faction_in_team")
        two_anomaly = _aa_row_gated_on("anomaly_count_2_in_team")
        three_anomaly = _aa_row_gated_on("anomaly_count_3_in_team")

        tier_1 = _bake_atk_scaled_modifier(one_anomaly, atk).value
        tier_2 = tier_1 + _bake_atk_scaled_modifier(two_anomaly, atk).value
        tier_3 = tier_2 + _bake_atk_scaled_modifier(three_anomaly, atk).value

        assert tier_1 == round(atk * 0.06)
        assert tier_2 == round(atk * 0.12)
        assert tier_3 == round(atk * 0.40)

    def test_strictly_increasing_below_4000_atk(self):
        # Floor-division plateaus at single-ATK granularity (e.g. 3998 and
        # 3999 both floor to the same integer) -- compare across a
        # materially-sized gap instead, matching D-KV17's own materiality
        # scale rather than asserting monotonicity at every integer step.
        assert _total_atk_buff(1000) < _total_atk_buff(2000) < _total_atk_buff(3999)

    def test_flat_at_and_above_4000_atk(self):
        assert _total_atk_buff(4000) == 1600
        assert _total_atk_buff(4001) == 1600
        assert _total_atk_buff(10_000) == 1600

    def test_kink_is_exactly_at_4000(self):
        # d(team buff)/d(ATK) == 0 at 4001 via the buff path: one more ATK
        # point above the cap changes nothing.
        assert _total_atk_buff(4001) == _total_atk_buff(4000)
        # ...but strictly less just below it.
        assert _total_atk_buff(3999) < _total_atk_buff(4000)


class TestOneAndTwoAnomalyTiersAtTheirEncodedCaps:
    """The 1-/2-Anomaly tiers are known-inexact (DESIGN §6.1): pin the
    *encoded* (not true) caps so the deviation is tested, not latent."""

    def test_one_anomaly_tier_caps_at_240_not_the_true_1600(self):
        one_anomaly = _aa_row_gated_on("same_specialty_or_faction_in_team")
        assert _bake_atk_scaled_modifier(one_anomaly, 100_000).value == 240
        assert one_anomaly.value == 240

    def test_two_anomaly_tier_caps_at_480_combined_not_the_true_1600(self):
        one_anomaly = _aa_row_gated_on("same_specialty_or_faction_in_team")
        two_anomaly = _aa_row_gated_on("anomaly_count_2_in_team")
        combined = (
            _bake_atk_scaled_modifier(one_anomaly, 100_000).value
            + _bake_atk_scaled_modifier(two_anomaly, 100_000).value
        )
        assert combined == 480

    def test_approximation_note_is_present_on_the_inexact_rows(self):
        """Rows 1/2 (1-/2-Anomaly tiers) are known-inexact and carry the
        note; row 3 (3-Anomaly tier) is exact at every ATK value per
        DESIGN §6.1's own cap table and correctly carries none."""
        kit = json.loads(MODIFIERS_PATH.read_text())
        aa_mods = [m for m in kit["modifiers"] if m.get("source") == "additional_ability"]
        assert len(aa_mods) == 3
        expected_note = (
            "shared-cap decomposed to proportional per-row caps -- "
            "exact only for the 3-Anomaly tier (DESIGN_remielle.md §6.1)"
        )
        inexact_rows = [m for m in aa_mods if m["conditions"][0] != "anomaly_count_3_in_team"]
        exact_row = next(m for m in aa_mods if m["conditions"][0] == "anomaly_count_3_in_team")
        assert len(inexact_rows) == 2
        for mod in inexact_rows:
            assert mod.get("approximation") == expected_note
        assert "approximation" not in exact_row


class TestSimStateConditionsWireUp:
    def test_prismatic_row_is_gated_on_lumiflux_buildup_active(self):
        mods = load_agent_modifiers(REMIELLE_HAKUSHIN_ID)
        prismatic = next(m for m in mods if m.stat == "anomaly_buildup")
        assert prismatic.conditions == (Condition.LUMIFLUX_BUILDUP_ACTIVE,)
        assert prismatic.value == 1500
        assert prismatic.target.value == "team"

    def test_phase_flow_squad_dmg_row_is_18_percent_at_max_skill_level(self):
        mods = load_agent_modifiers(REMIELLE_HAKUSHIN_ID)
        pf_dmg = next(m for m in mods if m.stat == "dmg_bonus")
        assert pf_dmg.conditions == (Condition.PHASE_FLOW_ACTIVE,)
        assert pf_dmg.value == 1800  # 0 + 12*1.5 = 18%
        assert pf_dmg.target.value == "team"

    def test_refringe_flat_bonus_rows_are_self_and_sum_to_30_percent_at_max_mindscape(self):
        mods = load_agent_modifiers(REMIELLE_HAKUSHIN_ID)
        refringe_rows = [m for m in mods if m.stat == "refringe_flat_bonus_bp"]
        assert len(refringe_rows) == 2
        assert all(m.target.value == "self" for m in refringe_rows)
        assert sum(m.value for m in refringe_rows) == 3000  # 10% core + 20% M2

    def test_m1_res_ignore_is_authored_against_the_luminize_scoped_bucket(self):
        """Audit finding S1-A / hardening Task 4, retired by Task 19.

        M1 reads "When Remielle triggers Luminize to deal DMG, she ignores 50%
        of the target's All-Attribute RES" -- a res-ignore scoped to ONE damage
        source. The kit first shipped it as a plain always/all self `res_ignore`
        row, but `res_ignore` is read by every damage path she has, so the row
        also cut enemy RES for her Ultimate, Chain, EX and Phase Flow ticks --
        roughly a 1.5x inflation on damage the clause never touches (RESArea
        1.0 -> 1.5 against a 0-RES enemy). That is the D-KV6 wrong-wiring class,
        not an approximation inside D-KV17's 2% ceiling, so Task 4 REMOVED the
        row rather than re-encoding it narrower and ledgered the gap.

        Task 19 built the missing bucket -- `luminize_res_ignore`, a contribution
        consumed only by `calculate_luminize_damage` -- and authored the row
        against it. The 5000 bp was never in doubt; only its wiring was.

        Both halves are asserted. The row must exist (Task 4's removal
        under-credited M1, which was the lesser of two wrongs, not a resting
        place), and the generic bucket must stay empty (that is the leak).
        """
        mods = load_agent_modifiers(REMIELLE_HAKUSHIN_ID)

        rows = [m for m in mods if m.stat == "luminize_res_ignore"]
        assert len(rows) == 1, "M1's Luminize RES-ignore row is missing"
        row = rows[0]
        assert row.value == 5000
        assert row.min_mindscape == 1
        assert row.target.value == "self"

        # The leak, still shut. `res_ignore` is the bucket every damage path
        # reads; nothing in this kit may put the M1 clause back into it.
        assert [m for m in mods if m.stat == "res_ignore"] == []

    def test_m2_refringe_bonus_gates_on_mindscape_2(self):
        mods = load_agent_modifiers(REMIELLE_HAKUSHIN_ID)
        m2 = next(m for m in mods if m.stat == "refringe_flat_bonus_bp" and m.min_mindscape > 0)
        assert m2.min_mindscape == 2
        assert m2.value == 2000


class TestM1TeamAnomalyDmgBuff:
    """Audit finding S1-C / hardening Task 5.

    M1's final clause -- "While Remielle is in the [Phase Flow] state, other
    squad members' Attribute Anomaly DMG increases by 10%" -- was missing
    from the kit entirely. M1 was represented only by its RES-ignore clause,
    so a headline team buff on her signature mindscape contributed nothing.
    """

    def _row(self):
        mods = load_agent_modifiers(REMIELLE_HAKUSHIN_ID)
        return next(
            m
            for m in mods
            if m.stat == "anomaly_dmg_bonus" and m.source == ModifierSource.MINDSCAPE
        )

    def _resolved(self, *, mindscape: int, phase_flow: bool):
        mods = [
            m for m in load_agent_modifiers(REMIELLE_HAKUSHIN_ID)
            if mindscape_allows(m, mindscape)
        ]
        active = {Condition.ALWAYS}
        if phase_flow:
            active.add(Condition.PHASE_FLOW_ACTIVE)
        return resolve_modifiers(
            mods,
            ActiveConditions(active=active),
            target_filter=ModifierTarget.TEAM,
        )

    def test_row_shape(self):
        row = self._row()
        assert row.value == 1000
        assert row.min_mindscape == 1
        assert row.target == ModifierTarget.TEAM
        assert row.conditions == (Condition.PHASE_FLOW_ACTIVE,)

    def test_teammates_get_the_buff_at_m1_during_phase_flow(self):
        assert self._resolved(mindscape=1, phase_flow=True).anomaly_dmg_bonus == 1000

    def test_no_buff_at_m0(self):
        assert self._resolved(mindscape=0, phase_flow=True).anomaly_dmg_bonus == 0

    def test_no_buff_outside_phase_flow(self):
        assert self._resolved(mindscape=1, phase_flow=False).anomaly_dmg_bonus == 0

    def test_buff_persists_at_higher_mindscapes(self):
        assert self._resolved(mindscape=6, phase_flow=True).anomaly_dmg_bonus == 1000
