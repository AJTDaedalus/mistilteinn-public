"""F-20: buildup-share-weighted anomaly attribution.

Reference: Arkkus — anomaly damage is proportional to each contributing
agent's share of the triggering buildup, each share snapshotted at its own
accumulation time (e.g. Burnice 80% / Lucy 20%); bangboo contribution dilutes
to near-zero damage. Prior behavior credited 100% of the proc to whichever
agent's hit happened to cross the threshold — wrong for dual-anomaly comps.

Uses Shatter (ice, 1 proc, instant, ungated) to keep the trigger math free of
F-19's on-hit gating machinery.
"""

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot


class _MoveSpec:
    def __init__(self, buildup, duration_s, hits, element, scope="basic"):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope


class _AgentMovesSpec:
    def __init__(self, moves):
        self.moves = moves


def _enemy() -> EnemyProfile:
    return EnemyProfile(
        name="F-20 Attribution Target",
        level=60,
        defense=50,
        ice_res=0,
        anomaly_capacity_ice=100,  # threshold = 100 * 100 = 10000 (n=1, no escalation)
        anomaly_duration_default=10.0,
    )


def _build(atk: int, ap: int, name: str = "agent") -> BuildSnapshot:
    return BuildSnapshot(
        agent_name=name,
        agent_element="ice",
        agent_level=60,
        agent_base_atk=atk,
        agent_anomaly_proficiency=ap,
    )


def _ticks(result, element="ice"):
    return [e for e in result.events if e.kind == "anomaly_tick" and e.element == element]


def test_single_agent_reduces_exactly_to_solo_output():
    """Golden regression: with only one contributor, share=1.0 must reproduce
    the same per-proc damage a plain (pre-F-20) single-snapshot calc would."""
    enemy = _enemy()
    builds = {"solo": _build(2000, 200, "Solo")}
    moves_db = {"solo": _AgentMovesSpec({"hit": _MoveSpec(10000, 1.0, 1, "ice")})}
    steps = [SimulatedAttackStep("solo", "hit", [])]

    result = simulate(builds, steps, enemy, moves_db)

    ticks = _ticks(result)
    assert len(ticks) == 1
    dmg = ticks[0].damage
    assert dmg > 0
    # 100% attributed to the sole contributor; totals match the tick exactly.
    assert result.per_agent_attribution["solo"] == dmg
    assert result.totals["anomaly"] == dmg
    assert result.totals["total"] == dmg


def test_two_agent_80_20_split_credits_proportionally():
    """Two agents contribute buildup toward the same element (80/20 split by
    buildup); the trigger fires on the low-contributor's hit (the old
    single-applier bug would have credited 100% to them). Total damage must
    equal the buildup-share-weighted sum of each contributor's own snapshot
    (Sigma share_i * damage_i); per_agent_attribution must split by each
    contributor's own term in that sum (their buildup share times their own
    damage), not by raw buildup share alone -- so a low-damage contributor's
    credit is diluted even if their buildup share was large (see the Bangboo
    test below for the extreme case)."""
    enemy = _enemy()

    # Solo baselines: what each agent's snapshot alone would produce for the
    # same threshold-crossing buildup, via the same (now solo-reducing) code path.
    solo_a = simulate(
        {"agent_a": _build(3000, 300, "agent_a")},
        [SimulatedAttackStep("agent_a", "hit", [])],
        _enemy(),
        {"agent_a": _AgentMovesSpec({"hit": _MoveSpec(10000, 1.0, 1, "ice")})},
    )
    solo_b = simulate(
        {"agent_b": _build(200, 50, "agent_b")},
        [SimulatedAttackStep("agent_b", "hit", [])],
        _enemy(),
        {"agent_b": _AgentMovesSpec({"hit": _MoveSpec(10000, 1.0, 1, "ice")})},
    )
    per_proc_a = _ticks(solo_a)[0].damage
    per_proc_b = _ticks(solo_b)[0].damage
    expected_weighted = round(0.8 * per_proc_a + 0.2 * per_proc_b)

    builds = {
        "agent_a": _build(3000, 300, "agent_a"),
        "agent_b": _build(200, 50, "agent_b"),
    }
    moves_db = {
        "agent_a": _AgentMovesSpec({"hit_a": _MoveSpec(8000, 1.0, 1, "ice")}),
        "agent_b": _AgentMovesSpec({"hit_b": _MoveSpec(2000, 0.5, 1, "ice")}),
    }
    steps = [
        SimulatedAttackStep("agent_a", "hit_a", []),
        SimulatedAttackStep("agent_b", "hit_b", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    ticks = _ticks(result)
    assert len(ticks) == 1
    assert ticks[0].damage == expected_weighted

    # Both agents contributed damage-share; low contributor is NOT zeroed out,
    # and the two shares reconstruct the total exactly (no rounding leak).
    assert result.per_agent_attribution["agent_a"] > 0
    assert result.per_agent_attribution["agent_b"] > 0
    assert (
        result.per_agent_attribution["agent_a"] + result.per_agent_attribution["agent_b"]
        == expected_weighted
    )
    # Per-agent split is proportional to each contributor's OWN term in the
    # weighted sum (buildup_share_i * per_proc_i), not to raw buildup share --
    # agent_a's 80% buildup share combined with its much higher per-proc damage
    # means its attribution share exceeds 80%.
    term_a = 0.8 * per_proc_a
    term_b = 0.2 * per_proc_b
    expected_agent_a_share = term_a / (term_a + term_b)
    assert expected_agent_a_share > 0.8
    assert result.per_agent_attribution["agent_a"] == round(
        expected_agent_a_share * expected_weighted
    )

    # Prove the old single-applier bug is gone: the trigger fires on agent_b's
    # hit, but the credited damage is well above what 100%-to-agent_b would be.
    assert expected_weighted > per_proc_b


def test_bangboo_style_low_contributor_dilutes_toward_zero():
    """A near-zero-damage contributor (e.g. a Bangboo) that adds buildup but
    has negligible ATK/AP should dilute the credited total toward zero rather
    than being ignored (no special-casing) or wrongly boosting the total."""
    enemy = _enemy()

    solo_strong = simulate(
        {"agent_a": _build(3000, 300, "agent_a")},
        [SimulatedAttackStep("agent_a", "hit", [])],
        _enemy(),
        {"agent_a": _AgentMovesSpec({"hit": _MoveSpec(10000, 1.0, 1, "ice")})},
    )
    per_proc_strong = _ticks(solo_strong)[0].damage

    builds = {
        "agent_a": _build(3000, 300, "agent_a"),
        "bangboo": _build(1, 0, "bangboo"),
    }
    moves_db = {
        "agent_a": _AgentMovesSpec({"hit_a": _MoveSpec(2000, 1.0, 1, "ice")}),
        "bangboo": _AgentMovesSpec({"hit_bb": _MoveSpec(8000, 0.5, 1, "ice")}),
    }
    steps = [
        SimulatedAttackStep("agent_a", "hit_a", []),
        SimulatedAttackStep("bangboo", "hit_bb", []),
    ]

    result = simulate(builds, steps, enemy, moves_db)

    ticks = _ticks(result)
    assert len(ticks) == 1
    # Bangboo supplied 80% of the buildup but ~0% of the damage potential —
    # the weighted total must be far below the strong agent's solo (100%) proc,
    # proving dilution rather than crediting the full solo value to whoever's
    # hit happened to cross the threshold.
    assert 0 < ticks[0].damage < per_proc_strong * 0.3
    assert result.per_agent_attribution["bangboo"] < result.per_agent_attribution["agent_a"]
