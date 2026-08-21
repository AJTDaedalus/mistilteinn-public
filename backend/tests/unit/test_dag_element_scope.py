"""`element_scope` is honoured on the DAG path (#164).

`resolve_modifiers` filters element-scoped rows only when the caller supplies a
`damage_element`, and its docstring named "the DAG parity path" as one that did
not. That path is what the **optimizer and simulator** use, so every
element-scoped row applied to every element there: 23 `res_ignore` /
`res_reduction` rows across ~20 agents, e.g. Miyabi's Ice RES-ignore reaching a
Fire teammate's damage. RESArea is a full multiplicative zone, so this was not a
rounding-level error.

It also blocked #162's kit data: Jane's Assault CRIT grant is a `teamBuff` scoped
`.physical`, so authoring it while scoping was unfiltered would have handed her
Assault CRIT to a teammate's non-Physical anomalies.
"""

from __future__ import annotations

import pytest

from app.services.buff_resolver import ELEMENT_SCOPE_HONORED_STATS
from app.services.damage_dag_service import _build_registry
from app.services.modifiers import Modifier, ModifierSource, ModifierTarget


def _snapshot(monkey_modifiers):
    from app.services.build_damage_service import BuildSnapshot

    return BuildSnapshot(
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        disc_stats=[],
        modifiers=monkey_modifiers,
    )


def _enemy():
    from app.services.build_damage_service import EnemySnapshot

    return EnemySnapshot(level=60, base_def=50, element_res=0)


def _scoped_row(stat: str, elements: list[str], value: int = 5000):
    return Modifier(
        stat=stat,
        value=value,
        source=ModifierSource.CORE_SKILL,
        target=ModifierTarget.SELF,
        element_scope=elements,
    )


def _resolve(modifiers, damage_element):
    from app.services.modifiers import ActiveConditions, AttackScope

    _reg, buffs, _stats = _build_registry(
        _snapshot(modifiers),
        _enemy(),
        ActiveConditions(),
        AttackScope.ALL,
        is_stunned=False,
        stun_dmg_mult=10000,
        damage_element=damage_element,
    )
    return buffs


@pytest.mark.parametrize("stat", sorted(ELEMENT_SCOPE_HONORED_STATS))
class TestScopedRowsAreFiltered:
    def test_a_matching_element_keeps_the_row(self, stat: str) -> None:
        buffs = _resolve([_scoped_row(stat, ["ice"])], "ice")
        assert buffs.combat_bonuses.get(stat, 0) == 5000

    def test_a_different_element_drops_it(self, stat: str) -> None:
        """The leak: an Ice-scoped row must not apply to Fire damage."""
        buffs = _resolve([_scoped_row(stat, ["ice"])], "fire")
        assert buffs.combat_bonuses.get(stat, 0) == 0, (
            f"{stat} scoped to ice still applied to fire damage — element_scope "
            "is unfiltered on the DAG path (#164)"
        )

    def test_a_multi_element_scope_matches_any_listed(self, stat: str) -> None:
        buffs = _resolve([_scoped_row(stat, ["ice", "fire"])], "fire")
        assert buffs.combat_bonuses.get(stat, 0) == 5000

    def test_an_unscoped_row_applies_to_every_element(self, stat: str) -> None:
        row = Modifier(
            stat=stat, value=5000, source=ModifierSource.CORE_SKILL, target=ModifierTarget.SELF
        )
        assert _resolve([row], "fire").combat_bonuses.get(stat, 0) == 5000
        assert _resolve([row], "ether").combat_bonuses.get(stat, 0) == 5000


class TestNoElementContextIsStillUnfiltered:
    def test_none_keeps_the_permissive_behaviour(self) -> None:
        """Callers with no element context must not silently lose buffs.

        `damage_element=None` means "no element context", not "no element" — the
        buff-roster callers rely on seeing every row.
        """
        buffs = _resolve([_scoped_row("res_ignore", ["ice"])], None)
        assert buffs.combat_bonuses.get("res_ignore", 0) == 5000
