"""Tests for derived and stat-threshold condition injection."""

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import (
    ActiveConditions,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.snapshot_builder import inject_stat_threshold_conditions
from app.services.stat_calculator import TotalStats

# ---------------------------------------------------------------------------
# inject_stat_threshold_conditions unit tests
# ---------------------------------------------------------------------------


def _conds(*extras: Condition) -> ActiveConditions:
    return ActiveConditions(active={Condition.ALWAYS, *extras})


def test_ap_gte_375_injected():
    conds = _conds()
    inject_stat_threshold_conditions(conds, TotalStats(anomaly_proficiency=375))
    assert Condition.ANOMALY_PROFICIENCY_GTE_375 in conds.active


def test_ap_below_375_not_injected():
    conds = _conds()
    inject_stat_threshold_conditions(conds, TotalStats(anomaly_proficiency=374))
    assert Condition.ANOMALY_PROFICIENCY_GTE_375 not in conds.active


def test_mastery_115_injected():
    conds = _conds()
    inject_stat_threshold_conditions(conds, TotalStats(anomaly_mastery=115))
    assert Condition.ANOMALY_MASTERY_GTE_115 in conds.active


def test_mastery_150_injected_at_150():
    conds = _conds()
    inject_stat_threshold_conditions(conds, TotalStats(anomaly_mastery=150))
    assert Condition.ANOMALY_MASTERY_GTE_115 in conds.active
    assert Condition.ANOMALY_MASTERY_GTE_150 in conds.active


def test_mastery_115_does_not_inject_150():
    conds = _conds()
    inject_stat_threshold_conditions(conds, TotalStats(anomaly_mastery=115))
    assert Condition.ANOMALY_MASTERY_GTE_150 not in conds.active


def test_crit_rate_gte_50_at_boundary():
    conds = _conds()
    inject_stat_threshold_conditions(conds, TotalStats(crit_rate=5000))
    assert Condition.CRIT_RATE_GTE_50 in conds.active


def test_crit_rate_below_50_not_injected():
    conds = _conds()
    inject_stat_threshold_conditions(conds, TotalStats(crit_rate=4999))
    assert Condition.CRIT_RATE_GTE_50 not in conds.active


# ---------------------------------------------------------------------------
# Simulator: ENEMY_HAS_ANOMALY auto-injection
# ---------------------------------------------------------------------------

_ENEMY = EnemyProfile(
    name="Dummy",
    level=60,
    defense=50,
    fire_res=0,
    electric_res=0,
    # capacity=1 → threshold=100 BP; our test hits deliver 200 BP → always trigger immediately.
    anomaly_capacity_fire=1,
    anomaly_capacity_electric=1,
    anomaly_res_fire=0,
    anomaly_res_electric=0,
    anomaly_duration_default=10.0,
    stun_buildup_multiplier=10000,
)


def _build(element: str, ap: int = 0, modifiers=None) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=f"Agent_{element}",
        agent_element=element,
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=ap,
        modifiers=modifiers or [],
    )


class _MockMoves:
    """Minimal moves-db stub the simulator accepts."""

    def __init__(self):
        self.moves = {}

    def get(self, key, default=None):
        return self.moves.get(key, default)


def _run_two_agents(elem1, elem2, *, ap1=0, ap2=0, mods1=None, mods2=None):
    """Run a two-step sim: agent1 hits, agent2 hits. Returns the sim result."""
    b1 = _build(elem1, ap=ap1, modifiers=mods1)
    b2 = _build(elem2, ap=ap2, modifiers=mods2)
    builds = {"a1": b1, "a2": b2}
    steps = [
        SimulatedAttackStep(
            agent_id="a1",
            move_name="basic",
            attacks=[MockAttack("basic", 10000, elem1)],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="a1",
            move_name="basic",
            attacks=[MockAttack("basic", 10000, elem1)],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="a2",
            move_name="basic",
            attacks=[MockAttack("basic", 10000, elem2)],
            conditions=[],
        ),
    ]
    return simulate(builds, steps, _ENEMY, {})


class MockAttack:
    def __init__(
        self, name: str, damage_base: int, element: str, buildup: int = 9999, dur: float = 0.1
    ) -> None:
        self.name = name
        self.damage_base = damage_base
        self.element = element
        self.anomaly_buildup = buildup
        self.duration = dur
        self.anomaly_type = None
        self.hit_index = 0
        self.skill_key = name
        self.variant_label = None


def test_enemy_has_anomaly_auto_injected_in_simulator():
    """After fire aura is applied, ENEMY_HAS_ANOMALY should be active.

    We gate a dmg_bonus modifier on ENEMY_HAS_ANOMALY and verify the second
    fire hit (which occurs after the aura is on the enemy) benefits from it.
    """
    mod = Modifier(
        stat="dmg_bonus",
        value=5000,
        conditions=(Condition.ENEMY_HAS_ANOMALY,),
        source=ModifierSource.WENGINE_PASSIVE,
        target=ModifierTarget.SELF,
        max_stacks=1,
        source_label="test_dmg",
    )
    # Two fire hits: first applies aura (buildup > capacity 50), second hits
    # into active aura → should have ENEMY_HAS_ANOMALY active.
    b = BuildSnapshot(
        agent_name="Tester",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=100,
        modifiers=[mod],
    )
    builds = {"a": b}
    steps = [
        SimulatedAttackStep(
            agent_id="a",
            move_name="hit1",
            # buildup=200 → hit_buildup≈200, threshold=100 → aura triggers on hit1.
            attacks=[MockAttack("hit1", 10000, "fire", buildup=200)],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="a",
            move_name="hit2",
            attacks=[MockAttack("hit2", 10000, "fire", buildup=10)],
            conditions=[],
        ),
    ]
    result = simulate(builds, steps, _ENEMY, {})
    # hit events carry attack_name in their detail dict.
    # hit1: aura not yet applied → modifier inactive.
    # hit2: aura is active → ENEMY_HAS_ANOMALY injected → modifier applies → higher damage.
    hit1_dmg = next(
        e for e in result.events
        if e.kind == "hit" and isinstance(e.detail, dict) and e.detail.get("attack_name") == "hit1"
    )
    hit2_dmg = next(
        e for e in result.events
        if e.kind == "hit" and isinstance(e.detail, dict) and e.detail.get("attack_name") == "hit2"
    )
    assert hit2_dmg.damage > hit1_dmg.damage, (
        "hit2 should benefit from ENEMY_HAS_ANOMALY dmg_bonus; "
        f"hit1={hit1_dmg.damage}, hit2={hit2_dmg.damage}"
    )


# ---------------------------------------------------------------------------
# Simulator: OFF_FIELD_OR_5S_AFTER_SWAP auto-injection
# ---------------------------------------------------------------------------


def test_off_field_5s_window_injected_at_swap():
    """OFF_FIELD_OR_5S_AFTER_SWAP fires after a real swap-in, not on the initial None→agent.

    Two-agent setup: A acts first (implicit None→A, not a real swap), then B acts.
    A→B is a real swap (charge_time=True) that records in field_timeline.
    B's step fires within 5s of the swap → OFF_FIELD_OR_5S_AFTER_SWAP must be active on B.
    The initial None→A step must NOT get the condition (fixes phantom Chaos Jazz 4pc inflation).
    """
    mod = Modifier(
        stat="dmg_bonus",
        value=5000,
        conditions=(Condition.OFF_FIELD_OR_5S_AFTER_SWAP,),
        source=ModifierSource.DISC_SET_4PC,
        target=ModifierTarget.SELF,
        max_stacks=1,
        source_label="4pc_off_field",
    )
    b_a = BuildSnapshot(
        agent_name="AgentA",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=[mod],
    )
    b_b = BuildSnapshot(
        agent_name="AgentB",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=[mod],
    )
    b_b_no_mod = BuildSnapshot(
        agent_name="AgentB",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=[],
    )
    attack = MockAttack("hit1", 10000, "fire", buildup=0)
    steps = [
        SimulatedAttackStep(agent_id="a", move_name="hit_a", attacks=[attack], conditions=[]),
        SimulatedAttackStep(agent_id="b", move_name="hit_b", attacks=[attack], conditions=[]),
    ]

    # B gets the modifier: its step follows a real A→B swap and should see the condition.
    result_mod = simulate({"a": b_a, "b": b_b}, steps, _ENEMY, {})
    # B without the modifier: baseline.
    result_no_mod = simulate({"a": b_a, "b": b_b_no_mod}, steps, _ENEMY, {})

    b_hit_mod = next(e for e in result_mod.events if e.kind == "hit" and e.agent_id == "b")
    b_hit_no_mod = next(e for e in result_no_mod.events if e.kind == "hit" and e.agent_id == "b")
    assert b_hit_mod.damage > b_hit_no_mod.damage, (
        "OFF_FIELD_OR_5S_AFTER_SWAP should be active for B immediately after a real A→B swap; "
        f"with_mod={b_hit_mod.damage}, no_mod={b_hit_no_mod.damage}"
    )

    # A's step (None→A, no real swap) must NOT get the condition.
    a_hit_mod = next(e for e in result_mod.events if e.kind == "hit" and e.agent_id == "a")
    b_a_no_mod = BuildSnapshot(
        agent_name="AgentA",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=0,
        modifiers=[],
    )
    result_a_no_mod = simulate({"a": b_a_no_mod, "b": b_b}, steps, _ENEMY, {})
    a_hit_no_mod = next(
        e for e in result_a_no_mod.events if e.kind == "hit" and e.agent_id == "a"
    )
    assert a_hit_mod.damage == a_hit_no_mod.damage, (
        "OFF_FIELD_OR_5S_AFTER_SWAP must NOT fire for the initial None→A step (no real swap); "
        f"with_mod={a_hit_mod.damage}, no_mod={a_hit_no_mod.damage}"
    )


# ---------------------------------------------------------------------------
# Simulator: ANOMALY_PROFICIENCY_GTE_375 stat-threshold injection
# ---------------------------------------------------------------------------


def test_ap_gte_375_condition_active_in_simulator():
    """Modifier gated on ANOMALY_PROFICIENCY_GTE_375 fires when AP >= 375."""
    mod_active = Modifier(
        stat="dmg_bonus",
        value=2500,
        conditions=(Condition.ANOMALY_PROFICIENCY_GTE_375,),
        source=ModifierSource.WENGINE_PASSIVE,
        target=ModifierTarget.SELF,
        max_stacks=1,
        source_label="disorder_ap_threshold",
    )
    b_high_ap = BuildSnapshot(
        agent_name="Yanagi",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=400,
        modifiers=[mod_active],
    )
    b_low_ap = BuildSnapshot(
        agent_name="Yanagi",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=300,
        modifiers=[mod_active],
    )

    hit = MockAttack("hit", 10000, "electric", buildup=0)
    step = SimulatedAttackStep(
        agent_id="a", move_name="hit", attacks=[hit], conditions=[]
    )

    result_high = simulate({"a": b_high_ap}, [step], _ENEMY, {})
    result_low = simulate({"a": b_low_ap}, [step], _ENEMY, {})

    dmg_high = next(e for e in result_high.events if e.kind == "hit").damage
    dmg_low = next(e for e in result_low.events if e.kind == "hit").damage

    assert dmg_high > dmg_low, (
        "AP=400 build should benefit from GTE_375 modifier; "
        f"high_ap={dmg_high}, low_ap={dmg_low}"
    )
