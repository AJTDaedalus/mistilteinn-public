"""An off-field step must not receive ACTIVE-target buffs (B3).

`_gated_out` admits `ModifierTarget.ACTIVE` rows unconditionally, which is right
for almost every damage instance — they happen on-field. A Phase Flow tick does
not: the simulator resolves it under the OFF-FIELD merge, but it is scored as an
ordinary `ComboStep`, so an ACTIVE-only buff the sim correctly excluded reached
the scored tick. A bounded over-credit, documented in place since P-F2 and now
closed.
"""

from __future__ import annotations

import pytest

from app.services.buff_resolver import resolve_modifiers
from app.services.combo_types import ComboStep
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


def _row(target: ModifierTarget, value: int = 3000):
    return Modifier(
        stat="dmg_bonus",
        value=value,
        source=ModifierSource.CORE_SKILL,
        target=target,
        conditions=[Condition.ALWAYS],
    )


def _total(rows, *, include_active: bool):
    return resolve_modifiers(
        rows,
        ActiveConditions(active={Condition.ALWAYS}),
        attack_scope=AttackScope.ALL,
        target_filter=ModifierTarget.SELF,
        include_active=include_active,
    ).total_dmg_bonus


class TestActiveRowsAreDroppedOffField:
    def test_on_field_keeps_active_rows(self) -> None:
        """The default, and every caller but the Phase Flow tick."""
        assert _total([_row(ModifierTarget.ACTIVE)], include_active=True) == 3000

    def test_off_field_drops_them(self) -> None:
        assert _total([_row(ModifierTarget.ACTIVE)], include_active=False) == 0

    @pytest.mark.parametrize("target", [ModifierTarget.SELF, ModifierTarget.TEAM])
    def test_self_and_team_rows_survive_off_field(self, target: ModifierTarget) -> None:
        """Only the ACTIVE tier is on-field-gated.

        A team buff still applies to an off-field agent — dropping those too
        would trade one bounded error for a larger one in the other direction.
        """
        assert _total([_row(target)], include_active=False) == 3000

    def test_a_mixed_roster_drops_only_the_active_row(self) -> None:
        rows = [_row(ModifierTarget.SELF, 1000), _row(ModifierTarget.ACTIVE, 2000)]
        assert _total(rows, include_active=True) == 3000
        assert _total(rows, include_active=False) == 1000


class TestTheStepCarriesTheFlag:
    def test_combo_step_defaults_to_on_field(self) -> None:
        """Every pre-existing construction site must be unchanged."""
        step = ComboStep(
            label="Hit",
            attack_id="hit",
            attack_name="Hit",
            scope=AttackScope.ALL,
            multiplier=1000,
        )
        assert step.off_field is False

    def test_the_optimizer_signature_separates_on_and_off_field(self) -> None:
        """Two ticks identical but for `off_field` must not share a context.

        The signature keys on `(scope, off_field)`; without the flag in it, the
        first-built context would be reused for both and one of them scored
        under the wrong modifier set.
        """
        on = ComboStep(
            label="x", attack_id="x", attack_name="x", scope=AttackScope.SPECIAL, multiplier=1
        )
        off = ComboStep(
            label="x",
            attack_id="x",
            attack_name="x",
            scope=AttackScope.SPECIAL,
            multiplier=1,
            off_field=True,
        )
        assert (on.scope, on.off_field) != (off.scope, off.off_field)
