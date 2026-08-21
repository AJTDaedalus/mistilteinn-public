"""Unit tests for damage calculation engine (damage_calculator.py).

Cross-referenced against:
- ZZZ-Plugin Calculator.js formulas
- Thereallo1026's damage guide
- Known community-verified values (Level 60 factor = 794)
"""

from __future__ import annotations

from app.services.damage_calculator import (
    AbloomResult,
    AnomalyResult,
    AnomalyType,
    CritMode,
    DamageResult,
    DisorderResult,
    VortexResult,
    anomaly_level_multiplier,
    anomaly_proficiency_multiplier,
    base_damage,
    calculate_abloom_damage,
    calculate_anomaly_damage,
    calculate_buildup,
    calculate_disorder_damage,
    calculate_standard_damage,
    calculate_vortex_damage,
    crit_multiplier,
    def_multiplier,
    dmg_bonus_multiplier,
    dmg_taken_multiplier,
    level_factor,
    res_multiplier,
    stun_multiplier,
)

# ---------------------------------------------------------------------------
# Zone 1: Base damage
# ---------------------------------------------------------------------------


class TestBaseDamage:
    def test_simple(self):
        # 1000 ATK * 31.20% multiplier = 312
        assert base_damage(1000, 3120) == 312

    def test_large_multiplier(self):
        # 2000 ATK * 500% = 10000
        assert base_damage(2000, 50000) == 10000

    def test_zero_stat(self):
        assert base_damage(0, 5000) == 0

    def test_zero_multiplier(self):
        assert base_damage(1000, 0) == 0

    def test_floors_result(self):
        # 333 * 31.20% = 103.896 -> 103
        assert base_damage(333, 3120) == 103


# ---------------------------------------------------------------------------
# Zone 2: DMG bonus (boost area)
# ---------------------------------------------------------------------------


class TestDmgBonusMultiplier:
    def test_no_bonuses(self):
        assert dmg_bonus_multiplier([]) == 10000

    def test_single_bonus(self):
        # 30% elemental DMG = 1.3*
        assert dmg_bonus_multiplier([3000]) == 13000

    def test_multiple_bonuses_stack(self):
        # 30% elemental + 25% generic + 10% skill = 65% -> 1.65*
        assert dmg_bonus_multiplier([3000, 2500, 1000]) == 16500

    def test_negative_bonus(self):
        # Some debuffs could reduce DMG
        assert dmg_bonus_multiplier([-2000]) == 8000


# ---------------------------------------------------------------------------
# Zone 3: Crit area
# ---------------------------------------------------------------------------


class TestCritMultiplier:
    def test_expected_average(self):
        # 50% crit rate * 100% crit dmg -> 1 + 0.5 * 1.0 = 1.5*
        result = crit_multiplier(5000, 10000, CritMode.EXPECTED)
        assert result == 15000

    def test_expected_default_stats(self):
        # 5% crit rate * 50% crit dmg -> 1 + 0.05 * 0.5 = 1.025*
        result = crit_multiplier(500, 5000, CritMode.EXPECTED)
        assert result == 10250

    def test_always_crit(self):
        # 1 + 100% crit dmg = 2.0*
        result = crit_multiplier(5000, 10000, CritMode.CRIT)
        assert result == 20000

    def test_never_crit(self):
        result = crit_multiplier(5000, 10000, CritMode.NO_CRIT)
        assert result == 10000

    def test_crit_rate_capped_at_100(self):
        # 150% crit rate should be clamped to 100%
        result = crit_multiplier(15000, 10000, CritMode.EXPECTED)
        assert result == 20000  # 1 + 1.0 * 1.0

    def test_crit_rate_floor_at_zero(self):
        result = crit_multiplier(-1000, 10000, CritMode.EXPECTED)
        assert result == 10000  # 1 + 0 * 1.0

    def test_high_crit_dmg(self):
        # 80% rate * 200% dmg = 1 + 0.8 * 2.0 = 2.6*
        result = crit_multiplier(8000, 20000, CritMode.EXPECTED)
        assert result == 26000


# ---------------------------------------------------------------------------
# Zone 4: DEF area
# ---------------------------------------------------------------------------


class TestLevelFactor:
    def test_level_1(self):
        # floor(0.1551 * 1 + 3.141 * 1 + 47.2039) = floor(50.5) = 50
        assert level_factor(1) == 50

    def test_level_60(self):
        # Community consensus: 794
        assert level_factor(60) == 794

    def test_level_capped_at_60(self):
        # Levels above 60 should be capped
        assert level_factor(70) == level_factor(60)

    def test_level_floor_at_1(self):
        assert level_factor(0) == level_factor(1)

    def test_level_30(self):
        # floor(0.1551 * 900 + 3.141 * 30 + 47.2039) = floor(139.59 + 94.23 + 47.20)
        # = floor(281.02) = 281
        assert level_factor(30) == 281


class TestDefMultiplier:
    def test_equal_level_default_def(self):
        """Level 60 vs level 60 with base DEF 50 (standard enemy)."""
        result = def_multiplier(60, 50, 60)
        # enemy_def = 50 * 794 / 50 = 794
        # def_mult = 794 / (794 + 794) = 0.5 = 5000bp
        assert result == 5000

    def test_zero_def(self):
        """Enemy with 0 DEF -> 100% damage."""
        result = def_multiplier(60, 0, 60)
        assert result == 10000

    def test_pen_ratio(self):
        """20% PEN ratio reduces effective DEF."""
        result = def_multiplier(60, 50, 60, pen_ratio=2000)
        # enemy_def = 794, after 20% pen: 794 * 0.8 = 635.2 -> 635
        # def_mult = 794 / (635 + 794) = 794/1429 ≈ 0.5556 -> 5556bp
        # Integer math: 794 * 8000 // 10000 = 635
        # 794 * 10000 // (635 + 794) = 7940000 // 1429 = 5556
        assert result == 5556

    def test_pen_flat(self):
        """Flat PEN subtracts from effective DEF."""
        result = def_multiplier(60, 50, 60, pen_flat=200)
        # enemy_def = 794, after flat pen: max(0, 794 - 200) = 594
        # def_mult = 794 / (594 + 794) = 794/1388 ≈ 0.5720 -> 5720bp
        assert result == 5720

    def test_def_ignore_plus_pen(self):
        """DEF ignore applied before PEN ratio."""
        result = def_multiplier(60, 50, 60, def_ignore=2000, pen_ratio=2000)
        # 794*8000//10000=635, 635*8000//10000=508
        # 794*10000//(508+794) = 7940000//1302 = 6098
        assert result == 6098

    def test_effective_def_floor_at_zero(self):
        """Massive PEN shouldn't go below 0 DEF -> 100% damage."""
        result = def_multiplier(60, 50, 60, pen_flat=10000)
        assert result == 10000

    def test_low_level_attacker(self):
        """Low-level attacker vs high-level enemy gets penalized."""
        result = def_multiplier(30, 50, 60)
        # atk_factor = 281, enemy_def = 794
        # 281*10000//(794+281) = 2810000//1075 = 2613
        assert result == 2613


# ---------------------------------------------------------------------------
# Zone 5: RES area
# ---------------------------------------------------------------------------


class TestResMultiplier:
    def test_neutral_res(self):
        """0% resistance -> 1.0* multiplier."""
        assert res_multiplier(0) == 10000

    def test_weakness(self):
        """-20% resistance (weakness) -> 1.2* multiplier."""
        assert res_multiplier(-2000) == 12000

    def test_resistance(self):
        """30% resistance -> 0.7* multiplier."""
        assert res_multiplier(3000) == 7000

    def test_res_reduction(self):
        """20% base RES, 15% reduction -> 0.95* -> 10500bp."""
        assert res_multiplier(2000, res_reduction=1500) == 9500

    def test_res_ignore(self):
        assert res_multiplier(3000, res_ignore=3000) == 10000

    def test_clamped_at_zero(self):
        """Massive resistance shouldn't go below 0*."""
        assert res_multiplier(30000) == 0

    def test_clamped_at_two(self):
        """Massive weakness shouldn't exceed 2.0*."""
        assert res_multiplier(-20000) == 20000


# ---------------------------------------------------------------------------
# Zone 6: Vulnerability (DMG taken)
# ---------------------------------------------------------------------------


class TestDmgTakenMultiplier:
    def test_no_vulnerability(self):
        assert dmg_taken_multiplier([]) == 10000

    def test_single_debuff(self):
        # 25% increased damage taken
        assert dmg_taken_multiplier([2500]) == 12500

    def test_multiple_debuffs(self):
        assert dmg_taken_multiplier([2500, 1000]) == 13500


# ---------------------------------------------------------------------------
# Zone 7: Stun area
# ---------------------------------------------------------------------------


class TestStunMultiplier:
    def test_not_stunned(self):
        assert stun_multiplier(False) == 10000

    def test_stunned_default(self):
        # Default 1.5* when stunned
        assert stun_multiplier(True) == 15000

    def test_stunned_custom(self):
        # Boss with 2.0* stun vulnerability
        assert stun_multiplier(True, 20000) == 20000

    def test_clamped_low(self):
        assert stun_multiplier(True, 1000) == 2000

    def test_clamped_high(self):
        assert stun_multiplier(True, 60000) == 50000

    def test_stun_area_override_out_of_stun(self):
        # Even if not stunned, override of 11000 bp (110%) gives 1.0 + 1.1 = 2.1x (21000 bp)
        assert stun_multiplier(False, stun_area_override=11000) == 21000

    def test_stun_area_override_beats_natural_stun(self):
        # Override of 11000 bp beats natural stun 1.5x (15000 bp) and is used instead
        assert stun_multiplier(True, 15000, stun_area_override=11000) == 21000


# ---------------------------------------------------------------------------
# Anomaly-specific zones
# ---------------------------------------------------------------------------


class TestAnomalyProficiencyMultiplier:
    def test_zero_proficiency(self):
        assert anomaly_proficiency_multiplier(0) == 0

    def test_standard_proficiency(self):
        # 115 AP -> 115 * 100 = 11500bp = 1.15*
        assert anomaly_proficiency_multiplier(115) == 11500

    def test_clamped_at_max(self):
        # 1500 AP -> would be 150000 but capped at 100000 (10*)
        assert anomaly_proficiency_multiplier(1500) == 100000


class TestAnomalyLevelMultiplier:
    def test_level_1(self):
        # 1 + 0/59 * 0 = 1.0*
        assert anomaly_level_multiplier(1) == 10000

    def test_level_60(self):
        # 1 + 59/59 = 2.0*
        assert anomaly_level_multiplier(60) == 20000

    def test_level_30(self):
        # 1 + 29/59 ≈ 1.4915 -> integer: 10000 + 10000*29//59 = 10000+4915 = 14915
        assert anomaly_level_multiplier(30) == 14915


# ---------------------------------------------------------------------------
# Composite: Standard damage
# ---------------------------------------------------------------------------


class TestCalculateStandardDamage:
    def test_basic_calculation(self):
        """Simple damage calc with known values."""
        result = calculate_standard_damage(
            scaling_stat=1000,
            multiplier=10000,  # 100%
            crit_rate=5000,  # 50%
            crit_dmg=10000,  # 100%
            attacker_level=60,
            enemy_base_def=50,
            enemy_level=60,
        )
        assert isinstance(result, DamageResult)
        # base = 1000, boost = 1.0, crit = 1.5, def = 0.5, res = 1.0
        # 1000 * 1.0 * 1.5 * 0.5 * 1.0 * 1.0 * 1.0 = 750
        assert result.total == 750
        assert result.base_dmg == 1000
        assert result.crit_mult == 15000
        assert result.def_mult == 5000

    def test_with_dmg_bonuses(self):
        result = calculate_standard_damage(
            scaling_stat=1000,
            multiplier=10000,
            dmg_bonuses=[3000],  # 30%
            crit_mode=CritMode.NO_CRIT,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
        )
        # base=1000, boost=1.3, no crit, def=1.0 (zero def), res=1.0
        assert result.total == 1300

    def test_with_weakness(self):
        result = calculate_standard_damage(
            scaling_stat=1000,
            multiplier=10000,
            crit_mode=CritMode.NO_CRIT,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            enemy_res=-2000,  # -20% weakness
        )
        # base=1000, boost=1.0, no crit, def=1.0, res=1.2
        assert result.total == 1200

    def test_stunned_enemy(self):
        result = calculate_standard_damage(
            scaling_stat=1000,
            multiplier=10000,
            crit_mode=CritMode.NO_CRIT,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            is_stunned=True,
        )
        # base=1000, everything 1.0 except stun=1.5
        assert result.total == 1500

    def test_all_zones_active(self):
        """Every zone contributes."""
        result = calculate_standard_damage(
            scaling_stat=2000,
            multiplier=5000,  # 50% -> base=1000
            dmg_bonuses=[3000],  # 30% -> 1.3
            crit_rate=5000,
            crit_dmg=10000,  # 50% * 100% -> 1.5
            crit_mode=CritMode.EXPECTED,
            attacker_level=60,
            enemy_base_def=50,
            enemy_level=60,  # -> 0.5
            enemy_res=-2000,  # -> 1.2
            vulnerability_bonuses=[2500],  # -> 1.25
            is_stunned=True,
            stun_dmg_mult=15000,  # -> 1.5
        )
        # 1000 * 1.3 * 1.5 * 0.5 * 1.2 * 1.25 * 1.5
        # = 1000 * 1.3 = 1300
        # * 1.5 = 1950
        # * 0.5 = 975
        # * 1.2 = 1170
        # * 1.25 = 1462 (1462.5 floored by integer division)
        # * 1.5 = 2193
        assert result.total == 2193

    def test_result_fields(self):
        result = calculate_standard_damage(
            scaling_stat=1000,
            multiplier=10000,
            attacker_level=60,
            enemy_base_def=50,
            enemy_level=60,
        )
        assert result.boost_mult == 10000
        assert result.res_mult == 10000
        assert result.vulnerability_mult == 10000
        assert result.stun_mult == 10000


# ---------------------------------------------------------------------------
# Composite: Anomaly damage
# ---------------------------------------------------------------------------


class TestCalculateAnomalyDamage:
    def test_burn_basic(self):
        """Burn: 50% ATK * 20 procs."""
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.BURN,
            atk=2000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
        )
        assert isinstance(result, AnomalyResult)
        assert result.procs == 20
        # base = 2000 * 50% = 1000
        assert result.base_dmg == 1000
        # anomaly_prof = 100 * 100 = 10000bp (1.0*)
        assert result.anomaly_prof_mult == 10000
        # level = 2.0*
        assert result.level_mult == 20000

    def test_shock_procs(self):
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.SHOCK,
            atk=1000,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
        )
        assert result.procs == 10
        # base = 1000 * 125% = 1250
        assert result.base_dmg == 1250

    def test_shatter_single_proc(self):
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.SHATTER,
            atk=1000,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
        )
        assert result.procs == 1
        assert result.base_dmg == 5000  # 500% ATK

    def test_assault_single_proc(self):
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.ASSAULT,
            atk=1000,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
        )
        assert result.procs == 1
        assert result.base_dmg == 7130  # 713% ATK

    def test_custom_procs_override(self):
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.BURN,
            atk=1000,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            procs=5,
        )
        assert result.procs == 5

    def test_total_is_per_proc_times_procs(self):
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.BURN,
            atk=1000,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
        )
        assert result.total == result.per_proc * result.procs

    def test_anomaly_dmg_bonus(self):
        """Anomaly-specific DMG bonus zone."""
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.BURN,
            atk=1000,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            anomaly_proficiency=0,
            anomaly_dmg_bonus=2000,  # 20%
        )
        assert result.anomaly_boost_mult == 12000  # 1.2*

    def test_no_crit_in_anomaly(self):
        """Anomaly damage should NOT have a crit zone."""
        result = calculate_anomaly_damage(
            anomaly_type=AnomalyType.BURN,
            atk=1000,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            anomaly_proficiency=0,
        )
        # No crit field in AnomalyResult
        assert not hasattr(result, "crit_mult")


# ---------------------------------------------------------------------------
# Buildup Calculations
# ---------------------------------------------------------------------------


class TestCalculateBuildup:
    def test_basic_buildup(self):
        # move=60, bonus=0, AM=100, res=0, stunned=False -> 60
        result = calculate_buildup(
            move_buildup=60,
            anomaly_buildup_bonus=0,
            anomaly_mastery=100,
            enemy_anomaly_res=0,
            is_stunned=False,
        )
        assert result == 60

    def test_with_buildup_bonus_and_mastery(self):
        # move=60, bonus=30% (3000bp), AM=115, res=-20% weakness (-2000bp), stunned=True
        # val = 60 * 1.3 = 78
        # val = 78 * 1.15 = 89.7 -> 89 (integer math: 78 * 115 // 100 = 89)
        # val = 89 * 1.2 = 106.8 -> 106 (integer math: 89 * 12000 // 10000 = 106)
        # val = 106 * 1.5 = 159 (integer math: 106 * 15000 // 10000 = 159)
        result = calculate_buildup(
            move_buildup=60,
            anomaly_buildup_bonus=3000,
            anomaly_mastery=115,
            enemy_anomaly_res=-2000,
            is_stunned=True,
            stun_buildup_multiplier=15000,
        )
        assert result == 159


# ---------------------------------------------------------------------------
# Disorder Damage Calculations
# ---------------------------------------------------------------------------


class TestCalculateDisorderDamage:
    def test_burn_disorder(self):
        # Burn Disorder: 450% + remaining_duration * 100%
        # atk=2000, remaining_duration=5.0s, max_duration=10s, base_def=0
        # disorder_mv = 45000 + 5.0 * 10000 = 95000 (950% ATK)
        # base_dmg = 2000 * 95% = 1900
        # total_dmg = 1900 * 2.0 (level_mult) = 3800
        result = calculate_disorder_damage(
            anomaly_type=AnomalyType.BURN,
            atk=2000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            remaining_duration=5.0,
            max_duration=10.0,
            disorder_dmg_bonus=1000,  # 10% -> 1.1*
        )
        assert isinstance(result, DisorderResult)
        # Base damage is 19000
        assert result.base_dmg == 19000
        # Multipliers: boost=1.0, def=1.0, res=1.0, prof=1.0
        # level=2.0, anomaly_boost=1.0, disorder_boost=1.1
        # 19000 * 2.0 * 1.1 = 41800
        assert result.total == 41800
        assert result.disorder_boost_mult == 11000
        assert result.time_remaining_factor == 5000  # 50%

    def test_shock_disorder(self):
        # Shock Disorder: 450% + remaining_duration * 125%
        # atk=1000, remaining_duration=4.0s, max_duration=10.0s, base_def=0
        # Expected disorder MV is 45000 + 4.0 * 12500 = 95000
        result = calculate_disorder_damage(
            anomaly_type=AnomalyType.SHOCK,
            atk=1000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            remaining_duration=4.0,
            max_duration=10.0,
        )
        assert result.base_dmg == 9500
        # 9500 * 2.0 (level_mult) = 19000
        assert result.total == 19000

    def test_windswept_disorder(self):
        # Windswept Disorder: 100% flat
        # atk=1000, remaining_duration=12.0s, max_duration=20.0s, base_def=0
        # Expected disorder MV is 10000
        result = calculate_disorder_damage(
            anomaly_type=AnomalyType.WINDSWEPT,
            atk=1000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            remaining_duration=12.0,
            max_duration=20.0,
        )
        assert result.base_dmg == 1000
        # 1000 * 2.0 (level_mult) = 2000
        assert result.total == 2000

    def test_disorder_stun_area_override(self):
        result = calculate_disorder_damage(
            anomaly_type=AnomalyType.WINDSWEPT,
            atk=1000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            remaining_duration=12.0,
            max_duration=20.0,
            is_stunned=False,
            stun_area_override=11000,  # 2.1x
        )
        # 1000 * 2.0 (level_mult) * 2.1 (stun override) = 4200
        assert result.total == 4200
        assert result.stun_mult == 21000

    def test_flat_base_dmg_added_before_multipliers(self):
        # Windswept MV=10000 → ATK base = atk * 10000 // 10000 = 1000.
        # flat_base_dmg = 500 added to base before multiplier chain.
        # combined_base = 1500; total = 1500 * 2.0 (level_mult) = 3000.
        result = calculate_disorder_damage(
            anomaly_type=AnomalyType.WINDSWEPT,
            atk=1000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            remaining_duration=12.0,
            max_duration=20.0,
            flat_base_dmg=500,
        )
        assert result.base_dmg == 1500
        assert result.total == 3000

    def test_base_dmg_bonus_pct_scales_atk_mv_then_flat_added(self):
        # Polarity Disorder: BaseDMGBonus% = -8500 (→ 15% of ATK×MV base).
        # Windswept: ATK base = 1000; scaled = 1000 * 1500 // 10000 = 150.
        # flat_base_dmg = 500 added after scaling.
        # combined_base = 150 + 500 = 650; total = 650 * 2.0 = 1300.
        # Source: Leifa "DMG Formula for Anomaly, Disorder and Vortex" — Polarity Disorder formula.
        result = calculate_disorder_damage(
            anomaly_type=AnomalyType.WINDSWEPT,
            atk=1000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            remaining_duration=12.0,
            max_duration=20.0,
            base_dmg_bonus_pct=-8500,
            flat_base_dmg=500,
        )
        assert result.base_dmg == 650
        assert result.total == 1300


class TestDisorderMvPinTests:
    """Per-type disorder MV pin tests vs Leifa at t=0 and t=max.

    Formulas (Leifa — DMG Formula for Anomaly, Disorder and Vortex):
      BURN:       45000 + floor(t / 0.5) * 5000   (450% + [t/0.5] ticks × 50%)
      SHOCK:      45000 + t * 12500               (450% + t × 125%)
      CORRUPTION: 45000 + floor(t / 0.5) * 6250   (450% + [t/0.5] ticks × 62.5%)
      SHATTER:    45000 + floor(t * 750)           (450% + t × 7.5%, Ice-Freeze)
      ASSAULT:    45000 + floor(t * 750)           (450% + t × 7.5%)
      WINDSWEPT:  10000                            (100%, flat)

    Setup: atk=1000, AP=100, level=60, enemy_def=0, no bonuses.
      level_mult(60) = 2.0, prof_mult(100) = 1.0
      base_dmg = atk * mv // 10000; total = base_dmg * 2
    """

    def _calc(
        self,
        anomaly_type: AnomalyType,
        remaining_duration: float,
        max_duration: float,
    ) -> DisorderResult:
        return calculate_disorder_damage(
            anomaly_type=anomaly_type,
            atk=1000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            remaining_duration=remaining_duration,
            max_duration=max_duration,
        )

    # --- BURN: mv = 45000 + floor(t/0.5)*5000 ---

    def test_burn_t0(self):
        # mv = 45000, base = 4500, total = 9000
        r = self._calc(AnomalyType.BURN, 0.0, 10.0)
        assert r.base_dmg == 4500
        assert r.total == 9000

    def test_burn_tmax(self):
        # t=10s: mv = 45000 + floor(10/0.5)*5000 = 45000+100000 = 145000
        # base = 14500, total = 29000
        r = self._calc(AnomalyType.BURN, 10.0, 10.0)
        assert r.base_dmg == 14500
        assert r.total == 29000

    # --- SHOCK: mv = 45000 + t*12500 ---

    def test_shock_t0(self):
        # mv = 45000, base = 4500, total = 9000
        r = self._calc(AnomalyType.SHOCK, 0.0, 10.0)
        assert r.base_dmg == 4500
        assert r.total == 9000

    def test_shock_tmax(self):
        # t=10s: mv = 45000 + 10*12500 = 170000, base = 17000, total = 34000
        r = self._calc(AnomalyType.SHOCK, 10.0, 10.0)
        assert r.base_dmg == 17000
        assert r.total == 34000

    # --- CORRUPTION: mv = 45000 + floor(t/0.5)*6250 ---

    def test_corruption_t0(self):
        # mv = 45000, base = 4500, total = 9000
        r = self._calc(AnomalyType.CORRUPTION, 0.0, 10.0)
        assert r.base_dmg == 4500
        assert r.total == 9000

    def test_corruption_tmax(self):
        # t=10s: mv = 45000 + floor(10/0.5)*6250 = 45000+20*6250 = 170000
        # base = 17000, total = 34000
        r = self._calc(AnomalyType.CORRUPTION, 10.0, 10.0)
        assert r.base_dmg == 17000
        assert r.total == 34000

    # --- SHATTER (Ice-Freeze): mv = 45000 + floor(t*750) ---

    def test_shatter_t0(self):
        # mv = 45000 + floor(0*750) = 45000, base = 4500, total = 9000
        # Leifa Ice-Freeze: 450% base (not 600% Frost-Freeze)
        r = self._calc(AnomalyType.SHATTER, 0.0, 10.0)
        assert r.base_dmg == 4500
        assert r.total == 9000

    def test_shatter_tmax(self):
        # t=10s: mv = 45000 + floor(10*750) = 45000+7500 = 52500
        # base = 5250, total = 10500
        r = self._calc(AnomalyType.SHATTER, 10.0, 10.0)
        assert r.base_dmg == 5250
        assert r.total == 10500

    # --- ASSAULT: mv = 45000 + floor(t*750) ---

    def test_assault_t0(self):
        # mv = 45000, base = 4500, total = 9000
        r = self._calc(AnomalyType.ASSAULT, 0.0, 1.0)
        assert r.base_dmg == 4500
        assert r.total == 9000

    def test_assault_tmax(self):
        # t=1s: mv = 45000 + floor(1*750) = 45750, base = 4575, total = 9150
        r = self._calc(AnomalyType.ASSAULT, 1.0, 1.0)
        assert r.base_dmg == 4575
        assert r.total == 9150

    # --- WINDSWEPT: mv = 10000 ---

    def test_windswept_t0(self):
        # mv = 10000, base = 1000, total = 2000
        r = self._calc(AnomalyType.WINDSWEPT, 0.0, 20.0)
        assert r.base_dmg == 1000
        assert r.total == 2000

    def test_windswept_tmax(self):
        # t=20s: mv = 10000 (flat), base = 1000, total = 2000
        r = self._calc(AnomalyType.WINDSWEPT, 20.0, 20.0)
        assert r.base_dmg == 1000
        assert r.total == 2000


# ---------------------------------------------------------------------------
# Vortex Damage Calculations
# ---------------------------------------------------------------------------


class TestCalculateVortexDamage:
    def test_burn_vortex(self):
        # Burn Vortex: 900% + remaining_duration * 100%
        # atk=1000, remaining_duration=5.0s, base_def=0
        # vortex_mv = 90000 + 5.0 * 10000 = 140000 (1400% ATK)
        # base_dmg = 1000 * 14 = 14000
        # total = 14000 * 2.0 (level_mult) = 28000
        result = calculate_vortex_damage(
            vortex_kind="burn",
            atk=1000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            remaining_duration=5.0,
            vortex_dmg_bonus=2000,  # 20%
        )
        assert isinstance(result, VortexResult)
        assert result.base_dmg == 14000
        # 14000 * 2.0 (level_mult) * 1.2 (vortex_boost) = 33600
        assert result.total == 33600
        assert result.vortex_boost_mult == 12000

    def test_vortex_stun_area_override(self):
        result = calculate_vortex_damage(
            vortex_kind="burn",
            atk=1000,
            anomaly_proficiency=100,
            attacker_level=60,
            enemy_base_def=0,
            enemy_level=60,
            remaining_duration=5.0,
            vortex_dmg_bonus=2000,  # 20%
            is_stunned=False,
            stun_area_override=11000,  # 2.1x
        )
        # 14000 * 2.0 (level_mult) * 1.2 (vortex_boost) * 2.1 (stun override) = 70560
        assert result.total == 70560
        assert result.stun_mult == 21000


# ---------------------------------------------------------------------------
# Zone: Abloom damage (secondary-anomaly mechanic)
# ---------------------------------------------------------------------------
# Formula (Leifa / game text — LOG_abloom.md A1):
#   AdditionalDMG = (abloom_mv_bp / 10000) × (AP / 10) × original_anomaly_dmg
#   = original_anomaly_dmg * abloom_mv_bp * ap // 100_000
# Vivian per-element MVs (bp) sourced from agent_kit_atlas.json:4160 Core Passive:
#   Ether=615, Electric=320, Fire=800, Physical=75, Ice=108
# All pin tests use AP=100, original_anomaly_dmg=10_000 for clean integer results.


class TestCalculateAbloomDamage:
    """Pin tests for calculate_abloom_damage() — one per Vivian element + boost path."""

    def _call(self, abloom_mv_bp: int, abloom_dmg_bonus: int = 0) -> AbloomResult:
        return calculate_abloom_damage(
            abloom_mv_bp=abloom_mv_bp,
            original_anomaly_dmg=10_000,
            ap=100,
            abloom_dmg_bonus=abloom_dmg_bonus,
        )

    def test_ether(self):
        # Vivian Ether: 6.15%/10AP. AP=100 → 6.15% × 10 × 10000 = 6150
        result = self._call(615)
        assert isinstance(result, AbloomResult)
        assert result.total == 6150

    def test_electric(self):
        # Vivian Electric: 3.2%/10AP. AP=100 → 3.2% × 10 × 10000 = 3200
        assert self._call(320).total == 3200

    def test_fire(self):
        # Vivian Fire: 8%/10AP. AP=100 → 8% × 10 × 10000 = 8000
        assert self._call(800).total == 8000

    def test_physical(self):
        # Vivian Physical: 0.75%/10AP. AP=100 → 0.75% × 10 × 10000 = 750
        assert self._call(75).total == 750

    def test_ice(self):
        # Vivian Ice: 1.08%/10AP. AP=100 → 1.08% × 10 × 10000 = 1080
        assert self._call(108).total == 1080

    def test_abloom_dmg_bonus(self):
        # Frostfall Sickle R1: +40% Abloom DMG (4000 bp). Ether base=6150 × 1.40 = 8610
        assert self._call(615, abloom_dmg_bonus=4000).total == 8610

    def test_zero_ap_gives_zero(self):
        result = calculate_abloom_damage(abloom_mv_bp=615, original_anomaly_dmg=10_000, ap=0)
        assert result.total == 0

    def test_zero_original_dmg_gives_zero(self):
        result = calculate_abloom_damage(abloom_mv_bp=615, original_anomaly_dmg=0, ap=100)
        assert result.total == 0

    def test_half_ap(self):
        # Ether at AP=50 → 6.15% × 5 × 10000 = 3075
        result = calculate_abloom_damage(abloom_mv_bp=615, original_anomaly_dmg=10_000, ap=50)
        assert result.total == 3075

    def test_flat_mv_grace_fire_pin(self):
        # Grace fire: 7000bp flat (abloom_ap_scaled=False). AP is irrelevant.
        # 10_000 × 7000 // 10_000 = 7000 (70% of original).
        result = calculate_abloom_damage(
            abloom_mv_bp=7000,
            original_anomaly_dmg=10_000,
            ap=100,
            abloom_ap_scaled=False,
        )
        assert result.total == 7000

    def test_flat_mv_ap_irrelevant(self):
        # ap=0 still gives 70% when abloom_ap_scaled=False.
        result = calculate_abloom_damage(
            abloom_mv_bp=7000,
            original_anomaly_dmg=10_000,
            ap=0,
            abloom_ap_scaled=False,
        )
        assert result.total == 7000

    def test_flat_mv_dmg_bonus_still_applied(self):
        # +40% dmg bonus on top of flat path: 7000 × 1.40 = 9800.
        result = calculate_abloom_damage(
            abloom_mv_bp=7000,
            original_anomaly_dmg=10_000,
            ap=0,
            abloom_ap_scaled=False,
            abloom_dmg_bonus=4000,
        )
        assert result.total == 9800
