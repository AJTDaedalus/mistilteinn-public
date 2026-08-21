"""Unit tests for the aftershock damage tag and authored step (Task 1)."""

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget


def _base_enemy() -> EnemyProfile:
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


def _build(name: str, modifiers: list | None = None) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=modifiers or [],
    )


class _MoveSpec:
    def __init__(self, buildup=0, duration_s=1.0, hits=1, element="electric", scope="basic"):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope


class _AgentMovesSpec:
    def __init__(self, moves: dict):
        self.moves = moves


def _empty_moves_db() -> dict:
    return {}


def test_aftershock_tag_and_total():
    """An authored aftershock step emits a kind='aftershock' event and updates totals."""
    builds = {"agent_a": _build("AgentA")}
    enemy = _base_enemy()

    steps = [
        SimulatedAttackStep(
            agent_id="agent_a",
            move_name="aftershock",
            attacks=[],
            conditions=[],
            aftershock_mv_bp=50_00,  # 50% ATK
        )
    ]

    result = simulate(builds, steps, enemy, _empty_moves_db())

    aftershock_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(aftershock_events) == 1, "Exactly one aftershock event should be emitted"

    ev = aftershock_events[0]
    assert ev.agent_id == "agent_a"
    assert ev.damage is not None
    assert ev.damage > 0
    assert ev.detail.get("aftershock") is True

    assert "aftershock" in result.totals
    assert result.totals["aftershock"] == ev.damage
    assert result.totals["total"] >= result.totals["aftershock"]
    assert result.per_agent_attribution["agent_a"] >= ev.damage


def test_aftershock_active_auto_set_applies_buff():
    """Aftershock proc with AFTERSHOCK_ACTIVE-gated +X% DMG modifier produces higher damage."""
    aftershock_buff = Modifier(
        stat="dmg_bonus",
        value=50_00,  # +50% DMG
        source=ModifierSource.CORE_SKILL,
        source_label="Aftershock Passive",
        target=ModifierTarget.SELF,
        conditions=(Condition.AFTERSHOCK_ACTIVE,),
    )

    build_with_buff = _build("AgentWithBuff", modifiers=[aftershock_buff])
    build_without = _build("AgentWithout", modifiers=[])

    enemy = _base_enemy()
    mv_bp = 100_00  # 100% ATK

    def _run(build: BuildSnapshot) -> int:
        result = simulate(
            {"agent": build},
            [
                SimulatedAttackStep(
                    agent_id="agent",
                    move_name="aftershock",
                    attacks=[],
                    conditions=[],
                    aftershock_mv_bp=mv_bp,
                )
            ],
            enemy,
            _empty_moves_db(),
        )
        events = [e for e in result.events if e.kind == "aftershock"]
        assert len(events) == 1
        return events[0].damage

    dmg_buffed = _run(build_with_buff)
    dmg_base = _run(build_without)

    assert dmg_buffed > dmg_base, (
        f"Buffed ({dmg_buffed}) should exceed base ({dmg_base}): "
        "AFTERSHOCK_ACTIVE was not auto-set or DMG buff did not apply"
    )
