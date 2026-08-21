"""Hardening Task 2 / tests-review finding T-M2 — absolute integer pin on
Phase Flow tick damage, and on the shipped Lv.12 flight-attack tuples that
feed it (audit finding S1-D).

Two gaps this closes, both found by the PR #104 post-merge review:

* **S1-D** — `flight_attack_mv_bp` / `flight_attack_daze_bp` shipped the
  *Lv.1 base* values straight out of the Task 3 Dimbreath read, while every
  other skill-scaled number in this kit is authored at Lv.12 (D-KV4). Nothing
  in L0-L2 can see a wrong-but-well-formed integer tuple.
* **T-M2** — `test_phase_flow.py` asserts the tick's `ev_mv_bp` *detail field*
  and that damage is `> 0`, but never pins the resulting damage integer. A
  bp-vs-fraction mutation at the tick's `multiplier=` call site
  (`anomaly_simulator.py`, the `calculate_build_damage` call inside the Phase
  Flow post-pass) therefore survived the suite.

Unlike `test_phase_flow.py`'s hand-built fixtures, everything here is built
from the **shipped** kit block, so the pin tracks production data.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.lumiflux import LumifluxSpec, phase_flow_expected_value

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REMIELLE_KIT = BACKEND_ROOT / "app" / "data" / "modifiers" / "agents" / "remielle.json"

# Chosen so the DEF zone is a clean, *non-degenerate* fraction: at attacker
# level 60 the level factor is 794 and this enemy's effective DEF is 4764,
# which is exactly 794 * 6 -- so DEFArea = 794 / (794 + 4764) = 1/7. (The
# obvious alternative, defense=50, lands on effective DEF == level factor and
# so collapses DEFArea to exactly 1/2, where a numerator/denominator swap
# would be invisible.)
_ENEMY_DEFENSE = 300
_DEF_AREA_DIVISOR = 7


def _shipped_spec(**overrides) -> LumifluxSpec:
    block = json.loads(REMIELLE_KIT.read_text())["lumiflux"]
    kwargs = {k: v for k, v in block.items() if k != "notes"}
    for key in ("flight_attack_points", "flight_attack_mv_bp", "flight_attack_daze_bp"):
        kwargs[key] = tuple(kwargs[key])
    kwargs.update(overrides)
    return LumifluxSpec(**kwargs)


def _build() -> BuildSnapshot:
    # Base ATK 1000 flat, no modifiers, no discs -- so total ATK is exactly
    # 1000 and the BaseDMG term is readable straight off the multiplier.
    return BuildSnapshot(
        agent_name="Remielle",
        agent_element="lumiflux",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=200,
        modifiers=[],
    )


def _enemy() -> EnemyProfile:
    return EnemyProfile(
        name="Phase Flow Pin Target",
        level=60,
        defense=_ENEMY_DEFENSE,
        anomaly_duration_default=10.0,
    )


class _MoveSpec:
    def __init__(self, buildup=0, duration_s=0.1, hits=1, element=None, scope="basic"):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope


class _AgentMoves:
    def __init__(self, moves):
        self.moves = moves


def _tick(spec: LumifluxSpec):
    """One Phase Flow tick, from a window short enough to contain exactly one."""
    result = simulate(
        {"remielle": _build()},
        [SimulatedAttackStep("remielle", "noop", [])],
        _enemy(),
        {"remielle": _AgentMoves({"noop": _MoveSpec()})},
        lumiflux_specs={"remielle": spec},
        phase_flow_windows={"remielle": [(0.0, 6.0)]},
    )
    ticks = [e for e in result.events if e.kind == "phase_flow_tick"]
    assert len(ticks) == 1, f"expected exactly one tick, got {len(ticks)}"
    return ticks[0]


class TestShippedFlightAttackTuplesAreAtSkillLevel12:
    """S1-D. Lv.12 = base + growth * 11, from the Task 3 source table
    (docs/LOG_remielle.md: AvatarSkillTemplateTb rows 1581022/1581023/1581024,
    read at anchor-verified column positions).
    """

    def test_mv_bp_tuple(self):
        # bases (8130, 20320, 16250), growths (740, 1850, 1480):
        #   8130 + 740*11  = 8130 + 8140  = 16270
        #   20320 + 1850*11 = 20320 + 20350 = 40670
        #   16250 + 1480*11 = 16250 + 16280 = 32530
        assert _shipped_spec().flight_attack_mv_bp == (16270, 40670, 32530)

    def test_daze_bp_tuple(self):
        # bases (27500, 37820, 37820), growths (1250, 1720, 1720):
        #   27500 + 1250*11 = 27500 + 13750 = 41250
        #   37820 + 1720*11 = 37820 + 18920 = 56740
        #   37820 + 1720*11 = 37820 + 18920 = 56740
        # Rows 1581023/1581024 share identical daze base AND growth in the
        # source table, so their Lv.12 values coincide -- that is the data,
        # not a duplicated entry.
        assert _shipped_spec().flight_attack_daze_bp == (41250, 56740, 56740)

    def test_ev_is_the_rounded_mean_of_the_level_12_multipliers(self):
        # (16270 + 40670 + 32530) / 3 = 89470 / 3 = 29823.33... -> 29823
        assert phase_flow_expected_value(_shipped_spec().flight_attack_mv_bp) == 29823


class TestPhaseFlowTickDamageIsPinnedAbsolutely:
    """T-M2. The whole damage chain, from the shipped tuples to one integer.

    Mutations this catches that the pre-existing suite did not: a
    bp-vs-fraction slip at the tick's `multiplier=` argument (dividing by
    10^4 there drops the tick to ~0); the tuples reverting to their Lv.1
    values; the EV collapsing to a max/min/first-element instead of a mean;
    the crit or DEF zone dropping out of the tick's damage call.
    """

    def test_tick_damage(self):
        tick = _tick(_shipped_spec())

        # Derivation, by hand, zone by zone (see the tick's `zone_formulas`
        # detail for the engine's own breakdown of the same numbers):
        #   BaseDMG  = ATK 1000 * 29823 bp // 10000        = 2982
        #   BoostArea = 1 + 0 dmg%                          = 1.0
        #   CritArea  = 1 + 0.05 crit rate * 0.50 crit dmg  = 1.025
        #   DEFArea   = 794 / (794 + 4764)                  = 1/7
        #   RESArea, VulnArea, StunArea                     = 1.0 each
        # Multiplying those together and truncating: 2982 * 1.025 = 3056.55,
        # divided by 7 is 436.65, truncated to 436.
        assert tick.detail["ev_mv_bp"] == 29823
        assert tick.damage == 436

    def test_the_level_one_tuples_would_not_produce_that_damage(self):
        """Guards the pin itself: the pre-fix tuples land on a different int.

        EV = round((8130 + 20320 + 16250) / 3) = round(14900.0) = 14900, so
        BaseDMG = 1000 * 14900 // 10000 = 1490 and the total is
        trunc(1490 * 1.025 / 7) = trunc(1527.25 / 7) = trunc(218.17) = 218.
        """
        tick = _tick(_shipped_spec(flight_attack_mv_bp=(8130, 20320, 16250)))
        assert tick.detail["ev_mv_bp"] == 14900
        assert tick.damage == 218

    def test_a_fraction_instead_of_bp_at_the_multiplier_site_would_be_visible(self):
        """The specific T-M2 mutation, simulated at the only input we control.

        Feeding the multiplier as a fraction (29823 bp / 10^4 ~ 3) instead of
        basis points collapses the tick to zero damage -- so the absolute pin
        above cannot be satisfied by a fraction-valued multiplier.
        """
        tick = _tick(_shipped_spec(flight_attack_mv_bp=(3, 3, 3)))
        assert tick.damage == 0
