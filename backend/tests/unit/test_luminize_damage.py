"""Task 13 — calculate_luminize_damage (DESIGN_remielle.md §7.2, §2 OQ-1,
§2.1, §9.1 test 4).
"""

import json
from pathlib import Path

import pytest

from app.services.damage_calculator import base_damage, calculate_luminize_damage

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REMIELLE_KIT = BACKEND_ROOT / "app" / "data" / "modifiers" / "agents" / "remielle.json"

_BASE_KWARGS = {
    "voidflare_atk": 1000,
    "voidflare_dmg_bonus_bp": 0,
    "voidflare_pen_ratio_bp": 0,
    "voidflare_pen_flat": 0,
    "voidflare_anomaly_proficiency": 100,
    "luminize_mult_bp": 20_000,  # 200%
    "attacker_level": 60,
    "remielle_anomaly_proficiency": 0,
    # Synthetic round number for the formula-shape tests below -- deliberately
    # NOT the shipped coefficient. The shipped value is pinned absolutely in
    # TestShippedCoefficientAbsolutePin.
    "ap_bonus_per_point_bp": 10,
    "remielle_anomaly_dmg_bonus": 0,
    "enemy_base_def": 0,
    "enemy_level": 60,
}


class TestEffectiveMultiplierIsMultiplicative:
    def test_exact_formula(self):
        result = calculate_luminize_damage(
            **{**_BASE_KWARGS, "remielle_anomaly_proficiency": 200, "ap_bonus_per_point_bp": 10}
        )
        # effective_mult_bp = 20000 * (10000 + 10*200) // 10000 = 24000 (bp)
        expected_base = base_damage(1000, 24000)
        assert result.base_dmg == expected_base

    def test_zero_remielle_ap_is_neutral(self):
        result = calculate_luminize_damage(**{**_BASE_KWARGS, "remielle_anomaly_proficiency": 0})
        assert result.base_dmg == base_damage(1000, 20_000)


class TestTwoAPTermsAreIndependent:
    """DESIGN §2.1's naming trap: `voidflare_anomaly_proficiency` (the stored
    snapshot, AnomalyProfArea only) and `remielle_anomaly_proficiency`
    (Remielle's own live AP, multiplier-bonus term only) must never be
    conflated -- doubling one must leave the other's zone untouched."""

    def test_doubling_remielle_ap_only_changes_base_dmg_not_anom_prof_zone(self):
        low = calculate_luminize_damage(**{**_BASE_KWARGS, "remielle_anomaly_proficiency": 100})
        high = calculate_luminize_damage(**{**_BASE_KWARGS, "remielle_anomaly_proficiency": 200})

        assert high.base_dmg > low.base_dmg
        assert high.anomaly_prof_mult == low.anomaly_prof_mult

    def test_doubling_voidflare_ap_only_changes_anom_prof_zone_not_base_dmg(self):
        low = calculate_luminize_damage(**{**_BASE_KWARGS, "voidflare_anomaly_proficiency": 100})
        high = calculate_luminize_damage(**{**_BASE_KWARGS, "voidflare_anomaly_proficiency": 200})

        assert high.anomaly_prof_mult > low.anomaly_prof_mult
        assert high.base_dmg == low.base_dmg


class TestStoredValuesUsedLiveEnemyDebuffsApply:
    def test_stored_dmg_bonus_scales_boost_zone(self):
        plain = calculate_luminize_damage(**_BASE_KWARGS)
        buffed = calculate_luminize_damage(**{**_BASE_KWARGS, "voidflare_dmg_bonus_bp": 5000})
        assert buffed.boost_mult == plain.boost_mult + 5000
        assert buffed.total > plain.total

    def test_stored_pen_scales_def_zone(self):
        plain = calculate_luminize_damage(**{**_BASE_KWARGS, "enemy_base_def": 1000})
        pen = calculate_luminize_damage(
            **{**_BASE_KWARGS, "enemy_base_def": 1000, "voidflare_pen_ratio_bp": 5000}
        )
        assert pen.def_mult > plain.def_mult
        assert pen.total > plain.total

    def test_live_enemy_res_reduces_damage(self):
        no_res = calculate_luminize_damage(**{**_BASE_KWARGS, "enemy_res": 0})
        with_res = calculate_luminize_damage(**{**_BASE_KWARGS, "enemy_res": 3000})
        assert with_res.total < no_res.total

    def test_live_stun_state_applies(self):
        unstunned = calculate_luminize_damage(**{**_BASE_KWARGS, "is_stunned": False})
        stunned = calculate_luminize_damage(
            **{**_BASE_KWARGS, "is_stunned": True, "stun_dmg_mult": 20000}
        )
        assert stunned.total > unstunned.total


class TestRemiellesOwnAnomalyBoostAppliesPostStorage:
    def test_remielle_anomaly_dmg_bonus_scales_final_zone(self):
        plain = calculate_luminize_damage(**_BASE_KWARGS)
        buffed = calculate_luminize_damage(
            **{**_BASE_KWARGS, "remielle_anomaly_dmg_bonus": 3000}
        )
        assert buffed.anomaly_boost_mult == plain.anomaly_boost_mult + 3000
        assert buffed.total > plain.total


class TestLuminizeIsStructurallyImmuneToPerAnomalyTypeEffects:
    """DESIGN §9.1 test 4: Assault CRIT DMG / Assault DMG Bonus (Jane-style
    per-anomaly-type effects) must never touch Luminize. There is no
    parameter for either -- passing one is a TypeError, not a silent no-op,
    which is the strongest possible guarantee this function can give."""

    def test_no_assault_crit_dmg_parameter(self):
        with pytest.raises(TypeError):
            calculate_luminize_damage(**_BASE_KWARGS, assault_crit_dmg_bp=5000)

    def test_no_assault_dmg_bonus_parameter(self):
        with pytest.raises(TypeError):
            calculate_luminize_damage(**_BASE_KWARGS, assault_dmg_bonus=5000)


class TestLuminizeIsAlwaysExactlyOneInstance:
    def test_procs_is_one_and_total_equals_per_proc(self):
        result = calculate_luminize_damage(**_BASE_KWARGS)
        assert result.procs == 1
        assert result.total == result.per_proc

    def test_default_refringe_mult_is_neutral(self):
        """Luminize is a brand-new instance, never itself Refringed (only
        the stored anomaly that fed the Voidflare could have been)."""
        result = calculate_luminize_damage(**_BASE_KWARGS)
        assert result.refringe_mult == 10000


class TestShippedCoefficientAbsolutePin:
    """Absolute integer pin on the *shipped* Luminize AP coefficient.

    Hardening Task 1 / audit finding S1-B: `luminize_ap_bonus_bp` shipped as
    10 (the DB's core-level-1 value) when the D-KV4 max-level convention makes
    core level 7 -- 0.2%/AP, i.e. 20 -- the authoring point, and the "matching
    the guide's stated '0.1%/AP'" note attributing it to the guide was
    fabricated (references/remielle_guide.txt states no per-AP number at all).

    Nothing in the L0-L2 harness can see a wrong-but-well-formed integer here,
    so this test carries the assertion that would have caught it: the shipped
    coefficient composed with a shipped Luminize multiplier, through the real
    calculator, against a hand-derived expected value.

    Mutations this catches: `luminize_ap_bonus_bp` reverting to the level-1
    value 10 (or any other level on the curve); the calculator switching the
    AP-bonus term from multiplicative to additive; a bp-vs-fraction slip on
    either factor.
    """

    # Guide line 167: 448 AP is Remielle's reference endgame build.
    REFERENCE_AP = 448

    def _shipped(self) -> dict:
        return json.loads(REMIELLE_KIT.read_text())["lumiflux"]

    def test_effective_multiplier_at_the_reference_build(self):
        block = self._shipped()
        ap_bonus_bp = block["luminize_ap_bonus_bp"]
        base_mult_bp = block["luminize_multipliers"]["Basic Attack: Fleeting Grace"]

        # Derivation, by hand, from the shipped inputs. The AP bonus is 20 bp
        # per AP point -- db(core_skills, level 7), i.e. 0.2%/AP. The base
        # multiplier is 32000 bp -- Basic Attack: Fleeting Grace, i.e. 320%.
        # At 448 AP the bonus factor is 10000 + 20*448 = 18960 bp, so the
        # effective multiplier is 32000 * 18960 // 10000, which is
        # 606_720_000 // 10000 = 60_672 bp, i.e. 606.72%.
        assert ap_bonus_bp == 20
        assert base_mult_bp == 32_000
        expected_effective_bp = 60_672

        result = calculate_luminize_damage(
            **{
                **_BASE_KWARGS,
                "luminize_mult_bp": base_mult_bp,
                "remielle_anomaly_proficiency": self.REFERENCE_AP,
                "ap_bonus_per_point_bp": ap_bonus_bp,
            }
        )
        assert result.base_dmg == base_damage(1000, expected_effective_bp)

    def test_the_level_one_value_would_not_produce_that_multiplier(self):
        """Guards the pin itself: the pre-fix coefficient lands elsewhere.

        With the level-1 bonus of 10 bp/AP the factor is 10000 + 10*448 =
        14480 bp, giving 32000 * 14480 // 10000 = 46_336 bp -- a different
        number from the 60_672 pinned above, so the pin above is load-bearing.
        """
        result = calculate_luminize_damage(
            **{
                **_BASE_KWARGS,
                "luminize_mult_bp": 32_000,
                "remielle_anomaly_proficiency": self.REFERENCE_AP,
                "ap_bonus_per_point_bp": 10,
            }
        )
        assert result.base_dmg == base_damage(1000, 46_336)


class TestLuminizeScopedResIgnore:
    """Hardening Task 19 — M1 (Naive Oath), the bucket that makes it encodable.

    M1 reads, DB-verbatim: "When Remielle triggers Luminize to deal DMG, she
    ignores 50% of the target's All-Attribute RES." That is a res-ignore scoped
    to a *single damage source*, and the schema had nowhere to put it: generic
    `res_ignore` is read by every damage path she has, and `scopes[]` gates by
    move category, which Luminize is not — it is a separate emission fired
    after a trigger move.

    Shipping it as a plain always/all `res_ignore` row was audit finding S1-A:
    RESArea 1.0 -> 1.5 against a 0-RES enemy for her Ultimate, Chain, EX and
    Phase Flow ticks too, ~1.5x on damage the clause never touches. Task 4
    removed the row; this bucket is what lets Task 19 put it back honestly.
    """

    def test_luminize_res_ignore_raises_res_area(self):
        plain = calculate_luminize_damage(**_BASE_KWARGS)
        ignored = calculate_luminize_damage(**{**_BASE_KWARGS, "luminize_res_ignore": 5000})
        # RESArea = 1 - enemy_res + res_reduction + res_ignore, so +50% on a
        # 0-RES enemy is exactly 1.0 -> 1.5.
        assert ignored.res_mult == plain.res_mult + 5000
        assert ignored.total > plain.total

    def test_it_is_additive_with_the_generic_bucket_not_a_replacement(self):
        """A team debuff's `res_ignore` and her own M1 both apply. Luminize is
        still ordinary damage as far as everyone else's debuffs are concerned;
        the new bucket only adds a term nobody else can see."""
        both = calculate_luminize_damage(
            **{**_BASE_KWARGS, "res_ignore": 1000, "luminize_res_ignore": 5000}
        )
        generic_only = calculate_luminize_damage(**{**_BASE_KWARGS, "res_ignore": 1000})
        assert both.res_mult == generic_only.res_mult + 5000

    def test_it_shares_the_res_area_clamp(self):
        """RESArea is clamped to [0, 2.0] (`res_multiplier`). A Luminize-scoped
        term must not become a way around that ceiling."""
        capped = calculate_luminize_damage(**{**_BASE_KWARGS, "luminize_res_ignore": 50_000})
        assert capped.res_mult == 20000

    def test_default_is_inert(self):
        """Every other agent, and Remielle below M1, must be byte-identical."""
        assert (
            calculate_luminize_damage(**{**_BASE_KWARGS, "luminize_res_ignore": 0}).total
            == calculate_luminize_damage(**_BASE_KWARGS).total
        )
