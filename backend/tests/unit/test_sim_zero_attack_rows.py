"""A step whose move resolves to zero attack rows must say so (issue #149).

The failure it guards is silent, which is what makes it dangerous: with a curated
move spec present, a step with no DB attack rows still produces anomaly damage off
the spec's buildup, so the timeline looks alive while the direct-damage instance is
simply gone. The reported symptom was "Velina doesn't even trigger her attacks in
the combo" — that is exactly this, and nothing in the response said a word.

The existing `Move spec missing for ...` warning covers a *different* failure —
absent curation. Absent *data* had no warning at all, and the two are independent:
a move can have curation and no rows, rows and no curation, both, or neither.
"""

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot

_NO_ROWS = "No attack rows resolved"


class _MockAttack:
    def __init__(self, *, element: str = "wind", damage_base: int = 10_000) -> None:
        self.name = "Ultimate: Heed the Tempest"
        self.element = element
        self.damage_base = damage_base
        self.damage_growth = 0
        self.energy_gain = 0
        self.anomaly_buildup = 5_000
        self.skill_key = "Ultimate"


class _MoveSpec:
    def __init__(self, buildup=15_000, duration_s=1.0, hits=1, element="wind", scope="ultimate"):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope


class _AgentMoves:
    def __init__(self, moves):
        self.moves = moves


def _enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Zero-Rows Target",
        level=60,
        defense=50,
        wind_res=0,
        anomaly_capacity_wind=100,
        anomaly_capacity_ether=100,
        anomaly_duration_default=10.0,
    )


def _build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_name="Velina",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1500,
        agent_anomaly_proficiency=300,
    )


def _run(move_name: str, attacks, *, with_spec: bool):
    moves = {"velina": _AgentMoves({move_name: _MoveSpec()} if with_spec else {})}
    return simulate(
        {"v": _build()},
        [SimulatedAttackStep("v", move_name, attacks)],
        _enemy(),
        moves,
    )


def _zero_row_warnings(result) -> list[str]:
    return [w for w in result.warnings if _NO_ROWS in w]


def test_zero_rows_warns_even_when_a_curated_spec_exists():
    """The silent case: curation supplies buildup, so the step still produces anomaly
    damage and looks healthy. Without a warning this is invisible."""
    result = _run("Ultimate: Heed the Tempest", [], with_spec=True)

    assert [e for e in result.events if e.kind == "hit"] == []
    assert result.totals["standard"] == 0
    assert result.totals["anomaly"] > 0, "precondition: the step still looks alive"

    warned = _zero_row_warnings(result)
    assert len(warned) == 1, f"expected exactly one zero-rows warning, got {result.warnings}"
    assert "Velina" in warned[0]
    assert "Ultimate: Heed the Tempest" in warned[0]


def test_zero_rows_warns_independently_of_the_missing_spec_warning():
    """Both failures can co-occur, and each must be reported on its own terms."""
    result = _run("Ultimate: Heed the Tempest", [], with_spec=False)

    assert len(_zero_row_warnings(result)) == 1
    assert any("Move spec missing" in w for w in result.warnings)


def test_resolved_rows_produce_no_zero_row_warning():
    result = _run("Ultimate: Heed the Tempest", [_MockAttack()], with_spec=True)

    assert [e for e in result.events if e.kind == "hit"]
    assert _zero_row_warnings(result) == []


def test_markers_legitimately_carry_no_rows_and_must_stay_quiet():
    """`switch` / `stun_trigger` / `stun_end` / `aftershock` never have attack rows.
    Warning on those would be noise, and noise is how a real warning gets ignored."""
    for marker in ("switch", "stun_trigger", "stun_end", "aftershock"):
        result = simulate(
            {"v": _build()},
            [SimulatedAttackStep("v", marker, [])],
            _enemy(),
            {"velina": _AgentMoves({})},
        )
        assert _zero_row_warnings(result) == [], f"{marker} should not warn about rows"
