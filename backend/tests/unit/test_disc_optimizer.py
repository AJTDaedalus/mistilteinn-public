"""Unit tests for the disc optimizer (Phase 6.3a MVP).

The optimizer is pure: given a base ``BuildSnapshot`` (agent + W-Engine +
modifiers, no disc stats / no set-bonus modifiers), a user inventory of
``DiscCandidate`` instances, per-set-id 2pc/4pc modifier bundles, and a
combo to score against, it returns the top-N builds ranked by DAG combo
total. Exhaustive search, required-set and locked-slot pruning, top-N
tracked with heapq.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import disc_optimizer as _disc_optimizer_module
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import AnomalyStep, ComboStep
from app.services.disc_optimizer import (
    DiscCandidate,
    OptimizerCancelled,
    OptimizerConstraints,
    OptimizerProgress,
    SetFrame,
    optimize_discs,
)
from app.services.modifiers import (
    ActiveConditions,
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)


@pytest.fixture(autouse=True)
def _disable_pareto_filter():
    """This file predates the Task 5e Pareto layer (P1d) and exercises search
    mechanics (exhaustive counts, ranking, stat floors, progress) with tiny
    hand-built inventories that are frequently mutually dominated by design
    (e.g. a "weak" vs "strong" pair) — exactly what P1d is meant to prune.
    Disabling it here keeps this file's assertions about raw combo counts and
    controlled candidate pairs isolated from that unrelated, separately-tested
    optimization (see test_disc_optimizer_pareto.py).
    """
    with patch.object(
        _disc_optimizer_module,
        "_pareto_filter",
        side_effect=lambda slot_cands, *a, **kw: (slot_cands, 0),
    ):
        yield


def _base_build(*, modifiers: list[Modifier] | None = None) -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="ice",
        modifiers=modifiers or [],
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
        ),
    ]


def _disc(
    disc_id: str,
    slot: int,
    *,
    set_id: int = 1,
    main_stat_type: str = "atk",
    main_stat_value: int = 0,
    substats: list[dict] | None = None,
) -> DiscCandidate:
    return DiscCandidate(
        disc_id=disc_id,
        slot=slot,
        set_id=set_id,
        main_stat_type=main_stat_type,
        main_stat_value=main_stat_value,
        substats=substats or [],
    )


def _mod(
    stat: str = "atk_pct",
    value: int = 1000,
    *,
    source: ModifierSource = ModifierSource.DISC_SET_2PC,
    source_label: str = "2pc",
    conditions: tuple[Condition, ...] = (Condition.ALWAYS,),
) -> Modifier:
    return Modifier(
        stat=stat,
        value=value,
        source=source,
        source_label=source_label,
        target=ModifierTarget.SELF,
        conditions=conditions,
        scopes=(AttackScope.ALL,),
        max_stacks=1,
    )


def _six_slots(set_id: int = 1) -> list[DiscCandidate]:
    """Minimal inventory: exactly one disc per slot, all of one set."""
    return [_disc(f"d{i}", slot=i, set_id=set_id) for i in range(1, 7)]


class TestOptimizerBasic:
    def test_single_valid_combination_produces_one_result(self):
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=_six_slots(),
            disc_set_modifiers={},
            constraints=OptimizerConstraints(top_n=5),
            conditions=ActiveConditions(),
        )
        assert len(result.builds) == 1
        assert result.evaluated == 1
        assert result.builds[0].total_damage > 0

    def test_top_n_ordering_desc(self):
        """Higher-rolled discs should rank above lower-rolled ones."""
        inv = _six_slots()
        # Two options for slot 1: one flat with no substats, one with a strong roll.
        inv = [d for d in inv if d.slot != 1]
        inv.append(_disc("d1-weak", slot=1, substats=[]))
        inv.append(_disc("d1-strong", slot=1, substats=[{"stat": "atk_pct", "value": 2000}]))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(top_n=5),
            conditions=ActiveConditions(),
        )
        assert len(result.builds) == 2
        assert result.builds[0].total_damage > result.builds[1].total_damage
        assert result.builds[0].disc_ids[0] == "d1-strong"

    def test_top_n_caps_result_count(self):
        inv = _six_slots()
        # 3 options per slot for slots 1 and 2 → 9 combinations.
        inv = [d for d in inv if d.slot not in {1, 2}]
        for i in range(3):
            inv.append(_disc(f"d1-{i}", slot=1, substats=[{"stat": "atk_pct", "value": 100 * i}]))
            inv.append(_disc(f"d2-{i}", slot=2, substats=[{"stat": "atk_pct", "value": 100 * i}]))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(top_n=3),
            conditions=ActiveConditions(),
        )
        assert result.evaluated == 9
        assert len(result.builds) == 3

    def test_missing_slot_produces_empty_result(self):
        """If any slot has no candidates, no combinations exist."""
        inv = [d for d in _six_slots() if d.slot != 3]
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        assert result.builds == []
        assert result.evaluated == 0


class TestLockedSlots:
    def test_locked_slot_forces_disc(self):
        """A locked slot ignores other candidates for that slot."""
        inv = _six_slots()
        inv = [d for d in inv if d.slot != 1]
        inv.append(_disc("free", slot=1, substats=[{"stat": "atk_pct", "value": 500}]))
        inv.append(_disc("locked", slot=1, substats=[]))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(locked_slots={1: "locked"}),
            conditions=ActiveConditions(),
        )
        # Only one combination exists under the lock.
        assert result.evaluated == 1
        assert result.builds[0].disc_ids[0] == "locked"

    def test_locked_slot_missing_in_inventory_is_empty(self):
        inv = _six_slots()
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(locked_slots={1: "does-not-exist"}),
            conditions=ActiveConditions(),
        )
        assert result.builds == []
        assert result.evaluated == 0


class TestRequiredSets:
    def test_required_4pc_rejects_mismatched_combos(self):
        """A required 4-piece constraint excludes combos with <4 of that set."""
        # Slots 1-4 have both set 1 and set 2 options; slots 5-6 are set 2 only.
        inv: list[DiscCandidate] = []
        for i in range(1, 5):
            inv.append(_disc(f"s1-{i}", slot=i, set_id=1))
            inv.append(_disc(f"s2-{i}", slot=i, set_id=2))
        inv.extend(_disc(f"s2-{i}", slot=i, set_id=2) for i in (5, 6))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(required_sets={1: 4}),
            conditions=ActiveConditions(),
        )
        # Need 4+ of set 1 — only one way: all four slot-1..4 must be set 1.
        assert result.evaluated == 1
        assert all(did.startswith("s1-") for did in result.builds[0].disc_ids[:4])

    def test_required_2pc_admits_all_matching(self):
        """A 2pc requirement just needs any two slots carrying that set."""
        inv: list[DiscCandidate] = [_disc(f"s1-{i}", slot=i, set_id=1) for i in range(1, 7)]
        # Slot 1 has a second option from set 2.
        inv.append(_disc("s2-1", slot=1, set_id=2))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(required_sets={1: 2}),
            conditions=ActiveConditions(),
        )
        # Both s1-1 and s2-1 give a build with ≥ 2 of set 1 (slots 2-6 are all set 1).
        assert result.evaluated == 2


class TestSetModifierApplication:
    def test_4pc_modifier_boosts_damage(self):
        """A 4pc ATK modifier should raise the total vs. not having the set."""
        inv = _six_slots(set_id=1)
        set_mods = {
            1: [
                _mod("atk_pct", 3000, source=ModifierSource.DISC_SET_4PC, source_label="4pc"),
            ],
        }
        with_set = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers=set_mods,
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        without_set = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        assert with_set.builds[0].total_damage > without_set.builds[0].total_damage

    def test_2pc_applied_only_when_count_sufficient(self):
        """A 2pc modifier from a set with <2 pieces must not apply."""
        inv = [_disc(f"d{i}", slot=i, set_id=1) for i in range(1, 7)]
        # Replace slot 1 with a set-2 disc — set 1 now has 5 pieces, set 2 has 1.
        inv = [d for d in inv if d.slot != 1]
        inv.append(_disc("s2-only", slot=1, set_id=2))
        set_mods = {
            2: [_mod("atk_pct", 9000, source=ModifierSource.DISC_SET_2PC, source_label="2pc")],
        }
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers=set_mods,
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        # Set 2 has only one piece in every combo so its 2pc mod should not apply.
        # Compare vs no modifiers at all.
        baseline = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        assert result.builds[0].total_damage == baseline.builds[0].total_damage


class TestStatFloors:
    def test_min_atk_floor_prunes_low_atk_combos(self):
        """Combos below the min_atk floor never reach the DAG evaluator."""
        # Slot 2 has two options: one with huge flat ATK, one with nothing.
        inv = _six_slots()
        inv = [d for d in inv if d.slot != 2]
        inv.append(_disc("atk-heavy", slot=2, main_stat_type="atk", main_stat_value=300))
        inv.append(_disc("atk-light", slot=2, main_stat_type="atk", main_stat_value=0))
        # Base ATK is 900+600=1500; atk-heavy adds 300 flat = 1800.
        # Floor at 1700 leaves only the heavy option viable.
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(min_stats={"atk": 1700}),
            conditions=ActiveConditions(),
        )
        assert result.pruned_stats == 1
        assert result.evaluated == 1
        assert result.builds[0].disc_ids[1] == "atk-heavy"

    def test_min_crit_rate_floor(self):
        """Crit-rate floor prunes by crit_rate basis points."""
        inv = _six_slots()
        inv = [d for d in inv if d.slot != 4]
        inv.append(_disc("cr-strong", slot=4, substats=[{"stat": "crit_rate", "value": 2400}]))
        inv.append(_disc("cr-weak", slot=4, substats=[]))
        # Base CR is 500; strong adds 2400 → 2900. Floor at 1000 admits only strong.
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(min_stats={"crit_rate": 1000}),
            conditions=ActiveConditions(),
        )
        assert result.pruned_stats == 1
        assert result.builds[0].disc_ids[3] == "cr-strong"

    def test_multiple_floors_all_must_pass(self):
        """Every declared floor must be satisfied; missing any prunes the combo."""
        inv = _six_slots()
        inv = [d for d in inv if d.slot not in {4, 5}]
        inv.append(_disc("slot4", slot=4, substats=[{"stat": "crit_rate", "value": 2400}]))
        inv.append(_disc("slot5-hi", slot=5, substats=[{"stat": "crit_dmg", "value": 4800}]))
        inv.append(_disc("slot5-lo", slot=5, substats=[]))
        # CR and CD floors: slot5-hi passes both; slot5-lo fails the CD floor.
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                min_stats={"crit_rate": 1000, "crit_dmg": 7000},
            ),
            conditions=ActiveConditions(),
        )
        assert result.pruned_stats == 1
        assert result.builds[0].disc_ids[4] == "slot5-hi"

    def test_no_floors_means_no_stats_pruning(self):
        inv = _six_slots()
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        assert result.pruned_stats == 0

    def test_stat_floor_applied_after_set_pruning(self):
        """Stat pruning runs only on combos that passed the set requirement."""
        # One set-1 disc per slot (satisfies required_sets) + a set-2 slot-1
        # disc that would otherwise be cheaper.
        inv: list[DiscCandidate] = [_disc(f"s1-{i}", slot=i, set_id=1) for i in range(1, 7)]
        inv.append(_disc("s2-slot1", slot=1, set_id=2))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                required_sets={1: 4},
                min_stats={"atk": 10**9},  # impossibly high — forces pruning
            ),
            conditions=ActiveConditions(),
        )
        assert result.evaluated == 0
        # Two combos pass the set check; both get pruned on stats.
        assert result.pruned_stats == 2
        # Neither combo violated set requirements.
        assert result.pruned_sets == 0


class TestResultShape:
    def test_build_result_exposes_snapshot_and_set_counts(self):
        inv = _six_slots(set_id=1)
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        br = result.builds[0]
        assert br.set_counts == {1: 6}
        assert len(br.disc_ids) == 6
        assert br.snapshot.agent_base_atk == 900
        # Snapshot's disc_stats covers all six slots.
        assert len(br.snapshot.disc_stats) == 6

    def test_disc_ids_ordered_by_slot(self):
        inv = _six_slots(set_id=1)
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        # disc_ids[i] corresponds to slot i+1
        assert result.builds[0].disc_ids == ["d1", "d2", "d3", "d4", "d5", "d6"]


class TestSetFrameValidation:
    def test_counts_sum_to_six(self):
        SetFrame(counts={1: 4, 2: 2})  # ok
        SetFrame(counts={1: 6})

    def test_counts_below_six_rejected(self):
        with pytest.raises(ValueError, match="sum to 6"):
            SetFrame(counts={1: 4, 2: 1})

    def test_counts_above_six_rejected(self):
        with pytest.raises(ValueError, match="sum to 6"):
            SetFrame(counts={1: 4, 2: 3})


class TestAllowedFrames:
    def test_single_frame_matches_exhaustive_when_inventory_is_pure(self):
        """One frame {1:6}, inventory all set 1 → same result as exhaustive."""
        inv = _six_slots(set_id=1)
        exhaustive = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        framed = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                allowed_frames=[SetFrame(counts={1: 6})],
            ),
            conditions=ActiveConditions(),
        )
        assert framed.evaluated == exhaustive.evaluated == 1
        assert framed.builds[0].total_damage == exhaustive.builds[0].total_damage
        assert framed.builds[0].disc_ids == exhaustive.builds[0].disc_ids

    def test_frame_filters_out_combos_outside_declared_distribution(self):
        """A {1:4, 2:2} frame must not evaluate combos with other splits."""
        # Every slot has one set-1 and one set-2 option → 2^6 = 64 exhaustive combos.
        # Only C(6,2) = 15 of those have exactly 4 set-1 + 2 set-2 discs.
        inv: list[DiscCandidate] = []
        for i in range(1, 7):
            inv.append(_disc(f"s1-{i}", slot=i, set_id=1))
            inv.append(_disc(f"s2-{i}", slot=i, set_id=2))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
            ),
            conditions=ActiveConditions(),
        )
        assert result.evaluated == 15
        for build in result.builds:
            assert build.set_counts == {1: 4, 2: 2}

    def test_multiple_frames_union_their_combos(self):
        """Two frames are both searched; evaluated is the sum."""
        inv: list[DiscCandidate] = []
        for i in range(1, 7):
            inv.append(_disc(f"s1-{i}", slot=i, set_id=1))
            inv.append(_disc(f"s2-{i}", slot=i, set_id=2))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                top_n=50,
                allowed_frames=[
                    SetFrame(counts={1: 4, 2: 2}),
                    SetFrame(counts={2: 4, 1: 2}),
                ],
            ),
            conditions=ActiveConditions(),
        )
        # 15 combos per frame, 2 frames = 30 combos evaluated, disjoint counts.
        assert result.evaluated == 30
        assert {frozenset(b.set_counts.items()) for b in result.builds} == {
            frozenset({(1, 4), (2, 2)}),
            frozenset({(2, 4), (1, 2)}),
        }

    def test_frame_with_impossible_distribution_yields_no_builds(self):
        """Frame {1:4, 2:2} against an inventory of only set 1 → nothing."""
        inv = _six_slots(set_id=1)
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
            ),
            conditions=ActiveConditions(),
        )
        assert result.builds == []
        assert result.evaluated == 0

    def test_frame_respects_locked_slots(self):
        """A lock that conflicts with a frame's assignment narrows options."""
        # Slot 1 has both set-1 and set-2 options; other slots have both too.
        inv: list[DiscCandidate] = []
        for i in range(1, 7):
            inv.append(_disc(f"s1-{i}", slot=i, set_id=1))
            inv.append(_disc(f"s2-{i}", slot=i, set_id=2))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                locked_slots={1: "s1-1"},  # force slot 1 = set 1
                allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
            ),
            conditions=ActiveConditions(),
        )
        # Slot 1 is pinned to set 1, so of the 15 permutations only those with
        # slot-1 carrying set 1 remain — that's C(5,2) = 10.
        assert result.evaluated == 10
        assert all(b.disc_ids[0] == "s1-1" for b in result.builds)

    def test_frame_pruning_interacts_with_stat_floors(self):
        """Stat floors still prune combos that survive the frame filter."""
        inv = _six_slots(set_id=1)
        # Replace slot 2 with a high-ATK + low-ATK pair.
        inv = [d for d in inv if d.slot != 2]
        inv.append(_disc("heavy", slot=2, main_stat_type="atk", main_stat_value=300, set_id=1))
        inv.append(_disc("light", slot=2, main_stat_type="atk", main_stat_value=0, set_id=1))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                min_stats={"atk": 1700},
                allowed_frames=[SetFrame(counts={1: 6})],
            ),
            conditions=ActiveConditions(),
        )
        assert result.evaluated == 1
        assert result.pruned_stats == 1
        assert result.builds[0].disc_ids[1] == "heavy"

    def test_frame_mismatching_required_sets_is_skipped(self):
        """A frame that fails required_sets counts toward pruned_sets, not eval."""
        inv: list[DiscCandidate] = []
        for i in range(1, 7):
            inv.append(_disc(f"s1-{i}", slot=i, set_id=1))
            inv.append(_disc(f"s2-{i}", slot=i, set_id=2))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                required_sets={1: 4},
                allowed_frames=[
                    SetFrame(counts={1: 4, 2: 2}),  # passes
                    SetFrame(counts={2: 4, 1: 2}),  # fails required_sets
                ],
            ),
            conditions=ActiveConditions(),
        )
        assert result.pruned_sets == 1
        assert result.evaluated == 15

    def test_frame_applies_set_modifiers_by_count(self):
        """2pc/4pc modifiers activate based on the frame's declared counts."""
        inv: list[DiscCandidate] = []
        for i in range(1, 7):
            inv.append(_disc(f"s1-{i}", slot=i, set_id=1))
            inv.append(_disc(f"s2-{i}", slot=i, set_id=2))
        set_mods = {
            1: [
                _mod("atk_pct", 5000, source=ModifierSource.DISC_SET_4PC, source_label="4pc"),
            ],
        }
        with_4pc = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers=set_mods,
            constraints=OptimizerConstraints(
                allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
            ),
            conditions=ActiveConditions(),
        )
        without = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
            ),
            conditions=ActiveConditions(),
        )
        assert with_4pc.builds[0].total_damage > without.builds[0].total_damage


class TestExhaustiveSearch:
    def test_no_frames_path_is_exhaustive(self):
        """No-frames path evaluates all combinations — no cap pruning."""
        inv = [d for d in _six_slots() if d.slot != 1]
        for i in range(2):
            inv.append(_disc(f"s1-{i}", slot=1))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(top_n=10),
            conditions=ActiveConditions(),
        )
        assert result.evaluated == 2

    def test_all_slot_combinations_evaluated(self):
        """2 candidates per slot → 2^6 = 64 combos evaluated exhaustively."""
        inv: list[DiscCandidate] = []
        for slot in range(1, 7):
            inv.append(_disc(f"s{slot}-a", slot=slot))
            inv.append(_disc(f"s{slot}-b", slot=slot))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(top_n=100),
            conditions=ActiveConditions(),
        )
        assert result.evaluated == 2**6


class TestTotalStats:
    def test_total_stats_populated_on_every_build(self):
        """Every accepted build has non-empty total_stats with required keys."""
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=_six_slots(),
            disc_set_modifiers={},
            constraints=OptimizerConstraints(top_n=5),
            conditions=ActiveConditions(),
        )
        assert len(result.builds) == 1
        stats = result.builds[0].total_stats
        assert stats.atk > 0, "ATK must be > 0 (base_atk=900 + wengine=600)"
        # crit_rate default is 500 bp (5%); must be in basis points
        assert stats.crit_rate >= 500
        assert stats.crit_dmg >= 0
        assert stats.pen_ratio >= 0
        assert stats.anomaly_proficiency >= 0
        assert stats.pen_flat >= 0
        # Full-coverage fields from BuildStatsSummary
        assert stats.hp >= 0
        assert stats.defense >= 0
        assert stats.physical_dmg >= 0

    def test_total_stats_populated_when_min_stats_active(self):
        """total_stats still filled even when stat-floor pruning is enabled."""
        inv = _six_slots()
        inv = [d for d in inv if d.slot != 1]
        inv.append(_disc("d1-strong", slot=1, substats=[{"stat": "atk_pct", "value": 2000}]))
        inv.append(_disc("d1-weak", slot=1, substats=[]))
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                min_stats={"crit_rate": 500},
                top_n=5,
            ),
            conditions=ActiveConditions(),
        )
        for build in result.builds:
            assert build.total_stats.atk > 0


class TestProgressCallback:
    def test_progress_callback_invoked_per_assignment(self):
        """Frames path: callback fires once per set-assignment;
        done is monotonically increasing."""
        inv: list[DiscCandidate] = []
        for i in range(1, 7):
            inv.append(_disc(f"s1-{i}", slot=i, set_id=1))
            inv.append(_disc(f"s2-{i}", slot=i, set_id=2))

        snapshots: list[OptimizerProgress] = []

        def cb(p: OptimizerProgress) -> None:
            snapshots.append(p)

        optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(
                allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
                top_n=10,
            ),
            conditions=ActiveConditions(),
            progress_callback=cb,
        )

        assert len(snapshots) > 0
        dones = [p.assignments_done for p in snapshots]
        assert dones == sorted(dones), "assignments_done should be monotonically increasing"
        assert snapshots[-1].assignments_done == snapshots[-1].assignments_total

    def test_progress_callback_can_cancel(self):
        """Callback raising OptimizerCancelled on the second tick aborts the search."""
        # Use {1:4, 2:2} frame which has 15 assignments → many ticks.
        inv: list[DiscCandidate] = []
        for i in range(1, 7):
            inv.append(_disc(f"s1-{i}", slot=i, set_id=1))
            inv.append(_disc(f"s2-{i}", slot=i, set_id=2))

        call_count = 0

        def cb(p: OptimizerProgress) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise OptimizerCancelled

        with pytest.raises(OptimizerCancelled):
            optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(
                    allowed_frames=[SetFrame(counts={1: 4, 2: 2})],
                    top_n=10,
                ),
                conditions=ActiveConditions(),
                progress_callback=cb,
            )

        assert call_count >= 2
        # Must not have run all 15 assignments.
        assert call_count < 15

    def test_optimize_discs_default_no_callback(self):
        """Existing behavior is unchanged when no progress_callback is passed."""
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=_six_slots(),
            disc_set_modifiers={},
            constraints=OptimizerConstraints(),
            conditions=ActiveConditions(),
        )
        assert len(result.builds) == 1


class TestMultiplexedScoring:
    def test_multiplexed_scoring_selects_correct_am_index(self):
        """event_log_by_am sentinel routes S6-AM combo to the high-AM log; no-AM to base."""
        # base_agent_am=100; S6-AM disc adds 60 → coarse_am 160
        # AM=100 → multiplier 10000; AM=160 → multiplier 20000
        _step = lambda mult: [  # noqa: E731
            ComboStep(
                label="BA",
                attack_id="a1",
                attack_name="A",
                scope=AttackScope.BASIC,
                multiplier=mult,
                element="ice",
            )
        ]
        event_log_by_am = {100: _step(10000), 160: _step(20000)}

        base_build = BuildSnapshot(
            agent_base_atk=900,
            wengine_base_atk=600,
            agent_element="ice",
            agent_anomaly_mastery=100,
        )

        # No S6 AM → coarse_am=100 → multiplier 10000
        inv_base = [
            _disc(f"d{i}", slot=i, set_id=1, main_stat_type="atk" if i == 6 else "hp")
            for i in range(1, 7)
        ]
        # FB 2pc, no S6 AM → still coarse_am=100 (FB is AP, not AM)
        inv_fb_only = [
            _disc(
                f"d{i}",
                slot=i,
                set_id=31300 if i in (5, 6) else 1,
                main_stat_type="atk" if i == 6 else "hp",
            )
            for i in range(1, 7)
        ]
        # S6 AM with main_stat_value=60 → coarse_am=160 → multiplier 20000
        inv_s6 = [
            _disc(
                f"d{i}",
                slot=i,
                set_id=1,
                main_stat_type="anomaly_mastery" if i == 6 else "hp",
                main_stat_value=60 if i == 6 else 0,
            )
            for i in range(1, 7)
        ]
        # FB 2pc + S6 AM → still coarse_am=160 (FB adds no AM axis)
        inv_fb_s6 = [
            _disc(
                f"d{i}",
                slot=i,
                set_id=31300 if i in (5, 6) else 1,
                main_stat_type="anomaly_mastery" if i == 6 else "hp",
                main_stat_value=60 if i == 6 else 0,
            )
            for i in range(1, 7)
        ]

        def opt(inv):
            return (
                optimize_discs(
                    base_build=base_build,
                    enemy=_enemy(),
                    combo_steps=next(iter(event_log_by_am.values())),
                    event_log_by_am=event_log_by_am,
                    inventory=inv,
                    disc_set_modifiers={},
                    constraints=OptimizerConstraints(),
                    conditions=ActiveConditions(),
                )
                .builds[0]
                .total_damage
            )

        dmg_base = opt(inv_base)
        dmg_fb_only = opt(inv_fb_only)
        dmg_s6 = opt(inv_s6)
        dmg_fb_s6 = opt(inv_fb_s6)

        # FB-only must score the same as base (both coarse_am=100)
        assert dmg_fb_only == pytest.approx(dmg_base), (
            "FB-only should map to coarse_am=100, same as base — FB gives AP not AM"
        )
        # S6 AM must score higher (coarse_am=160, multiplier 2×)
        assert dmg_s6 > 1.8 * dmg_base
        # FB + S6 AM must score the same as S6 AM alone (both coarse_am=160)
        assert dmg_fb_s6 == pytest.approx(dmg_s6), (
            "FB+S6 AM should map to coarse_am=160, same as S6 AM alone — FB adds no axis"
        )


class TestStepSignatureConsolidation:
    """Tests for the multiplicity-weighted step consolidation in _build_frame_contexts.

    Consolidation collapses steps sharing a signature (step_kind, scope/anomaly_type,
    multiplier/procs, in_stun, conditions, buff_window_state) into a single weighted
    entry. The scoring loop becomes ``total += count * compute_*(ctx, disc)``.
    This is exact for linear damage sums.
    """

    def _opt(
        self,
        steps: list,
        *,
        inventory: list[DiscCandidate] | None = None,
    ) -> float:
        inv = inventory or _six_slots()
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=steps,
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(top_n=1),
            conditions=ActiveConditions(),
        )
        assert result.builds, "optimizer returned no builds"
        return result.builds[0].total_damage

    def test_repeated_combo_steps_consolidated_total_equals_expanded(self):
        """Six identical ComboSteps → one weighted ctx ×6; total == 6× single."""
        single_step = [
            ComboStep(
                label="BA",
                attack_id="a1",
                attack_name="Basic",
                scope=AttackScope.BASIC,
                multiplier=10000,
                element="ice",
            )
        ]
        six_steps = single_step * 6

        dmg_single = self._opt(single_step)
        dmg_six = self._opt(six_steps)

        assert dmg_six == pytest.approx(6 * dmg_single, rel=1e-9), (
            f"Consolidated 6x step ({dmg_six}) should equal 6x single ({6 * dmg_single})"
        )

    def test_repeated_anomaly_steps_consolidated_exact(self):
        """16 identical AnomalyStep(procs=1) → one weighted ctx ×16; total == 16× single."""
        single_tick = [
            AnomalyStep(
                label="Shock",
                attack_id="a1",
                anomaly_type="shock",
                element="electric",
                procs_override=1,
            )
        ]
        sixteen_ticks = single_tick * 16

        dmg_single = self._opt(single_tick)
        dmg_sixteen = self._opt(sixteen_ticks)

        assert dmg_sixteen == pytest.approx(16 * dmg_single, rel=1e-9), (
            f"16 Shock ticks ({dmg_sixteen}) should equal 16x single tick ({16 * dmg_single})"
        )

    def test_distinct_signatures_not_merged(self):
        """Steps with different multipliers have distinct signatures and are not merged."""
        step_low = ComboStep(
            label="BA1",
            attack_id="a1",
            attack_name="Basic 1",
            scope=AttackScope.BASIC,
            multiplier=5000,
            element="ice",
        )
        step_high = ComboStep(
            label="BA2",
            attack_id="a2",
            attack_name="Basic 2",
            scope=AttackScope.BASIC,
            multiplier=10000,
            element="ice",
        )
        # Verify that two distinct steps together == sum of two single-step runs
        dmg_low = self._opt([step_low])
        dmg_high = self._opt([step_high])
        dmg_both = self._opt([step_low, step_high])

        assert dmg_both == pytest.approx(dmg_low + dmg_high, rel=1e-9), (
            "Steps with different multipliers must remain separate — damage must be additive"
        )

    def test_forward_compat_distinct_scopes_produce_separate_groups(self):
        """Two steps with different scopes occupy different signature groups.

        Forward-compat stub: today ``conditions`` and ``in_stun`` are uniform,
        so only scope/multiplier/anomaly_type/procs differentiate groups. When
        per-step conditions or timed-buff window state arrive, they will be added
        to the step before grouping; this test locks the contract that DIFFERENT
        context-building inputs → DIFFERENT groups → no incorrect merging.
        """
        step_basic = ComboStep(
            label="BA",
            attack_id="a1",
            attack_name="Basic",
            scope=AttackScope.BASIC,
            multiplier=10000,
            element="ice",
        )
        step_special = ComboStep(
            label="SP",
            attack_id="a2",
            attack_name="Special",
            scope=AttackScope.SPECIAL,
            multiplier=10000,
            element="ice",
        )
        dmg_basic = self._opt([step_basic])
        dmg_special = self._opt([step_special])
        dmg_both = self._opt([step_basic, step_special])

        # Both steps in one combo: total must equal sum of individuals since scopes
        # use the same flat ATK base (no scope-filtered modifiers in this build).
        assert dmg_both == pytest.approx(dmg_basic + dmg_special, rel=1e-9)

    def test_mixed_combo_and_anomaly_consolidation(self):
        """A realistic anomaly-heavy combo: 6 basics + 16 Shock ticks.

        Consolidated into 2 unique signatures (1 ComboStep ctx ×6, 1 AnomalyStep ctx ×16).
        Total must match running the same steps expanded one-by-one.
        """
        basic = ComboStep(
            label="BA",
            attack_id="a1",
            attack_name="Basic",
            scope=AttackScope.BASIC,
            multiplier=10000,
            element="ice",
        )
        shock = AnomalyStep(
            label="Shock",
            attack_id="a2",
            anomaly_type="shock",
            element="electric",
            procs_override=1,
        )
        # Expanded combo (22 steps)
        expanded = [basic] * 6 + [shock] * 16
        # Compressed single-pass reference (same math, just fewer iterations)
        basic_only_dmg = self._opt([basic] * 6)
        shock_only_dmg = self._opt([shock] * 16)

        dmg_mixed = self._opt(expanded)
        assert dmg_mixed == pytest.approx(basic_only_dmg + shock_only_dmg, rel=1e-9), (
            "Mixed combo: consolidated total must equal sum of part-totals"
        )


def _ex_combo() -> list[ComboStep]:
    """A single EX-Special step — energy gating credits only EX-scope damage."""
    return [
        ComboStep(
            label="EX",
            attack_id="ex-1",
            attack_name="EX Special",
            scope=AttackScope.EX_SPECIAL,
            multiplier=10000,
            element="ice",
        ),
    ]


def _er_build(*, base_regen: int = 120, agent_er: int = 0) -> BuildSnapshot:
    """Base build carrying passive regen (bp/100 = energy/s) and kit ER% (bp/10000)."""
    return BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="ice",
        agent_base_energy_regen=base_regen,
        agent_energy_regen=agent_er,
    )


def _er_disc(disc_id: str, slot: int, er_bp: int) -> DiscCandidate:
    return _disc(disc_id, slot, substats=[{"stat": "energy_regen", "value": er_bp}])


class TestPrefilterTopK:
    """Item A — opt-in top-K candidate pre-filtering (heuristic accelerator)."""

    def _slot1_inv(self, n: int) -> list[DiscCandidate]:
        """slots 2-6 single fixed; slot 1 has n candidates with increasing atk_pct rolls."""
        inv = [d for d in _six_slots() if d.slot != 1]
        for i in range(n):
            inv.append(_disc(f"d1-{i}", slot=1, substats=[{"stat": "atk_pct", "value": 100 * i}]))
        return inv

    def _run(self, inv: list[DiscCandidate], **ckw):
        return optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(**ckw),
            conditions=ActiveConditions(),
        )

    def test_default_none_is_exhaustive(self):
        """prefilter_top_k=None (default) drops nothing."""
        result = self._run(self._slot1_inv(4), top_n=10)
        assert result.prefiltered == 0
        assert result.evaluated == 4

    def test_k_geq_group_identical_to_exhaustive(self):
        """K >= group size is exact: same builds and evaluated count as exhaustive."""
        inv = self._slot1_inv(5)
        ex = self._run(inv, top_n=10)
        pf = self._run(inv, top_n=10, prefilter_top_k=5)
        assert pf.prefiltered == 0
        assert pf.evaluated == ex.evaluated
        assert [b.disc_ids for b in pf.builds] == [b.disc_ids for b in ex.builds]

    def test_small_k_prunes_but_preserves_optimum(self):
        """Small K reduces evaluated count while keeping the top build.

        Union keep (top-UNION_STAT_KEEP per synergy stat) expands beyond K_dmg,
        so `prefiltered` depends on stat diversity in the bucket.  The key
        invariant is that the optimum is preserved and evaluated is reduced.
        """
        inv = self._slot1_inv(5)
        ex = self._run(inv, top_n=3)
        pf = self._run(inv, top_n=3, prefilter_top_k=2)
        assert pf.prefiltered >= 0  # union expansion may rescue some discs
        assert pf.evaluated < ex.evaluated
        assert pf.builds[0].disc_ids == ex.builds[0].disc_ids

    def test_keeps_best_candidate_per_set(self):
        """Grouping is by (slot, set_id): K=1 keeps the best disc of EACH set in a slot.

        Union keep may also rescue lower-ranked discs via synergy-stat keep, so
        prefiltered is at least 0.  The correctness assertion is that the top build
        per set uses the highest-atk disc from each set.
        """
        inv = [d for d in _six_slots() if d.slot != 1]  # slots 2-6 are set 1
        inv.append(_disc("s1a", slot=1, set_id=1, substats=[{"stat": "atk_pct", "value": 2000}]))
        inv.append(_disc("s1b", slot=1, set_id=1, substats=[{"stat": "atk_pct", "value": 1000}]))
        inv.append(_disc("s2a", slot=1, set_id=2, substats=[{"stat": "atk_pct", "value": 50}]))
        inv.append(_disc("s2b", slot=1, set_id=2, substats=[{"stat": "atk_pct", "value": 10}]))
        result = self._run(inv, top_n=10, prefilter_top_k=1)
        assert result.prefiltered >= 0  # union may rescue weaker discs from small buckets
        disc_ids_0 = {b.disc_ids[0] for b in result.builds}
        # Both sets must be represented (the core grouping-by-set_id invariant).
        assert "s1a" in disc_ids_0
        assert "s2a" in disc_ids_0
        assert result.builds[0].disc_ids[0] == "s1a"  # absolute best is ranked first


class TestEnergyGating:
    """Item B — opt-in energy-gated EX credit (ER% influences optimizer rankings)."""

    def _run(self, inv, combo, build=None, **ckw):
        return optimize_discs(
            base_build=build or _er_build(),
            enemy=_enemy(),
            combo_steps=combo,
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(**ckw),
            conditions=ActiveConditions(),
        )

    def test_no_constraint_er_disc_has_no_effect(self):
        """Without rotation_energy_cost, ER% does not change damage (it isn't a damage stat)."""
        inv = [d for d in _six_slots() if d.slot != 6]
        inv.append(_er_disc("d6-er", 6, er_bp=5000))
        inv.append(_disc("d6-plain", 6))
        result = self._run(inv, _ex_combo(), top_n=10)
        assert len(result.builds) == 2
        assert result.builds[0].total_damage == pytest.approx(result.builds[1].total_damage)

    def test_ex_only_combo_scales_by_feasibility(self):
        """EX-only combo at feasibility 0.5 → total is exactly half the ungated total."""
        inv = _six_slots()  # no ER discs → er_mult = 1.0
        ungated = self._run(inv, _ex_combo(), top_n=1)
        # base_regen 120 → 1.2/s; duration 10s → 12 energy; cost 24 → feasibility 0.5
        gated = self._run(
            inv, _ex_combo(), top_n=1, rotation_energy_cost=24.0, rotation_duration_s=10.0
        )
        assert gated.builds[0].total_damage == pytest.approx(
            0.5 * ungated.builds[0].total_damage
        )

    def test_starved_rotation_er_disc_outranks_plain(self):
        """When energy-starved, the ER disc earns more EX credit and ranks first."""
        inv = [d for d in _six_slots() if d.slot != 6]
        inv.append(_er_disc("d6-er", 6, er_bp=5000))  # +50% ER
        inv.append(_disc("d6-plain", 6))
        result = self._run(
            inv, _ex_combo(), top_n=10, rotation_energy_cost=40.0, rotation_duration_s=10.0
        )
        assert result.builds[0].disc_ids[5] == "d6-er"
        assert result.builds[0].total_damage > result.builds[1].total_damage

    def test_fully_fed_rotation_er_disc_ties_plain(self):
        """Once the rotation is self-sustaining (feasibility caps at 1.0), ER stops mattering."""
        inv = [d for d in _six_slots() if d.slot != 6]
        inv.append(_er_disc("d6-er", 6, er_bp=5000))
        inv.append(_disc("d6-plain", 6))
        # base_regen 120 → 1.2/s; duration 10s → ≥12 energy ≥ cost 5 → feasibility 1.0 for both
        result = self._run(
            inv, _ex_combo(), top_n=10, rotation_energy_cost=5.0, rotation_duration_s=10.0
        )
        assert len(result.builds) == 2
        assert result.builds[0].total_damage == pytest.approx(result.builds[1].total_damage)

    def test_prefilter_keeps_er_disc_when_gating(self):
        """A×B: with gating on, K=1 keeps the high-ER disc even if its raw damage is lowest."""
        inv = [d for d in _six_slots() if d.slot != 6]
        # Same set; plain disc has a damage roll, ER disc has none → ER disc loses on raw damage.
        inv.append(_disc("d6-plain", 6, substats=[{"stat": "atk_pct", "value": 2000}]))
        inv.append(_er_disc("d6-er", 6, er_bp=5000))
        result = self._run(
            inv,
            _ex_combo(),
            top_n=10,
            prefilter_top_k=1,
            rotation_energy_cost=40.0,
            rotation_duration_s=10.0,
        )
        kept_slot6 = {b.disc_ids[5] for b in result.builds}
        assert "d6-er" in kept_slot6  # survived prefilter via the ER-keep guard
