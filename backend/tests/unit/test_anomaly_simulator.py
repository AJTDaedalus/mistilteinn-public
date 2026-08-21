"""Unit tests for the stateful anomaly simulator."""

from dataclasses import dataclass, replace

from app.models.build import EnemyProfile
from app.models.enums import HitMode
from app.services.anomaly_simulator import (
    SimulatedAttackStep,
    simulate,
)
from app.services.build_damage_service import BuildSnapshot
from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget


class MockAttack:
    def __init__(self, name: str, damage_base: int, element: str):
        self.name = name
        self.damage_base = damage_base
        self.element = element


def test_basic_buildup_and_anomaly_trigger():
    # 1. Setup Enemy with 100 capacity for fire
    enemy = EnemyProfile(
        name="Mock Practice Target",
        level=60,
        defense=50,
        fire_res=0,
        anomaly_capacity_fire=100,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )

    # 2. Setup Burnice BuildSnapshot
    burnice_build = BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=500,
        agent_crit_dmg=5000,
        agent_anomaly_proficiency=115,  # 1.15 AP mult
        modifiers=[],
    )

    builds = {
        "burnice_id": burnice_build,
    }

    # 3. Setup moves DB (moves spec)
    # Burnice EX Special: 15000 buildup, duration 2.5s, 6 hits
    class MoveSpec:
        def __init__(self, buildup, duration_s, hits, element, scope):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = scope

    class AgentMovesSpec:
        def __init__(self, agent_id, agent_name, moves):
            self.agent_id = agent_id
            self.agent_name = agent_name
            self.moves = moves

    moves_db = {
        "burnice": AgentMovesSpec(
            agent_id="burnice_id",
            agent_name="Burnice",
            moves={
                "EX Special Attack: Intense Heat Aging Method": MoveSpec(
                    buildup=15000,
                    duration_s=2.5,
                    hits=6,
                    element="fire",
                    scope="special",
                )
            },
        )
    }

    # 4. Create sequential attack steps
    steps = [
        SimulatedAttackStep(
            agent_id="burnice_id",
            move_name="EX Special Attack: Intense Heat Aging Method",
            attacks=[
                MockAttack("Intense Heat Tick 1", 1000, "fire"),
                MockAttack("Intense Heat Tick 2", 1000, "fire"),
            ],
            conditions=[],
        )
    ]

    # 5. Run simulation
    result = simulate(builds, steps, enemy, moves_db)

    # 6. Assertions
    assert not result.warnings
    assert result.totals["total"] > 0
    assert result.totals["anomaly"] > 0

    # Ensure anomaly event exists in the timeline
    anomaly_events = [e for e in result.events if e.kind == "anomaly"]
    assert len(anomaly_events) == 1
    assert anomaly_events[0].element == "fire"
    assert anomaly_events[0].agent_id == "burnice_id"

    # Ensure 20 anomaly proc tick events exist
    ticks = [e for e in result.events if e.kind == "anomaly_tick"]
    assert len(ticks) == 20
    for tick in ticks:
        assert tick.damage > 0
        assert tick.agent_id == "burnice_id"


def test_disorder_trigger():
    # 1. Setup Enemy
    enemy = EnemyProfile(
        name="Mock Elite Target",
        level=60,
        defense=50,
        fire_res=0,
        electric_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_duration_default=10.0,
    )

    # 2. Setup Team Builds
    burnice_build = BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    grace_build = BuildSnapshot(
        agent_name="Grace",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1200,
        agent_anomaly_proficiency=150,
    )

    builds = {
        "burnice": burnice_build,
        "grace": grace_build,
    }

    # 3. Setup Moves DB
    class MoveSpec:
        def __init__(self, buildup, duration_s, hits, element):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = "basic"

    class AgentMovesSpec:
        def __init__(self, moves):
            self.moves = moves

    moves_db = {
        "burnice": AgentMovesSpec(
            {
                "fire_move": MoveSpec(15000, 1.0, 1, "fire"),
            }
        ),
        "grace": AgentMovesSpec(
            {
                "elec_move": MoveSpec(15000, 1.0, 1, "electric"),
            }
        ),
    }

    # 4. First step: Burnice triggers Fire Anomaly at t=1.0s (Burn duration expires at t=11.0s)
    # Second step: Grace triggers Electric Anomaly at t=3.0s (burnice→grace switch costs 1s)
    steps = [
        SimulatedAttackStep("burnice", "fire_move", []),
        SimulatedAttackStep("grace", "elec_move", []),
    ]

    # 5. Run simulation
    result = simulate(builds, steps, enemy, moves_db)

    # 6. Assertions
    # We expect an anomaly trigger at t=1.0 for fire
    anom_events = [e for e in result.events if e.kind == "anomaly"]
    assert len(anom_events) == 2
    assert anom_events[0].element == "fire"
    assert anom_events[0].t == 1.0
    assert anom_events[1].element == "electric"
    # Switch burnice→grace costs 1s (t=1.0 → 2.0); grace's step ends at t=3.0.
    assert anom_events[1].t == 3.0

    # We expect a disorder event of fire element at t=3.0s (switch-adjusted)
    disorder_events = [e for e in result.events if e.kind == "disorder"]
    assert len(disorder_events) == 1
    disorder = disorder_events[0]
    assert disorder.t == 3.0
    assert disorder.element == "fire"
    assert disorder.applier_agent_id == "burnice"
    assert disorder.damage > 0
    assert result.totals["disorder"] > 0
    assert result.per_agent_attribution["burnice"] > 0


def test_disorder_uses_applier_conditions_not_trigger_conditions():
    """Disorder must resolve under the applier's conditions at application time.

    Burnice applies fire while ENEMY_BURNING is active (giving her a disorder_dmg_bonus).
    Grace triggers disorder without ENEMY_BURNING.
    After the fix the disorder damage must equal the case where Burnice's bonus fires,
    NOT the lower value that results from using Grace's (no ENEMY_BURNING) conditions.

    H1 fix (Task 8): store active_conditions on the aura at application time and use
    them (not the trigger's conditions) when building old_ctx for disorder/polarity.
    """
    enemy = EnemyProfile(
        name="H1 Test Target",
        level=60,
        defense=50,
        fire_res=0,
        electric_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_duration_default=10.0,
    )

    # Burnice has a disorder_dmg_bonus gated on ENEMY_BURNING (+100% = 10000 bp)
    burning_bonus_modifier = Modifier(
        stat="disorder_dmg_bonus",
        value=10000,  # +100% disorder bonus, large enough to detect
        source=ModifierSource.CORE_SKILL,
        source_label="H1 test: disorder bonus when burning",
        target=ModifierTarget.SELF,
        conditions=(Condition.ENEMY_BURNING,),
    )

    burnice_build = BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=120,
        modifiers=[burning_bonus_modifier],
    )
    grace_build = BuildSnapshot(
        agent_name="Grace",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=800,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )

    builds = {"burnice": burnice_build, "grace": grace_build}

    class MoveSpec:
        def __init__(self, buildup, duration_s, hits, element):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = "basic"

    class AgentMovesSpec:
        def __init__(self, moves):
            self.moves = moves

    moves_db = {
        "burnice": AgentMovesSpec({"fire_move": MoveSpec(15000, 1.0, 1, "fire")}),
        "grace": AgentMovesSpec({"elec_move": MoveSpec(15000, 1.0, 1, "electric")}),
    }

    # Burnice applies fire with ENEMY_BURNING active (her bonus fires at application time)
    # Grace triggers disorder with NO conditions (no ENEMY_BURNING)
    steps_with_burning = [
        SimulatedAttackStep("burnice", "fire_move", [], conditions=["enemy_burning"]),
        SimulatedAttackStep("grace", "elec_move", [], conditions=[]),
    ]

    # Baseline: Burnice has no conditions at application time (bonus inactive)
    steps_without_burning = [
        SimulatedAttackStep("burnice", "fire_move", [], conditions=[]),
        SimulatedAttackStep("grace", "elec_move", [], conditions=[]),
    ]

    result_with = simulate(builds, steps_with_burning, enemy, moves_db)
    result_without = simulate(builds, steps_without_burning, enemy, moves_db)

    disorder_with = result_with.totals.get("disorder", 0)
    disorder_without = result_without.totals.get("disorder", 0)

    assert disorder_with > 0, "disorder should fire"
    # With applier conditions stored and used: +100% disorder bonus must increase disorder DMG
    assert disorder_with > disorder_without, (
        f"disorder with applier burning bonus ({disorder_with}) should exceed "
        f"baseline without bonus ({disorder_without}); H1 fix not working"
    )


def test_shock_dmg_bonus_excluded_from_disorder():
    """F-22: Grace's shock_dmg_bonus must scale the Shock proc but NOT the
    Disorder damage that fires when her Electric aura is overridden.

    Grace applies Electric (Shock) first; Burnice's Fire anomaly then
    overrides the active aura before it naturally expires, triggering an
    Electric Disorder (old_elem == "electric", applier == Grace) — exactly
    the code path the F-22 TODO flagged. Leifa: attribute-anomaly DMG%
    bonuses apply to the triggering anomaly, not to the resulting Disorder.
    """
    enemy = EnemyProfile(
        name="F-22 Test Target",
        level=60,
        defense=50,
        fire_res=0,
        electric_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_duration_default=10.0,
    )

    shock_bonus_modifier = Modifier(
        stat="shock_dmg_bonus",
        value=5000,  # +50%, large enough to detect
        source=ModifierSource.CORE_SKILL,
        source_label="F-22 test: Grace shock_dmg_bonus",
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
    )

    def _make_builds(*, with_bonus: bool) -> dict:
        grace_build = BuildSnapshot(
            agent_name="Grace",
            agent_element="electric",
            agent_level=60,
            agent_base_atk=1200,
            agent_anomaly_proficiency=150,
            modifiers=[shock_bonus_modifier] if with_bonus else [],
        )
        burnice_build = BuildSnapshot(
            agent_name="Burnice",
            agent_element="fire",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=100,
        )
        return {"grace": grace_build, "burnice": burnice_build}

    MoveSpec, AgentMovesSpec = _make_move_spec_classes()
    moves_db = {
        "grace": AgentMovesSpec({"elec_move": MoveSpec(15000, 1.0, 1, "electric")}),
        "burnice": AgentMovesSpec({"fire_move": MoveSpec(15000, 1.0, 1, "fire")}),
    }
    steps = [
        SimulatedAttackStep("grace", "elec_move", []),
        SimulatedAttackStep("burnice", "fire_move", []),
    ]

    result_with = simulate(_make_builds(with_bonus=True), steps, enemy, moves_db)
    result_without = simulate(_make_builds(with_bonus=False), steps, enemy, moves_db)

    disorder_events_with = [e for e in result_with.events if e.kind == "disorder"]
    disorder_events_without = [e for e in result_without.events if e.kind == "disorder"]
    assert len(disorder_events_with) == 1
    assert disorder_events_with[0].element == "electric"
    assert disorder_events_with[0].applier_agent_id == "grace"

    # The preceding Shock proc DOES change with the bonus (applies to the trigger).
    assert result_with.totals["anomaly"] > result_without.totals["anomaly"]

    # The resulting Electric Disorder does NOT change with the bonus (F-22 fix).
    assert result_with.totals["disorder"] == result_without.totals["disorder"]
    assert disorder_events_with[0].damage == disorder_events_without[0].damage


def _make_move_spec_classes():
    class MoveSpec:
        def __init__(self, buildup, duration_s, hits, element):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = "basic"

    class AgentMovesSpec:
        def __init__(self, moves):
            self.moves = moves

    return MoveSpec, AgentMovesSpec


def _vortex_enemy(*, wind=True, ice=True):
    return EnemyProfile(
        name="Vortex Target",
        level=60,
        defense=50,
        wind_res=0 if wind else None,
        ice_res=0 if ice else None,
        anomaly_capacity_wind=100 if wind else None,
        anomaly_capacity_ice=100 if ice else None,
        anomaly_duration_default=10.0,
    )


def test_vortex_non_wind_on_wind():
    """Non-wind anomaly on Windswept aura → vortex fires with non-wind element (Leifa)."""
    MoveSpec, AgentMovesSpec = _make_move_spec_classes()

    # moves_db keyed by agent_name.lower() (how the simulator looks up specs)
    moves_db = {
        "soukaku": AgentMovesSpec({}),
        "windguy": AgentMovesSpec({"wind_hit": MoveSpec(15000, 1.0, 1, "wind")}),
        "iceguy": AgentMovesSpec({"ice_hit": MoveSpec(15000, 1.0, 1, "ice")}),
    }
    soukaku = BuildSnapshot(
        agent_name="Soukaku",
        agent_element="ice",
        agent_level=60,
        agent_base_atk=1500,
        agent_anomaly_proficiency=200,
    )
    wind_agent = BuildSnapshot(
        agent_name="WindGuy",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    ice_agent = BuildSnapshot(
        agent_name="IceGuy",
        agent_element="ice",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    builds = {"soukaku": soukaku, "wind_agent": wind_agent, "ice_agent": ice_agent}
    steps = [
        SimulatedAttackStep("wind_agent", "wind_hit", []),  # sets Windswept aura
        SimulatedAttackStep("ice_agent", "ice_hit", []),  # disorder → ice vortex
    ]
    result = simulate(builds, steps, _vortex_enemy(), moves_db)

    disorders = [e for e in result.events if e.kind == "disorder"]
    assert len(disorders) == 1

    vortices = [e for e in result.events if e.kind == "vortex"]
    assert len(vortices) == 1
    assert vortices[0].element == "ice"
    assert vortices[0].agent_id == "soukaku"
    assert vortices[0].damage > 0
    assert result.totals["vortex"] > 0


def test_vortex_wind_on_non_wind():
    """Wind anomaly on non-wind aura → vortex fires with non-wind element (Leifa)."""
    MoveSpec, AgentMovesSpec = _make_move_spec_classes()

    moves_db = {
        "soukaku": AgentMovesSpec({}),
        "windguy": AgentMovesSpec({"wind_hit": MoveSpec(15000, 1.0, 1, "wind")}),
        "iceguy": AgentMovesSpec({"ice_hit": MoveSpec(15000, 1.0, 1, "ice")}),
    }
    soukaku = BuildSnapshot(
        agent_name="Soukaku",
        agent_element="ice",
        agent_level=60,
        agent_base_atk=1500,
        agent_anomaly_proficiency=200,
    )
    wind_agent = BuildSnapshot(
        agent_name="WindGuy",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    ice_agent = BuildSnapshot(
        agent_name="IceGuy",
        agent_element="ice",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    builds = {"soukaku": soukaku, "wind_agent": wind_agent, "ice_agent": ice_agent}
    steps = [
        SimulatedAttackStep("ice_agent", "ice_hit", []),  # sets ice aura
        SimulatedAttackStep("wind_agent", "wind_hit", []),  # disorder → ice vortex
    ]
    result = simulate(builds, steps, _vortex_enemy(), moves_db)

    disorders = [e for e in result.events if e.kind == "disorder"]
    assert len(disorders) == 1

    vortices = [e for e in result.events if e.kind == "vortex"]
    assert len(vortices) == 1
    assert vortices[0].element == "ice"
    assert vortices[0].agent_id == "soukaku"
    assert vortices[0].damage > 0


def test_vortex_wind_on_wind_no_trigger():
    """Wind anomaly reapplying Windswept → no vortex, aura refreshed."""
    MoveSpec, AgentMovesSpec = _make_move_spec_classes()

    moves_db = {
        "soukaku": AgentMovesSpec({}),
        "windguy": AgentMovesSpec({"wind_hit": MoveSpec(15000, 1.0, 1, "wind")}),
        "windguy2": AgentMovesSpec({"wind_hit2": MoveSpec(15000, 1.0, 1, "wind")}),
    }
    soukaku = BuildSnapshot(
        agent_name="Soukaku",
        agent_element="ice",
        agent_level=60,
        agent_base_atk=1500,
        agent_anomaly_proficiency=200,
    )
    wind_agent = BuildSnapshot(
        agent_name="WindGuy",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    wind_agent2 = BuildSnapshot(
        agent_name="WindGuy2",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    enemy = EnemyProfile(
        name="Vortex Target",
        level=60,
        defense=50,
        wind_res=0,
        anomaly_capacity_wind=100,
        anomaly_duration_default=10.0,
    )
    builds = {"soukaku": soukaku, "wind_agent": wind_agent, "wind_agent2": wind_agent2}
    steps = [
        SimulatedAttackStep("wind_agent", "wind_hit", []),  # sets Windswept
        SimulatedAttackStep("wind_agent2", "wind_hit2", []),  # refresh — no disorder, no vortex
    ]
    result = simulate(builds, steps, enemy, moves_db)

    vortices = [e for e in result.events if e.kind == "vortex"]
    assert len(vortices) == 0
    disorders = [e for e in result.events if e.kind == "disorder"]
    assert len(disorders) == 0


def test_vortex_ye_shunguang_name_normalization():
    """DB name 'Ye Shunguang' (with space) normalizes to 'ye_shunguang' for allowlist check."""
    MoveSpec, AgentMovesSpec = _make_move_spec_classes()

    # Ye Shunguang is physical; vortex element comes from the disorder, not her element
    ye = BuildSnapshot(
        agent_name="Ye Shunguang",  # DB display name with space → must normalize to ye_shunguang
        agent_element="physical",
        agent_level=60,
        agent_base_atk=1500,
        agent_anomaly_proficiency=200,
    )
    wind_agent = BuildSnapshot(
        agent_name="WindGuy",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    ice_agent = BuildSnapshot(
        agent_name="IceGuy",
        agent_element="ice",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    moves_db = {
        "ye_shunguang": AgentMovesSpec({}),
        "windguy": AgentMovesSpec({"wind_hit": MoveSpec(15000, 1.0, 1, "wind")}),
        "iceguy": AgentMovesSpec({"ice_hit": MoveSpec(15000, 1.0, 1, "ice")}),
    }
    builds = {"ye": ye, "wind_agent": wind_agent, "ice_agent": ice_agent}
    steps = [
        SimulatedAttackStep("wind_agent", "wind_hit", []),
        SimulatedAttackStep("ice_agent", "ice_hit", []),
    ]
    result = simulate(builds, steps, _vortex_enemy(), moves_db)
    vortices = [e for e in result.events if e.kind == "vortex"]
    assert len(vortices) == 1
    assert vortices[0].agent_id == "ye"


def test_yanagi_polarity_disorder():
    # 1. Setup Enemy
    enemy = EnemyProfile(
        name="Mock Practice Target",
        level=60,
        defense=50,
        fire_res=0,
        electric_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_duration_default=10.0,
    )

    # 2. Setup Builds including Yanagi
    yanagi = BuildSnapshot(
        agent_name="Yanagi",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=200,
    )
    burnice = BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )

    builds = {
        "yanagi": yanagi,
        "burnice": burnice,
    }

    # 3. Moves DB
    class MoveSpec:
        def __init__(
            self,
            buildup,
            duration_s,
            hits,
            element,
            consolidated=False,
            polarity_disorder=False,
        ):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = "ex_special"
            self.consolidated = consolidated
            self.polarity_disorder = polarity_disorder

    class AgentMovesSpec:
        def __init__(self, moves):
            self.moves = moves

    moves_db = {
        "yanagi": AgentMovesSpec(
            {
                "EX Special Attack: Gekka Ruten": MoveSpec(
                    15000,
                    1.5,
                    2,
                    "electric",
                    consolidated=True,
                    polarity_disorder=True,
                ),
            }
        ),
        "burnice": AgentMovesSpec(
            {
                "fire_move": MoveSpec(15000, 1.0, 1, "fire"),
            }
        ),
    }

    # 4. Step 1: Burnice triggers Fire Anomaly at t=1.0s (lasts until t=11.0s)
    # Step 2: Yanagi hits with EX Special Gekka Ruten.
    #   - Hit 1 (t=1.75s) triggers Electric Anomaly and overrides Fire -> standard Disorder
    #   - Hit 2 (t=2.5s): Electric aura active; EX Special Gekka Ruten triggers Polarity Disorder.
    steps = [
        SimulatedAttackStep("burnice", "fire_move", []),
        SimulatedAttackStep("yanagi", "EX Special Attack: Gekka Ruten", []),
    ]

    # 5. Run simulation
    result = simulate(builds, steps, enemy, moves_db)

    # 6. Assertions
    anoms = [e for e in result.events if e.kind == "anomaly"]
    assert len(anoms) == 2
    assert anoms[0].element == "fire"
    assert anoms[1].element == "electric"

    # We expect standard disorder at t=1.75s (Fire overriden by Electric)
    disorders = [e for e in result.events if e.kind == "disorder"]
    assert len(disorders) == 2  # One standard, one polarity!

    # First disorder: standard disorder of fire aura
    assert disorders[0].element == "fire"
    assert disorders[0].detail.get("disorder_kind") is None

    # Second disorder: Yanagi Polarity disorder on the same-element Electric Shock aura!
    assert disorders[1].element == "electric"
    assert disorders[1].detail.get("disorder_kind") == "polarity"
    assert disorders[1].damage > 0
    assert result.totals["disorder"] > 0


def _polarity_shared_setup():
    """Shared setup for polarity tests: Burnice (fire) + Yanagi (electric, 2-hit EX).

    Step sequence:
      - Burnice fires → fire anomaly (capacity=100, threshold=10000, buildup=15000).
      - Yanagi EX hit 1 (t≈1.75) → electric displaces fire → standard disorder + electric aura.
      - Yanagi EX hit 2 (t≈2.5)  → electric hits same-element electric aura → polarity!
    Electric (Shock) DoT ticks run ~0.625s apart; several land after t=2.5.
    """
    enemy = EnemyProfile(
        name="Mock Practice Target",
        level=60,
        defense=50,
        fire_res=0,
        electric_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_duration_default=10.0,
    )
    burnice = BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    yanagi = BuildSnapshot(
        agent_name="Yanagi",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=200,
    )
    return enemy, {"burnice": burnice, "yanagi": yanagi}


class _MoveSpec:
    def __init__(
        self,
        buildup,
        duration_s,
        hits,
        element,
        consolidated=False,
        polarity_disorder=False,
        polarity_additional_mv=0,
        polarity_ap_coeff_base=0,
        polarity_ap_coeff_growth=0,
    ):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = "ex_special"
        self.consolidated = consolidated
        self.polarity_disorder = polarity_disorder
        self.polarity_additional_mv = polarity_additional_mv
        self.polarity_ap_coeff_base = polarity_ap_coeff_base
        self.polarity_ap_coeff_growth = polarity_ap_coeff_growth


class _AgentMovesSpec:
    def __init__(self, moves):
        self.moves = moves


def _polarity_moves_db(
    polarity_additional_mv: int = 0,
    polarity_ap_coeff_base: int = 0,
    polarity_ap_coeff_growth: int = 0,
) -> dict:
    return {
        "burnice": _AgentMovesSpec(
            {
                "fire_move": _MoveSpec(15000, 1.0, 1, "fire"),
            }
        ),
        "yanagi": _AgentMovesSpec(
            {
                "EX Special Attack: Gekka Ruten": _MoveSpec(
                    15000,
                    1.5,
                    2,
                    "electric",
                    consolidated=True,
                    polarity_disorder=True,
                    polarity_additional_mv=polarity_additional_mv,
                    polarity_ap_coeff_base=polarity_ap_coeff_base,
                    polarity_ap_coeff_growth=polarity_ap_coeff_growth,
                ),
                # Zero-buildup follow-up hit (F-19: on-hit-gated Shock ticks need an
                # actual post-polarity hit to prove the aura survives polarity).
                "basic_electric_hit": _MoveSpec(0, 1.0, 1, "electric"),
            }
        ),
    }


def test_polarity_preserves_aura_and_ticks():
    """H2a: polarity must not wipe the active aura or prune its remaining DoT ticks.

    F-19 note: Shock ticks are on-hit-gated, so a further tick after the polarity
    event requires an actual subsequent hit — a follow-up basic hit is added within
    the aura's window to prove the aura (and its gating) survives polarity intact.
    """
    enemy, builds = _polarity_shared_setup()
    steps = [
        SimulatedAttackStep("burnice", "fire_move", []),
        SimulatedAttackStep("yanagi", "EX Special Attack: Gekka Ruten", []),
        SimulatedAttackStep("yanagi", "basic_electric_hit", []),
    ]

    result = simulate(builds, steps, enemy, _polarity_moves_db())

    polarity_events = [
        e
        for e in result.events
        if e.kind == "disorder" and e.detail.get("disorder_kind") == "polarity"
    ]
    assert len(polarity_events) == 1, "polarity should fire exactly once"

    polarity_t = polarity_events[0].t
    # Electric (Shock) DoT ticks must still appear AFTER the polarity event
    post_polarity_ticks = [
        e
        for e in result.events
        if e.kind == "anomaly_tick" and e.element == "electric" and e.t > polarity_t
    ]
    assert len(post_polarity_ticks) > 0, "electric DoT ticks after polarity must not be pruned"


def test_polarity_additional_mv_applied():
    """H2a: polarity damage must include the additional_mv term from the move spec."""
    enemy, builds = _polarity_shared_setup()
    steps = [
        SimulatedAttackStep("burnice", "fire_move", []),
        SimulatedAttackStep("yanagi", "EX Special Attack: Gekka Ruten", []),
    ]

    def _polarity_dmg(polarity_additional_mv: int) -> int:
        r = simulate(builds, steps, enemy, _polarity_moves_db(polarity_additional_mv))
        pol = [
            e
            for e in r.events
            if e.kind == "disorder" and e.detail.get("disorder_kind") == "polarity"
        ]
        return pol[0].damage if pol else 0

    dmg_base = _polarity_dmg(0)
    dmg_bonus = _polarity_dmg(25000)  # +250% additional MV (Yanagi kit value)

    assert dmg_base > 0, "polarity should deal damage"
    assert dmg_bonus > dmg_base, "+250% additional_mv must increase polarity damage"


def test_polarity_ap_coeff_adds_flat_base():
    """H2b: polarity_ap_coeff_base/growth × Yanagi's current AP adds a flat base DMG term.

    Yanagi AP=200, coeff_base=7250, coeff_growth=2250, skill_level=12 (default).
    effective_coeff = 7250 + 2250*11 = 32000 (3200% @ T12, verified nanoka.cc + Leifa).
    flat_base = 200 * 32000 // 10000 = 640 added to base before multipliers.
    Damage with coeff must exceed damage without.
    """
    enemy, builds = _polarity_shared_setup()
    steps = [
        SimulatedAttackStep("burnice", "fire_move", []),
        SimulatedAttackStep("yanagi", "EX Special Attack: Gekka Ruten", []),
    ]

    def _polarity_dmg(ap_coeff_base: int, ap_coeff_growth: int) -> int:
        r = simulate(
            builds,
            steps,
            enemy,
            _polarity_moves_db(
                polarity_ap_coeff_base=ap_coeff_base,
                polarity_ap_coeff_growth=ap_coeff_growth,
            ),
        )
        pol = [
            e
            for e in r.events
            if e.kind == "disorder" and e.detail.get("disorder_kind") == "polarity"
        ]
        return pol[0].damage if pol else 0

    dmg_no_ap = _polarity_dmg(0, 0)
    dmg_with_ap = _polarity_dmg(7250, 2250)  # T12 = 3200%

    assert dmg_no_ap > 0, "polarity without AP coeff should still deal damage"
    assert dmg_with_ap > dmg_no_ap, "flat AP term must increase polarity damage"


def test_ye_shunguang_veil_override_simulation():
    # 1. Setup Enemy
    enemy = EnemyProfile(
        name="Mock Target",
        level=60,
        defense=50,
        physical_res=0,
        anomaly_duration_default=10.0,
    )

    # 2. Setup Ye Shunguang BuildSnapshot
    from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget

    ysg_build = BuildSnapshot(
        agent_name="Ye Shunguang",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,  # Disable crits to make math deterministic
        agent_crit_dmg=0,
        modifiers=[
            Modifier(
                stat="stun_area_override",
                value=1000,
                source=ModifierSource.CORE_SKILL,
                source_label="Veil Vulnerability",
                target=ModifierTarget.SELF,
                conditions=(Condition.VEIL_ACTIVE,),
                max_stacks=11,
            )
        ],
        stack_counts={"Veil Vulnerability": 11},
    )

    builds = {
        "ysg": ysg_build,
    }

    # 3. Setup Moves DB
    class MoveSpec:
        def __init__(self, buildup, duration_s, hits, element):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = "basic"

    class AgentMovesSpec:
        def __init__(self, moves):
            self.moves = moves

    moves_db = {
        "ye_shunguang": AgentMovesSpec(
            {
                "basic_move": MoveSpec(0, 1.0, 1, "physical"),
            }
        ),
    }

    # 4. Step 1: No conditions (out of stun, no veil)
    # Step 2: With veil_active condition (out of stun, with veil stacks)
    steps = [
        SimulatedAttackStep(
            agent_id="ysg",
            move_name="basic_move",
            attacks=[MockAttack("Basic Hit 1", 1000, "physical")],
            conditions=[],
        ),
        SimulatedAttackStep(
            agent_id="ysg",
            move_name="basic_move",
            attacks=[MockAttack("Basic Hit 2", 1000, "physical")],
            conditions=["veil_active"],
        ),
    ]

    # 5. Run simulation
    result = simulate(builds, steps, enemy, moves_db)

    # 6. Assertions
    assert not result.warnings
    hit_events = [e for e in result.events if e.kind == "hit"]
    assert len(hit_events) == 2

    # First hit: standard damage without stun/veil
    # ATK=1000, mult=1000 -> base=100. def=0.5. res=1.0. stun=1.0. -> total = 50
    assert hit_events[0].damage == 50

    # Second hit: veil_active is toggled on, so stun_area_override applies!
    # Stacks=11 → override=11000 bp (110%) → stun_mult=1.0+1.1=2.1× (21000 bp)
    # total = base * def * stun_mult = 100 * 0.5 * 2.1 = 105
    assert hit_events[1].damage == 105


def test_teammate_active_modifier_propagation():
    # 1. Setup Enemy
    enemy = EnemyProfile(
        name="Mock Target",
        level=60,
        defense=50,
        physical_res=0,
    )

    # 2. Setup Builds including a support teammate (Lucy) who has an active-target ATK buff
    from app.services.modifiers import Condition, Modifier, ModifierSource, ModifierTarget

    dps_build = BuildSnapshot(
        agent_name="Billy",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=0,
        modifiers=[],
    )

    # Lucy core cheer_on active ATK buff: flat_atk +200, conditional on cheer_on_active
    lucy_buff = Modifier(
        stat="flat_atk",
        value=200,
        source=ModifierSource.CORE_SKILL,
        source_label="Cheer On: ATK buff",
        target=ModifierTarget.ACTIVE,
        conditions=(Condition.ALWAYS,),
    )

    lucy_build = BuildSnapshot(
        agent_name="Lucy",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        modifiers=[lucy_buff],
    )

    builds = {
        "billy": dps_build,
        "lucy": lucy_build,
    }

    # 3. Setup Moves DB
    class MoveSpec:
        def __init__(self, buildup, duration_s, hits, element):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = "basic"

    class AgentMovesSpec:
        def __init__(self, moves):
            self.moves = moves

    moves_db = {
        "billy": AgentMovesSpec(
            {
                "basic_move": MoveSpec(0, 1.0, 1, "physical"),
            }
        ),
    }

    # 4. Step: Billy hits with Basic Attack
    steps = [
        SimulatedAttackStep(
            agent_id="billy",
            move_name="basic_move",
            attacks=[MockAttack("Basic Hit 1", 1000, "physical")],
            conditions=[],
        ),
    ]

    # 5. Run simulation
    result = simulate(builds, steps, enemy, moves_db)

    # 6. Assertions
    assert not result.warnings
    hit_events = [e for e in result.events if e.kind == "hit"]
    assert len(hit_events) == 1

    # Base damage with Lucy active ATK buff:
    # Billy base ATK = 1000. Lucy ATK buff = +200 flat ATK.
    # Total ATK = 1200. Mult = 1000 (10%) -> Base = 120. DEF mult = 0.5 -> Total damage = 60.
    # Without the buff, Billy ATK = 1000, Base = 100, DEF = 0.5 -> Total damage = 50.
    assert hit_events[0].damage == 60


def test_anomaly_mastery_used_directly_no_fallback():
    """Task 3 — simulate() must use ctx.stats.anomaly_mastery as-is; no 'or 100' fallback.

    Build with agent_anomaly_mastery=114 should produce more buildup than one with AM=100,
    proving the real value (not a hardcoded 100) flows through calculate_buildup.
    """

    class MoveSpec:
        def __init__(self, buildup, duration_s, hits, element, scope):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = scope

    class AgentMovesSpec:
        def __init__(self, agent_id, agent_name, moves):
            self.agent_id = agent_id
            self.agent_name = agent_name
            self.moves = moves

    # capacity=100 is the "default" sentinel: threshold = 100 * 100 = 10000 buildup units.
    # buildup=9000, hits=1:
    #   AM=100 → 9000 * 100 // 100 = 9000  (<10000, no trigger)
    #   AM=114 → 9000 * 114 // 100 = 10260 (>10000, triggers)
    # If 'or 100' fallback were still present, AM=114 would be clamped to 100 and also miss.
    enemy_threshold = EnemyProfile(
        name="Mock Practice Target",
        level=60,
        defense=50,
        fire_res=0,
        anomaly_capacity_fire=100,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )

    moves_db = {
        "burnice": AgentMovesSpec(
            agent_id="burnice_id",
            agent_name="Burnice",
            moves={
                "EX Special Attack: Fire": MoveSpec(
                    buildup=9000,
                    duration_s=1.0,
                    hits=1,
                    element="fire",
                    scope="special",
                )
            },
        )
    }

    steps = [
        SimulatedAttackStep(
            agent_id="burnice_id",
            move_name="EX Special Attack: Fire",
            attacks=[MockAttack("Fire Hit", 1000, "fire")],
            conditions=[],
        )
    ]

    build_am100 = BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_mastery=100,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )
    build_am114 = BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_mastery=114,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )

    result_100 = simulate({"burnice_id": build_am100}, steps, enemy_threshold, moves_db)
    result_114 = simulate({"burnice_id": build_am114}, steps, enemy_threshold, moves_db)

    anomaly_100 = [e for e in result_100.events if e.kind == "anomaly"]
    anomaly_114 = [e for e in result_114.events if e.kind == "anomaly"]

    assert len(anomaly_100) == 0, "AM=100 should not meet threshold=10000 with buildup=9000"
    assert len(anomaly_114) == 1, "AM=114 should exceed threshold=10000 (check 'or 100' fallback)"


# ---------------------------------------------------------------------------
# Task 6 — Threshold ×100 (Cluster B)
# ---------------------------------------------------------------------------


class TestThresholdUniform:
    """Threshold must always be capacity * 100 regardless of the capacity value.

    Old formula: capacity*100 if capacity==100 else capacity*10
    Correct formula: capacity*100 for all capacities.

    Pin test: with capacity=600 and 6 hits each adding 10000 buildup (AM=100),
    the old formula triggers on every hit (threshold=6000 < 10000), producing 6
    anomaly events.  The correct formula triggers once after the 6th hit
    (cumulative 60000 == threshold), producing exactly 1 anomaly event.
    """

    # Helper builders so each test stays self-contained.
    class _MoveSpec:
        def __init__(self, buildup: int, element: str):
            self.buildup = buildup
            self.duration_s = 1.0
            self.hits = 1
            self.element = element
            self.scope = "special"

    class _AgentMovesSpec:
        def __init__(self, agent_id: str, agent_name: str, moves: dict):
            self.agent_id = agent_id
            self.agent_name = agent_name
            self.moves = moves

    def _make_enemy(self, capacity: int) -> EnemyProfile:
        return EnemyProfile(
            name="Test Target",
            level=60,
            defense=0,
            fire_res=0,
            anomaly_capacity_fire=capacity,
            anomaly_res_fire=0,
            anomaly_duration_default=10.0,
            stun_buildup_multiplier=10000,
        )

    def _make_build(self) -> "BuildSnapshot":
        return BuildSnapshot(
            agent_name="Burnice",
            agent_element="fire",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_mastery=100,
            agent_anomaly_proficiency=100,
            modifiers=[],
        )

    def test_capacity_600_triggers_once_after_six_hits(self):
        # capacity=600 → threshold=60000.
        # Move has total buildup=60000, 6 hits → each hit contributes 10000 (AM=100, no bonus).
        # Cumulative after 6 hits: 60000 == threshold → exactly 1 anomaly trigger.
        #
        # Old formula (capacity*10=6000): first hit (10000>6000) triggers immediately,
        # resets the gauge; then 5 more triggers.  Total: 6 triggers, proving the regression.
        enemy = self._make_enemy(600)
        build = self._make_build()
        agent_id = "burnice_id"

        class _Move60k:
            buildup = 60000
            duration_s = 1.0
            hits = 6
            element = "fire"
            scope = "special"

        moves_spec = self._AgentMovesSpec(
            agent_id=agent_id,
            agent_name="Burnice",
            moves={"fire_move": _Move60k()},
        )
        moves_db = {"burnice": moves_spec}
        builds = {agent_id: build}

        steps = [
            SimulatedAttackStep(
                agent_id=agent_id,
                move_name="fire_move",
                attacks=[MockAttack(f"hit_{i}", 100, "fire") for i in range(6)],
                conditions=[],
            )
        ]

        result = simulate(builds, steps, enemy, moves_db)
        anom_events = [e for e in result.events if e.kind == "anomaly"]
        # capacity=600 → threshold=60000; 6x10000 buildup → exactly 1 trigger
        assert len(anom_events) == 1, f"expected 1 trigger, got {len(anom_events)}"

    def test_capacity_600_no_trigger_below_threshold(self):
        # 5 hits x 10000 = 50000 < threshold=60000 → no trigger.
        enemy = self._make_enemy(600)
        build = self._make_build()
        agent_id = "burnice_id"

        class _Move50k:
            buildup = 50000
            duration_s = 1.0
            hits = 5
            element = "fire"
            scope = "special"

        moves_spec = self._AgentMovesSpec(
            agent_id=agent_id,
            agent_name="Burnice",
            moves={"fire_move": _Move50k()},
        )
        moves_db = {"burnice": moves_spec}
        builds = {agent_id: build}

        steps = [
            SimulatedAttackStep(
                agent_id=agent_id,
                move_name="fire_move",
                attacks=[MockAttack(f"hit_{i}", 100, "fire") for i in range(5)],
                conditions=[],
            )
        ]

        result = simulate(builds, steps, enemy, moves_db)
        anom_events = [e for e in result.events if e.kind == "anomaly"]
        # capacity=600 → threshold=60000; 5x10000=50000 should not trigger
        assert len(anom_events) == 0, f"expected 0 triggers, got {len(anom_events)}"


class TestAliceDisorderDurationScaling:
    """Alice core passive: Disorder DMG +18%/s remaining Assault duration (max 180%).

    Verified by running two scenarios where an electric aura triggers disorder
    from Alice's physical aura at different remaining durations.  The early
    trigger (most duration remaining) must produce more disorder DMG than the
    late trigger (little duration remaining).
    """

    def _enemy(self) -> EnemyProfile:
        return EnemyProfile(
            name="Alice Duration Test",
            level=60,
            defense=50,
            physical_res=0,
            electric_res=0,
            anomaly_capacity_physical=100,
            anomaly_capacity_electric=100,
            anomaly_duration_default=10.0,
        )

    def _alice_build(self) -> BuildSnapshot:
        duration_mod = Modifier(
            stat="disorder_duration_bonus_rate",
            value=1800,
            source=ModifierSource.CORE_SKILL,
            source_label="Core: Disorder Duration Scaling",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
        )
        return BuildSnapshot(
            agent_name="Alice",
            agent_element="physical",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=120,
            modifiers=[duration_mod],
        )

    def _grace_build(self) -> BuildSnapshot:
        return BuildSnapshot(
            agent_name="Grace",
            agent_element="electric",
            agent_level=60,
            agent_base_atk=800,
            agent_anomaly_proficiency=100,
            modifiers=[],
        )

    class _MoveSpec:
        def __init__(self, buildup, duration_s, hits, element):
            self.buildup = buildup
            self.duration_s = duration_s
            self.hits = hits
            self.element = element
            self.scope = "basic"
            self.consolidated = False
            self.polarity_disorder = False
            self.polarity_additional_mv = 0
            self.polarity_ap_coeff_base = 0
            self.polarity_ap_coeff_growth = 0

    class _AgentMovesSpec:
        def __init__(self, moves):
            self.moves = moves

    def _moves_db(self):
        return {
            "alice": self._AgentMovesSpec(
                {
                    # High buildup to trigger Assault in one hit
                    "phys_move": self._MoveSpec(100000, 1.0, 1, "physical"),
                    # Zero-buildup filler: burns clock without refreshing the aura
                    "idle": self._MoveSpec(0, 1.0, 1, "physical"),
                }
            ),
            "grace": self._AgentMovesSpec(
                {
                    # Electric move triggers disorder from Alice's Assault aura
                    "elec_move": self._MoveSpec(100000, 1.0, 1, "electric"),
                }
            ),
        }

    def _disorder_dmg(self, grace_delay_steps: int) -> int:
        """Run sim; insert `grace_delay_steps` idle Alice moves before Grace triggers.

        Each idle step consumes 1s of the 10s Assault aura without refreshing it,
        so disorder is triggered with (10 - delay) seconds remaining.
        """
        alice = self._alice_build()
        grace = self._grace_build()
        builds = {"alice": alice, "grace": grace}
        enemy = self._enemy()

        steps = (
            [SimulatedAttackStep("alice", "phys_move", [], conditions=[])]
            + [
                SimulatedAttackStep("alice", "idle", [], conditions=[])
                for _ in range(grace_delay_steps)
            ]
            + [SimulatedAttackStep("grace", "elec_move", [], conditions=[])]
        )
        result = simulate(builds, steps, enemy, self._moves_db())
        disorder_events = [e for e in result.events if e.kind == "disorder"]
        return sum(e.damage for e in disorder_events if e.damage)

    def test_disorder_dmg_increases_with_remaining_duration(self):
        """Early trigger (more time remaining) must deal more disorder DMG than late trigger."""
        early_dmg = self._disorder_dmg(grace_delay_steps=0)  # trigger right after Alice
        # 7 idles + 1s switch = 8s consumed; hit at t=10.0 with 1s aura remaining.
        # (8 idles would hit exactly at expiry t=11.0, which prunes the aura first.)
        late_dmg = self._disorder_dmg(grace_delay_steps=7)  # 7 extra 1s moves burn ~7s

        assert early_dmg > 0, "disorder should fire"
        assert late_dmg > 0, "disorder should fire on late trigger too"
        assert early_dmg > late_dmg, (
            f"early trigger (more duration remaining) should deal more DMG: "
            f"early={early_dmg}, late={late_dmg}"
        )

    def test_modifier_adds_bonus_on_top_of_intrinsic_scaling(self):
        """Alice's modifier must add disorder DMG on top of the intrinsic t×750 ASSAULT scaling.

        At the same trigger timing, a build WITH disorder_duration_bonus_rate must deal
        more disorder DMG than one without.
        """
        grace = self._grace_build()
        enemy = self._enemy()

        def _dmg_at_delay(delay: int, with_modifier: bool) -> int:
            if with_modifier:
                alice = self._alice_build()
            else:
                alice = BuildSnapshot(
                    agent_name="Alice",
                    agent_element="physical",
                    agent_level=60,
                    agent_base_atk=1000,
                    agent_anomaly_proficiency=120,
                    modifiers=[],
                )
            steps = (
                [SimulatedAttackStep("alice", "phys_move", [], conditions=[])]
                + [SimulatedAttackStep("alice", "idle", [], conditions=[]) for _ in range(delay)]
                + [SimulatedAttackStep("grace", "elec_move", [], conditions=[])]
            )
            r = simulate({"alice": alice, "grace": grace}, steps, enemy, self._moves_db())
            return sum(e.damage for e in r.events if e.kind == "disorder" and e.damage)

        # Test at delay=0 (most remaining duration → largest Alice modifier bonus)
        with_mod = _dmg_at_delay(0, with_modifier=True)
        without_mod = _dmg_at_delay(0, with_modifier=False)
        assert with_mod > 0
        assert with_mod > without_mod, (
            f"Alice's modifier must increase disorder DMG: with={with_mod}, without={without_mod}"
        )


# ---------------------------------------------------------------------------
# Task A4 — Abloom trigger in the simulator
# ---------------------------------------------------------------------------


class _AbloomMoveSpec:
    """Minimal MoveSpec with abloom_mv_by_element for Abloom trigger tests."""

    def __init__(
        self,
        buildup: int,
        duration_s: float,
        hits: int,
        element: str,
        abloom_mv_by_element: dict[str, int] | None = None,
        abloom_ap_scaled: bool = True,
        abloom_stat: str = "anomaly_proficiency",
        abloom_stun_mv_bonus: int = 0,
        requires_charge_level: int = 0,
    ):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = "basic"
        self.consolidated = False
        self.polarity_disorder = False
        self.polarity_additional_mv = 0
        self.polarity_ap_coeff_base = 0
        self.polarity_ap_coeff_growth = 0
        self.abloom_mv_by_element = abloom_mv_by_element
        self.abloom_ap_scaled = abloom_ap_scaled
        self.abloom_stat = abloom_stat
        self.abloom_stun_mv_bonus = abloom_stun_mv_bonus
        self.requires_charge_level = requires_charge_level


@dataclass
class _SequentialHit:
    """Stand-in for one DB Attack row of a sequential combo.

    `hit_index` drives the Abloom final-hit gate; `hit_mode` drives the whole-cycle
    buildup divisor. Both mirror real `Attack` columns.
    """

    hit_index: int
    hit_mode: HitMode = HitMode.SEQUENTIAL
    name: str = "sequential_move"
    element: str = "ether"
    skill_key: str = "Basic"
    damage_base: int = 0
    damage_growth: int = 0
    anomaly_buildup: int = 0
    energy_gain: int = 0
    id: str | None = None


class _AbloomAgentMovesSpec:
    def __init__(self, moves: dict):
        self.moves = moves


def _abloom_enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Abloom Test Target",
        level=60,
        defense=0,
        fire_res=0,
        electric_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_duration_default=10.0,
    )


def _vivian_build(ap: int = 120) -> "BuildSnapshot":
    return BuildSnapshot(
        agent_name="Vivian",
        agent_element="ether",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=ap,
        modifiers=[],
    )


def _burnice_build() -> "BuildSnapshot":
    return BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )


def test_abloom_fires_on_flagged_move_with_active_aura():
    """Flagged move on an active aura fires exactly one Abloom of the aura's element."""
    enemy = _abloom_enemy()
    burnice = _burnice_build()
    vivian = _vivian_build(ap=120)
    builds = {"burnice": burnice, "vivian": vivian}

    moves_db = {
        "burnice": _AbloomAgentMovesSpec(
            {
                "fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire"),
            }
        ),
        "vivian": _AbloomAgentMovesSpec(
            {
                # Vivian Featherbloom: fire MV = 800 (8%/10AP, Leifa LOG_abloom.md A1)
                "featherbloom": _AbloomMoveSpec(
                    0,
                    1.0,
                    1,
                    "ether",
                    abloom_mv_by_element={"fire": 800, "electric": 320},
                ),
            }
        ),
    }

    steps = [
        SimulatedAttackStep("burnice", "fire_move", []),  # triggers fire aura
        SimulatedAttackStep("vivian", "featherbloom", []),  # Abloom fires on fire aura
    ]

    result = simulate(builds, steps, enemy, moves_db)

    abloom_events = [e for e in result.events if e.kind == "abloom"]
    assert len(abloom_events) == 1, f"expected 1 Abloom, got {len(abloom_events)}"
    ev = abloom_events[0]
    assert ev.element == "fire", "Abloom element must match the active aura element"
    assert ev.damage > 0, "Abloom must deal positive damage"
    assert ev.agent_id == "vivian", "Abloom attributed to triggering agent"
    assert result.totals.get("abloom", 0) > 0, "abloom total must be positive"
    assert result.totals["total"] > 0


def test_abloom_aura_preserved_after_trigger():
    """Active aura and its ticks must survive an Abloom trigger (Abloom coexists)."""
    enemy = _abloom_enemy()
    burnice = _burnice_build()
    vivian = _vivian_build(ap=120)
    builds = {"burnice": burnice, "vivian": vivian}

    moves_db = {
        "burnice": _AbloomAgentMovesSpec(
            {
                "fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire"),
            }
        ),
        "vivian": _AbloomAgentMovesSpec(
            {
                "featherbloom": _AbloomMoveSpec(
                    0,
                    1.0,
                    1,
                    "ether",
                    abloom_mv_by_element={"fire": 800},
                ),
            }
        ),
    }

    steps = [
        SimulatedAttackStep("burnice", "fire_move", []),
        SimulatedAttackStep("vivian", "featherbloom", []),
        # Vivian hits again after Abloom — fire ticks should still be present
        SimulatedAttackStep("vivian", "featherbloom", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    # Aura still active: second Vivian step must also produce an Abloom
    abloom_events = [e for e in result.events if e.kind == "abloom"]
    assert len(abloom_events) == 2, "each flagged step on active aura should produce one Abloom"

    # Fire DoT ticks must still exist (Abloom did not consume the aura)
    fire_ticks = [e for e in result.events if e.kind == "anomaly_tick" and e.element == "fire"]
    assert len(fire_ticks) > 0, "fire DoT ticks must remain after Abloom trigger"


def test_abloom_no_fire_on_bare_enemy():
    """Flagged move on enemy with no active aura → no Abloom."""
    enemy = _abloom_enemy()
    vivian = _vivian_build(ap=120)
    builds = {"vivian": vivian}

    moves_db = {
        "vivian": _AbloomAgentMovesSpec(
            {
                "featherbloom": _AbloomMoveSpec(
                    0,
                    1.0,
                    1,
                    "ether",
                    abloom_mv_by_element={"fire": 800},
                ),
            }
        ),
    }

    steps = [
        SimulatedAttackStep("vivian", "featherbloom", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    abloom_events = [e for e in result.events if e.kind == "abloom"]
    assert len(abloom_events) == 0, "no aura → no Abloom"
    assert result.totals.get("abloom", 0) == 0


def test_abloom_no_fire_on_unflagged_move():
    """Unflagged move (no abloom_mv_by_element) on active aura → no Abloom."""
    enemy = _abloom_enemy()
    burnice = _burnice_build()
    vivian = _vivian_build(ap=120)
    builds = {"burnice": burnice, "vivian": vivian}

    moves_db = {
        "burnice": _AbloomAgentMovesSpec(
            {
                "fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire"),
            }
        ),
        "vivian": _AbloomAgentMovesSpec(
            {
                # No abloom_mv_by_element — unflagged
                "regular_move": _AbloomMoveSpec(0, 1.0, 1, "ether"),
            }
        ),
    }

    steps = [
        SimulatedAttackStep("burnice", "fire_move", []),
        SimulatedAttackStep("vivian", "regular_move", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    abloom_events = [e for e in result.events if e.kind == "abloom"]
    assert len(abloom_events) == 0, "unflagged move must never produce Abloom"
    assert result.totals.get("abloom", 0) == 0


def _requires_charge_level_abloom_events(presses: int, requires_charge_level: int) -> int:
    """Abloom event count over *presses* single-tap presses of a 5-hit sequential move.

    Mirrors how `combo_step_resolver` / `optimizer_pipeline` actually resolve a
    `hit_mode='sequential'` move: one Attack row per step, hit_index cycling 0-4.
    """
    enemy = _abloom_enemy()
    burnice = _burnice_build()
    aria = _vivian_build(ap=120)
    builds = {"burnice": burnice, "vivian": aria}

    moves_db = {
        "burnice": _AbloomAgentMovesSpec({"fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire")}),
        "vivian": _AbloomAgentMovesSpec(
            {
                # 0.5s/press keeps all 10 presses inside the 10s fire aura, so the
                # counts below measure the gate and not aura expiry.
                "perfect_pitch": _AbloomMoveSpec(
                    0,
                    0.5,
                    5,
                    "ether",
                    abloom_mv_by_element={"fire": 800},
                    requires_charge_level=requires_charge_level,
                ),
            }
        ),
    }

    steps = [SimulatedAttackStep("burnice", "fire_move", [])]
    steps += [
        SimulatedAttackStep("vivian", "perfect_pitch", [_SequentialHit(hit_index=i % 5)])
        for i in range(presses)
    ]

    result = simulate(builds, steps, enemy, moves_db)
    return len([e for e in result.events if e.kind == "abloom"])


def test_abloom_requires_charge_level_fires_once_per_sequential_cycle():
    """`requires_charge_level` binds Abloom to the final hit of the sequential cycle.

    Unit-level guard for the Aria Perfect Pitch gate (#77 / PR #79). The integration
    coverage in `tests/integration/test_abloom_crossval.py::TestAriaAbloom` needs the
    seeded app DB and therefore skips in CI, leaving this behaviour unverified there.
    Two full cycles (10 single-tap presses) must produce exactly 2 Abloom events, not 10.
    """
    assert _requires_charge_level_abloom_events(presses=10, requires_charge_level=3) == 2


def test_abloom_without_charge_level_fires_on_every_sequential_press():
    """Control: the same move without the gate fires on every press.

    Pins that the assertion above is testing the gate itself rather than some
    incidental once-per-cycle behaviour of the aura or the step loop.
    """
    assert _requires_charge_level_abloom_events(presses=10, requires_charge_level=0) == 10


def _applied_move_buildup(monkeypatch, hit_mode: HitMode, presses: int) -> int:
    """Total `move_buildup` the simulator feeds `calculate_buildup` over *presses* steps.

    Each step carries exactly one Attack row of a 5-hit move whose curated spec
    authors `buildup=50_000` as the whole-move total.
    """
    import app.services.anomaly_simulator as sim_mod

    recorded: list[int] = []
    original = sim_mod.calculate_buildup

    def _spy(**kwargs):
        recorded.append(kwargs["move_buildup"])
        return original(**kwargs)

    monkeypatch.setattr(sim_mod, "calculate_buildup", _spy)

    builds = {"vivian": _vivian_build()}
    moves_db = {
        "vivian": _AbloomAgentMovesSpec({"combo": _AbloomMoveSpec(50_000, 1.0, 5, "ether")})
    }
    steps = [
        SimulatedAttackStep(
            "vivian", "combo", [_SequentialHit(hit_index=i % 5, hit_mode=hit_mode)]
        )
        for i in range(presses)
    ]
    simulate(builds, steps, _abloom_enemy(), moves_db)
    return sum(recorded)


def test_sequential_single_tap_spreads_buildup_over_the_whole_cycle(monkeypatch):
    """A curated `buildup` is a whole-move total, so one press applies only its share.

    `hit_mode='sequential'` moves are always resolved single-tap (one Attack row per
    step) by combo_step_resolver and optimizer_pipeline, so `len(step.attacks)` is 1
    while the authored total covers all 5 hits. Dividing by the step's hit count
    applied the full cycle total on *every* press — a 5x anomaly-buildup over-count on
    Aria's Perfect Pitch, Grace's High-Pressure Spike and Burnice's Direct Flame Blend.
    """
    applied = _applied_move_buildup(monkeypatch, HitMode.SEQUENTIAL, presses=10)
    # 2 full cycles of a 50_000 whole-move total, not 10x50_000.
    assert applied == 100_000


def test_atomic_step_buildup_divisor_is_unchanged(monkeypatch):
    """Control: an atomic row keeps this step's own hit count as the divisor.

    An atomic move's authored `hits` is an animation-hit count that legitimately
    exceeds its DB row count (Burnice's Stirring Method authors 6 over 2 rows), and
    every row lands in the same step — so the sequential rule must not apply here.
    """
    applied = _applied_move_buildup(monkeypatch, HitMode.ATOMIC, presses=10)
    assert applied == 500_000


def test_kit_formula_buildup_stays_per_step_on_a_sequential_move(monkeypatch):
    """A kit formula's gauge is granted per *step*, so it keeps the per-step divisor.

    It shares the buildup path with the move's own total but not its basis — folding
    both into one accumulator would have shrunk Burnice's afterburn gauge 5x the
    moment the whole-cycle divisor landed.
    """
    import app.services.anomaly_simulator as sim_mod
    from app.services.kit_formulas import KitFormula

    recorded: list[int] = []
    original = sim_mod.calculate_buildup

    def _spy(**kwargs):
        recorded.append(kwargs["move_buildup"])
        return original(**kwargs)

    monkeypatch.setattr(sim_mod, "calculate_buildup", _spy)

    snap = replace(
        _vivian_build(),
        kit_formulas=(
            KitFormula(name="afterburn", quantity="anom_buildup", scope="basic", buildup=6_000),
        ),
    )
    moves_db = {
        "vivian": _AbloomAgentMovesSpec({"combo": _AbloomMoveSpec(50_000, 1.0, 5, "ether")})
    }
    steps = [
        SimulatedAttackStep("vivian", "combo", [_SequentialHit(hit_index=0)]),
    ]
    simulate({"vivian": snap}, steps, _abloom_enemy(), moves_db)

    # One press: 50_000/5 of the move total, plus the kit formula's full per-step 6_000.
    assert sum(recorded) == 10_000 + 6_000


def _applied_with_spec_buildup(monkeypatch, spec_buildup: int | None) -> int:
    """Total `move_buildup` applied for one atomic step whose rows carry 4_000 of gauge."""
    import app.services.anomaly_simulator as sim_mod

    recorded: list[int] = []
    original = sim_mod.calculate_buildup

    def _spy(**kwargs):
        recorded.append(kwargs["move_buildup"])
        return original(**kwargs)

    monkeypatch.setattr(sim_mod, "calculate_buildup", _spy)

    spec = _AbloomMoveSpec(spec_buildup, 1.0, 2, "ether")
    steps = [
        SimulatedAttackStep(
            "vivian",
            "combo",
            [
                _SequentialHit(hit_index=0, hit_mode=HitMode.ATOMIC, anomaly_buildup=1_000),
                _SequentialHit(hit_index=1, hit_mode=HitMode.ATOMIC, anomaly_buildup=3_000),
            ],
        )
    ]
    simulate(
        {"vivian": _vivian_build()},
        steps,
        _abloom_enemy(),
        {"vivian": _AbloomAgentMovesSpec({"combo": spec})},
    )
    return sum(recorded)


def test_omitted_buildup_falls_back_to_db_rows(monkeypatch):
    """An omitted (`None`) buildup means "not authored", not "authored as zero".

    Nine specs across Pulchra and Soldier 0 - Anby exist purely to carry non-buildup
    curation (`grants_state`, `grants_full_charge`, aftershock re-tags) and omit
    `buildup` entirely. Collapsing `None` to 0 made those specs silently delete every
    point of the move's real gauge — including S0 Anby's whole basic combo (51,063).
    The fallback is the same per-step DB row sum the no-spec path already computes.
    """
    assert _applied_with_spec_buildup(monkeypatch, None) == 4_000


def test_explicit_zero_buildup_still_suppresses(monkeypatch):
    """An authored `0` is a deliberate statement and must keep suppressing.

    The distinction matters: all 18 explicit zeros in the curated set are moves the DB
    independently agrees carry no gauge, so this path must not start inventing one.
    """
    assert _applied_with_spec_buildup(monkeypatch, 0) == 0


def test_abloom_damage_value_pin():
    """Pin test: Vivian (AP=120) Abloom on fire aura, fire MV=800.

    Abloom formula (Leifa LOG_abloom.md A1):
      total = original_anomaly_dmg * abloom_mv_bp * ap // 100_000
    where original_anomaly_dmg = per_proc of the Burn aura triggered by Burnice
    (AP=100, ATK=1000, level=60, no bonuses).

    We don't fix the exact aura DMG value here — just assert that scaling AP
    from 120 to 240 doubles Abloom DMG proportionally (the formula is linear in AP).
    """
    enemy = _abloom_enemy()

    def _abloom_dmg(vivian_ap: int) -> int:
        burnice = _burnice_build()
        vivian = _vivian_build(ap=vivian_ap)
        builds = {"burnice": burnice, "vivian": vivian}
        moves_db = {
            "burnice": _AbloomAgentMovesSpec(
                {
                    "fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire"),
                }
            ),
            "vivian": _AbloomAgentMovesSpec(
                {
                    "featherbloom": _AbloomMoveSpec(
                        0,
                        1.0,
                        1,
                        "ether",
                        abloom_mv_by_element={"fire": 800},
                    ),
                }
            ),
        }
        steps = [
            SimulatedAttackStep("burnice", "fire_move", []),
            SimulatedAttackStep("vivian", "featherbloom", []),
        ]
        r = simulate(builds, steps, enemy, moves_db)
        return sum(e.damage for e in r.events if e.kind == "abloom")

    dmg_120 = _abloom_dmg(120)
    dmg_240 = _abloom_dmg(240)
    assert dmg_120 > 0, "Abloom must deal positive damage"
    # AP doubles → Abloom DMG doubles (linear formula: dmg ∝ ap)
    assert dmg_240 == dmg_120 * 2, f"doubling AP must double Abloom DMG: {dmg_120}x2 != {dmg_240}"


def test_vivian_m2_abloom_mv_bonus_scales_damage():
    """Vivian M2 abloom_mv_bonus=3000 (×1.3) raises Abloom DMG to 130% of base.

    Source: agent_kit_atlas.json:4175 M2 "The benefits of Abloom from Anomaly
    Proficiency are raised to 130% of the original value." DECISIONS.md D14.
    Formula: total_with_m2 = (mv_bp / 10000) × (AP / 10) × orig_dmg × 1.3
    """
    enemy = _abloom_enemy()

    def _run_abloom(with_m2: bool) -> int:
        m2_modifier = Modifier(
            stat="abloom_mv_bonus",
            value=3000,
            source=ModifierSource.MINDSCAPE,
            source_label="M2: Abloom MV Bonus",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
        )
        vivian = BuildSnapshot(
            agent_name="Vivian",
            agent_element="ether",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=100,
            modifiers=[m2_modifier] if with_m2 else [],
        )
        burnice = _burnice_build()
        builds = {"burnice": burnice, "vivian": vivian}
        moves_db = {
            "burnice": _AbloomAgentMovesSpec(
                {
                    "fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire"),
                }
            ),
            "vivian": _AbloomAgentMovesSpec(
                {
                    # fire MV=800 (8%/10AP): agent_kit_atlas.json:4160 Core Passive
                    "featherbloom": _AbloomMoveSpec(
                        0,
                        1.0,
                        1,
                        "ether",
                        abloom_mv_by_element={"fire": 800},
                    ),
                }
            ),
        }
        steps = [
            SimulatedAttackStep("burnice", "fire_move", []),
            SimulatedAttackStep("vivian", "featherbloom", []),
        ]
        r = simulate(builds, steps, enemy, moves_db)
        return sum(e.damage for e in r.events if e.kind == "abloom")

    base_dmg = _run_abloom(with_m2=False)
    m2_dmg = _run_abloom(with_m2=True)

    assert base_dmg > 0, "base Abloom must be positive"
    # M2 raises MV to 130% — formula is linear in mv_bonus, so m2_dmg = base_dmg * 1.3
    # Integer arithmetic: base * 13000 // 10000
    expected = base_dmg * 13000 // 10000
    assert m2_dmg == expected, (
        f"M2 abloom_mv_bonus=3000 must yield {expected} (base {base_dmg} x 1.3), got {m2_dmg}"
    )


def test_frostfall_sickle_abloom_dmg_bonus_scales_damage():
    """Frostfall Sickle abloom_dmg_bonus=4000 (R1 ×1.4) raises Abloom DMG to 140% of base.

    Source: frostfall_sickle.json "Abloom DMG +40%..64%". R1=4000bp.
    """
    enemy = _abloom_enemy()

    def _run_abloom(with_sickle: bool) -> int:
        sickle_modifier = Modifier(
            stat="abloom_dmg_bonus",
            value=4000,
            source=ModifierSource.WENGINE_PASSIVE,
            source_label="Frostfall Sickle: Abloom DMG",
            target=ModifierTarget.SELF,
            conditions=(Condition.ALWAYS,),
        )
        vivian = BuildSnapshot(
            agent_name="Vivian",
            agent_element="ether",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=100,
            modifiers=[sickle_modifier] if with_sickle else [],
        )
        burnice = _burnice_build()
        builds = {"burnice": burnice, "vivian": vivian}
        moves_db = {
            "burnice": _AbloomAgentMovesSpec(
                {
                    "fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire"),
                }
            ),
            "vivian": _AbloomAgentMovesSpec(
                {
                    "featherbloom": _AbloomMoveSpec(
                        0,
                        1.0,
                        1,
                        "ether",
                        abloom_mv_by_element={"fire": 800},
                    ),
                }
            ),
        }
        steps = [
            SimulatedAttackStep("burnice", "fire_move", []),
            SimulatedAttackStep("vivian", "featherbloom", []),
        ]
        r = simulate(builds, steps, enemy, moves_db)
        return sum(e.damage for e in r.events if e.kind == "abloom")

    base_dmg = _run_abloom(with_sickle=False)
    sickle_dmg = _run_abloom(with_sickle=True)

    assert base_dmg > 0, "base Abloom must be positive"
    # R1 abloom_dmg_bonus=4000 → boost = 14000/10000 = 1.4×
    expected = base_dmg * 14000 // 10000
    assert sickle_dmg == expected, (
        f"Frostfall R1 abloom_dmg_bonus=4000 must yield {expected} "
        f"(base {base_dmg} x 1.4), got {sickle_dmg}"
    )


def test_m2_frostfall_stacking_additive_pin():
    """Pin: M2 (abloom_mv_bonus=3000) + Frostfall R1 (abloom_dmg_bonus=4000) stack additively.

    Current behavior: both bonuses sum into one abloom_dmg_bonus pool before
    calculate_abloom_damage, giving (1 + 7000/10000) = ×1.70 of base.

    ASSUMPTION UNVERIFIED — additive stacking assumed; ZO repo unavailable at
    time of writing (2026-05-31). In-game confirmation or ZO source needed to
    confirm additive vs multiplicative (×1.82). See DECISIONS.md D14, OQ-2,
    docs/LOG_abloom_v2.md C2.

    If the correct answer is multiplicative:
      - Scale mv_bp by (1 + abloom_mv_bonus/10000) before calculate_abloom_damage
      - Reserve abloom_dmg_bonus for true DMG% lines (Frostfall)
      - Update this test: expected = base * 14000 // 10000 * 13000 // 10000
    """
    enemy = _abloom_enemy()

    def _run_abloom(with_m2: bool, with_sickle: bool) -> int:
        modifiers = []
        if with_m2:
            modifiers.append(
                Modifier(
                    stat="abloom_mv_bonus",
                    value=3000,
                    source=ModifierSource.MINDSCAPE,
                    source_label="M2: Abloom MV Bonus",
                    target=ModifierTarget.SELF,
                    conditions=(Condition.ALWAYS,),
                )
            )
        if with_sickle:
            modifiers.append(
                Modifier(
                    stat="abloom_dmg_bonus",
                    value=4000,
                    source=ModifierSource.WENGINE_PASSIVE,
                    source_label="Frostfall Sickle: Abloom DMG",
                    target=ModifierTarget.SELF,
                    conditions=(Condition.ALWAYS,),
                )
            )
        vivian = BuildSnapshot(
            agent_name="Vivian",
            agent_element="ether",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=100,
            modifiers=modifiers,
        )
        burnice = _burnice_build()
        builds = {"burnice": burnice, "vivian": vivian}
        moves_db = {
            "burnice": _AbloomAgentMovesSpec(
                {
                    "fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire"),
                }
            ),
            "vivian": _AbloomAgentMovesSpec(
                {
                    "featherbloom": _AbloomMoveSpec(
                        0,
                        1.0,
                        1,
                        "ether",
                        abloom_mv_by_element={"fire": 800},
                    ),
                }
            ),
        }
        steps = [
            SimulatedAttackStep("burnice", "fire_move", []),
            SimulatedAttackStep("vivian", "featherbloom", []),
        ]
        r = simulate(builds, steps, enemy, moves_db)
        return sum(e.damage for e in r.events if e.kind == "abloom")

    base_dmg = _run_abloom(with_m2=False, with_sickle=False)
    combined_dmg = _run_abloom(with_m2=True, with_sickle=True)

    assert base_dmg > 0, "base Abloom must be positive"
    # Additive: (3000 + 4000) / 10000 = 0.70 → boost = 1 + 0.70 = ×1.70
    expected = base_dmg * 17000 // 10000
    assert combined_dmg == expected, (
        f"M2+Frostfall additive pin: expected {expected} (base {base_dmg} x1.70), "
        f"got {combined_dmg}. "
        f"If multiplicative is confirmed (x1.82), update formula and this pin."
    )


# ---------------------------------------------------------------------------
# C4 — per-move abloom_stat selector (AP vs AM)
# ---------------------------------------------------------------------------


def test_abloom_stat_am_uses_anomaly_mastery():
    """abloom_stat='anomaly_mastery' → Abloom scales on AM, not AP.

    Aria's path: the move sets abloom_stat='anomaly_mastery'.
    Two builds identical except AM (120 vs 240, same AP=0).
    Doubling AM must double Abloom DMG (formula is linear in the stat).
    """
    enemy = _abloom_enemy()

    def _aria_abloom_dmg(am: int) -> int:
        burnice = _burnice_build()
        aria = BuildSnapshot(
            agent_name="Aria",
            agent_element="ether",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=0,
            agent_anomaly_mastery=am,
            modifiers=[],
        )
        builds = {"burnice": burnice, "aria": aria}
        moves_db = {
            "burnice": _AbloomAgentMovesSpec(
                {
                    "fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire"),
                }
            ),
            "aria": _AbloomAgentMovesSpec(
                {
                    "featherbloom": _AbloomMoveSpec(
                        0,
                        1.0,
                        1,
                        "ether",
                        abloom_mv_by_element={"fire": 800},
                        abloom_stat="anomaly_mastery",
                    ),
                }
            ),
        }
        steps = [
            SimulatedAttackStep("burnice", "fire_move", []),
            SimulatedAttackStep("aria", "featherbloom", []),
        ]
        r = simulate(builds, steps, enemy, moves_db)
        return sum(e.damage for e in r.events if e.kind == "abloom")

    dmg_120 = _aria_abloom_dmg(am=120)
    dmg_240 = _aria_abloom_dmg(am=240)
    assert dmg_120 > 0, "AM-path Abloom must be positive"
    assert dmg_240 == dmg_120 * 2, f"doubling AM must double Abloom DMG: {dmg_120}x2 != {dmg_240}"


def test_abloom_stat_default_byte_identical_to_ap():
    """Default abloom_stat='anomaly_proficiency' is byte-identical to omitting the field.

    Ensures C4 doesn't break existing AP-scaled agents (Vivian, etc.).
    Compare explicit abloom_stat='anomaly_proficiency' vs. test without that field set
    at the same AP value.
    """
    enemy = _abloom_enemy()

    def _run(explicit_stat: str | None) -> int:
        burnice = _burnice_build()
        vivian = _vivian_build(ap=120)
        builds = {"burnice": burnice, "vivian": vivian}
        spec_kwargs: dict = {"abloom_mv_by_element": {"fire": 800}}
        if explicit_stat is not None:
            spec_kwargs["abloom_stat"] = explicit_stat
        moves_db = {
            "burnice": _AbloomAgentMovesSpec(
                {
                    "fire_move": _AbloomMoveSpec(15000, 1.0, 1, "fire"),
                }
            ),
            "vivian": _AbloomAgentMovesSpec(
                {
                    "featherbloom": _AbloomMoveSpec(0, 1.0, 1, "ether", **spec_kwargs),
                }
            ),
        }
        steps = [
            SimulatedAttackStep("burnice", "fire_move", []),
            SimulatedAttackStep("vivian", "featherbloom", []),
        ]
        r = simulate(builds, steps, enemy, moves_db)
        return sum(e.damage for e in r.events if e.kind == "abloom")

    dmg_default = _run(explicit_stat=None)
    dmg_explicit = _run(explicit_stat="anomaly_proficiency")
    assert dmg_default > 0
    assert dmg_explicit == dmg_default, (
        "explicit abloom_stat='anomaly_proficiency' must match default behaviour"
    )


# ---------------------------------------------------------------------------
# C5 — Aria base Abloom (AM path, Perfect Pitch 3rd hit)
# ---------------------------------------------------------------------------
# MVs are L7 (max core-passive level) from live DB: Core Passive: Innate Stage Presence.
# Source: agent_skills table, re-seeded 2026-05-31 via Part B audit.
# abloom_stat="anomaly_mastery" (AM), NOT anomaly_proficiency (AP).
# OQ-3 UNRESOLVED: "initial" Anomaly Mastery semantics not confirmed against ZO or in-game.
#   Modeled as LIVE AM (ctx.stats.anomaly_mastery at step time). If snapshot semantics
#   are verified, AM capture at anomaly application time must be added to the simulator.
# Stun bonus: +50% to MV ratio (abloom_stun_mv_bonus=5000 → mv_bp × 1.5 when stunned).
# ---------------------------------------------------------------------------

_ARIA_MV_L7 = {
    "ether": 2750,
    "electric": 1430,
    "fire": 3570,
    "physical": 250,
    "ice": 360,
    "wind": 140,
}

_ARIA_STUN_BONUS = 5000  # +50% MV when target stunned


def _aria_build(am: int = 100) -> "BuildSnapshot":
    """Aria build with anomaly_mastery as the Abloom stat."""
    return BuildSnapshot(
        agent_name="Aria",
        agent_element="ether",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_mastery=am,
        modifiers=[],
    )


def _aria_perfect_pitch_spec(stunned_bonus: int = _ARIA_STUN_BONUS) -> "_AbloomMoveSpec":
    """Perfect Pitch (Level 3) spec — the only charge level that triggers Abloom."""
    return _AbloomMoveSpec(
        buildup=0,
        duration_s=1.2,
        hits=1,
        element="ether",
        abloom_mv_by_element=_ARIA_MV_L7,
        abloom_stat="anomaly_mastery",
        abloom_stun_mv_bonus=stunned_bonus,
    )


def _aria_scenario(
    *,
    am: int = 100,
    is_stunned: bool = False,
    aura_element: str = "fire",
    stunned_bonus: int = _ARIA_STUN_BONUS,
) -> tuple[int, int]:
    """Run Aria Perfect Pitch on an active aura; return (abloom_dmg, expected_dmg)."""
    enemy = EnemyProfile(
        name="Aria Test Target",
        level=60,
        defense=0,
        fire_res=0,
        electric_res=0,
        ether_res=0,
        physical_res=0,
        ice_res=0,
        wind_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_capacity_ether=100,
        anomaly_capacity_physical=100,
        anomaly_capacity_ice=100,
        anomaly_capacity_wind=100,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )
    # Applier that raises an aura (same element as aura_element).
    applier = BuildSnapshot(
        agent_name="Applier",
        agent_element=aura_element,
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )
    aria = _aria_build(am=am)
    builds = {"applier": applier, "aria": aria}
    aura_move = _AbloomMoveSpec(15000, 1.0, 1, aura_element)
    moves_db = {
        "applier": _AbloomAgentMovesSpec({"aura_move": aura_move}),
        "aria": _AbloomAgentMovesSpec(
            {
                "perfect_pitch_l3": _aria_perfect_pitch_spec(stunned_bonus),
            }
        ),
    }
    steps: list = [SimulatedAttackStep("applier", "aura_move", [])]
    if is_stunned:
        steps.append(SimulatedAttackStep("aria", "stun_trigger", []))
    steps.append(SimulatedAttackStep("aria", "perfect_pitch_l3", []))
    result = simulate(builds, steps, enemy, moves_db)

    abloom_events = [e for e in result.events if e.kind == "abloom"]
    actual = sum(e.damage or 0 for e in abloom_events)

    # Compute expected: total = original_per_proc * mv_bp * am // 100_000
    # (abloom_boost_mult = 10000 → ×1.0; no bonus modifiers on aria build)
    mv_bp = _ARIA_MV_L7[aura_element]
    if is_stunned and stunned_bonus:
        mv_bp = mv_bp * (10000 + stunned_bonus) // 10000
    original_dmg = abloom_events[0].detail["original_anomaly_dmg"] if abloom_events else 0
    expected = original_dmg * mv_bp * am // 100_000

    return actual, expected


def test_aria_abloom_unstunned_ether_pin_l7():
    """Aria Perfect Pitch (L7) on active Ether/Corruption aura, unstunned.

    Pin: total = original_anomaly_dmg × 2750 × am // 100_000 (am=100).
    OQ-3 unresolved — modeled as live AM.
    """
    actual, expected = _aria_scenario(am=100, is_stunned=False, aura_element="ether")
    assert actual > 0, "Abloom must fire"
    assert actual == expected, f"Aria ether unstunned pin failed: {actual} != {expected}"


def test_aria_abloom_stunned_ether_pin_l7():
    """Aria Perfect Pitch (L7) on Ether aura, target stunned → MV ×1.5.

    Pin: mv_bp = 2750 × (10000+5000)//10000 = 4125.
    total = original_anomaly_dmg × 4125 × am // 100_000.
    """
    actual_stunned, expected_stunned = _aria_scenario(
        am=100, is_stunned=True, aura_element="ether"
    )
    actual_unstunned, _ = _aria_scenario(am=100, is_stunned=False, aura_element="ether")

    assert actual_stunned > 0, "Abloom must fire when stunned"
    assert actual_stunned == expected_stunned, (
        f"Aria ether stunned pin failed: {actual_stunned} != {expected_stunned}"
    )
    # Stunned must be strictly larger than unstunned (1.5× MV)
    assert actual_stunned > actual_unstunned, "Stunned Abloom must exceed unstunned"


def test_aria_abloom_fire_mv_pin_l7():
    """Aria Perfect Pitch (L7) on active Fire/Burn aura, unstunned.

    Pin: total = original_anomaly_dmg × 3570 × am // 100_000 (am=100).
    """
    actual, expected = _aria_scenario(am=100, is_stunned=False, aura_element="fire")
    assert actual > 0, "Abloom must fire on Fire aura"
    assert actual == expected, f"Aria fire MV pin failed: {actual} != {expected}"


def test_aria_abloom_wind_mv_pin_l7():
    """Aria Perfect Pitch (L7) on active Wind/Windswept aura, unstunned.

    Pin: total = original_anomaly_dmg × 140 × am // 100_000 (am=100).
    """
    actual, expected = _aria_scenario(am=100, is_stunned=False, aura_element="wind")
    assert actual > 0 or expected == 0, "Wind MV=140 is small but non-zero"
    assert actual == expected, f"Aria wind MV pin failed: {actual} != {expected}"


def test_aria_abloom_no_fire_on_non_qualifying_move():
    """A move without abloom_mv_by_element (simulating non-L3 Perfect Pitch) → no Abloom.

    State-gate: only the L3 charge release (flagged move) triggers Abloom.
    """
    enemy = EnemyProfile(
        name="Aria Gate Test",
        level=60,
        defense=0,
        fire_res=0,
        anomaly_capacity_fire=100,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )
    applier = BuildSnapshot(
        agent_name="Applier",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )
    aria = _aria_build(am=100)
    builds = {"applier": applier, "aria": aria}

    unflagged_spec = _AbloomMoveSpec(
        buildup=0,
        duration_s=1.2,
        hits=1,
        element="ether",
        abloom_mv_by_element=None,  # no flag → simulates L1/L2 Perfect Pitch
        abloom_stat="anomaly_mastery",
    )
    moves_db = {
        "applier": _AbloomAgentMovesSpec({"aura_move": _AbloomMoveSpec(15000, 1.0, 1, "fire")}),
        "aria": _AbloomAgentMovesSpec({"perfect_pitch_l1": unflagged_spec}),
    }
    steps = [
        SimulatedAttackStep("applier", "aura_move", []),
        SimulatedAttackStep("aria", "perfect_pitch_l1", []),
    ]
    result = simulate(builds, steps, enemy, moves_db)

    abloom_events = [e for e in result.events if e.kind == "abloom"]
    assert abloom_events == [], (
        f"Non-qualifying move must not trigger Abloom; got {len(abloom_events)} events"
    )
    assert result.totals.get("abloom", 0) == 0


# ---------------------------------------------------------------------------
# Grace — Pulse Grenade Abloom (C6)
# Flat-MV path (abloom_ap_scaled=False): total = original_anomaly_dmg × mv_bp // 10000
# MVs level-invariant from Pulse state machine description (re-seeded DB 2026-05-31).
# Gate: Pulse Grenade fires when 8 Zap stacks consumed while Pulse > 0 (25 from Ultimate).
# MULTIPLICITY: up to 3 Pulse Grenades per Ultimate (25 Pulse / 8 Zap = 3 trips, 1 wasted).
# Min-viable model fires once; multiplicity documented in grace.json notes.
# ---------------------------------------------------------------------------

_GRACE_MV: dict[str, int] = {
    "ether": 5600,
    "electric": 2800,
    "fire": 7000,
    "physical": 500,
    "ice": 700,
    "wind": 280,
}


def _grace_build() -> "BuildSnapshot":
    return BuildSnapshot(
        agent_name="Grace",
        agent_element="electric",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )


def _grace_pulse_grenade_spec() -> "_AbloomMoveSpec":
    """Pulse Grenade Multiplier — the Pulse-gated Abloom move."""
    return _AbloomMoveSpec(
        buildup=0,
        duration_s=0.5,
        hits=1,
        element="electric",
        abloom_mv_by_element=_GRACE_MV,
        abloom_ap_scaled=False,
    )


def _grace_scenario(*, aura_element: str = "ether") -> tuple[int, int]:
    """Run Grace Pulse Grenade on an active aura; return (abloom_dmg, expected_dmg)."""
    enemy = EnemyProfile(
        name="Grace Test Target",
        level=60,
        defense=0,
        fire_res=0,
        electric_res=0,
        ether_res=0,
        physical_res=0,
        ice_res=0,
        wind_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_capacity_ether=100,
        anomaly_capacity_physical=100,
        anomaly_capacity_ice=100,
        anomaly_capacity_wind=100,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )
    applier = BuildSnapshot(
        agent_name="Applier",
        agent_element=aura_element,
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )
    grace = _grace_build()
    builds = {"applier": applier, "grace": grace}
    aura_move = _AbloomMoveSpec(15000, 1.0, 1, aura_element)
    moves_db = {
        "applier": _AbloomAgentMovesSpec({"aura_move": aura_move}),
        "grace": _AbloomAgentMovesSpec({"pulse_grenade": _grace_pulse_grenade_spec()}),
    }
    steps: list = [
        SimulatedAttackStep("applier", "aura_move", []),
        SimulatedAttackStep("grace", "pulse_grenade", []),
    ]
    result = simulate(builds, steps, enemy, moves_db)

    abloom_events = [e for e in result.events if e.kind == "abloom"]
    actual = sum(e.damage or 0 for e in abloom_events)

    # Flat formula: original_anomaly_dmg × mv_bp // 10000 (no AP divisor)
    mv_bp = _GRACE_MV[aura_element]
    original_dmg = abloom_events[0].detail["original_anomaly_dmg"] if abloom_events else 0
    expected = original_dmg * mv_bp // 10000

    return actual, expected


def test_grace_abloom_ether_pin():
    """Grace Pulse Grenade on active Ether/Corruption aura — flat MV 5600 bp.

    Flat formula (no AP): total = original_anomaly_dmg × 5600 // 10000.
    """
    actual, expected = _grace_scenario(aura_element="ether")
    assert actual > 0, "Abloom must fire on active Ether aura"
    assert actual == expected, f"Grace ether flat pin failed: {actual} != {expected}"


def test_grace_abloom_fire_pin():
    """Grace Pulse Grenade on active Fire/Burn aura — flat MV 7000 bp (highest).

    Flat formula: total = original_anomaly_dmg × 7000 // 10000.
    """
    actual, expected = _grace_scenario(aura_element="fire")
    assert actual > 0, "Abloom must fire on active Fire aura"
    assert actual == expected, f"Grace fire flat pin failed: {actual} != {expected}"


def test_grace_abloom_no_fire_without_pulse_grenade_flag():
    """Move without abloom_mv_by_element does not trigger Abloom.

    Simulates a plain Special attack (no Pulse Grenade gate) — verifies the
    flag is the gate, not the move name.
    """
    enemy = EnemyProfile(
        name="Grace Gate Target",
        level=60,
        defense=0,
        fire_res=0,
        electric_res=0,
        ether_res=0,
        physical_res=0,
        ice_res=0,
        wind_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_capacity_ether=100,
        anomaly_capacity_physical=100,
        anomaly_capacity_ice=100,
        anomaly_capacity_wind=100,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )
    applier = BuildSnapshot(
        agent_name="Applier",
        agent_element="ether",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )
    grace = _grace_build()
    builds = {"applier": applier, "grace": grace}
    aura_move = _AbloomMoveSpec(15000, 1.0, 1, "ether")
    unflagged_spec = _AbloomMoveSpec(
        buildup=0,
        duration_s=0.5,
        hits=1,
        element="electric",
        abloom_mv_by_element=None,  # no flag → plain special, no Abloom
        abloom_ap_scaled=False,
    )
    moves_db = {
        "applier": _AbloomAgentMovesSpec({"aura_move": aura_move}),
        "grace": _AbloomAgentMovesSpec({"plain_special": unflagged_spec}),
    }
    steps = [
        SimulatedAttackStep("applier", "aura_move", []),
        SimulatedAttackStep("grace", "plain_special", []),
    ]
    result = simulate(builds, steps, enemy, moves_db)
    abloom_events = [e for e in result.events if e.kind == "abloom"]
    assert abloom_events == [], (
        f"Plain special must not trigger Abloom; got {len(abloom_events)} events"
    )
    assert result.totals.get("abloom", 0) == 0


# ---------------------------------------------------------------------------
# Burnice — Emberflow Tossing Method Abloom (C7)
# Flat-MV path (abloom_ap_scaled=False): total = original_anomaly_dmg × mv_bp // 10000
# MVs sourced from DESIGN_abloom_v2.md Part B audit (re-seeded DB cross-ref).
# Gate: 12 Afterburn triggers → 1 Emberflow stack → consumed on EX entry.
# AM-3: Mixed Flame Blend Afterburn counts ×2 toward 12-trigger counter (documented
#        in burnice.json notes; counter not simulated in unit tests, gate assumed armed).
# ---------------------------------------------------------------------------

_BURNICE_MV: dict[str, int] = {
    "ether": 4800,
    "electric": 2400,
    "fire": 6000,
    "physical": 400,
    "ice": 600,
    "wind": 240,
}


def _burnice_build() -> "BuildSnapshot":
    return BuildSnapshot(
        agent_name="Burnice",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )


def _burnice_tossing_method_spec() -> "_AbloomMoveSpec":
    """EX Special Attack: Intense Heat Tossing Method — Emberflow-gated Abloom move."""
    return _AbloomMoveSpec(
        buildup=0,
        duration_s=1.2,
        hits=1,
        element="fire",
        abloom_mv_by_element=_BURNICE_MV,
        abloom_ap_scaled=False,
    )


def _burnice_scenario(*, aura_element: str = "ether") -> tuple[int, int]:
    """Run Burnice Tossing Method on an active aura; return (abloom_dmg, expected_dmg)."""
    enemy = EnemyProfile(
        name="Burnice Test Target",
        level=60,
        defense=0,
        fire_res=0,
        electric_res=0,
        ether_res=0,
        physical_res=0,
        ice_res=0,
        wind_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_capacity_ether=100,
        anomaly_capacity_physical=100,
        anomaly_capacity_ice=100,
        anomaly_capacity_wind=100,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )
    applier = BuildSnapshot(
        agent_name="Applier",
        agent_element=aura_element,
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )
    burnice = _burnice_build()
    builds = {"applier": applier, "burnice": burnice}
    aura_move = _AbloomMoveSpec(15000, 1.0, 1, aura_element)
    moves_db = {
        "applier": _AbloomAgentMovesSpec({"aura_move": aura_move}),
        "burnice": _AbloomAgentMovesSpec({"tossing_method": _burnice_tossing_method_spec()}),
    }
    steps: list = [
        SimulatedAttackStep("applier", "aura_move", []),
        SimulatedAttackStep("burnice", "tossing_method", []),
    ]
    result = simulate(builds, steps, enemy, moves_db)

    abloom_events = [e for e in result.events if e.kind == "abloom"]
    actual = sum(e.damage or 0 for e in abloom_events)

    mv_bp = _BURNICE_MV[aura_element]
    original_dmg = abloom_events[0].detail["original_anomaly_dmg"] if abloom_events else 0
    expected = original_dmg * mv_bp // 10000

    return actual, expected


def test_burnice_abloom_ether_pin():
    """Burnice Tossing Method on active Ether/Corruption aura — flat MV 4800 bp.

    Flat formula (no AP): total = original_anomaly_dmg × 4800 // 10000.
    """
    actual, expected = _burnice_scenario(aura_element="ether")
    assert actual > 0, "Abloom must fire on active Ether aura"
    assert actual == expected, f"Burnice ether flat pin failed: {actual} != {expected}"


def test_burnice_abloom_fire_pin():
    """Burnice Tossing Method on active Fire/Burn aura — flat MV 6000 bp (highest).

    Flat formula: total = original_anomaly_dmg × 6000 // 10000.
    """
    actual, expected = _burnice_scenario(aura_element="fire")
    assert actual > 0, "Abloom must fire on active Fire aura"
    assert actual == expected, f"Burnice fire flat pin failed: {actual} != {expected}"


def test_burnice_abloom_no_fire_without_tossing_method_flag():
    """Move without abloom_mv_by_element does not trigger Abloom (Emberflow gate).

    Simulates a plain EX Special (no Tossing Method flag) — verifies the
    abloom_mv_by_element field is the gate, not the move name or scope.
    """
    enemy = EnemyProfile(
        name="Burnice Gate Target",
        level=60,
        defense=0,
        fire_res=0,
        electric_res=0,
        ether_res=0,
        physical_res=0,
        ice_res=0,
        wind_res=0,
        anomaly_capacity_fire=100,
        anomaly_capacity_electric=100,
        anomaly_capacity_ether=100,
        anomaly_capacity_physical=100,
        anomaly_capacity_ice=100,
        anomaly_capacity_wind=100,
        anomaly_res_fire=0,
        anomaly_duration_default=10.0,
        stun_buildup_multiplier=10000,
    )
    applier = BuildSnapshot(
        agent_name="Applier",
        agent_element="ether",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
        modifiers=[],
    )
    burnice = _burnice_build()
    builds = {"applier": applier, "burnice": burnice}
    aura_move = _AbloomMoveSpec(15000, 1.0, 1, "ether")
    unflagged_spec = _AbloomMoveSpec(
        buildup=0,
        duration_s=1.2,
        hits=1,
        element="fire",
        abloom_mv_by_element=None,  # no flag → plain EX, no Abloom
        abloom_ap_scaled=False,
    )
    moves_db = {
        "applier": _AbloomAgentMovesSpec({"aura_move": aura_move}),
        "burnice": _AbloomAgentMovesSpec({"plain_ex": unflagged_spec}),
    }
    steps = [
        SimulatedAttackStep("applier", "aura_move", []),
        SimulatedAttackStep("burnice", "plain_ex", []),
    ]
    result = simulate(builds, steps, enemy, moves_db)
    abloom_events = [e for e in result.events if e.kind == "abloom"]
    assert abloom_events == [], (
        f"Plain EX must not trigger Abloom; got {len(abloom_events)} events"
    )
    assert result.totals.get("abloom", 0) == 0


def test_hit_event_detail_carries_zone_formulas():
    """A standard hit's serialized detail must include zone_formulas (DESIGN §2.1/2.2).

    ``StepAttribution.zone_formulas`` is fully computed by the damage
    calculator (Task A1) but was previously dropped by
    ``_serialize_attribution`` -- F1's per-zone formula drill-down on the
    calculate page has no data source without this.
    """
    enemy = EnemyProfile(
        name="Mock Target",
        level=60,
        defense=50,
        physical_res=0,
    )
    build = BuildSnapshot(
        agent_name="Billy",
        agent_element="physical",
        agent_level=60,
        agent_base_atk=1000,
        agent_crit_rate=0,
        agent_crit_dmg=0,
        modifiers=[],
    )
    builds = {"billy": build}

    class MoveSpec:
        def __init__(self):
            self.buildup = 0
            self.duration_s = 1.0
            self.hits = 1
            self.element = "physical"
            self.scope = "basic"

    class AgentMovesSpec:
        def __init__(self, moves):
            self.moves = moves

    moves_db = {"billy": AgentMovesSpec({"basic_move": MoveSpec()})}
    steps = [
        SimulatedAttackStep(
            agent_id="billy",
            move_name="basic_move",
            attacks=[MockAttack("Basic Hit", 1000, "physical")],
            conditions=[],
        )
    ]

    result = simulate(builds, steps, enemy, moves_db)
    hit_events = [e for e in result.events if e.kind == "hit"]
    assert len(hit_events) == 1
    formulas = hit_events[0].detail["zone_formulas"]
    assert {"base", "boost", "crit", "def", "res", "vulnerability", "stun"} <= set(formulas)
    assert formulas["def"]["result_bp"] > 0
    assert formulas["def"]["template"]
    assert "terms" in formulas["def"]


def test_velina_vortex_allowlist():
    """Velina in VORTEX_ALLOWLIST: wind→fire disorder fires ≥1 vortex attributed to Velina."""
    MoveSpec, AgentMovesSpec = _make_move_spec_classes()

    velina = BuildSnapshot(
        agent_name="Velina",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1500,
        agent_anomaly_proficiency=200,
    )
    fire_agent = BuildSnapshot(
        agent_name="FireGuy",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    moves_db = {
        # duration_s=4.0 spaces each attack >3s apart so successive disorders
        # clear the F-18 global 3s disorder CD (Arkkus rules) added after this
        # test was first authored — required to fire 3 real vortices in sequence.
        "velina": AgentMovesSpec({"wind_hit": MoveSpec(15000, 4.0, 1, "wind")}),
        "fireguy": AgentMovesSpec({"fire_hit": MoveSpec(15000, 4.0, 1, "fire")}),
    }
    enemy = EnemyProfile(
        name="Vortex Target",
        level=60,
        defense=50,
        wind_res=0,
        fire_res=0,
        anomaly_capacity_wind=100,
        anomaly_capacity_fire=100,
        anomaly_duration_default=10.0,
    )
    builds = {"velina": velina, "fire_agent": fire_agent}
    steps = [
        SimulatedAttackStep("velina", "wind_hit", []),   # sets Windswept
        SimulatedAttackStep("fire_agent", "fire_hit", []),  # disorder → Vortex
    ]
    result = simulate(builds, steps, enemy, moves_db)

    vortices = [e for e in result.events if e.kind == "vortex"]
    assert len(vortices) >= 1, "Expected ≥1 vortex event — Velina must be in VORTEX_ALLOWLIST"
    assert vortices[0].agent_id == "velina"
    assert vortices[0].damage > 0
    assert result.totals["vortex"] > 0


def test_velina_windbite_state_machine():
    """Windbite counter cycles 1→2→consume(0); +150% Core only on 3rd (consuming) Vortex."""
    MoveSpec, AgentMovesSpec = _make_move_spec_classes()

    # Core +150% modifier conditioned on WINDBITE_CONSUMED — armed only on the consuming Vortex.
    core_bonus = Modifier(
        stat="vortex_dmg_bonus",
        value=15000,
        source=ModifierSource.CORE_SKILL,
        source_label="Core Passive: Breeze in Bloom",
        target=ModifierTarget.SELF,
        conditions=(Condition.WINDBITE_CONSUMED,),
    )
    velina = BuildSnapshot(
        agent_name="Velina",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1500,
        agent_anomaly_proficiency=200,
        modifiers=[core_bonus],
    )
    fire_agent = BuildSnapshot(
        agent_name="FireGuy",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )
    moves_db = {
        # duration_s=4.0 spaces each attack >3s apart so successive disorders
        # clear the F-18 global 3s disorder CD (Arkkus rules) added after this
        # test was first authored — required to fire 3 real vortices in sequence.
        "velina": AgentMovesSpec({"wind_hit": MoveSpec(15000, 4.0, 1, "wind")}),
        "fireguy": AgentMovesSpec({"fire_hit": MoveSpec(15000, 4.0, 1, "fire")}),
    }
    enemy = EnemyProfile(
        name="Vortex Target",
        level=60,
        defense=50,
        wind_res=0,
        fire_res=0,
        anomaly_capacity_wind=100,
        anomaly_capacity_fire=100,
        anomaly_duration_default=10.0,
    )
    builds = {"velina": velina, "fire_agent": fire_agent}
    # 4 steps → 3 wind/fire crossings → 3 Vortex events
    steps = [
        SimulatedAttackStep("velina", "wind_hit", []),      # Windswept aura
        SimulatedAttackStep("fire_agent", "fire_hit", []),  # disorder → Vortex #1
        SimulatedAttackStep("velina", "wind_hit", []),      # disorder → Vortex #2
        SimulatedAttackStep("fire_agent", "fire_hit", []),  # disorder → Vortex #3 (consuming)
    ]
    result = simulate(builds, steps, enemy, moves_db)

    vortices = [e for e in result.events if e.kind == "vortex"]
    assert len(vortices) == 3, f"Expected 3 vortex events, got {len(vortices)}"

    # Counter cycles: 0→1, 1→2, 2→0 (consume)
    assert vortices[0].detail["windbite_before"] == 0
    assert vortices[0].detail["windbite_after"] == 1
    assert vortices[0].detail["cyclone_kind"] == "condensed"

    assert vortices[1].detail["windbite_before"] == 1
    assert vortices[1].detail["windbite_after"] == 2
    assert vortices[1].detail["cyclone_kind"] == "condensed"

    assert vortices[2].detail["windbite_before"] == 2
    assert vortices[2].detail["windbite_after"] == 0
    assert vortices[2].detail["cyclone_kind"] == "sweeping"

    # Core +150% must be present on only the 3rd (consuming) Vortex — its damage is higher.
    dmg_1 = vortices[0].damage
    dmg_2 = vortices[1].damage
    dmg_3 = vortices[2].damage
    assert dmg_1 == dmg_2, "First two Vortex events must have equal damage (same conditions)"
    assert dmg_3 > dmg_1, "Consuming Vortex must be stronger due to Core +150% WINDBITE_CONSUMED"


def test_velina_vortex_end_to_end_rotation():
    """V11: Velina Vortex end-to-end rotation — bonus-reach and magnitude cross-check.

    Rotation: wind→fire→wind→fire = 3 Vortex events (condensed, condensed, sweeping).
    Verifies each of the three Vortex DMG bonuses moves total damage in the expected direction
    and that the consuming (sweeping) Vortex is scaled by exactly 27500/12500 = 2.2× the
    condensed baseline (Leifa vortex_boost area).

    Fixture provenance:
    - Burn Vortex MV (Leifa): 900% + t*100%/s; t=min(10,10)=10s → MV=1900% (190000 bp).
    - vortex_boost with all: condensed=12500 (AA+M2), sweeping=27500 (+Core).
    - ER-scaling stats (Wind DMG +35%, AM +84) intentionally absent (project_energy_regen).
    """
    MoveSpec, AgentMovesSpec = _make_move_spec_classes()

    aa_team = Modifier(
        stat="vortex_dmg_bonus",
        value=1000,
        source=ModifierSource.CORE_SKILL,
        source_label="AA: Vortex DMG +10% (team)",
        target=ModifierTarget.TEAM,
        conditions=(Condition.ALWAYS,),
    )
    m2_self = Modifier(
        stat="vortex_dmg_bonus",
        value=1500,
        source=ModifierSource.MINDSCAPE,
        source_label="M2: Vortex DMG +15% (self)",
        target=ModifierTarget.SELF,
        conditions=(Condition.ALWAYS,),
    )
    core_consuming = Modifier(
        stat="vortex_dmg_bonus",
        value=15000,
        source=ModifierSource.CORE_SKILL,
        source_label="Core: Vortex DMG +150% (sweeping)",
        target=ModifierTarget.SELF,
        conditions=(Condition.WINDBITE_CONSUMED,),
    )

    moves_db = {
        # duration_s=4.0 spaces each attack >3s apart so successive disorders
        # clear the F-18 global 3s disorder CD (Arkkus rules) added after this
        # test was first authored — required to fire 3 real vortices in sequence.
        "velina": AgentMovesSpec({"wind_hit": MoveSpec(15000, 4.0, 1, "wind")}),
        "fireguy": AgentMovesSpec({"fire_hit": MoveSpec(15000, 4.0, 1, "fire")}),
    }
    enemy = EnemyProfile(
        name="Vortex Target",
        level=60,
        defense=50,
        wind_res=0,
        fire_res=0,
        anomaly_capacity_wind=100,
        anomaly_capacity_fire=100,
        anomaly_duration_default=10.0,
    )
    steps = [
        SimulatedAttackStep("velina", "wind_hit", []),       # wind aura
        SimulatedAttackStep("fire_agent", "fire_hit", []),   # disorder → Vortex #1 (condensed)
        SimulatedAttackStep("velina", "wind_hit", []),       # disorder → Vortex #2 (condensed)
        SimulatedAttackStep("fire_agent", "fire_hit", []),   # disorder → Vortex #3 (sweeping)
    ]

    def _run(mods):
        velina = _velina_snap(mods)
        fire_agent = BuildSnapshot(
            agent_name="FireGuy",
            agent_element="fire",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=100,
        )
        return simulate({"velina": velina, "fire_agent": fire_agent}, steps, enemy, moves_db)

    def _velina_snap(mods):
        return BuildSnapshot(
            agent_name="Velina",
            agent_element="wind",
            agent_level=60,
            agent_base_atk=1500,
            agent_anomaly_proficiency=200,
            modifiers=mods,
        )

    result_all = _run([aa_team, m2_self, core_consuming])
    result_no_aa = _run([m2_self, core_consuming])
    result_no_m2 = _run([aa_team, core_consuming])
    result_no_core = _run([aa_team, m2_self])

    vortices_all = [e for e in result_all.events if e.kind == "vortex"]
    vortices_no_aa = [e for e in result_no_aa.events if e.kind == "vortex"]
    vortices_no_m2 = [e for e in result_no_m2.events if e.kind == "vortex"]
    vortices_no_core = [e for e in result_no_core.events if e.kind == "vortex"]

    assert len(vortices_all) == 3, f"Expected 3 vortex events, got {len(vortices_all)}"

    # Direction: each bonus removal reduces total Vortex damage.
    total_all = sum(e.damage for e in vortices_all)
    assert sum(e.damage for e in vortices_no_aa) < total_all, "Removing AA +10% must lower total"
    assert sum(e.damage for e in vortices_no_m2) < total_all, "Removing M2 +15% must lower total"
    assert sum(e.damage for e in vortices_no_core) < total_all, (
        "Removing Core +150% must lower total"
    )

    # AA and M2 affect all three events; Core only affects the sweeping (3rd) one.
    for i in range(2):
        assert vortices_no_aa[i].damage < vortices_all[i].damage, f"AA must raise Vortex #{i+1}"
        assert vortices_no_m2[i].damage < vortices_all[i].damage, f"M2 must raise Vortex #{i+1}"
        assert vortices_no_core[i].damage == vortices_all[i].damage, (
            f"Core must not affect condensed Vortex #{i+1}"
        )

    dmg_sweeping_all = vortices_all[2].damage
    dmg_sweeping_no_core = vortices_no_core[2].damage
    assert dmg_sweeping_all > dmg_sweeping_no_core, "Core +150% must boost sweeping Vortex"

    # Cross-check magnitude (Leifa formula): vortex_boost ratio = 27500 / 12500 = 2.2 exactly.
    # Integer division may introduce ≤1 absolute rounding; use relative tolerance.
    ratio = dmg_sweeping_all / dmg_sweeping_no_core
    assert abs(ratio - 2.2) < 0.01, (
        f"Sweeping/condensed ratio should be 2.2 (27500÷12500); got {ratio:.4f}. "
        "Check Core +150% + AA/M2 routing into vortex_boost area."
    )


