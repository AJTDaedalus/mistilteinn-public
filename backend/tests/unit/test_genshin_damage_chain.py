"""F.4-F.6 — the damage chain, term by term.

Every constant these assert is cited in `app/formula/genshin/damage.py` to gcsim at the pin
in `docs/CROSSVAL_gcsim.md`. What the tests add is the arithmetic those citations imply, and
the two places this chain deliberately differs from the oracle.
"""

from __future__ import annotations

import pytest

from app.formula.genshin.damage import (
    Amplifying,
    DamageInputError,
    Hit,
    ScalingStat,
    amplifying_multiplier,
    compute_damage,
    crit_multiplier,
    def_multiplier,
    res_multiplier,
)

# ---- The DEF term ---------------------------------------------------------

def test_equal_levels_halve_the_damage():
    """`(90+100) / ((90+100) + (90+100))` — the familiar 0.5 at level parity."""
    assert def_multiplier(90, 90) == pytest.approx(0.5)


def test_a_higher_level_enemy_takes_less():
    assert def_multiplier(90, 100) < def_multiplier(90, 90) < def_multiplier(90, 80)


def test_def_reduction_and_def_ignore_are_separate_mechanics():
    """gcsim multiplies them separately (`damage.go:82-84`); pooling them would overstate a
    build that has both — Zhongli's shred and Raiden's C2 are not the same number."""
    both = def_multiplier(90, 90, def_reduction=0.2, def_ignore=0.3)
    pooled = def_multiplier(90, 90, def_reduction=0.5)

    assert both != pytest.approx(pooled)
    assert both == pytest.approx(190 / (190 + 190 * 0.8 * 0.7))


def test_def_reduction_is_capped_at_ninety_percent():
    """gcsim `damage.go:76-78`. Uncapped, a stacked shred would divide by nearly zero."""
    assert def_multiplier(90, 90, def_reduction=5.0) == pytest.approx(
        def_multiplier(90, 90, def_reduction=0.9),
    )


def test_full_def_ignore_removes_the_term_entirely():
    assert def_multiplier(90, 90, def_ignore=1.0) == pytest.approx(1.0)


def test_a_non_positive_level_is_rejected():
    with pytest.raises(DamageInputError, match="levels must be positive"):
        def_multiplier(0, 90)


# ---- The RES term ---------------------------------------------------------

def test_ordinary_resistance_subtracts():
    """The 10% every ordinary enemy has (D.6) is a 0.9 multiplier."""
    assert res_multiplier(0.1) == pytest.approx(0.9)
    assert res_multiplier(0.0) == pytest.approx(1.0)


def test_negative_resistance_is_halved_before_it_helps():
    """Shred past zero gives diminishing returns: `1 - res/2`, not `1 - res`.

    A Deepwood 4pc on a 10% enemy lands at -20% RES, which is a 1.10 multiplier and not 1.20.
    """
    assert res_multiplier(-0.2) == pytest.approx(1.1)


def test_very_high_resistance_uses_the_diminishing_branch():
    assert res_multiplier(0.9) == pytest.approx(1 / (4 * 0.9 + 1))


def test_the_curve_is_continuous_at_exactly_three_quarters():
    """**A deliberate divergence from the oracle**, and the reason it is a test.

    gcsim writes `else if res > 0.75`, so exactly 0.75 falls through to the *negative-RES*
    branch and returns `1 - 0.75/2 = 0.625` — where both neighbouring branches give 0.25.
    A 2.5x discontinuity at a single point, with the formulas either side agreeing there.

    This chain uses `>=`. If a crossval case ever targets an enemy at exactly 75% RES, the
    disagreement with gcsim is here, on purpose, and not a formula error.
    """
    assert res_multiplier(0.75) == pytest.approx(0.25)
    assert res_multiplier(0.7499) == pytest.approx(0.2501, abs=1e-4)
    assert res_multiplier(0.7501) == pytest.approx(1 / (4 * 0.7501 + 1))


# ---- Crit -----------------------------------------------------------------

def test_expected_crit_is_rate_times_damage():
    assert crit_multiplier(0.5, 1.0) == pytest.approx(1.5)


def test_crit_rate_is_clamped_to_one_hundred_percent():
    """gcsim `damage.go:66-71`. Unclamped, the optimizer would chase crit rate past 100%."""
    assert crit_multiplier(1.3, 1.0) == pytest.approx(crit_multiplier(1.0, 1.0))


def test_negative_crit_rate_cannot_reduce_damage():
    assert crit_multiplier(-0.5, 1.0) == pytest.approx(1.0)


# ---- Amplifying reactions -------------------------------------------------

def test_the_four_amplifying_multipliers():
    """Which element *triggers* decides the multiplier — melt.go and vaporize.go."""
    assert Amplifying.MELT.multiplier == 2.0
    assert Amplifying.REVERSE_MELT.multiplier == 1.5
    assert Amplifying.VAPORIZE.multiplier == 2.0
    assert Amplifying.REVERSE_VAPORIZE.multiplier == 1.5


def test_the_em_bonus_matches_the_published_curve():
    """`2.78 * em / (1400 + em)` — gcsim `damage.go:113`."""
    at_zero = amplifying_multiplier(Amplifying.VAPORIZE, 0)
    at_two_hundred = amplifying_multiplier(Amplifying.VAPORIZE, 200)

    assert at_zero == pytest.approx(2.0)
    assert at_two_hundred == pytest.approx(2.0 * (1 + (2.78 * 200) / (1400 + 200)))


def test_the_em_bonus_has_diminishing_returns():
    """The denominator is what makes stacking EM level off; a linear bonus would not."""
    first = amplifying_multiplier(Amplifying.MELT, 200) - amplifying_multiplier(Amplifying.MELT, 0)
    second = (
        amplifying_multiplier(Amplifying.MELT, 400)
        - amplifying_multiplier(Amplifying.MELT, 200)
    )

    assert second < first


def test_a_reaction_bonus_is_additive_inside_the_bracket():
    """Crimson Witch's 4pc adds to the EM bonus; it does not multiply the reaction."""
    plain = amplifying_multiplier(Amplifying.MELT, 100)
    boosted = amplifying_multiplier(Amplifying.MELT, 100, reaction_bonus=0.15)

    assert boosted == pytest.approx(plain + 2.0 * 0.15)


def test_negative_elemental_mastery_is_rejected():
    with pytest.raises(DamageInputError, match="cannot be negative"):
        amplifying_multiplier(Amplifying.MELT, -1)


# ---- The whole chain ------------------------------------------------------

def _hit(**overrides) -> Hit:
    base = {"multiplier": 1.0, "channel": "cryo", "scope": "burst"}
    return Hit(**{**base, **overrides})


def _result(**overrides):
    inputs = {
        "scaling_value": 2000.0,
        "dmg_bonus": 0.0,
        "crit_rate": 0.0,
        "crit_dmg": 0.5,
        "elemental_mastery": 0.0,
        "character_level": 90,
        "enemy_level": 90,
        "resistance": 0.1,
    }
    hit = overrides.pop("hit", _hit())
    return compute_damage(hit, **{**inputs, **overrides})


def test_the_chain_multiplies_in_the_published_order():
    """`base x (1+bonus) x def x res` — 2000 x 1.0 x 0.5 x 0.9."""
    assert _result().non_crit == pytest.approx(2000 * 0.5 * 0.9)


def test_flat_damage_is_added_inside_the_base():
    """gcsim `damage.go:65`: flat damage joins *before* the DMG-bonus multiplier, so a
    bonus applies to it too. Adding it at the end would understate every hit that has one.
    """
    with_flat = _result(hit=_hit(flat_damage=500.0), dmg_bonus=1.0)

    assert with_flat.non_crit == pytest.approx((2000 + 500) * 2.0 * 0.5 * 0.9)


def test_a_talent_can_scale_off_something_other_than_attack():
    """`ScalingStat` is data on the hit, not a branch in the chain (A6)."""
    hp_scaling = _hit(scaling_stat=ScalingStat.HP)

    assert hp_scaling.scaling_stat is ScalingStat.HP
    assert _result(hit=hp_scaling, scaling_value=30000.0).non_crit == pytest.approx(
        30000 * 0.5 * 0.9,
    )


def test_crit_and_expected_are_both_reported():
    result = _result(crit_rate=0.5, crit_dmg=1.0)

    assert result.crit == pytest.approx(result.non_crit * 2.0)
    assert result.expected == pytest.approx(result.non_crit * 1.5)
    assert result.non_crit < result.expected < result.crit


def test_an_amplifying_hit_gets_one_extra_step():
    plain = _result()
    melted = _result(hit=_hit(amplifying=Amplifying.MELT), elemental_mastery=0)

    assert melted.non_crit == pytest.approx(plain.non_crit * 2.0)
    assert [step.name for step in melted.steps][-1] == "amplifying"


def test_the_result_explains_every_step_in_order():
    """A6: the number says which multipliers applied, in what order, and from where."""
    account = _result(
        hit=_hit(amplifying=Amplifying.VAPORIZE), dmg_bonus=0.466, elemental_mastery=200,
    ).explain()

    assert [line.split()[0] for line in account.splitlines()[1:-1]] == [
        "base", "dmg", "def", "res", "amplifying",
    ]
    assert "46.6%" in account
    assert "vaporize at 200 EM" in account


def test_a_negative_talent_multiplier_is_rejected():
    with pytest.raises(DamageInputError, match="cannot be negative"):
        _result(hit=_hit(multiplier=-1.0))
