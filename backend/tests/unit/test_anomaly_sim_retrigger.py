"""Re-applying a one-proc burst anomaly onto its own live aura must deal damage again.

Assault, Shatter and Windswept are *single-instance* anomalies: each trigger is one
full damage instance (713% / 500% / 1250% ATK, `ANOMALY_PROC_COUNTS == 1`). Applying
one onto an enemy that already carries the same attribute's aura refreshes the aura
**and** resolves a fresh instance. Leifa states it for the wind case — "Applying a
Wind Anomaly on an existing Wind Anomaly ... only reapplies the Windswept effect"
(references/DMG Formula for Anomaly, Disorder and Vortex Leifa.html) — and Jane's
entire damage profile is repeated Assault procs.

The tick-based anomalies (Burn/Shock/Corruption) are the opposite case: their procs
were already scheduled off the original instance, so a re-application extends the
aura's life without adding a second wave. Both behaviours are pinned here, because
the fix is a split and the risk is that it leaks into the tick side.

Regression for the defect where the same-element branch emitted `refresh` and then
`continue`d past proc emission entirely, silently dropping every trigger after the
first (docs/DESIGN_kit_accuracy_gate.md Finding 0).
"""

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot

# Threshold is `anomaly_capacity_<element> * 100`, escalating x1.02 per repeat
# trigger, so 10 000 / 10 200 / 10 404 for the first three. One hit of this size
# crosses every one of them on its own.
_CROSSING_BUILDUP = 15_000

# Each step is one hit landing at t_start + duration. 3.5s spacing clears the 3s
# per-attribute cooldown (crossings at 3.5 / 7.0 / 10.5) while staying inside the
# 10s aura lifetime, which is what puts every crossing after the first onto the
# same-element re-application branch.
_STEP_DURATION_S = 3.5
_CROSSINGS = 3


class _MoveSpec:
    def __init__(
        self,
        buildup,
        duration_s,
        hits,
        element,
        scope="basic",
        abloom_mv_by_element=None,
    ):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.abloom_mv_by_element = abloom_mv_by_element
        self.abloom_ap_scaled = False
        self.abloom_requires_mindscape = 0
        self.abloom_mv_multiplier_bp = 10_000


class _AgentMovesSpec:
    def __init__(self, moves):
        self.moves = moves


def _enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Re-trigger Target",
        level=60,
        defense=50,
        physical_res=0,
        fire_res=0,
        ice_res=0,
        electric_res=0,
        ether_res=0,
        wind_res=0,
        anomaly_capacity_physical=100,
        anomaly_capacity_fire=100,
        anomaly_capacity_ice=100,
        anomaly_capacity_electric=100,
        # Wind reads the *ether* capacity to pick its tier; 100 matches no known
        # tier, so wind falls back to the generic curve for every n. Deliberate:
        # it keeps the wind thresholds identical to the other elements here.
        anomaly_capacity_ether=100,
        anomaly_capacity_wind=100,
        anomaly_duration_default=10.0,
    )


def _build(element: str) -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Grace",
        agent_element=element,
        agent_level=60,
        agent_base_atk=1200,
        agent_anomaly_proficiency=150,
    )


def _run(element: str, crossings: int = _CROSSINGS):
    """Land `crossings` threshold crossings on one element, each 3.5s apart."""
    moves = {
        f"crossing_{i}": _MoveSpec(_CROSSING_BUILDUP, _STEP_DURATION_S, 1, element)
        for i in range(crossings)
    }
    builds = {"grace": _build(element)}
    steps = [SimulatedAttackStep("grace", f"crossing_{i}", []) for i in range(crossings)]
    return simulate(builds, steps, _enemy(), {"grace": _AgentMovesSpec(moves)})


def _ticks(result, element):
    return [e for e in result.events if e.kind == "anomaly_tick" and e.element == element]


def _gate_passes(result, element):
    """A new aura or a refresh of the live one — either proves the crossing was let through."""
    return [e for e in result.events if e.kind in ("anomaly", "refresh") and e.element == element]


# --- burst anomalies: every crossing is its own damage instance ------------------


def test_assault_reapplication_deals_damage_again():
    result = _run("physical")

    assert len(_gate_passes(result, "physical")) == _CROSSINGS
    ticks = _ticks(result, "physical")
    assert len(ticks) == _CROSSINGS, (
        f"Assault has ANOMALY_PROC_COUNTS == 1, so {_CROSSINGS} threshold crossings owe "
        f"{_CROSSINGS} damage instances; got {len(ticks)}"
    )
    assert all(t.damage > 0 for t in ticks)
    assert result.totals["anomaly"] == sum(t.damage for t in ticks)


def test_shatter_reapplication_deals_damage_again():
    ticks = _ticks(_run("ice"), "ice")

    assert len(ticks) == _CROSSINGS
    assert all(t.damage > 0 for t in ticks)


def test_windswept_reapplication_deals_damage_again():
    ticks = _ticks(_run("wind"), "wind")

    assert len(ticks) == _CROSSINGS
    assert all(t.damage > 0 for t in ticks)


def test_burst_reproc_scales_the_anomaly_total_linearly():
    """The headline symptom: total anomaly damage must track the crossing count."""
    one = _run("physical", crossings=1).totals["anomaly"]
    three = _run("physical", crossings=_CROSSINGS).totals["anomaly"]

    assert one > 0
    assert three == 3 * one


def test_burst_reapplication_refreshes_the_aura_rather_than_replacing_it():
    """A re-application is one `anomaly` (the original) plus N-1 `refresh`, never N auras."""
    result = _run("physical")

    kinds = [e.kind for e in result.events if e.kind in ("anomaly", "refresh")]
    assert kinds == ["anomaly", "refresh", "refresh"]


# --- tick anomalies: re-application is duration-only, as before ------------------


def test_burn_reapplication_does_not_add_a_second_wave():
    """Burn's 20 procs are scheduled off the original instance; refreshing must not re-arm them."""
    result = _run("fire")

    assert len(_gate_passes(result, "fire")) == _CROSSINGS
    assert len(_ticks(result, "fire")) == 20, (
        "Burn re-application extends the aura only — a second batch of ticks would "
        "mean the burst-anomaly split leaked onto the tick side"
    )


def test_burn_total_is_flat_across_crossing_counts():
    assert _run("fire", crossings=1).totals["anomaly"] == _run("fire").totals["anomaly"]


# --- wind-on-wind pays Windswept but must NOT fire Vortex ------------------------


def test_wind_on_wind_reapplication_pays_damage_without_triggering_vortex():
    """Leifa is explicit: wind onto an existing Wind Anomaly reapplies Windswept and
    does *not* trigger Vortex. So the fix must restore the damage instance without
    advancing the Vortex/Windbite chain — Vortex still requires a wind/non-wind
    interaction, which goes through the Disorder-override branch instead.

    Run as Velina, who is on VORTEX_ALLOWLIST, so a spurious Vortex would actually
    surface here rather than being suppressed by the allowlist.
    """
    moves = {
        f"wind_{i}": _MoveSpec(_CROSSING_BUILDUP, _STEP_DURATION_S, 1, "wind")
        for i in range(_CROSSINGS)
    }
    builds = {
        "velina": BuildSnapshot(
            agent_name="Velina",
            agent_element="wind",
            agent_level=60,
            agent_base_atk=1200,
            agent_anomaly_proficiency=150,
        )
    }
    steps = [SimulatedAttackStep("velina", f"wind_{i}", []) for i in range(_CROSSINGS)]

    result = simulate(builds, steps, _enemy(), {"velina": _AgentMovesSpec(moves)})

    assert len(_ticks(result, "wind")) == _CROSSINGS
    assert [e for e in result.events if e.kind == "vortex"] == []


# --- a re-application hands the aura to the new applier --------------------------


def _disorder_damage_when_reapplied_by(atk: int) -> int:
    """A applies Assault, B re-applies it, C then overrides with Fire -> Disorder.

    The Disorder fires off the *physical* aura being destroyed, and resolves under
    that aura's applier snapshot. Because B's re-application is a fresh damage
    instance that the aura now represents, B is that applier — so the Disorder must
    scale with B's ATK. If the aura still carried A's snapshot from three seconds
    earlier, `atk` here would not move the result at all.
    """
    builds = {
        "a": BuildSnapshot(
            agent_name="Grace",
            agent_element="physical",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=100,
        ),
        "b": BuildSnapshot(
            agent_name="Billy",
            agent_element="physical",
            agent_level=60,
            agent_base_atk=atk,
            agent_anomaly_proficiency=100,
        ),
        "c": BuildSnapshot(
            agent_name="Ben",
            agent_element="fire",
            agent_level=60,
            agent_base_atk=1000,
            agent_anomaly_proficiency=100,
        ),
    }
    moves = {
        "grace": _AgentMovesSpec({"phys": _MoveSpec(_CROSSING_BUILDUP, 3.5, 1, "physical")}),
        "billy": _AgentMovesSpec({"phys": _MoveSpec(_CROSSING_BUILDUP, 3.5, 1, "physical")}),
        "ben": _AgentMovesSpec({"fire": _MoveSpec(_CROSSING_BUILDUP, 3.5, 1, "fire")}),
    }
    steps = [
        SimulatedAttackStep("a", "phys", []),  # t=3.5  new physical aura
        SimulatedAttackStep("b", "phys", []),  # t=7.0  re-application (aura live to 17.0)
        SimulatedAttackStep("c", "fire", []),  # t=10.5 fire crosses -> Disorder on physical
    ]
    result = simulate(builds, steps, _enemy(), moves)

    disorders = [e for e in result.events if e.kind == "disorder"]
    assert len(disorders) == 1, f"expected exactly one Disorder, got {len(disorders)}"
    return disorders[0].damage


def test_reapplication_moves_aura_ownership_to_the_new_applier():
    low = _disorder_damage_when_reapplied_by(1_000)
    high = _disorder_damage_when_reapplied_by(4_000)

    assert high > low, (
        "Disorder resolved under a stale applier snapshot — the re-applier's ATK "
        "must drive it, since the aura represents their application"
    )


# --- a mid-step re-proc must not leak into Abloom's basis ------------------------


def test_reproc_inside_a_step_does_not_move_ablooms_step_start_basis():
    """`pre_step_aura` means the aura as it stood when the step began.

    Abloom fractions the *pre-existing* aura — that is why the simulator snapshots
    it before the hit loop rather than reading `active_aura` live. Because a burst
    re-application rewrites `active_aura["dmg_per_proc"]` in place, snapshotting by
    reference let a strong re-applier's per-proc leak backwards into the Abloom of
    the very step that re-applied it.

    Here a weak agent opens the aura and a strong agent's Abloom move re-crosses the
    threshold in the next step. The re-proc must pay the strong agent's damage, while
    the Abloom must still fraction the weak agent's aura. Aliased, the Abloom came out
    20x high (228,160 against a correct 11,408).
    """
    builds = {
        "weak": BuildSnapshot(
            agent_name="Grace",
            agent_element="physical",
            agent_level=60,
            agent_base_atk=800,
            agent_anomaly_proficiency=100,
        ),
        "strong": BuildSnapshot(
            agent_name="Billy",
            agent_element="physical",
            agent_level=60,
            agent_base_atk=4000,
            agent_anomaly_proficiency=400,
        ),
    }
    moves = {
        "grace": _AgentMovesSpec({"open": _MoveSpec(_CROSSING_BUILDUP, 3.5, 1, "physical")}),
        "billy": _AgentMovesSpec(
            {
                "reproc": _MoveSpec(
                    _CROSSING_BUILDUP,
                    3.5,
                    1,
                    "physical",
                    abloom_mv_by_element={"physical": 20_000},  # 200% of dmg_per_proc
                )
            }
        ),
    }
    steps = [
        SimulatedAttackStep("weak", "open", []),
        SimulatedAttackStep("strong", "reproc", []),
    ]

    result = simulate(builds, steps, _enemy(), moves)

    ticks = _ticks(result, "physical")
    assert len(ticks) == 2
    weak_proc, strong_proc = ticks[0].damage, ticks[1].damage
    assert strong_proc > weak_proc * 10, "the re-proc should carry the strong agent's stats"

    abloom = [e for e in result.events if e.kind == "abloom"]
    assert len(abloom) == 1
    assert abloom[0].damage == 2 * weak_proc, (
        "Abloom must fraction the step-start aura (the weak opener), not the re-proc "
        "that landed inside this same step"
    )
