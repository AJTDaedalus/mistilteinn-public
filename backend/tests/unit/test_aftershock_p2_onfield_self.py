"""Task B1 — On-field self emit path (_resolve_onfield_aftershock).

Tests (TDD — written before implementation):
  - test_onfield_self_emits_for_active: active agent A with on_field_self spec emits
    an aftershock when A lands a hit.
  - test_onfield_self_uses_onfield_merge: a teammate ACTIVE buff reaches A's aftershock
    proc (unlike the off-field path where only TEAM buffs apply).
"""

from types import SimpleNamespace

from app.data.loaders.moves import AftershockSpec, AgentMovesSpec, MoveBuildupSpec
from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import AttackScope, Condition, Modifier, ModifierSource, ModifierTarget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ONFIELD_MV = 5_000  # 50% ATK


def _enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Test Target",
        level=60,
        defense=50,
        fire_res=0,
        anomaly_capacity_fire=10000,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )


def _build(name: str, element: str = "electric", modifiers: list | None = None) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element=element,
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=modifiers or [],
    )


def _hit(element: str = "electric", scope: str = "basic"):
    return SimpleNamespace(
        element=element,
        skill_key="Basic",
        damage_base=10_000,
        damage_growth=0,
        name="test_basic",
        id="1",
        anomaly_buildup=0,
    )


def _onfield_spec() -> AftershockSpec:
    """Aftershock spec with on_field_self=True; reacts to all hit types."""
    return AftershockSpec(
        react_to=["hit"],
        react_scopes=None,
        requires_off_field=False,
        on_field_self=True,
        aftershock_mv_bp=_ONFIELD_MV,
    )


_ACTOR_BASIC_MOVE = MoveBuildupSpec(hits=1, duration_s=1.0, scope="basic")


def _moves_db(agent_name: str, spec: AftershockSpec, move_name: str = "basic") -> dict:
    key = agent_name.lower().replace(" ", "_")
    return {key: AgentMovesSpec(moves={move_name: _ACTOR_BASIC_MOVE}, aftershock=spec)}


# ---------------------------------------------------------------------------
# test_onfield_self_emits_for_active
# ---------------------------------------------------------------------------


def test_onfield_self_emits_for_active():
    """Active agent A with on_field_self spec emits exactly one aftershock proc when A hits."""
    builds = {
        "A": _build("A"),
        "B": _build("B"),
    }
    mdb = _moves_db("A", _onfield_spec())

    rotation = [
        # A is active; A lands a basic hit
        SimulatedAttackStep(
            agent_id="A",
            move_name="basic",
            attacks=[_hit()],
            conditions=[],
        ),
    ]

    result = simulate(builds, rotation, _enemy(), mdb)

    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 1, f"expected 1 aftershock, got {len(as_events)}"
    assert as_events[0].agent_id == "A"
    assert result.totals["aftershock"] > 0


def test_onfield_self_no_emit_when_offfield():
    """on_field_self spec fires only when A is the active agent; if B is active, A gets no proc."""
    builds = {
        "A": _build("A"),
        "B": _build("B"),
    }
    mdb = _moves_db("A", _onfield_spec())
    mdb["b"] = AgentMovesSpec(moves={"basic": _ACTOR_BASIC_MOVE}, aftershock=None)

    rotation = [
        # B is active; B lands a hit — A's on_field_self spec must not fire
        SimulatedAttackStep(
            agent_id="B",
            move_name="basic",
            attacks=[_hit()],
            conditions=[],
        ),
    ]

    result = simulate(builds, rotation, _enemy(), mdb)

    as_events = [e for e in result.events if e.kind == "aftershock" and e.agent_id == "A"]
    assert len(as_events) == 0, "on_field_self spec must not fire while A is off-field"


# ---------------------------------------------------------------------------
# test_onfield_self_uses_onfield_merge
# ---------------------------------------------------------------------------


def test_onfield_self_uses_onfield_merge():
    """A teammate ACTIVE buff reaches A's on-field aftershock proc.

    We compare A's aftershock damage in two scenarios:
      - Scenario 1: teammate B has no buff.
      - Scenario 2: teammate B has a +5000bp (50%) ACTIVE dmg_bonus targeting ACTIVE agents.
    The damage in scenario 2 must be strictly higher than scenario 1.
    """
    active_buff = Modifier(
        stat="electric_dmg",
        value=5_000,  # +50% Electric DMG
        source=ModifierSource.WENGINE_PASSIVE,
        source_label="TestBuff: teammate ACTIVE electric_dmg",
        target=ModifierTarget.ACTIVE,
        conditions=(Condition.ALWAYS,),
        scopes=(AttackScope.ALL,),
    )

    rotation = [
        SimulatedAttackStep(
            agent_id="A",
            move_name="basic",
            attacks=[_hit()],
            conditions=[],
        ),
    ]

    mdb = _moves_db("A", _onfield_spec())
    mdb["b"] = AgentMovesSpec(moves={"basic": _ACTOR_BASIC_MOVE}, aftershock=None)

    # Scenario 1: no buff from B
    builds_no_buff = {
        "A": _build("A"),
        "B": _build("B"),
    }
    result_no_buff = simulate(builds_no_buff, rotation, _enemy(), mdb)
    as_no_buff = sum(e.damage for e in result_no_buff.events if e.kind == "aftershock")

    # Scenario 2: B has an ACTIVE buff for electric DMG
    builds_with_buff = {
        "A": _build("A"),
        "B": _build("B", modifiers=[active_buff]),
    }
    result_with_buff = simulate(builds_with_buff, rotation, _enemy(), mdb)
    as_with_buff = sum(e.damage for e in result_with_buff.events if e.kind == "aftershock")

    assert as_no_buff > 0, "baseline aftershock must be non-zero"
    assert as_with_buff > as_no_buff, (
        f"ACTIVE buff ({active_buff.value}bp electric_dmg) must raise on-field aftershock: "
        f"{as_no_buff} → {as_with_buff}"
    )
