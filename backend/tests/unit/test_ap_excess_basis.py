"""Track C4 — Anomaly Proficiency as a scaling basis, with a cap.

The audit narrowed kit-omission capability B to exactly one missing basis: AP.
`_SCALING_BAKERS` already covered base_atk, def, anomaly_mastery_excess, pen_ratio
and impact, and HP has its own `hp_scale_per_unit` path — AP was the only hole, and
it is the one blocking Jane's Passion ATK gain (+600 at her AP, ~24% of her total)
and her M1 AP→DMG% conversion.

The shape is "if <stat> exceeds T, each extra point grants R, up to a maximum of C",
which no existing baker implemented: `_bake_stat_scaled_modifier` treats `value` as
an additive offset and `_bake_am_excess_modifier` ignores it. `value` is the CAP
here, reusing the convention `hp_scale_per_unit` and `atk_scale_ratio` already
established rather than inventing a fourth reading.
"""

from dataclasses import replace as dc_replace

from app.services.modifiers import (
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.snapshot_builder import _bake_capped_excess_modifier

# Jane's Passion: AP above 120 grants +2 ATK per point, capped at +600.
_JANE_THRESHOLD = 120
_JANE_RATIO = 2.0
_JANE_CAP = 600


def _jane_passion_atk() -> Modifier:
    return Modifier(
        stat="flat_atk",
        value=_JANE_CAP,  # the cap
        source=ModifierSource.CORE_SKILL,
        source_label="Passion: ATK from Anomaly Proficiency",
        target=ModifierTarget.SELF,
        conditions=(Condition.PASSION_STATE_ACTIVE,),
        scaling_stat="anomaly_proficiency_excess",
        scaling_ratio=_JANE_RATIO,
        excess_threshold=_JANE_THRESHOLD,
    )


def _bake(ap: int) -> Modifier:
    return _bake_capped_excess_modifier(_jane_passion_atk(), ap)


def test_below_the_threshold_bakes_to_zero():
    assert _bake(120).value == 0
    assert _bake(50).value == 0


def test_scales_linearly_between_threshold_and_cap():
    # 220 AP → 100 excess × 2 = 200 ATK, well under the 600 cap.
    assert _bake(220).value == 200
    assert _bake(200).value == 160


def test_caps_and_does_not_exceed():
    """The cap is the whole reason this baker exists — uncapped, AP 413 gives 586,
    but a high-AP build must not run away past the kit's stated maximum."""
    assert _bake(420).value == _JANE_CAP  # 300 excess × 2 = 600, exactly the cap
    assert _bake(1000).value == _JANE_CAP  # 1760 uncapped, clamped


def test_janes_real_ap_lands_just_under_the_cap():
    """Jane's live build resolves AP 413 → 293 excess × 2 = 586. Pins the headline
    number the omission was costing: 586 flat ATK that currently bakes to zero."""
    assert _bake(413).value == 586


def test_baking_strips_the_scaling_fields_and_the_gate():
    baked = _bake(413)

    assert baked.scaling_stat is None
    assert baked.scaling_ratio == 0.0
    # Threshold is encoded in the arithmetic, so the condition must not re-gate it.
    assert baked.conditions == (Condition.ALWAYS,)


def test_a_zero_cap_is_treated_as_unauthored_rather_than_zeroing_the_buff():
    """A cap of 0 would silently delete a real buff. L0 should report the incoherent
    scale field; the engine must not quietly bake it to nothing."""
    uncapped = dc_replace(_jane_passion_atk(), value=0)

    assert _bake_capped_excess_modifier(uncapped, 413).value == 586


def test_a_zero_ratio_is_left_untouched_for_l0_to_report():
    no_ratio = dc_replace(_jane_passion_atk(), scaling_ratio=0.0)
    out = _bake_capped_excess_modifier(no_ratio, 413)

    assert out.scaling_stat == "anomaly_proficiency_excess"
    assert out.value == _JANE_CAP


def test_m1_dmg_percent_shape_also_works():
    """Jane M1: +0.1% DMG per AP point, max 30%. Same baker, bp units — 10 bp per
    point, cap 3000 bp. At AP 413 the uncapped 4130 clamps to the stated 30%."""
    m1 = Modifier(
        stat="dmg_bonus",
        value=3000,
        source=ModifierSource.MINDSCAPE,
        source_label="M1: DMG from Anomaly Proficiency",
        target=ModifierTarget.SELF,
        conditions=(Condition.PASSION_STATE_ACTIVE,),
        scaling_stat="anomaly_proficiency_excess",
        scaling_ratio=10.0,
        excess_threshold=0,
        min_mindscape=1,
    )

    assert _bake_capped_excess_modifier(m1, 413).value == 3000
    assert _bake_capped_excess_modifier(m1, 100).value == 1000
