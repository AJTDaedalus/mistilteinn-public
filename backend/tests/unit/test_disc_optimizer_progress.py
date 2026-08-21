"""Tests for Tasks 1-4 — combo-unit progress, numeric invariance, and cancellation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import disc_optimizer as _disc_optimizer_module
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.disc_optimizer import (
    PROGRESS_TICK_EVERY,
    DiscCandidate,
    OptimizerCancelled,
    OptimizerConstraints,
    OptimizerProgress,
    OptimizerResult,
    SetFrame,
    optimize_discs,
)
from app.services.modifiers import ActiveConditions, AttackScope


@pytest.fixture(autouse=True)
def _disable_pareto_filter():
    """Tasks 1-4 predate the Task 5e Pareto layer (P1d); these tests build large
    inventories of identical-stat discs purely to control combo counts for
    progress-cadence assertions, which P1d's tie-collapse would otherwise reduce
    to one survivor per bucket. Disabled here; covered separately in
    test_disc_optimizer_pareto.py.
    """
    with patch.object(
        _disc_optimizer_module,
        "_pareto_filter",
        side_effect=lambda slot_cands, *a, **kw: (slot_cands, 0),
    ):
        yield


def _base_build() -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="ice",
        modifiers=[],
    )


def _enemy() -> EnemySnapshot:
    return EnemySnapshot(level=60, base_def=50, element_res=0)


def _combo() -> list[ComboStep]:
    return [
        ComboStep(
            label="BA1",
            attack_id="att-1",
            attack_name="Basic 1",
            scope=AttackScope.BASIC,
            multiplier=10000,
            element="ice",
        )
    ]


def _disc(disc_id: str, slot: int, *, set_id: int = 1) -> DiscCandidate:
    return DiscCandidate(disc_id=disc_id, slot=slot, set_id=set_id)


def _run(
    inventory: list[DiscCandidate], constraints: OptimizerConstraints
) -> tuple[list[OptimizerProgress], OptimizerResult]:
    snapshots: list[OptimizerProgress] = []

    def cb(p: OptimizerProgress) -> None:
        snapshots.append(p)

    result = optimize_discs(
        base_build=_base_build(),
        enemy=_enemy(),
        combo_steps=_combo(),
        inventory=inventory,
        disc_set_modifiers={},
        constraints=constraints,
        conditions=ActiveConditions(),
        progress_callback=cb,
    )
    return snapshots, result


class TestTotalEmittedUpFront:
    def test_exhaustive_first_snapshot_is_zero_done_exact_product(self):
        """Exhaustive path: first snapshot done=0 and total = ∏ slot sizes."""
        # 2 discs per slot × 6 slots → 2^6 = 64 total combos.
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(2)]
        snapshots, _ = _run(inv, OptimizerConstraints(top_n=1))

        assert len(snapshots) >= 1
        first = snapshots[0]
        assert first.assignments_done == 0
        assert first.assignments_total == 64  # 2^6

    def test_frames_first_snapshot_is_zero_done_exact_product(self):
        """Frames path: first snapshot total = Σ over assignments of ∏ filtered sizes."""
        # 2 discs per set_id per slot; SetFrame {1:4, 2:2} → 15 assignments × 2^6 combos each.
        inv = [
            _disc(f"d{s}_{sid}_{i}", slot=s, set_id=sid)
            for s in range(1, 7)
            for sid in (1, 2)
            for i in range(2)
        ]
        snapshots, _ = _run(
            inv,
            OptimizerConstraints(
                allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
                top_n=1,
            ),
        )

        assert len(snapshots) >= 1
        first = snapshots[0]
        assert first.assignments_done == 0
        assert first.assignments_total == 960  # 15 × 2^6


class TestProgressTicksWithinChunk:
    def test_progress_ticks_within_chunk(self):
        """Exhaustive path: callback fires within a SINGLE slot-1 chunk (G2).

        Slot 1 is a single disc, so the whole search is one slot-1 chunk. The old
        per-slot-1 `_tick()` would emit only initial + 1 snapshot. With combo-cadence
        ticking, a search of > 3× PROGRESS_TICK_EVERY combos must emit ≥ 3 in-loop
        ticks (plus the initial and final flush) even though there's only one chunk.
        """
        # Slot 1 = 1 disc; slots 2-6 = 4 discs each → 1 × 4^5 = 1024 combos, one chunk.
        assert 3 * PROGRESS_TICK_EVERY < 1024  # guards the premise against constant changes
        inv = [_disc("d1", slot=1)]
        inv += [_disc(f"d{s}{i}", slot=s) for s in range(2, 7) for i in range(4)]
        snapshots, _ = _run(inv, OptimizerConstraints(top_n=1))

        # initial + ≥3 in-loop ticks (1024 // 256 = 4) + final flush.
        assert len(snapshots) >= 4
        # All in-loop ticks land within the single slot-1 chunk: done climbs before the end.
        interior = [p for p in snapshots if 0 < p.assignments_done < p.assignments_total]
        assert len(interior) >= 3

    def test_frames_done_monotonic_reaches_total(self):
        """Frames path: done is monotonically non-decreasing and ends at total."""
        inv = [
            _disc(f"d{s}_{sid}", slot=s, set_id=sid)
            for s in range(1, 7)
            for sid in (1, 2)
        ]
        snapshots, _ = _run(
            inv,
            OptimizerConstraints(
                allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
                top_n=1,
            ),
        )

        dones = [p.assignments_done for p in snapshots]
        assert dones == sorted(dones), "assignments_done must be non-decreasing"
        assert snapshots[-1].assignments_done == snapshots[-1].assignments_total

    def test_exhaustive_done_monotonic_reaches_total(self):
        """Exhaustive path: done monotonically non-decreasing and ends at total."""
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(2)]
        snapshots, _ = _run(inv, OptimizerConstraints(top_n=1))

        dones = [p.assignments_done for p in snapshots]
        assert dones == sorted(dones)
        assert snapshots[-1].assignments_done == snapshots[-1].assignments_total


class TestNumericInvariance:
    """Task 3 — progress callback must not change optimizer results."""

    def test_exhaustive_identical_results_with_and_without_callback(self):
        """Exhaustive: top-N disc_ids and total_damage are identical regardless of callback."""
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(2)]
        constraints = OptimizerConstraints(top_n=3)

        _, result_with_cb = _run(inv, constraints)
        result_no_cb = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=constraints,
            conditions=ActiveConditions(),
        )

        assert len(result_with_cb.builds) == len(result_no_cb.builds)
        for b_cb, b_no in zip(result_with_cb.builds, result_no_cb.builds, strict=True):
            assert b_cb.disc_ids == b_no.disc_ids
            assert b_cb.total_damage == b_no.total_damage

    def test_frames_identical_results_with_and_without_callback(self):
        """Frames: top-N disc_ids and total_damage are identical regardless of callback."""
        inv = [
            _disc(f"d{s}_{sid}", slot=s, set_id=sid)
            for s in range(1, 7)
            for sid in (1, 2)
        ]
        constraints = OptimizerConstraints(
            allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
            top_n=3,
        )

        _, result_with_cb = _run(inv, constraints)
        result_no_cb = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=constraints,
            conditions=ActiveConditions(),
        )

        assert len(result_with_cb.builds) == len(result_no_cb.builds)
        for b_cb, b_no in zip(result_with_cb.builds, result_no_cb.builds, strict=True):
            assert b_cb.disc_ids == b_no.disc_ids
            assert b_cb.total_damage == b_no.total_damage


class TestCancelStopsMidChunk:
    """Task 4 — cancel is honored within the new combo cadence."""

    def test_cancel_stops_early_within_a_single_chunk(self):
        """Callback raising OptimizerCancelled on the first in-loop tick stops early.

        The search is a single slot-1 chunk (slot 1 = 1 disc) of 1024 combos. Under
        combo-cadence ticking the first in-loop tick fires at PROGRESS_TICK_EVERY
        combos — mid-chunk — so cancellation is honored long before the chunk (and
        thus the whole search) completes. job_runner.cb already checks
        cancel_event.is_set() (job_runner.py:238) and raises OptimizerCancelled.
        """
        inv = [_disc("d1", slot=1)]
        inv += [_disc(f"d{s}{i}", slot=s) for s in range(2, 7) for i in range(4)]

        call_count = 0
        last_p: OptimizerProgress | None = None

        def cb(p: OptimizerProgress) -> None:
            nonlocal call_count, last_p
            last_p = p
            call_count += 1
            if call_count >= 2:  # 1 = initial emit; 2 = first in-loop tick
                raise OptimizerCancelled

        with pytest.raises(OptimizerCancelled):
            optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(top_n=1),
                conditions=ActiveConditions(),
                progress_callback=cb,
            )

        assert call_count == 2
        # 1024-combo single chunk; cancel lands at the first in-loop tick, mid-chunk.
        assert last_p is not None
        assert 0 < last_p.assignments_done < last_p.assignments_total
        assert last_p.assignments_done <= PROGRESS_TICK_EVERY
