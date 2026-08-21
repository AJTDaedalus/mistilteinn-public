"""Task 12 — VoidflareRecord, its store, and capture at the Refringe site
(DESIGN_remielle.md §7.2, §9.1 test 3).
"""

import dataclasses

import pytest

from app.models.build import EnemyProfile
from app.services.anomaly_simulator import SimulatedAttackStep, simulate
from app.services.build_damage_service import BuildSnapshot
from app.services.lumiflux import (
    LumifluxSpec,
    VoidflareRecord,
    clear_voidflare_store,
    store_voidflare,
)


def _record(**overrides) -> VoidflareRecord:
    fields = {
        "element": "fire",
        "atk": 1000,
        "dmg_bonus_bp": 0,
        "pen_ratio_bp": 0,
        "pen_flat": 0,
        "anomaly_proficiency": 100,
        "refringe_coefficient_bp": 200,
        "stored_at": 0.0,
    }
    fields.update(overrides)
    return VoidflareRecord(**fields)


class TestVoidflareRecordImmutability:
    def test_is_frozen(self):
        record = _record()
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.atk = 9999  # type: ignore[misc]

    def test_buffing_the_source_after_capture_does_not_change_the_record(self):
        """The record holds copied plain ints -- there is no reference back to
        the teammate's build/ctx for a later buff to retroactively affect."""
        source_atk = 1000
        record = _record(atk=source_atk)
        source_atk += 500  # "buff applied after storage"
        assert record.atk == 1000


class TestStoreVoidflareEviction:
    def test_fourth_capture_evicts_the_first(self):
        store = None
        records = [_record(stored_at=float(i)) for i in range(4)]
        for rec in records[:3]:
            store = store_voidflare(store, rec, cap=3)
        assert list(store) == records[:3]

        store = store_voidflare(store, records[3], cap=3)
        assert list(store) == records[1:4]
        assert len(store) == 3

    def test_below_cap_keeps_everything(self):
        store = store_voidflare(None, _record(stored_at=0.0), cap=3)
        store = store_voidflare(store, _record(stored_at=1.0), cap=3)
        assert len(store) == 2


class TestClearVoidflareStore:
    def test_returns_a_fresh_empty_store_with_the_same_cap(self):
        store = store_voidflare(None, _record(), cap=3)
        store = store_voidflare(store, _record(stored_at=1.0), cap=3)
        assert len(store) == 2

        cleared = clear_voidflare_store(cap=3)
        assert len(cleared) == 0
        cleared = store_voidflare(cleared, _record(), cap=3)
        cleared = store_voidflare(cleared, _record(), cap=3)
        cleared = store_voidflare(cleared, _record(), cap=3)
        cleared = store_voidflare(cleared, _record(stored_at=99.0), cap=3)
        assert len(cleared) == 3  # cap still enforced on the fresh store


class _MoveSpec:
    def __init__(
        self,
        buildup=0,
        duration_s=1.0,
        hits=1,
        element=None,
        scope="basic",
        triggers_luminize=False,
        luminize_mult_bp=0,
        clears_voidflare_store=False,
    ):
        self.buildup = buildup
        self.duration_s = duration_s
        self.hits = hits
        self.element = element
        self.scope = scope
        self.triggers_luminize = triggers_luminize
        self.luminize_mult_bp = luminize_mult_bp
        self.clears_voidflare_store = clears_voidflare_store


class _AgentMoves:
    def __init__(self, moves):
        self.moves = moves


def _spec():
    return LumifluxSpec(
        point_cap=4,
        voidflare_cap=3,
        refringe_ap_ratio_bp=2,
        refringe_flat_bonuses={},
        luminize_multipliers={},
        luminize_ap_bonus_bp=10,
        phase_flow_tick_s=5.0,
        phase_flow_duration_s=40.0,
        flight_attack_points=(0, 1, 2),
        flight_attack_mv_bp=(8130, 20320, 16250),
        flight_attack_daze_bp=(27500, 37820, 37820),
    )


def _lumiflux_build():
    return BuildSnapshot(
        agent_name="Remielle",
        agent_element="lumiflux",
        agent_level=60,
        agent_base_atk=1000,
        agent_anomaly_proficiency=200,
    )


def _velina_build():
    return BuildSnapshot(
        agent_name="Velina",
        agent_element="wind",
        agent_level=60,
        agent_base_atk=1500,
        agent_anomaly_proficiency=200,
    )


def _fire_build(atk=1000):
    return BuildSnapshot(
        agent_name="FireGuy",
        agent_element="fire",
        agent_level=60,
        agent_base_atk=atk,
        agent_anomaly_proficiency=100,
    )


def _enemy():
    return EnemyProfile(
        name="Voidflare Target",
        level=60,
        defense=50,
        wind_res=0,
        fire_res=0,
        anomaly_capacity_wind=100,
        anomaly_capacity_fire=100,
        anomaly_duration_default=10.0,
    )


def _moves_db():
    return {
        "velina": _AgentMoves({"wind_hit": _MoveSpec(15000, 4.0, 1, "wind")}),
        "fireguy": _AgentMoves({"fire_hit": _MoveSpec(15000, 4.0, 1, "fire")}),
    }


class TestVoidflareCaptureAtRefringeSite:
    def test_captures_only_when_refringe_fires_and_reads_the_triggering_anomalys_element(self):
        builds = {
            "velina": _velina_build(),
            "fire_agent": _fire_build(),
            "remielle": _lumiflux_build(),
        }
        steps = [
            SimulatedAttackStep("velina", "wind_hit", []),  # Windswept -- Refringes (1 pt)
            SimulatedAttackStep("fire_agent", "fire_hit", []),  # disorder/vortex; pool now empty
        ]

        result = simulate(
            builds,
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=1,
        )

        stored = result.final_voidflares["remielle"]
        # Only the wind trigger Refringed (1 point banked); the fire trigger's
        # own aura found an empty pool, so only one Voidflare was captured.
        assert len(stored) == 1
        record = stored[0]
        # The record's element is the triggering anomaly's own attribute
        # (wind, Velina's) -- never "lumiflux" (Remielle's) and never a fluxed
        # substitution (there is no flux in play here at all).
        assert record.element == "wind"
        assert record.atk == 1500  # Velina's ATK, not Remielle's (1000)
        assert record.anomaly_proficiency == 200
        assert record.refringe_coefficient_bp > 0
        assert result.final_lumiflux_points == 0

    def test_no_capture_when_pool_is_empty(self):
        builds = {
            "velina": _velina_build(),
            "fire_agent": _fire_build(),
            "remielle": _lumiflux_build(),
        }
        steps = [
            SimulatedAttackStep("velina", "wind_hit", []),
            SimulatedAttackStep("fire_agent", "fire_hit", []),
        ]

        result = simulate(
            builds,
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=0,
        )

        assert result.final_voidflares == {}

    def test_earlier_capture_is_unaffected_by_a_later_teammates_stats(self):
        """Two separate Refringe triggers, from teammates with different ATK
        (200 vs 1500) -- the earlier capture must not retroactively change."""
        builds = {
            "velina": _velina_build(),  # ATK 1500, triggers first (wind)
            "fire_agent": _fire_build(atk=200),  # ATK 200, triggers second (fire)
            "remielle": _lumiflux_build(),
        }
        steps = [
            SimulatedAttackStep("velina", "wind_hit", []),
            SimulatedAttackStep("fire_agent", "fire_hit", []),
        ]

        result = simulate(
            builds,
            steps,
            _enemy(),
            _moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=2,
        )

        stored = result.final_voidflares["remielle"]
        assert len(stored) == 2
        assert stored[0].element == "wind"
        assert stored[0].atk == 1500
        assert stored[1].element == "fire"
        assert stored[1].atk == 200


class TestVoidflareStoreClearsAreWired:
    """Engine finding E-F3 / hardening Task 10.

    `clear_voidflare_store` existed as a tested primitive with **no live call
    site**. The core text clears the store in two places -- db(core_skills,
    verbatim): "All stored Voidflares are cleared when Remielle enters the
    [Phase Flow] state or after using Basic Attack: Rainbow's End or Basic
    Attack: Fleeting Grace." -- and the move JSON's own notes *documented*
    that neither was wired.

    The consequence was an overcount, not a rounding error: back-to-back
    Luminize triggers re-fired the same Voidflares every time, and the store
    only ever grew toward its cap and stayed there.
    """

    def _builds(self):
        return {
            "velina": _velina_build(),
            "remielle": _lumiflux_build(),
        }

    def _moves_db(self):
        return {
            "velina": _AgentMoves({"wind_hit": _MoveSpec(15000, 4.0, 1, "wind")}),
            "remielle": _AgentMoves(
                {
                    # The two named Hold Basics: trigger Luminize AND clear.
                    "hold_basic": _MoveSpec(
                        0,
                        0.8,
                        1,
                        "lumiflux",
                        triggers_luminize=True,
                        luminize_mult_bp=16000,
                        clears_voidflare_store=True,
                    ),
                    # Ultimate: triggers Luminize but does NOT clear.
                    "ultimate": _MoveSpec(
                        0,
                        1.0,
                        1,
                        "lumiflux",
                        triggers_luminize=True,
                        luminize_mult_bp=33600,
                        scope="ultimate",
                    ),
                    "idle": _MoveSpec(0, 1.0, 1, None),
                }
            ),
        }

    def _run(self, steps, **kwargs):
        return simulate(
            self._builds(),
            steps,
            _enemy(),
            self._moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=1,
            **kwargs,
        )

    def _luminizes(self, result):
        return [e for e in result.events if e.kind == "luminize"]

    def test_hold_basic_empties_the_store(self):
        result = self._run(
            [
                SimulatedAttackStep("velina", "wind_hit", []),  # Refringe -> 1 Voidflare
                SimulatedAttackStep("remielle", "hold_basic", []),
            ]
        )
        assert len(self._luminizes(result)) == 1, "the clearing move still fires its Luminize"
        assert not result.final_voidflares.get("remielle"), "store should be empty afterwards"

    def test_back_to_back_hold_basics_do_not_refire_cleared_voidflares(self):
        """The overcount repro. Pre-fix both Hold Basics fired a Luminize off
        the same single stored Voidflare; post-fix only the first can."""
        result = self._run(
            [
                SimulatedAttackStep("velina", "wind_hit", []),
                SimulatedAttackStep("remielle", "hold_basic", []),
                SimulatedAttackStep("remielle", "hold_basic", []),
            ]
        )
        assert len(self._luminizes(result)) == 1

    def test_ultimate_triggers_luminize_without_clearing(self):
        """The clear is scoped to the two named basics -- folding it into
        `triggers_luminize` would wrongly clear here too."""
        result = self._run(
            [
                SimulatedAttackStep("velina", "wind_hit", []),
                SimulatedAttackStep("remielle", "ultimate", []),
                SimulatedAttackStep("remielle", "ultimate", []),
            ]
        )
        assert len(self._luminizes(result)) == 2
        assert len(result.final_voidflares["remielle"]) == 1

    def test_phase_flow_entry_empties_the_store(self):
        """Velina's wind hit runs 0.0-4.0s and banks a Voidflare; a Phase Flow
        window opening at 4.0s clears it before the later Hold Basic."""
        result = self._run(
            [
                SimulatedAttackStep("velina", "wind_hit", []),
                SimulatedAttackStep("remielle", "hold_basic", []),
            ],
            phase_flow_windows={"remielle": [(4.0, 20.0)]},
        )
        assert self._luminizes(result) == [], "the Voidflare was cleared on Phase Flow entry"

    def test_a_phase_flow_entry_does_not_retroactively_wipe_a_later_capture(self):
        """The ordering hazard the primitive's docstring called out, and the
        reason this could not be a post-pass: a window opening at t=1 must not
        wipe a Voidflare captured at t=5.

        Step 1 is a 1s idle, so the window at t=1.0 opens and drains before
        Velina's wind hit banks anything at all.
        """
        result = self._run(
            [
                SimulatedAttackStep("remielle", "idle", []),  # 0.0 - 1.0s
                SimulatedAttackStep("velina", "wind_hit", []),  # Refringe at >= 1.0s
                SimulatedAttackStep("remielle", "hold_basic", []),
            ],
            phase_flow_windows={"remielle": [(1.0, 20.0)]},
        )
        assert len(self._luminizes(result)) == 1, (
            "a capture after the window opened must survive the entry clear"
        )


class TestPrismaticLingerRunsFromPoolEmptying:
    """Engine finding E-F5(b) / hardening Task 13.

    The 8s Prismatic linger was measured from `last_point_at` -- the last time
    a point was ever *applied*. The DB text ties it to removal:
    db(core_skills, verbatim): "Prismatic is removed when the enemy no longer
    has Lumiflux Buildup. After Prismatic is removed, the Anomaly Buildup Rate
    increase persists for an additional 8s." Prismatic tracks the pool, so it
    is removed when the pool empties -- and measuring from application instead
    cut the buff short by however long the points sat unspent.

    Pinned at the state layer: the two mutators are the whole mechanism, and
    testing them directly avoids threading an 8s-scale rotation through the
    simulator to observe a boolean.
    """

    def _spec_obj(self):
        return _spec()

    def test_consuming_the_last_point_records_the_emptying_time(self):
        from app.services.lumiflux import apply_lumiflux_points, consume_lumiflux_points

        state = apply_lumiflux_points(None, self._spec_obj(), 1, agent_id="rem", at=0.0)
        assert state.emptied_at is None
        state = consume_lumiflux_points(state, 1, at=6.0)
        assert state.points == 0
        # The point was applied at 0.0 but spent at 6.0, so the linger runs
        # 6.0 -> 14.0, not 0.0 -> 8.0. That six-second difference is the bug.
        assert state.emptied_at == 6.0
        assert state.last_point_at == 0.0

    def test_consuming_a_non_final_point_does_not_start_the_clock(self):
        from app.services.lumiflux import apply_lumiflux_points, consume_lumiflux_points

        state = apply_lumiflux_points(None, self._spec_obj(), 2, agent_id="rem", at=0.0)
        state = consume_lumiflux_points(state, 1, at=3.0)
        assert state.points == 1
        assert state.emptied_at is None, "Prismatic is still up -- nothing removed yet"

    def test_reapplying_a_point_clears_a_pending_linger(self):
        from app.services.lumiflux import apply_lumiflux_points, consume_lumiflux_points

        state = apply_lumiflux_points(None, self._spec_obj(), 1, agent_id="rem", at=0.0)
        state = consume_lumiflux_points(state, 1, at=2.0)
        assert state.emptied_at == 2.0
        state = apply_lumiflux_points(state, self._spec_obj(), 1, agent_id="rem", at=3.0)
        assert state.emptied_at is None, "pool is non-empty again; no linger pending"

    def test_consuming_without_a_timestamp_leaves_the_clock_alone(self):
        """`at` is optional so callers that do not care about the linger are
        unaffected by the signature change."""
        from app.services.lumiflux import apply_lumiflux_points, consume_lumiflux_points

        state = apply_lumiflux_points(None, self._spec_obj(), 1, agent_id="rem", at=0.0)
        state = consume_lumiflux_points(state, 1)
        assert state.points == 0
        assert state.emptied_at is None


class TestPostCaptureTeammateBuffsDoNotReachLuminize:
    """Tests-review finding m-2 / hardening Task 14.

    DESIGN §9.1 test 3's first half -- "buff a teammate AFTER storage, Luminize
    damage byte-identical" -- had no live-sim coverage. The two tests that
    claimed it were vacuous: one called `calculate_luminize_damage` twice with
    byte-identical kwargs (`f(x) == f(x)`, true for any implementation), the
    other mutated a local Python int after constructing a frozen record.

    This runs the real thing: capture a Voidflare, change the teammate's stats
    mid-rotation, then Luminize -- and compares against the unbuffed run. The
    anti-vacuity control is the second test, where the same buff is live AT
    capture time and the damage genuinely moves.
    """

    def _velina_with(self, modifiers):
        return BuildSnapshot(
            agent_name="Velina",
            agent_element="wind",
            agent_level=60,
            agent_base_atk=1500,
            agent_anomaly_proficiency=200,
            modifiers=modifiers,
        )

    def _moves_db(self):
        return {
            "velina": _AgentMoves({"wind_hit": _MoveSpec(15000, 4.0, 1, "wind")}),
            "remielle": _AgentMoves(
                {
                    "hold_basic": _MoveSpec(
                        0, 0.8, 1, "lumiflux", triggers_luminize=True, luminize_mult_bp=16000
                    )
                }
            ),
        }

    def _luminize_total(self, velina_modifiers, *, stun_between):
        steps = [SimulatedAttackStep("velina", "wind_hit", [])]
        if stun_between:
            steps.append(SimulatedAttackStep("velina", "stun_trigger", []))
        steps.append(SimulatedAttackStep("remielle", "hold_basic", []))

        result = simulate(
            {"velina": self._velina_with(velina_modifiers), "remielle": _lumiflux_build()},
            steps,
            _enemy(),
            self._moves_db(),
            lumiflux_specs={"remielle": _spec()},
            initial_lumiflux_points=1,
        )
        luminizes = [e for e in result.events if e.kind == "luminize"]
        assert len(luminizes) == 1, f"expected one Luminize, got {len(luminizes)}"
        return luminizes[0].damage

    def _atk_buff(self, condition):
        from app.services.modifiers import Modifier, ModifierSource, ModifierTarget

        return Modifier(
            stat="atk_pct",
            value=5000,  # +50% -- far larger than any rounding band
            source=ModifierSource.CORE_SKILL,
            source_label="Teammate ATK buff",
            target=ModifierTarget.SELF,
            conditions=(condition,),
        )

    def test_a_buff_that_turns_on_after_capture_does_not_change_luminize(self):
        """The Voidflare froze Velina's ATK at capture. A buff that only
        becomes live afterwards -- here, gated on the enemy being stunned,
        with the stun landing between capture and Luminize -- must not reach
        the stored snapshot."""
        from app.services.modifiers import Condition

        plain = self._luminize_total([], stun_between=True)
        buffed_after = self._luminize_total(
            [self._atk_buff(Condition.ENEMY_STUNNED)], stun_between=True
        )
        assert buffed_after == plain

    def test_control_the_same_buff_live_at_capture_does_change_luminize(self):
        """Anti-vacuity: if this did not move, the test above would prove
        nothing about *when* the buff applies."""
        from app.services.modifiers import Condition

        plain = self._luminize_total([], stun_between=True)
        buffed_always = self._luminize_total(
            [self._atk_buff(Condition.ALWAYS)], stun_between=True
        )
        assert buffed_always > plain
