"""Unit tests for ComboStepInput new fields — T-B1."""

from app.schemas.build import ComboStepInput


def test_defaults_for_legacy_step() -> None:
    step = ComboStepInput(label="BA1", attack_id="att-1")
    assert step.variant_label is None
    assert step.single_tap is False
    assert step.cycle_position is None


def test_new_fields_round_trip() -> None:
    step = ComboStepInput(
        label="Swiftedge",
        move_name="Basic Attack: Swiftedge",
        single_tap=True,
        cycle_position=2,
        variant_label=None,
    )
    assert step.single_tap is True
    assert step.cycle_position == 2
    assert step.variant_label is None


def test_variant_label_preserved() -> None:
    step = ComboStepInput(
        label="Soaring Light (6)",
        move_name="EX Special Attack: Enlightened Mind - Soaring Light",
        variant_label="6 Qingming Swords",
    )
    assert step.variant_label == "6 Qingming Swords"
    assert step.single_tap is False
