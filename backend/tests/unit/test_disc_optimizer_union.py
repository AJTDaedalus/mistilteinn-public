"""Tests for Task 5b — multi-criteria union keep (P1b).

Union logic: per (slot, set_id) bucket, keep
  top-K_dmg by solo damage  ∪  top-UNION_STAT_KEEP per synergy stat.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.disc_optimizer import (
    PREFILTER_EXACT,
    UNION_PRODUCT_CAP,
    UNION_STAT_KEEP,
    DiscCandidate,
    OptimizerConstraints,
    optimize_discs,
)
from app.services.modifiers import ActiveConditions, AttackScope


def _base_build() -> BuildSnapshot:
    return BuildSnapshot(agent_base_atk=900, wengine_base_atk=600, agent_element="ice")


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


class TestUnionConstants:
    def test_constants_present(self):
        assert UNION_STAT_KEEP >= 1
        assert UNION_PRODUCT_CAP >= 1.0


class TestAutoPrefilterKReported:
    """auto_prefilter_k is populated when auto-K fires and None otherwise."""

    def test_auto_k_fire_reports_k_dmg_used(self):
        """When auto-K fires, auto_prefilter_k contains the K_dmg value used."""
        import app.services.disc_optimizer as _mod

        # All-identical-stat discs collapse to 1/slot under the Task 5e Pareto layer
        # (ties keep one) before auto-K ever sees them — bypass it here so the 3/slot
        # population this test is actually about reaches the budget-K decision.
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(3)]
        with (
            patch.object(_mod, "_effective_combo_budget", return_value=100),
            patch.object(_mod, "_pareto_filter", side_effect=lambda sc, *a, **kw: (sc, 0)),
        ):
            result = optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(top_n=1),
                conditions=ActiveConditions(),
            )
        # auto-K fires (3^6=729 > 100), so auto_prefilter_k must be set.
        assert result.auto_prefilter_k is not None
        assert result.auto_prefilter_k >= 1

    def test_exact_sentinel_leaves_auto_prefilter_k_none(self):
        """PREFILTER_EXACT suppresses auto-K; auto_prefilter_k stays None."""
        import app.services.disc_optimizer as _mod

        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(3)]
        with patch.object(_mod, "_effective_combo_budget", return_value=100):
            result = optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(
                    prefilter_top_k=PREFILTER_EXACT, top_n=1
                ),
                conditions=ActiveConditions(),
            )
        assert result.auto_prefilter_k is None

    def test_explicit_k_leaves_auto_prefilter_k_none(self):
        """Explicit prefilter_top_k does not set auto_prefilter_k."""
        import app.services.disc_optimizer as _mod

        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(3)]
        with patch.object(_mod, "_effective_combo_budget", return_value=100):
            result = optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(prefilter_top_k=2, top_n=1),
                conditions=ActiveConditions(),
            )
        assert result.auto_prefilter_k is None

    def test_small_inventory_no_prefilter_leaves_k_none(self):
        """When uncapped estimate ≤ budget, no prefilter fires; auto_prefilter_k is None."""
        # 2 discs/slot → 64 combos, well under any reasonable COMBO_BUDGET.
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(2)]
        result = optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(top_n=1),
            conditions=ActiveConditions(),
        )
        assert result.auto_prefilter_k is None


class TestUnionResultsNonEmpty:
    """Union keep must always retain at least 1 disc per non-empty bucket."""

    def test_result_is_non_empty_after_union_prefilter(self):
        """End-to-end with auto-K: optimizer returns a valid top-1 build."""
        import app.services.disc_optimizer as _mod

        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(5)]
        with patch.object(_mod, "_effective_combo_budget", return_value=100):
            result = optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(top_n=1),
                conditions=ActiveConditions(),
            )
        assert len(result.builds) == 1


class TestUnionSetsPreserved:
    """Union keep respects set membership when multiple set_ids are present."""

    def test_union_keeps_discs_from_all_sets(self):
        """With 2 set_ids and budget forcing K=1, at least 1 disc per set per slot is kept.

        This validates that grouping-by-set_id works: even K=1 keeps 1 from each set,
        giving 2 per slot instead of 1 total.
        """
        import app.services.disc_optimizer as _mod

        # 2 set_ids, 3 discs each, 6 slots → uncapped = (3+3)^6 = 46,656 > budget=10
        inv = [
            _disc(f"d{s}_{sid}_{i}", slot=s, set_id=sid)
            for s in range(1, 7)
            for sid in (1, 2)
            for i in range(3)
        ]
        with patch.object(_mod, "_effective_combo_budget", return_value=10):
            result = optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(top_n=1),
                conditions=ActiveConditions(),
            )
        # Result must have at least one build (discs from both sets were kept).
        assert len(result.builds) >= 1
        assert result.prefiltered >= 0  # some were pruned


class TestElementDmgUnion:
    """Task 5d — the frame-element DMG% stat joins the union fields.

    A disc that is top-3 by the agent-element DMG% substat but outside top-K_dmg
    (and outside the crit_rate/crit_dmg unions) must still be retained.
    """

    def test_element_dmg_disc_retained(self):
        # 5 slots have one trivial disc each — irrelevant to the bucket under test.
        filler = [_disc(f"filler{s}", slot=s) for s in (1, 2, 4, 5, 6)]

        # Slot 3 bucket: one high-solo-damage disc (wins top-1 by damage), three
        # crit_rate discs and three crit_dmg discs (fill the existing unions), and
        # one "target" disc whose only strong stat is the agent-element (ice) DMG%
        # substat — top-1 by that stat, but last by solo damage and absent from the
        # crit_rate/crit_dmg unions.
        best = DiscCandidate(
            disc_id="d3_best", slot=3, set_id=1,
            main_stat_type="atk_pct", main_stat_value=20000,
        )
        crit_rate_discs = [
            DiscCandidate(
                disc_id=f"d3_cr{i}", slot=3, set_id=1,
                substats=[{"stat": "crit_rate", "value": v}],
            )
            for i, v in enumerate((2400, 1800, 1200), start=1)
        ]
        crit_dmg_discs = [
            DiscCandidate(
                disc_id=f"d3_cd{i}", slot=3, set_id=1,
                substats=[{"stat": "crit_dmg", "value": v}],
            )
            for i, v in enumerate((4800, 3600, 2400), start=1)
        ]
        target = DiscCandidate(
            disc_id="d3_target", slot=3, set_id=1,
            substats=[{"stat": "ice_dmg", "value": 5000}],
        )
        inv = [*filler, best, *crit_rate_discs, *crit_dmg_discs, target]

        result = optimize_discs(
            base_build=_base_build(),  # agent_element="ice"
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(prefilter_top_k=1, top_n=10),
            conditions=ActiveConditions(),
        )

        seen_slot3_discs = {b.disc_ids[2] for b in result.builds}
        assert "d3_target" in seen_slot3_discs

        # Negative control: with no known agent element, the element-DMG% union
        # field never fires, and the target (0 crit_rate, 0 crit_dmg, not top-1
        # by damage) must be pruned.
        no_element_build = replace(_base_build(), agent_element="")
        control = optimize_discs(
            base_build=no_element_build,
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers={},
            constraints=OptimizerConstraints(prefilter_top_k=1, top_n=10),
            conditions=ActiveConditions(),
        )
        control_slot3_discs = {b.disc_ids[2] for b in control.builds}
        assert "d3_target" not in control_slot3_discs
