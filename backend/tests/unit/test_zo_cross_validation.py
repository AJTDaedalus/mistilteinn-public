"""Cross-validation of our damage calculator against zenless-optimizer (ZO).

Source: zenless-optimizer formula.test.ts — the canonical ZO damage test case
for Anby, sourced from /tmp/genshin-optimizer/libs/zzz/formula/src/formula.test.ts.

Setup (from the ZO test):
    Character:  Anby, Level 60, Promotion 5, Core 6, Mindscape 0, all skills 0
    W-Engine:   VortexRevolver, Level 60, Modification 5, Phase 1
    Buffs:      +25 initial flat ATK, +100 combat flat ATK, +8% combat ATK%,
                +70% crit rate, +104% crit DMG, +40% electric DMG,
                +5% PEN ratio, +90 flat PEN, +2% RES ignore, +338 anomaly prof
    Enemy:      DEF=635 (raw value), 10% electric RES, 15% RES reduction,
                10% dmg-taken-increase, 15% dmg-taken-reduction,
                stun_mult=1.5, unstun_mult=1.0

ZO expected values:
    base_atk = 1134.797, final_atk = 1597.697

    not_stunned, avg_crit:   standard=4464.062    anomaly=14880.206
    not_stunned, crit:       standard=5261.586    anomaly=14880.206
    not_stunned, no_crit:    standard=2071.490    anomaly=14880.206
    stunned,     avg_crit:   standard=6696.093    anomaly=22320.309
    stunned,     crit:       standard=7892.378    anomaly=22320.309
    stunned,     no_crit:    standard=3107.236    anomaly=22320.309

Notes on zone mapping:
  - ZO's `buff_mult_` zone (Timeweaver-style) is 1.0 here — we don't model it
    and it has no effect on this test.
  - ZO's `dmg_taken_mult_` = 1 + dmgInc_ - dmgRed_. We model via a single
    `vulnerability_bonuses` list: [+10%, -15%] = -5% net.
  - ZO passes enemy DEF as a raw value (635). We compute enemy_def from
    enemy_base_def * level_factor(enemy_level) / 50, so we pass
    enemy_base_def=40 which yields 40*794/50 = 635.2 (≈635).
  - Integer basis-point arithmetic causes small rounding. Tolerance: 1%.
"""

from __future__ import annotations

import pytest

from app.services.damage_calculator import (
    AnomalyType,
    CritMode,
    calculate_anomaly_damage,
    calculate_standard_damage,
)

# ZO base/final ATK values (floats). We floor to integers for our calculator.
ZO_BASE_ATK = 1134.797
ZO_FINAL_ATK = 1597.697

# Computed with our two-stage floor:
#   initial = floor(1134.797 * 1.2 + 25)      = 1386
#   final   = floor(1386 * 1.08 + 100)        = 1596
# ZO uses 1597.697 (float); we use 1596 (integer). The test tolerance absorbs this.
OUR_FINAL_ATK = 1596

# ZO enemy DEF=635 via enemy_base_def=40, enemy_level=60
# Our calc: 40 * level_factor(60) / 50 = 40 * 794 / 50 = 635.2
ENEMY_BASE_DEF = 40
ENEMY_LEVEL = 60
ATTACKER_LEVEL = 60


def _standard_kwargs(crit_mode: CritMode, is_stunned: bool) -> dict:
    """Inputs for `calculate_standard_damage` matching ZO's Anby test case."""
    return {
        "scaling_stat": OUR_FINAL_ATK,
        "multiplier": 15000,  # standardDmgInst: 1.5 * final.atk
        "dmg_bonuses": [4000],  # +40% electric DMG
        "crit_rate": 7500,  # base 5% + 70% = 75%
        "crit_dmg": 15400,  # base 50% + 104% = 154%
        "crit_mode": crit_mode,
        "attacker_level": ATTACKER_LEVEL,
        "enemy_base_def": ENEMY_BASE_DEF,
        "enemy_level": ENEMY_LEVEL,
        "pen_ratio": 500,  # +5% PEN
        "pen_flat": 90,  # +90 flat PEN
        "enemy_res": 1000,  # 10% electric RES
        "res_reduction": 1500,  # +15% RES reduction
        "res_ignore": 200,  # +2% RES ignore
        "vulnerability_bonuses": [1000, -1500],  # +10% dmgInc, -15% dmgRed
        "is_stunned": is_stunned,
        "stun_dmg_mult": 15000,  # stun_ = 1.5
    }


def _anomaly_kwargs(is_stunned: bool) -> dict:
    """Inputs for `calculate_anomaly_damage` matching ZO's Anby test case.

    ZO's `anomalyDmgInst` uses the electric anomaly multiplier (1.25x ATK) which
    matches our SHOCK.base_mult (12500 bp = 125%). Procs cap at 10 for shock
    (F-02). We compare per-proc against ZO's single-instance anomalyDmgInst value.
    """
    return {
        "anomaly_type": AnomalyType.SHOCK,
        "atk": OUR_FINAL_ATK,
        "anomaly_proficiency": 93 + 338,  # Anby base 93 + 338 buff
        "attacker_level": ATTACKER_LEVEL,
        "dmg_bonuses": [4000],  # +40% electric DMG
        "anomaly_dmg_bonus": 0,
        "enemy_base_def": ENEMY_BASE_DEF,
        "enemy_level": ENEMY_LEVEL,
        "pen_ratio": 500,
        "pen_flat": 90,
        "enemy_res": 1000,
        "res_reduction": 1500,
        "res_ignore": 200,
        "vulnerability_bonuses": [1000, -1500],
        "is_stunned": is_stunned,
        "stun_dmg_mult": 15000,
    }


def _within(actual: int, expected: float, *, tol_pct: float = 1.0) -> bool:
    """Integer-basis-point rounding introduces ~0.1-0.2% drift from ZO floats."""
    return abs(actual - expected) / expected <= tol_pct / 100


class TestZOStandardDamage:
    """Cross-validate standard damage against ZO's Anby test case."""

    @pytest.mark.parametrize(
        ("crit_mode", "is_stunned", "expected"),
        [
            (CritMode.EXPECTED, False, 4464.062),
            (CritMode.CRIT, False, 5261.586),
            (CritMode.NO_CRIT, False, 2071.490),
            (CritMode.EXPECTED, True, 6696.093),
            (CritMode.CRIT, True, 7892.378),
            (CritMode.NO_CRIT, True, 3107.236),
        ],
    )
    def test_matches_zo(self, crit_mode: CritMode, is_stunned: bool, expected: float):
        result = calculate_standard_damage(**_standard_kwargs(crit_mode, is_stunned))
        assert _within(result.total, expected), (
            f"standard dmg mismatch: ours={result.total}, ZO={expected}, "
            f"diff={abs(result.total - expected) / expected * 100:.2f}%"
        )


class TestZOAnomalyDamage:
    """Cross-validate anomaly per-proc damage against ZO's Anby test case."""

    @pytest.mark.parametrize(
        ("is_stunned", "expected"),
        [
            (False, 14880.206),
            (True, 22320.309),
        ],
    )
    def test_matches_zo(self, is_stunned: bool, expected: float):
        result = calculate_anomaly_damage(**_anomaly_kwargs(is_stunned))
        assert _within(result.per_proc, expected), (
            f"anomaly per-proc mismatch: ours={result.per_proc}, ZO={expected}, "
            f"diff={abs(result.per_proc - expected) / expected * 100:.2f}%"
        )


class TestZOStatDerivation:
    """Sanity-check that our two-stage ATK formula agrees with ZO's.

    This doesn't exercise the damage calculator — it just documents the
    stat pipeline so future changes don't silently drift.
    """

    def test_two_stage_atk(self):
        """ZO formula: initial = base*(1+initial_pct)+flat; final = initial*(1+combat_pct)+flat."""
        base_atk = 1134.797  # Anby L60 P5 Core6 + VortexRevolver L60 M5
        initial_atk_pct = 0.20  # 0.08 VR secondary * (1 + 0.3*5)
        combat_atk_pct = 0.08
        flat_initial = 25
        flat_combat = 100

        initial = base_atk * (1 + initial_atk_pct) + flat_initial
        final = initial * (1 + combat_atk_pct) + flat_combat

        # ZO expects 1597.696912
        assert abs(final - 1597.697) < 0.001
