"""Task 31 — per-move Lumiflux Buildup Point application (DESIGN §7.1).

`moves/agents/remielle.json` has authored `lumiflux_points` since Task 20 and
`MoveBuildupSpec` has parsed it since then; nothing read it. This pins the read:
a move that declares points, acted by a registered Lumiflux agent, fills the
per-enemy pool — with no `initial_lumiflux_points` seam anywhere in sight.
"""

from __future__ import annotations

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import (
    SimulatedAttackStep,
    _SyntheticAttack,
    simulate,
)
from app.services.build_damage_service import BuildSnapshot
from app.services.lumiflux import LumifluxSpec
from app.services.modifiers import AttackScope

REMIELLE_ID = "1581"


def _spec(**overrides) -> LumifluxSpec:
    base = {
        "point_cap": 4,
        "voidflare_cap": 3,
        "refringe_ap_ratio_bp": 2,
        "refringe_flat_bonuses": {},
        "luminize_multipliers": {},
        "luminize_ap_bonus_bp": 10,
        "phase_flow_tick_s": 5.0,
        "phase_flow_duration_s": 40.0,
        "flight_attack_points": (0, 1, 2),
        "flight_attack_mv_bp": (8130, 20320, 16250),
        "flight_attack_daze_bp": (27500, 37820, 37820),
    }
    base.update(overrides)
    return LumifluxSpec(**base)


class _MoveSpec:
    def __init__(
        self,
        *,
        duration_s: float = 1.0,
        hits: int = 1,
        element: str = "lumiflux",
        scope=AttackScope.EX_SPECIAL,
        buildup: int = 0,
        lumiflux_points: int = 0,
    ) -> None:
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.buildup = buildup
        self.consolidated = False
        self.lumiflux_points = lumiflux_points


class _AgentMoves:
    def __init__(self, moves: dict) -> None:
        self.moves = moves


def _remielle() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Remielle",
        agent_element="lumiflux",
        agent_source_id=REMIELLE_ID,
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=200,
    )


def _teammate() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Ally",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=100,
    )


def _enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Point Target",
        level=60,
        defense=50,
        anomaly_duration_default=10.0,
    )


def _attack(name: str, element: str, buildup: int = 0) -> _SyntheticAttack:
    return _SyntheticAttack(
        id=None, name=name, element=element, skill_key="Basic", anomaly_buildup=buildup
    )


def _moves_db(*, points: int = 2, hits: int = 1) -> dict:
    return {
        "remielle": _AgentMoves(
            {
                "EX Special Attack: Ode to Dawn": _MoveSpec(
                    duration_s=1.8, hits=hits, lumiflux_points=points
                ),
                "Basic Attack: Leap": _MoveSpec(duration_s=1.2),
            }
        ),
        "ally": _AgentMoves(
            {
                "Big Fire Hit": _MoveSpec(
                    duration_s=2.0, element="fire", scope=AttackScope.BASIC, buildup=10_000
                )
            }
        ),
    }


def _rotation() -> list[SimulatedAttackStep]:
    return [
        SimulatedAttackStep("rem", "EX Special Attack: Ode to Dawn", [_attack("ex", "lumiflux")]),
        SimulatedAttackStep("ally", "Big Fire Hit", [_attack("fire hit", "fire", 10_000)]),
    ]


def _kinds(result, kind: str) -> list:
    return [e for e in result.events if e.kind == kind]


class TestPointsReachThePool:
    def test_declared_points_apply_without_the_seam(self) -> None:
        result = simulate(
            {"rem": _remielle(), "ally": _teammate()},
            _rotation(),
            _enemy(),
            _moves_db(),
            lumiflux_specs={"rem": _spec()},
        )
        points = _kinds(result, "lumiflux_point")
        assert len(points) == 1
        assert points[0].detail["points_added"] == 2
        assert points[0].detail["points"] == 2
        assert points[0].agent_id == "rem"

    def test_points_then_refringe_on_the_teammate_anomaly(self) -> None:
        result = simulate(
            {"rem": _remielle(), "ally": _teammate()},
            _rotation(),
            _enemy(),
            _moves_db(),
            lumiflux_specs={"rem": _spec()},
        )
        assert _kinds(result, "lumiflux_point")
        refringes = _kinds(result, "refringe")
        assert refringes, "a teammate anomaly after points land must Refringe"
        assert refringes[0].t >= _kinds(result, "lumiflux_point")[0].t

    def test_points_land_after_the_skill_ends(self) -> None:
        # The DB text puts the application after the skill ends, not on its
        # first hit -- so it lands at the step's end, t_start + duration_s.
        result = simulate(
            {"rem": _remielle(), "ally": _teammate()},
            _rotation(),
            _enemy(),
            _moves_db(),
            lumiflux_specs={"rem": _spec()},
        )
        assert _kinds(result, "lumiflux_point")[0].t == 1.8

    def test_points_are_capped_by_the_spec(self) -> None:
        steps = [
            SimulatedAttackStep(
                "rem", "EX Special Attack: Ode to Dawn", [_attack("ex", "lumiflux")]
            )
            for _ in range(4)
        ]
        result = simulate(
            {"rem": _remielle()},
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"rem": _spec(point_cap=4)},
        )
        assert _kinds(result, "lumiflux_point")[-1].detail["points"] == 4

    def test_multi_hit_move_applies_its_count_once_not_once_per_hit(self) -> None:
        # "apply 2 ... to all enemies hit" is per enemy; this engine simulates
        # one. A per-animation-hit placement would silently emit 4 points here.
        result = simulate(
            {"rem": _remielle()},
            [
                SimulatedAttackStep(
                    "rem",
                    "EX Special Attack: Ode to Dawn",
                    [_attack("ex", "lumiflux"), _attack("ex", "lumiflux")],
                )
            ],
            _enemy(),
            _moves_db(points=2, hits=2),
            lumiflux_specs={"rem": _spec()},
        )
        points = _kinds(result, "lumiflux_point")
        assert len(points) == 1
        assert points[0].detail["points"] == 2


class TestGuards:
    def test_no_spec_means_no_points(self) -> None:
        result = simulate(
            {"rem": _remielle(), "ally": _teammate()},
            _rotation(),
            _enemy(),
            _moves_db(),
        )
        assert _kinds(result, "lumiflux_point") == []
        assert _kinds(result, "refringe") == []

    def test_a_non_lumiflux_agents_move_cannot_open_a_pool(self) -> None:
        """The same guard shape as Luminize: an authored `lumiflux_points` on
        somebody else's move must not register."""
        moves = _moves_db()
        moves["ally"].moves["Big Fire Hit"].lumiflux_points = 3
        result = simulate(
            {"ally": _teammate()},
            [SimulatedAttackStep("ally", "Big Fire Hit", [_attack("fire hit", "fire", 10_000)])],
            _enemy(),
            moves,
            lumiflux_specs={},
        )
        assert _kinds(result, "lumiflux_point") == []

    def test_move_without_points_emits_nothing(self) -> None:
        result = simulate(
            {"rem": _remielle()},
            [SimulatedAttackStep("rem", "Basic Attack: Leap", [_attack("leap", "lumiflux")])],
            _enemy(),
            _moves_db(),
            lumiflux_specs={"rem": _spec()},
        )
        assert _kinds(result, "lumiflux_point") == []


class TestRealKitData:
    def test_the_shipped_moves_json_declares_the_points_this_reads(self) -> None:
        from app.data.loaders.moves import load_agent_moves

        moves = load_agent_moves()["remielle"].moves
        declared = {n: s.lumiflux_points for n, s in moves.items() if s.lumiflux_points}
        assert declared == {
            "EX Special Attack: Ode to Dawn": 2,
            "Chain Attack: Interwoven Dance Steps": 2,
        }


class TestPhaseFlowTickPointsAreConsumableInRun:
    """Engine finding E-F1 / hardening Task 11.

    Phase Flow tick points used to be applied in the tick *post-pass*, which
    runs after every step has already been resolved. Structurally, that meant
    no tick-earned point could ever be consumed by anything: a rotation whose
    only point source was Phase Flow could never fire a Refringe, and
    Prismatic never saw tick-earned buildup in-run. The final pool count
    looked right, so nothing downstream noticed.

    Per the DESIGN ruling the tick's *damage* stays a post-pass expected-value
    quantity; only the *point state* moved into the step loop, at the tick's
    own timestamp.
    """

    def _moves_db(self) -> dict:
        return {
            # Remielle contributes NO points of her own -- the only point
            # source in this rotation is the Phase Flow ticks.
            "remielle": _AgentMoves({"Basic Attack: Leap": _MoveSpec(duration_s=1.2)}),
            "ally": _AgentMoves(
                {
                    "Big Fire Hit": _MoveSpec(
                        duration_s=2.0,
                        element="fire",
                        scope=AttackScope.BASIC,
                        buildup=10_000,
                    )
                }
            ),
        }

    def _run(self, *, windows):
        return simulate(
            {"rem": _remielle(), "ally": _teammate()},
            [
                # Five 1.2s Remielle basics carry the clock 0.0 -> 6.0s past
                # the first Phase Flow tick at 5.0s. None of them banks a
                # point: `Basic Attack: Leap` declares no `lumiflux_points`,
                # so the ticks are the rotation's only point source.
                *[
                    SimulatedAttackStep(
                        "rem", "Basic Attack: Leap", [_attack("leap", "lumiflux")]
                    )
                    for _ in range(5)
                ],
                # Starts at 6.0s, after the 5.0s tick. This is the FIRST
                # teammate anomaly in the rotation, so it genuinely triggers
                # (rather than landing on an aura that is already up) and can
                # spend the tick-earned point.
                SimulatedAttackStep("ally", "Big Fire Hit", [_attack("f1", "fire", 10_000)]),
            ],
            _enemy(),
            self._moves_db(),
            lumiflux_specs={"rem": _spec()},
            initial_lumiflux_points=0,
            phase_flow_windows=windows,
        )

    def test_a_tick_earned_point_can_fire_a_refringe(self):
        """The starvation repro. Pre-fix this was structurally impossible --
        not merely unlikely -- because the points did not exist until every
        step had been resolved."""
        result = self._run(windows={"rem": [(0.0, 30.0)]})

        point_events = _kinds(result, "lumiflux_point")
        assert point_events, "Phase Flow ticks should bank points"
        assert min(e.t for e in point_events) == 5.0

        refringes = _kinds(result, "refringe")
        assert len(refringes) >= 1, (
            "a teammate anomaly after a Phase Flow tick must be able to spend "
            "the tick-earned point"
        )
        assert all(e.t >= 5.0 for e in refringes), (
            "no Refringe may fire before the first tick banked a point"
        )

    def test_without_a_phase_flow_window_there_is_nothing_to_spend(self):
        """Control: same rotation, no window -- no points, so no Refringe.
        Confirms the Refringe above is genuinely tick-funded."""
        result = self._run(windows={})
        assert _kinds(result, "lumiflux_point") == []
        assert _kinds(result, "refringe") == []

    def test_tick_points_still_reach_the_final_pool_count(self):
        """Regression guard on the move itself: ticks scheduled past the end
        of the last step still have to land, exactly as the old post-pass did
        -- a Phase Flow window can outlive the authored rotation."""
        result = self._run(windows={"rem": [(0.0, 30.0)]})
        # Ticks at 5,10,15,20,25s -> 5 ticks x E[points]=1, capped at 4.
        assert len(_kinds(result, "lumiflux_point")) == 5
        assert result.final_lumiflux_points > 0
