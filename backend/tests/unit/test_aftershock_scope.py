"""Aftershock damage must respect attack scope (issue #154).

Both aftershock emission paths used to resolve with `attack_scope=AttackScope.ALL`.
The scope gate only excludes a modifier when the *query* scope is not `ALL`
(`buff_resolver.py`), so passing `ALL` disabled scope filtering entirely: every
narrow-scoped bonus the emitter owned applied to their aftershocks at once — an
agent with "Ultimate DMG +30%" collected it on aftershocks alongside their Basic,
Chain and EX bonuses.

Measured blast radius when this was found: 87 narrow-scoped and 23 element-scoped
modifiers across 52 corpus sources.

The counterpart matters just as much: a row that *should* reach aftershocks must
still do so. Shadow Harmony's 2pc is literally "Aftershock/Dash DMG" and was
scoped `["dash"]`, i.e. it reached aftershocks only through the bug — so the fix
has to re-scope it rather than silently drop a real bonus.
"""

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)

_AFTERSHOCK_MV = 10_000  # 100% ATK, so the bonus shows up cleanly in the total


def _enemy() -> EnemyProfile:
    return EnemyProfile(name="Aftershock Target", level=60, defense=50, electric_res=0)


def _mod(scopes: tuple[AttackScope, ...]) -> Modifier:
    return Modifier(
        stat="dmg_bonus",
        value=5000,  # +50%, large enough that its presence is unambiguous
        source=ModifierSource.CORE_SKILL,
        source_label="test dmg bonus",
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
        scopes=scopes,
    )


def _aftershock_damage(scopes: tuple[AttackScope, ...] | None) -> int:
    build = BuildSnapshot(
        agent_name="Anby",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[_mod(scopes)] if scopes else [],
    )
    step = SimulatedAttackStep(
        agent_id="a", move_name="aftershock", attacks=[], conditions=[]
    )
    step.aftershock_mv_bp = _AFTERSHOCK_MV
    result = simulate({"a": build}, [step], _enemy(), {})
    return sum(e.damage or 0 for e in result.events if e.kind == "aftershock")


def test_baseline_aftershock_lands():
    assert _aftershock_damage(None) > 0


def test_ultimate_scoped_bonus_does_not_reach_an_aftershock():
    """The headline defect: a category bonus leaking onto a different category."""
    baseline = _aftershock_damage(None)
    with_ult = _aftershock_damage((AttackScope.ULTIMATE,))

    assert with_ult == baseline, (
        "an Ultimate-scoped DMG bonus must not apply to aftershock damage — "
        "scope filtering is being bypassed"
    )


def test_all_scoped_bonus_still_reaches_an_aftershock():
    """The guardrail: the fix must not over-correct into dropping global bonuses."""
    baseline = _aftershock_damage(None)
    with_all = _aftershock_damage((AttackScope.ALL,))

    assert with_all > baseline


def test_aftershock_scoped_bonus_reaches_an_aftershock():
    """What Shadow Harmony's 2pc needs in order to keep working after the fix."""
    baseline = _aftershock_damage(None)
    with_as = _aftershock_damage((AttackScope.DASH, AttackScope.AFTERSHOCK))

    assert with_as > baseline, (
        "a row explicitly scoped to aftershock must apply — otherwise the fix "
        "deletes Shadow Harmony's 2pc instead of correcting how it is expressed"
    )


def test_dash_only_bonus_does_not_reach_an_aftershock():
    """The exact shape Shadow Harmony had before re-scoping: dash-only must not leak."""
    baseline = _aftershock_damage(None)
    with_dash = _aftershock_damage((AttackScope.DASH,))

    assert with_dash == baseline
