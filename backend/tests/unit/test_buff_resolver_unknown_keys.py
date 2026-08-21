"""F-27: unrecognized modifier `stat` keys must be surfaced, not dropped."""

from __future__ import annotations

from app.services.buff_resolver import resolve_modifiers
from app.services.modifiers import (
    ActiveConditions,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


def _mod(stat: str, value: int = 2500) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.CORE_SKILL,
        source_label="test",
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
    )


class TestUnknownModifierKeys:
    def test_unknown_key_does_not_raise(self) -> None:
        result = resolve_modifiers([_mod("crit_dmg_bonus")], ActiveConditions())
        # No exception — the buff is dropped from the calc path but must
        # still be attributed (see below), not silently swallowed.
        assert result is not None

    def test_unknown_key_reaches_attribution_as_unmodeled(self) -> None:
        result = resolve_modifiers([_mod("crit_dmg_bonus")], ActiveConditions())

        rows = result.stat_attributions.get("crit_dmg_bonus")
        assert rows is not None
        assert len(rows) == 1
        assert rows[0].is_modeled is False

    def test_unknown_key_does_not_pollute_recognized_buckets(self) -> None:
        result = resolve_modifiers([_mod("crit_dmg_bonus")], ActiveConditions())

        assert "crit_dmg_bonus" not in result.stat_bonuses
        assert "crit_dmg_bonus" not in result.combat_bonuses
        assert result.dmg_bonuses == []

    def test_known_key_still_resolves_normally(self) -> None:
        result = resolve_modifiers([_mod("atk_pct", value=1000)], ActiveConditions())

        assert result.stat_bonuses["atk_pct"] == 1000
        assert result.stat_attributions["atk_pct"][0].is_modeled is True
