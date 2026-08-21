"""F-28: `stun_area_override` must resolve as a max across sources, not a sum.

The `ResolvedBuffs.stun_area_override` property already computed a max over
`combat_attributions` rather than reading the summed `combat_bonuses` dict —
this test is the regression guard the batch was missing (no test previously
proved the max-not-sum semantics the inline comment promises).
"""

from __future__ import annotations

from app.services.buff_resolver import resolve_modifiers
from app.services.modifiers import (
    ActiveConditions,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


def _override_mod(value: int, source_label: str) -> Modifier:
    return Modifier(
        stat="stun_area_override",
        value=value,
        source=ModifierSource.CORE_SKILL,
        source_label=source_label,
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
    )


class TestStunAreaOverrideMax:
    def test_two_sources_resolve_to_max_not_sum(self) -> None:
        mods = [_override_mod(18000, "Source A"), _override_mod(20000, "Source B")]
        result = resolve_modifiers(mods, ActiveConditions())

        assert result.stun_area_override == 20000

    def test_single_source(self) -> None:
        result = resolve_modifiers([_override_mod(18000, "Source A")], ActiveConditions())
        assert result.stun_area_override == 18000

    def test_no_source_defaults_to_zero(self) -> None:
        result = resolve_modifiers([], ActiveConditions())
        assert result.stun_area_override == 0
