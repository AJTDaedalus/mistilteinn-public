"""F-26: one canonical ELEMENTS constant; every element-keyed table derives
from it (including wind, which several tables predated).
"""

from __future__ import annotations

from app.formula.zzz import stats as stats_module
from app.formula.zzz.tags import ELEMENTS
from app.services import damage_dag_service, disc_optimizer
from app.services.buff_resolver import resolve_modifiers
from app.services.modifiers import (
    ActiveConditions,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


class TestCanonicalElementsConstant:
    def test_includes_wind(self) -> None:
        assert ELEMENTS == ("physical", "fire", "ice", "electric", "ether", "wind")

    def test_stats_dag_elements_match_canonical(self) -> None:
        assert stats_module._ELEMENTS == ELEMENTS

    def test_disc_dag_elements_match_canonical(self) -> None:
        assert damage_dag_service._DISC_ELEMENTS == ELEMENTS

    def test_optimizer_element_dmg_fields_match_canonical(self) -> None:
        expected = {f"{element}_dmg" for element in ELEMENTS}
        assert expected == disc_optimizer._ELEMENT_DMG_FIELDS


class TestWindAnomalyBuildupRouting:
    def test_wind_anomaly_buildup_survives_resolution(self) -> None:
        mod = Modifier(
            stat="wind_anomaly_buildup",
            value=3000,
            source=ModifierSource.CORE_SKILL,
            source_label="test",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
        )
        result = resolve_modifiers([mod], ActiveConditions())

        assert result.combat_bonuses["wind_anomaly_buildup"] == 3000
