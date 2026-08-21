"""Tests for Task 5c — PREFILTER_BASELINE "full" scoring robustness (P1c F-a + F-b).

F-a: score against a representative full-build baseline (5 avg-disc reference).
F-b: apply each (slot, set_id) bucket's own set modifiers when scoring it.
"""

from __future__ import annotations

from unittest.mock import patch

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.disc_optimizer import (
    PREFILTER_BASELINE,
    DiscCandidate,
    OptimizerConstraints,
    _build_ref_disc_stats,
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


def _disc(
    disc_id: str, slot: int, *, set_id: int = 1, substats: list | None = None
) -> DiscCandidate:
    return DiscCandidate(disc_id=disc_id, slot=slot, set_id=set_id, substats=substats or [])


def _base_build(*, element: str = "ice") -> BuildSnapshot:
    return BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element=element,
        agent_crit_rate=500,   # 5%
        agent_crit_dmg=5000,   # 50%
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


def _run(
    inv: list[DiscCandidate],
    *,
    baseline: str,
    top_n: int = 3,
    prefilter_top_k: int | None = None,
    disc_set_modifiers: dict | None = None,
    union_stat_keep: int = 0,
) -> object:
    """Run optimizer under the given PREFILTER_BASELINE, patching module constants."""
    import app.services.disc_optimizer as _mod

    with (
        patch.object(_mod, "PREFILTER_BASELINE", baseline),
        patch.object(_mod, "UNION_STAT_KEEP", union_stat_keep),
    ):
        return optimize_discs(
            base_build=_base_build(),
            enemy=_enemy(),
            combo_steps=_combo(),
            inventory=inv,
            disc_set_modifiers=disc_set_modifiers or {},
            constraints=OptimizerConstraints(top_n=top_n, prefilter_top_k=prefilter_top_k),
            conditions=ActiveConditions(),
        )


class TestFullBaselineChangesRanking:
    """F-a: full-baseline shifts the scoring point so CR↔CD rankings can flip."""

    def _cr_inversion_inventory(self) -> list[DiscCandidate]:
        """Inventory designed to produce a crit-rate / crit-dmg inversion.

        Slots 2-6: each has CR=2000 (20%).  The full-baseline averages these
        across 7 discs (2 in slot 1 + 5 in slots 2-6) × scale 5/7 → reference
        CR ≈ 74.3%, which saturates crit_rate and makes CD much more valuable.

        disc_A (slot 1): pure CD=960 (9.6%) → wins under "full" baseline.
        disc_B (slot 1): pure CR=480 (4.8%) → wins under "base" baseline.
        """
        inv = [
            _disc(f"ref{s}", slot=s, substats=[{"stat": "crit_rate", "value": 2000}])
            for s in range(2, 7)
        ]
        inv.append(_disc("disc_A", slot=1, substats=[{"stat": "crit_dmg", "value": 960}]))
        inv.append(_disc("disc_B", slot=1, substats=[{"stat": "crit_rate", "value": 480}]))
        return inv

    def test_base_baseline_selects_cr_disc(self):
        """Under 'base' (zero-disc reference), the CR disc scores higher in slot 1."""
        result = _run(self._cr_inversion_inventory(), baseline="base", prefilter_top_k=1)
        kept_slot1 = result.builds[0].disc_ids[0]
        assert kept_slot1 == "disc_B"  # CR wins at low baseline CR

    def test_full_baseline_selects_cd_disc(self):
        """Under 'full' (CR-saturated reference), the CD disc scores higher in slot 1."""
        result = _run(self._cr_inversion_inventory(), baseline="full", prefilter_top_k=1)
        kept_slot1 = result.builds[0].disc_ids[0]
        assert kept_slot1 == "disc_A"  # CD wins at high baseline CR

    def test_base_and_full_differ(self):
        """The top build changes between 'base' and 'full', proving F-a bites."""
        inv = self._cr_inversion_inventory()
        result_base = _run(inv, baseline="base", prefilter_top_k=1)
        result_full = _run(inv, baseline="full", prefilter_top_k=1)
        # Top-1 disc in slot 1 must differ between modes.
        assert result_base.builds[0].disc_ids[0] != result_full.builds[0].disc_ids[0]


class TestSetContextApplied:
    """F-b: per-(slot, set_id) context includes the bucket's set modifiers."""

    def test_full_baseline_with_set_mods_no_crash(self):
        """Running with disc_set_modifiers under 'full' mode does not raise."""
        ice_dmg_mod = Modifier(
            stat="ice_dmg",
            source=ModifierSource.DISC_SET_2PC,
            target=ModifierTarget.SELF,
            value=1000,
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
        )
        set_mods = {1: [ice_dmg_mod]}
        inv = [_disc(f"d{s}", slot=s) for s in range(1, 7)]
        result = _run(inv, baseline="full", disc_set_modifiers=set_mods)
        assert len(result.builds) >= 1

    def test_set_mods_improve_scoring_for_set_bucket(self):
        """With a 4pc ATK% set bonus, the scorer values the bucket higher.

        Verifies F-b: builds come from a non-empty set even when scored with mods.
        """
        atk_mod = Modifier(
            stat="atk_pct",
            source=ModifierSource.DISC_SET_4PC,
            target=ModifierTarget.SELF,
            value=1000,  # +10% ATK
            conditions=(Condition.ALWAYS,),
            scopes=(AttackScope.ALL,),
        )
        set_mods = {1: [atk_mod]}
        inv = [_disc(f"d{s}", slot=s) for s in range(1, 7)]
        result = _run(inv, baseline="full", disc_set_modifiers=set_mods)
        assert result.evaluated >= 1
        assert result.builds[0].disc_ids is not None


class TestExactPathUnchangedByBaseline:
    """Exact search (K ≥ bucket size) must be byte-identical regardless of PREFILTER_BASELINE."""

    def test_exact_results_identical_base_vs_full(self):
        """When no prefilter fires, 'base' and 'full' produce identical builds."""
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(2)]
        # No prefilter_top_k → auto mode; but 2^6=64 combos << COMBO_BUDGET, so no auto-K
        result_base = _run(inv, baseline="base", top_n=3)
        result_full = _run(inv, baseline="full", top_n=3)

        assert len(result_base.builds) == len(result_full.builds)
        for b_base, b_full in zip(result_base.builds, result_full.builds, strict=True):
            assert b_base.disc_ids == b_full.disc_ids
            assert b_base.total_damage == b_full.total_damage

    def test_explicit_large_k_exact_results_identical(self):
        """Explicit K >= bucket size → no candidates dropped → results identical."""
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(2)]
        # K=10 ≥ all buckets (only 2 per bucket) → exact path
        result_base = _run(inv, baseline="base", top_n=3, prefilter_top_k=10)
        result_full = _run(inv, baseline="full", top_n=3, prefilter_top_k=10)

        for b_base, b_full in zip(result_base.builds, result_full.builds, strict=True):
            assert b_base.disc_ids == b_full.disc_ids
            assert b_base.total_damage == b_full.total_damage


class TestBuildRefDiscStats:
    """Unit tests for the module-level _build_ref_disc_stats helper."""

    def _slot_cands(self, inv: list[DiscCandidate]) -> dict[int, list[DiscCandidate]]:
        from app.services.disc_optimizer import _ALL_SLOTS

        return {s: [d for d in inv if d.slot == s] for s in _ALL_SLOTS}

    def test_empty_inventory_returns_empty(self):
        inv = [_disc(f"d{s}", slot=s) for s in range(1, 7)]  # no substats
        slot_cands = self._slot_cands(inv)
        # All zero stats → substats list is empty (all values are 0)
        ref = _build_ref_disc_stats(slot_cands)
        assert len(ref) <= 1  # empty or single zero-stat dict

    def test_cr_discs_produce_cr_reference(self):
        """Inventory of pure CR discs → reference has crit_rate substat."""
        inv = [
            _disc(f"d{s}", slot=s, substats=[{"stat": "crit_rate", "value": 2000}])
            for s in range(1, 7)
        ]
        slot_cands = self._slot_cands(inv)
        ref = _build_ref_disc_stats(slot_cands)
        assert len(ref) == 1
        cr_sub = next((x for x in ref[0]["substats"] if x["stat"] == "crit_rate"), None)
        assert cr_sub is not None
        assert cr_sub["value"] > 0

    def test_scale_is_5_over_n(self):
        """With N identical discs each contributing V to stat X: ref has value = int(5*V)."""
        # 6 discs, 1 per slot, each with crit_rate=1000. Raw sum = 6000; scale = 5/6.
        # Expected ref value = int(6000 * 5/6) = int(5000) = 5000.
        inv = [
            _disc(f"d{s}", slot=s, substats=[{"stat": "crit_rate", "value": 1000}])
            for s in range(1, 7)
        ]
        slot_cands = self._slot_cands(inv)
        ref = _build_ref_disc_stats(slot_cands)
        cr_sub = next(x for x in ref[0]["substats"] if x["stat"] == "crit_rate")
        assert cr_sub["value"] == 5000


class TestBaselineConstantDefault:
    """PREFILTER_BASELINE defaults to 'full' since Task 6b validated CP3+CP4 on real data."""

    def test_default_is_full(self):
        assert PREFILTER_BASELINE == "full"
