"""Unit tests for stat aggregation (stat_calculator.py)."""

from __future__ import annotations

from app.services.stat_calculator import (
    StatInputs,
    TotalStats,
    accumulate_disc_stats,
    compute_total_stats,
)


class TestComputeTotalStats:
    """Tests for the ATK/HP/DEF aggregation formula."""

    def test_base_atk_only(self):
        """Agent base ATK + W-Engine base ATK with no bonuses."""
        inputs = StatInputs(agent_base_atk=600, wengine_base_atk=400)
        result = compute_total_stats(inputs)
        # (600+400) * (1+0) + 0 = 1000, no final bonuses
        assert result.atk == 1000

    def test_atk_with_percentage(self):
        """ATK% bonus from disc substats etc."""
        inputs = StatInputs(
            agent_base_atk=600,
            wengine_base_atk=400,
            atk_pct=3000,  # 30%
        )
        result = compute_total_stats(inputs)
        # (1000 * 1.3) = 1300
        assert result.atk == 1300

    def test_atk_with_flat(self):
        """Flat ATK added after percentage."""
        inputs = StatInputs(
            agent_base_atk=600,
            wengine_base_atk=400,
            atk_pct=3000,
            flat_atk=200,
        )
        result = compute_total_stats(inputs)
        # (1000 * 1.3 + 200) = 1500
        assert result.atk == 1500

    def test_atk_full_formula(self):
        """Full ATK formula with final multipliers."""
        inputs = StatInputs(
            agent_base_atk=600,
            wengine_base_atk=400,
            atk_pct=3000,
            flat_atk=200,
            final_atk_pct=1000,  # 10%
            final_flat_atk=50,
        )
        result = compute_total_stats(inputs)
        # ((1000 * 1.3 + 200) * 1.1) + 50 = 1500 * 1.1 + 50 = 1650 + 50 = 1700
        assert result.atk == 1700

    def test_hp_formula(self):
        """HP uses same formula as ATK but without W-Engine base."""
        inputs = StatInputs(
            agent_base_hp=8000,
            hp_pct=2000,  # 20%
        )
        result = compute_total_stats(inputs)
        # 8000 * 1.2 = 9600
        assert result.hp == 9600

    def test_def_formula(self):
        inputs = StatInputs(
            agent_base_def=500,
            def_pct=5000,  # 50%
            flat_def=100,
        )
        result = compute_total_stats(inputs)
        # (500 * 1.5 + 100) = 850
        assert result.defense == 850

    def test_combat_stats_passthrough(self):
        """Combat stats pass through directly."""
        inputs = StatInputs(
            crit_rate=2400,
            crit_dmg=9600,
            pen_flat=30,
            pen_ratio=2000,
            anomaly_mastery=92,
            anomaly_proficiency=115,
            fire_dmg=3000,
        )
        result = compute_total_stats(inputs)
        assert result.crit_rate == 2400
        assert result.crit_dmg == 9600
        assert result.pen_flat == 30
        assert result.pen_ratio == 2000
        assert result.anomaly_mastery == 92
        assert result.anomaly_proficiency == 115
        assert result.fire_dmg == 3000

    def test_floor_rounding(self):
        """Result should be floored, not rounded."""
        inputs = StatInputs(
            agent_base_atk=333,
            wengine_base_atk=0,
            atk_pct=3333,  # 33.33%
        )
        result = compute_total_stats(inputs)
        # 333 * 1.3333 = 443.9889 → floor = 443
        assert result.atk == 443

    def test_zero_inputs(self):
        """All zeros should produce base defaults."""
        inputs = StatInputs()
        result = compute_total_stats(inputs)
        assert result.atk == 0
        assert result.hp == 0
        assert result.defense == 0
        assert result.crit_rate == 500  # default 5%
        assert result.crit_dmg == 5000  # default 50%


class TestAccumulateDiscStats:
    def test_empty_discs(self):
        result = accumulate_disc_stats([])
        assert result.flat_hp == 0
        assert result.crit_rate == 0

    def test_single_disc_main_stat(self):
        discs = [{"main_stat_type": "crit_rate", "main_stat_value": 2400}]
        result = accumulate_disc_stats(discs)
        assert result.crit_rate == 2400

    def test_disc_with_substats(self):
        discs = [
            {
                "main_stat_type": "crit_rate",
                "main_stat_value": 2400,
                "substats": [
                    {"stat": "crit_dmg", "value": 480},
                    {"stat": "atk_pct", "value": 300},
                ],
            }
        ]
        result = accumulate_disc_stats(discs)
        assert result.crit_rate == 2400
        assert result.crit_dmg == 480
        assert result.atk_pct == 300

    def test_multiple_discs_sum(self):
        discs = [
            {"main_stat_type": "crit_rate", "main_stat_value": 2400},
            {
                "main_stat_type": "crit_dmg",
                "main_stat_value": 4800,
                "substats": [{"stat": "crit_rate", "value": 240}],
            },
        ]
        result = accumulate_disc_stats(discs)
        assert result.crit_rate == 2640  # 2400 + 240
        assert result.crit_dmg == 4800

    def test_flat_stats(self):
        discs = [
            {"main_stat_type": "hp", "main_stat_value": 4600},
            {"main_stat_type": "atk", "main_stat_value": 316},
        ]
        result = accumulate_disc_stats(discs)
        assert result.flat_hp == 4600
        assert result.flat_atk == 316

    def test_unknown_stat_ignored(self):
        discs = [{"main_stat_type": "nonexistent", "main_stat_value": 999}]
        result = accumulate_disc_stats(discs)
        # Should not raise, just ignore
        assert result.flat_hp == 0

    def test_null_substats_handled(self):
        discs = [{"main_stat_type": "hp", "main_stat_value": 100, "substats": None}]
        result = accumulate_disc_stats(discs)
        assert result.flat_hp == 100

    def test_elemental_dmg(self):
        discs = [{"main_stat_type": "fire_dmg", "main_stat_value": 3000}]
        result = accumulate_disc_stats(discs)
        assert result.fire_dmg == 3000


class TestAnomalyMasteryPct:
    """Task 1.6b — AM% multiplies base AM only; flat additions come after."""

    def test_am_pct_applies_to_base_only(self):
        # base_am=100, flat disc AM=90, am_pct=800 (8%)
        # total = floor(100 * 10800/10000 + 90) = floor(108 + 90) = 198
        inputs = StatInputs(agent_base_am=100, anomaly_mastery=90, am_pct=800)
        result = compute_total_stats(inputs)
        assert result.anomaly_mastery == 198

    def test_am_pct_zero_is_identity(self):
        # No AM% — result is base + flat, same as before
        inputs = StatInputs(agent_base_am=114, anomaly_mastery=36)
        result = compute_total_stats(inputs)
        assert result.anomaly_mastery == 150

    def test_am_pct_no_flat(self):
        # base_am=92, no flat, 8% => floor(92 * 10800/10000) = floor(99.36) = 99
        inputs = StatInputs(agent_base_am=92, am_pct=800)
        result = compute_total_stats(inputs)
        assert result.anomaly_mastery == 99

    def test_am_pct_does_not_scale_flat(self):
        # Verify flat disc AM is NOT multiplied by am_pct.
        # If it were, floor((100+90)*1.08)=205; correct value is 198.
        inputs = StatInputs(agent_base_am=100, anomaly_mastery=90, am_pct=800)
        result = compute_total_stats(inputs)
        assert result.anomaly_mastery == 198  # not 205

    def test_legacy_flat_passthrough(self):
        # StatInputs with only anomaly_mastery set (no agent_base_am) still works.
        # Existing tests use this form; result must be the flat value unchanged.
        inputs = StatInputs(anomaly_mastery=92)
        result = compute_total_stats(inputs)
        assert result.anomaly_mastery == 92


class TestTotalStatsElementalDmg:
    def test_elemental_dmg_lookup(self):
        stats = TotalStats(fire_dmg=3000, ice_dmg=2500)
        assert stats.elemental_dmg("fire") == 3000
        assert stats.elemental_dmg("ice") == 2500
        assert stats.elemental_dmg("electric") == 0
        assert stats.elemental_dmg("nonexistent") == 0
