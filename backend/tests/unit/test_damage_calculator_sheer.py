"""Golden-value unit tests for calculate_sheer_damage.

All expected values are hand-computed against the Sheer Damage formula:

  BaseDMG = floor(sheer_force * multiplier / 10000)
  SheerDMG = BaseDMG * BoostArea * CritArea * RESArea
             * VulnerabilityArea * StunArea * SheerBoostArea

  BoostArea = 10000 + sum(dmg_bonuses)   — same additive pool as standard
  SheerBoostArea = 10000 + sum(sheer_dmg_bonuses)  — SEPARATE multiplicative zone

The DEF zone is intentionally absent; PEN and def_ignore are not in the
function signature and cannot affect results.

References:
  - references/ZZZ Stats and Damage Calculation Reference.html (Sheer Damage)
  - DESIGN_sheer_damage.md §Formula
"""

from __future__ import annotations

import inspect

from app.services.damage_calculator import CritMode, SheerDamageResult, calculate_sheer_damage

_SF = 3600  # SheerForce shared across cases
_MV = 10000  # multiplier 100% = 10000 bp; BaseDMG = floor(3600*10000/10000) = 3600


class TestCalculateSheerDamage:
    def test_baseline(self):
        # BaseDMG=3600, all zones 1.0x -> total=3600
        result = calculate_sheer_damage(
            sheer_force=_SF,
            multiplier=_MV,
            crit_mode=CritMode.NO_CRIT,
        )
        assert result.base_dmg == 3600
        assert result.sheer_force == _SF
        assert result.total == 3600
        assert isinstance(result, SheerDamageResult)

    def test_dmg_bonus_applies(self):
        # BoostArea = 10000+1000=11000; 3600*11000//10000 = 3960
        result = calculate_sheer_damage(
            sheer_force=_SF,
            multiplier=_MV,
            dmg_bonuses=[1000],
            crit_mode=CritMode.NO_CRIT,
        )
        assert result.boost_mult == 11000
        assert result.total == 3600 * 11000 // 10000

    def test_sheer_dmg_bonus_applies(self):
        # SheerBoostArea = 10000+2000=12000; 3600*12000//10000 = 4320
        result = calculate_sheer_damage(
            sheer_force=_SF,
            multiplier=_MV,
            sheer_dmg_bonuses=[2000],
            crit_mode=CritMode.NO_CRIT,
        )
        assert result.sheer_boost_mult == 12000
        assert result.total == 3600 * 12000 // 10000

    def test_both_pools_multiply_independently(self):
        # BoostArea=11000, SheerBoostArea=12000 — two separate zones.
        # Correct: 3600*11000//10000*12000//10000 = 3960*12000//10000 = 4752
        # Wrong (additive pool): 3600*(10000+1000+2000)//10000 = 4680
        result = calculate_sheer_damage(
            sheer_force=_SF,
            multiplier=_MV,
            dmg_bonuses=[1000],
            sheer_dmg_bonuses=[2000],
            crit_mode=CritMode.NO_CRIT,
        )
        after_boost = 3600 * 11000 // 10000
        expected = after_boost * 12000 // 10000
        assert result.total == expected
        assert result.total != 3600 * 13000 // 10000  # additive answer is different

    def test_crit_area_applies(self):
        # CritArea(always) = 10000+5000=15000; 3600*15000//10000 = 5400
        result = calculate_sheer_damage(
            sheer_force=_SF,
            multiplier=_MV,
            crit_rate=10000,
            crit_dmg=5000,
            crit_mode=CritMode.CRIT,
        )
        assert result.crit_mult == 15000
        assert result.total == 3600 * 15000 // 10000

    def test_res_area_applies(self):
        # RESArea = clamp(0,20000, 10000-(-2000)+0+1000) = 13000
        result = calculate_sheer_damage(
            sheer_force=_SF,
            multiplier=_MV,
            enemy_res=-2000,
            res_ignore=1000,
            crit_mode=CritMode.NO_CRIT,
        )
        expected_res = min(20000, max(0, 10000 - (-2000) + 0 + 1000))
        assert result.res_mult == expected_res
        assert result.total == 3600 * expected_res // 10000

    def test_stun_area_applies(self):
        # StunArea=20000(2.0x); 3600*20000//10000 = 7200
        result = calculate_sheer_damage(
            sheer_force=_SF,
            multiplier=_MV,
            is_stunned=True,
            stun_dmg_mult=20000,
            crit_mode=CritMode.NO_CRIT,
        )
        assert result.stun_mult == 20000
        assert result.stun_base_mult == 20000
        assert result.total == 3600 * 20000 // 10000

    def test_vulnerability_area_applies(self):
        # VulnArea=11000; 3600*11000//10000 = 3960
        result = calculate_sheer_damage(
            sheer_force=_SF,
            multiplier=_MV,
            vulnerability_bonuses=[1000],
            crit_mode=CritMode.NO_CRIT,
        )
        assert result.vulnerability_mult == 11000
        assert result.total == 3600 * 11000 // 10000

    def test_def_parameters_not_in_signature(self):
        # Structural: DEF-related parameters must not exist in the function API.
        # If they cannot be passed, they cannot affect results.
        sig = inspect.signature(calculate_sheer_damage)
        def_params = {
            "attacker_level",
            "enemy_base_def",
            "enemy_level",
            "pen_ratio",
            "pen_flat",
            "def_ignore",
        }
        for param in def_params:
            assert param not in sig.parameters, (
                f"DEF parameter '{param}' must not be in calculate_sheer_damage"
            )

    def test_not_stunned_stun_base_mult_is_zero(self):
        result = calculate_sheer_damage(
            sheer_force=_SF,
            multiplier=_MV,
            is_stunned=False,
            crit_mode=CritMode.NO_CRIT,
        )
        assert result.stun_base_mult == 0
        assert result.stun_mult == 10000
