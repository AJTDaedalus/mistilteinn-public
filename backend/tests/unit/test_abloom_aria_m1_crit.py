"""Pin tests for Aria M1 Abloom crit mechanic.

Canonical text (M1 "Energetic Sound Waves"):
  "when Aria triggers Abloom, it has a chance to trigger a critical hit.
  The base CRIT Rate is 25%, and CRIT DMG is 25%.
  If initial Anomaly Mastery exceeds 100, each additional point of initial
  Anomaly Mastery increases this effect's CRIT Rate by 0.5%."

Design: DESIGN_abloom_c8.md §Feature A, LOG_abloom_c8.md §OQ-A1.

OQ-A1 resolution: initial_AM == ctx.stats.anomaly_mastery (live, same as C5 base path).
Snapshot risk: if confirmed to be application-time AM, both MV and crit paths need updating.

CritArea formula (expected value):
  eff_cr  = min(10000, crit_rate_bp + max(0, initial_AM - 100) * 50)
  crit_mult = 10000 + eff_cr * crit_dmg_bp // 10000  (basis points)
  result.total = base_abloom * crit_mult // 10000
"""

import pytest

from app.services.damage_calculator import AbloomResult, calculate_abloom_damage


class TestCalculateAbloomDamageCritArea:
    """Unit tests for the crit_rate_bp / crit_dmg_bp args added in A2."""

    def _call(
        self,
        *,
        abloom_mv_bp: int = 7000,
        original_anomaly_dmg: int = 10_000,
        ap: int = 0,
        abloom_ap_scaled: bool = False,
        crit_rate_bp: int = 0,
        crit_dmg_bp: int = 0,
    ) -> AbloomResult:
        return calculate_abloom_damage(
            abloom_mv_bp=abloom_mv_bp,
            original_anomaly_dmg=original_anomaly_dmg,
            ap=ap,
            abloom_ap_scaled=abloom_ap_scaled,
            crit_rate_bp=crit_rate_bp,
            crit_dmg_bp=crit_dmg_bp,
        )

    # --- M0 / default: no crit args → CritArea = 1, result byte-identical to current ---

    def test_no_crit_args_unchanged(self):
        """Default (no crit args) must be byte-identical to the pre-A2 formula.

        Flat MV=70%, original=10000 → base=7000. CritArea=1 → total=7000.
        """
        result = self._call()
        assert result.total == 7000

    def test_zero_crit_rate_no_crit(self):
        """crit_rate_bp=0 → CritArea=1 regardless of crit_dmg_bp."""
        result = self._call(crit_rate_bp=0, crit_dmg_bp=5000)
        assert result.total == 7000

    # --- Aria M1 base values: crit_rate=2500, crit_dmg=2500, AM ≤ 100 ---

    def test_aria_m1_am_le100(self):
        """AM ≤ 100 → eff_cr stays at base 25%, CritArea = 1 + 0.25×0.25 = 1.0625.

        Flat MV=70%, original=10000 → base=7000.
        crit_mult = 10000 + 2500*2500//10000 = 10000 + 625 = 10625 bp
        total = 7000 * 10625 // 10000 = 7437
        """
        result = self._call(crit_rate_bp=2500, crit_dmg_bp=2500)
        assert result.total == 7437

    def test_aria_m1_crit_mult_attribute(self):
        """AbloomResult.crit_mult must equal 10625 for base Aria M1 (AM ≤ 100)."""
        result = self._call(crit_rate_bp=2500, crit_dmg_bp=2500)
        assert result.crit_mult == 10625

    # --- AM = 200: eff_cr = 2500 + 100*50 = 7500; CritArea = 1 + 0.75×0.25 = 1.1875 ---
    # Note: AM scaling is applied at the trigger site (anomaly_simulator.py), not here.
    # These tests exercise the formula with the already-scaled eff_cr passed in.

    def test_aria_m1_am200_eff_cr_7500(self):
        """AM=200 → eff_cr=7500 at trigger site; CritArea = 1 + 0.75×0.25 = 1.1875.

        crit_mult = 10000 + 7500*2500//10000 = 10000 + 1875 = 11875 bp
        total = 7000 * 11875 // 10000 = 8312
        """
        result = self._call(crit_rate_bp=7500, crit_dmg_bp=2500)
        assert result.total == 8312
        assert result.crit_mult == 11875

    # --- CR clamp: any rate above 10000 treated as 10000 ---

    def test_crit_rate_clamped_at_100pct(self):
        """crit_rate_bp clamped to 10000 (100%). CritArea = 1 + 1.0×0.25 = 1.25.

        crit_mult = 10000 + 10000*2500//10000 = 10000 + 2500 = 12500 bp
        total = 7000 * 12500 // 10000 = 8750
        """
        result = self._call(crit_rate_bp=15000, crit_dmg_bp=2500)
        assert result.total == 8750
        assert result.crit_mult == 12500

    def test_crit_rate_exactly_10000(self):
        """crit_rate_bp=10000 (no overflow). Same result as the clamp case."""
        result = self._call(crit_rate_bp=10000, crit_dmg_bp=2500)
        assert result.total == 8750


class TestAbloomCritScalingAtTriggerSite:
    """Verify the AM-scaling formula that anomaly_simulator.py must apply before passing
    crit_rate_bp to calculate_abloom_damage (per DESIGN_abloom_c8.md §Feature A step 4).

    Formula: eff_cr = min(10000, abloom_crit_rate + max(0, initial_AM - 100) * 50)
    """

    @pytest.mark.parametrize(
        ("initial_am", "base_crit_rate", "expected_eff_cr"),
        [
            (0, 2500, 2500),  # AM below threshold — no scaling
            (100, 2500, 2500),  # exactly at threshold — no scaling
            (101, 2500, 2550),  # one point above — +50 bp
            (200, 2500, 7500),  # AM=200: +100*50=5000 bp added → 7500
            (260, 2500, 10000),  # AM=260: +160*50=8000 → 10500 → clamped to 10000
            (300, 2500, 10000),  # AM=300: would be 12500 → clamped
        ],
    )
    def test_am_scaling_formula(self, initial_am: int, base_crit_rate: int, expected_eff_cr: int):
        """Validate the trigger-site eff_cr formula independently."""
        eff_cr = min(10000, base_crit_rate + max(0, initial_am - 100) * 50)
        assert eff_cr == expected_eff_cr

    def test_am_scaling_matches_m1_base(self):
        """AM=100 with base M1 rate 2500 → no bonus, eff_cr stays 2500."""
        eff_cr = min(10000, 2500 + max(0, 100 - 100) * 50)
        assert eff_cr == 2500
