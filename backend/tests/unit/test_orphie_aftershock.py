"""Task 6 — Orphie & Magus (1301) aftershock JSON + energy gate tests.

Two scenarios:
  1. test_orphie_energy_gate_blocks_below_60 — energy < 60 → 0 procs
  2. test_orphie_autoex_4_procs_minus30      — energy ≥ 60 → 4 procs, energy −30
"""

from types import SimpleNamespace

import pytest

from app.data.loaders.moves import AftershockSpec, AgentMovesSpec, MoveBuildupSpec
from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot


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


def _build(
    name: str,
    element: str = "fire",
    base_energy_regen: int = 0,
) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element=element,
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        agent_base_energy_regen=base_energy_regen,
        modifiers=[],
    )


def _fake_attack() -> SimpleNamespace:
    return SimpleNamespace(
        element="electric",
        skill_key="Basic",
        damage_base=10_000,
        damage_growth=0,
        name="basic_test",
        id="1",
        anomaly_buildup=0,
    )


def _orphie_spec() -> AftershockSpec:
    """Orphie & Magus aftershock: energy≥60/−30, 5s CD, 4 laser procs."""
    return AftershockSpec(
        react_to=["hit"],
        react_scopes=None,
        requires_off_field=True,
        resource="energy",
        cost=30.0,
        min_resource=60.0,
        cooldown_s=5.0,
        procs_per_trigger=4,
        aftershock_mv_bp=16960,
        element="fire",
        damage_path="standard",
    )


# ---------------------------------------------------------------------------
# test_orphie_energy_gate_blocks_below_60
# ---------------------------------------------------------------------------


def test_orphie_energy_gate_blocks_below_60():
    """Orphie off-field with energy < 60 → 0 aftershock procs.

    Orphie has no passive regen; after one short step energy stays at 0.
    The min_resource=60 floor blocks the trigger.
    """
    builds = {
        "yanagi": _build("Yanagi", element="electric"),
        "orphie_magus": _build("Orphie & Magus", element="fire", base_energy_regen=0),
    }
    moves_db = {
        "yanagi": AgentMovesSpec(
            moves={
                "basic_move": MoveBuildupSpec(duration_s=1.0, hits=1),
            }
        ),
        "orphie_magus": AgentMovesSpec(moves={}, aftershock=_orphie_spec()),
    }
    steps = [
        SimulatedAttackStep(
            agent_id="yanagi",
            move_name="basic_move",
            attacks=[_fake_attack()],
            conditions=[],
        )
    ]
    result = simulate(builds, steps, _enemy(), moves_db)

    as_events = [e for e in result.events if e.kind == "aftershock"]
    assert len(as_events) == 0, (
        f"Expected 0 procs (energy {result.final_energy.get('orphie_magus', 0):.1f} < 60), "
        f"got {len(as_events)}"
    )
    assert result.totals["aftershock"] == 0


# ---------------------------------------------------------------------------
# test_orphie_autoex_4_procs_minus30
# ---------------------------------------------------------------------------


def test_orphie_autoex_4_procs_minus30():
    """Orphie off-field with energy ≥ 60 → 4 procs, energy −30.

    Orphie has base_energy_regen=600 (6/s). Step duration=10s → 60 energy accrued.
    Energy gate passes (60 ≥ 60, min_resource) → 4 laser procs fire.
    After consume: energy = 60 − 30 = 30.  5s cooldown gate is set.
    """
    builds = {
        "yanagi": _build("Yanagi", element="electric"),
        "orphie_magus": _build("Orphie & Magus", element="fire", base_energy_regen=600),
    }
    moves_db = {
        "yanagi": AgentMovesSpec(
            moves={
                "basic_move": MoveBuildupSpec(duration_s=10.0, hits=1),
            }
        ),
        "orphie_magus": AgentMovesSpec(moves={}, aftershock=_orphie_spec()),
    }
    steps = [
        SimulatedAttackStep(
            agent_id="yanagi",
            move_name="basic_move",
            attacks=[_fake_attack()],
            conditions=[],
        )
    ]
    result = simulate(builds, steps, _enemy(), moves_db)

    as_events = [
        e
        for e in result.events
        if e.kind == "aftershock" and e.agent_id == "orphie_magus"
    ]
    assert len(as_events) == 4, (
        f"Expected 4 procs (Orphie auto-EX, 4 lasers), got {len(as_events)}"
    )
    for ev in as_events:
        assert ev.element == "fire"
        assert ev.detail.get("on_field") is False
        assert ev.detail.get("aftershock") is True
        assert ev.damage is not None
        assert ev.damage > 0

    # Energy: 60 regen − 30 consume = 30
    orphie_energy = result.final_energy.get("orphie_magus", 0.0)
    assert orphie_energy == pytest.approx(30.0, abs=0.1), (
        f"Expected energy ≈ 30 after trigger, got {orphie_energy:.2f}"
    )

    assert result.totals["aftershock"] == pytest.approx(
        sum(e.damage for e in as_events if e.damage), abs=0.01
    )
