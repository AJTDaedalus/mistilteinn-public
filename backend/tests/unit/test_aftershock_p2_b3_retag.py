"""Task B3 — Chain & Ultimate re-tag as Aftershock DMG.

Tests (TDD — written before implementation):
  - test_anby_chain_ult_retag_aftershock_total: a Chain or Ultimate hit from an agent with
    retag_as_aftershock raises totals["aftershock"] by exactly that hit's damage.
  - test_anby_retag_no_double_count: totals["total"] counts the hit once (OQ-P2-4 guard).
  - test_anby_retag_applies_core_buff: result with AFTERSHOCK_ACTIVE buff present is
    measurably higher than without (re-tag reaches the calc).
"""

from types import SimpleNamespace

import pytest

from app.data.loaders.moves import AftershockSpec, AgentMovesSpec, MoveBuildupSpec
from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.modifiers import Condition, Modifier, ModifierSource


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


def _build(name: str, extra_modifiers: list | None = None):
    from app.services.build_damage_service import BuildSnapshot

    return BuildSnapshot(
        agent_name=name,
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=extra_modifiers or [],
    )


def _chain_hit():
    return SimpleNamespace(
        element="electric",
        skill_key="Chain",
        damage_base=20_000,
        damage_growth=0,
        name="chain_attack",
        id="chain_1",
        anomaly_buildup=0,
    )


def _ult_hit():
    return SimpleNamespace(
        element="electric",
        skill_key="Ultimate",
        damage_base=30_000,
        damage_growth=0,
        name="ultimate",
        id="ult_1",
        anomaly_buildup=0,
    )


def _basic_hit():
    return SimpleNamespace(
        element="electric",
        skill_key="Basic",
        damage_base=5_000,
        damage_growth=0,
        name="basic",
        id="basic_1",
        anomaly_buildup=0,
    )


_CHAIN_MOVE = MoveBuildupSpec(hits=1, duration_s=1.0, scope="chain")
_ULT_MOVE = MoveBuildupSpec(hits=1, duration_s=1.0, scope="ultimate")
_BASIC_MOVE = MoveBuildupSpec(hits=1, duration_s=1.0, scope="basic")


def _retag_spec() -> AftershockSpec:
    """Minimal spec that re-tags chain and ultimate hits as Aftershock DMG."""
    return AftershockSpec(
        react_to=[],          # no auto-proc triggering — only re-tag
        aftershock_mv_bp=0,   # required field; cascade not used here
        retag_as_aftershock=["chain", "ultimate"],
        element="electric",
    )


def _moves_db(agent_name: str, spec: AftershockSpec) -> dict:
    key = agent_name.lower().replace(" ", "_")
    return {
        key: AgentMovesSpec(
            moves={
                "chain": _CHAIN_MOVE,
                "ultimate": _ULT_MOVE,
                "basic": _BASIC_MOVE,
            },
            aftershock=spec,
        )
    }


# ---------------------------------------------------------------------------
# test_anby_chain_ult_retag_aftershock_total
# ---------------------------------------------------------------------------


def test_anby_chain_ult_retag_aftershock_total():
    """Chain and Ultimate hits from an agent with retag_as_aftershock appear in
    totals['aftershock'], which should be non-zero after either hit."""
    builds = {"A": _build("A")}
    mdb = _moves_db("A", _retag_spec())

    for move_name, attacks in [("chain", [_chain_hit()]), ("ultimate", [_ult_hit()])]:
        rotation = [
            SimulatedAttackStep(
                agent_id="A",
                move_name=move_name,
                attacks=attacks,
                conditions=[],
            )
        ]
        result = simulate(builds, rotation, _enemy(), mdb)
        hit_events = [e for e in result.events if e.kind == "hit"]
        assert len(hit_events) == 1, f"Expected 1 hit event for {move_name}"
        hit_dmg = hit_events[0].damage

        assert result.totals.get("aftershock", 0) == pytest.approx(hit_dmg, rel=1e-6), (
            f"{move_name}: totals['aftershock'] should equal hit damage; "
            f"got {result.totals.get('aftershock', 0)} vs hit {hit_dmg}"
        )


# ---------------------------------------------------------------------------
# test_anby_retag_no_double_count
# ---------------------------------------------------------------------------


def test_anby_retag_no_double_count():
    """totals['total'] counts a re-tagged Chain/Ultimate hit exactly once (OQ-P2-4 guard)."""
    builds = {"A": _build("A")}
    mdb = _moves_db("A", _retag_spec())

    rotation = [
        SimulatedAttackStep(
            agent_id="A",
            move_name="chain",
            attacks=[_chain_hit()],
            conditions=[],
        )
    ]
    result = simulate(builds, rotation, _enemy(), mdb)

    hit_events = [e for e in result.events if e.kind == "hit"]
    assert len(hit_events) == 1
    hit_dmg = hit_events[0].damage

    assert result.totals.get("total", 0) == pytest.approx(hit_dmg, rel=1e-6), (
        f"totals['total'] should equal hit damage exactly once; "
        f"got {result.totals.get('total', 0)} vs {hit_dmg}"
    )


# ---------------------------------------------------------------------------
# test_anby_retag_applies_core_buff
# ---------------------------------------------------------------------------


def test_anby_retag_applies_core_buff():
    """With an AFTERSHOCK_ACTIVE-gated +25% DMG modifier on the agent, a re-tagged
    Chain hit should deal more damage than the same hit without the modifier (i.e.
    AFTERSHOCK_ACTIVE is injected into the conditions before the damage roll)."""
    from app.services.modifiers import ModifierTarget

    aftershock_buff = Modifier(
        stat="dmg_bonus",
        source=ModifierSource.CORE_SKILL,
        source_label="core_aftershock",
        target=ModifierTarget.SELF,
        value=2500,          # +25% in basis points
        conditions=(Condition.AFTERSHOCK_ACTIVE,),
    )

    builds_plain = {"A": _build("A")}
    builds_buffed = {"A": _build("A", extra_modifiers=[aftershock_buff])}
    mdb = _moves_db("A", _retag_spec())

    rotation = [
        SimulatedAttackStep(
            agent_id="A",
            move_name="chain",
            attacks=[_chain_hit()],
            conditions=[],
        )
    ]

    result_plain = simulate(builds_plain, rotation, _enemy(), mdb)
    result_buffed = simulate(builds_buffed, rotation, _enemy(), mdb)

    dmg_plain = result_plain.totals.get("aftershock", 0)
    dmg_buffed = result_buffed.totals.get("aftershock", 0)

    assert dmg_buffed > dmg_plain, (
        f"Buffed chain (with AFTERSHOCK_ACTIVE +25%) should exceed plain; "
        f"got buffed={dmg_buffed}, plain={dmg_plain}"
    )
    # Expect roughly 25% more (allowing ±5% for rounding)
    ratio = dmg_buffed / dmg_plain if dmg_plain else 0
    assert 1.20 <= ratio <= 1.30, f"Expected ~1.25x ratio, got {ratio:.3f}"


# ---------------------------------------------------------------------------
# test_anby_basic_not_retagged
# ---------------------------------------------------------------------------


def test_anby_basic_not_retagged():
    """Basic attacks are NOT in retag_as_aftershock — totals['aftershock'] stays 0."""
    builds = {"A": _build("A")}
    mdb = _moves_db("A", _retag_spec())

    rotation = [
        SimulatedAttackStep(
            agent_id="A",
            move_name="basic",
            attacks=[_basic_hit()],
            conditions=[],
        )
    ]
    result = simulate(builds, rotation, _enemy(), mdb)
    assert result.totals.get("aftershock", 0) == 0, (
        "Basic hits should not be re-tagged as aftershock"
    )
