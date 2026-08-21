"""Tests for Task 5a — combo-count estimator + budget-driven K selection (P1a)."""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from unittest.mock import patch

from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.combo_types import ComboStep
from app.services.disc_optimizer import (
    COMBO_BUDGET,
    COMBO_BUDGET_TIME_S,
    PREFILTER_EXACT,
    RATE_CTX,
    RATE_CTX_OVERHEAD_S,
    DiscCandidate,
    OptimizerConstraints,
    SetFrame,
    _compute_effective_k,
    _effective_combo_budget,
    _estimate_combo_count,
    _extract_bucket_sizes,
    optimize_discs,
)
from app.services.modifiers import ActiveConditions, AttackScope

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "optimizer"


def _disc(disc_id: str, slot: int, *, set_id: int = 1) -> DiscCandidate:
    return DiscCandidate(disc_id=disc_id, slot=slot, set_id=set_id)


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


def _load_owner_bucket_sizes() -> dict[tuple[int, int], int]:
    """Build {(slot, set_id): count} from the captured owner fixture."""
    with (_FIXTURE_DIR / "owner_twst1_buckets.json").open() as f:
        data = json.load(f)
    return {(b["slot"], b["set_id"]): b["count"] for b in data["buckets"]}


def _owner_frame() -> SetFrame:
    """The single frame from the incident: 2pc Branch+Blade + 4pc White Water."""
    return SetFrame(counts={32700: 2, 33500: 4})


class TestEstimatorMatchesBruteforce:
    def test_exhaustive_uncapped_equals_product(self):
        """Exhaustive estimator = exact combo count for a tiny inventory."""
        inv = [_disc(f"d{s}{i}", slot=s, set_id=1) for s in range(1, 7) for i in range(3)]
        sizes = _extract_bucket_sizes({s: [d for d in inv if d.slot == s] for s in range(1, 7)})
        brute = sum(1 for _ in product(*([range(3)] * 6)))  # 3^6 = 729
        assert _estimate_combo_count(sizes, None, {}, k=None) == brute == 729

    def test_exhaustive_capped_k1(self):
        """K=1 caps each bucket to 1, giving product-of-set-count per slot."""
        # Slot 1: 2 set_ids (1, 2) with 2 discs each → K=1 → 1+1=2 per slot
        inv = [
            _disc(f"d{s}_{sid}_{i}", slot=s, set_id=sid)
            for s in range(1, 7)
            for sid in (1, 2)
            for i in range(2)
        ]
        sizes = _extract_bucket_sizes({s: [d for d in inv if d.slot == s] for s in range(1, 7)})
        # Each slot has 2 set_ids, K=1 → 1 from each → 2 per slot → 2^6 = 64 total.
        assert _estimate_combo_count(sizes, None, {}, k=1) == 64

    def test_frames_uncapped_matches_owner_fixture(self):
        """Frames estimator reproduces the fixture's 12,529,002 uncapped combo count."""
        sizes = _load_owner_bucket_sizes()
        frame = _owner_frame()
        result = _estimate_combo_count(sizes, [frame], {}, k=None)
        assert result == 12_529_002

    def test_frames_k7_matches_design(self):
        """K=7 estimate matches the DESIGN's stated 989,898."""
        sizes = _load_owner_bucket_sizes()
        frame = _owner_frame()
        assert _estimate_combo_count(sizes, [frame], {}, k=7) == 989_898

    def test_frames_k8_matches_design(self):
        """K=8 estimate matches the DESIGN's stated 1,628,672."""
        sizes = _load_owner_bucket_sizes()
        frame = _owner_frame()
        assert _estimate_combo_count(sizes, [frame], {}, k=8) == 1_628_672


class TestBudgetSelectsExpectedK:
    def test_uncapped_below_budget_returns_none(self):
        """When uncapped estimate ≤ budget, no prefilter is applied (exact search)."""
        # 2 discs per slot → 64 combos, well under COMBO_BUDGET.
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(2)]
        sizes = _extract_bucket_sizes({s: [d for d in inv if d.slot == s] for s in range(1, 7)})
        constraints = OptimizerConstraints(top_n=1)
        assert _compute_effective_k(sizes, constraints, COMBO_BUDGET) is None

    def test_budget_1m_selects_k7_on_owner(self):
        """budget=1,000,000 → K=7 (est=989,898 ≤ 1M; K=8 est=1,628,672 > 1M)."""
        sizes = _load_owner_bucket_sizes()
        frame = _owner_frame()
        constraints = OptimizerConstraints(allowed_frames=[frame], top_n=1)
        assert _compute_effective_k(sizes, constraints, 1_000_000) == 7

    def test_budget_1628672_selects_k8_on_owner(self):
        """budget=1,628,672 → K=8 (est=1,628,672 ≤ budget; K=9 est=2,549,070 > budget)."""
        sizes = _load_owner_bucket_sizes()
        frame = _owner_frame()
        constraints = OptimizerConstraints(allowed_frames=[frame], top_n=1)
        assert _compute_effective_k(sizes, constraints, 1_628_672) == 8


class TestExplicitKAndExactSentinelOverride:
    def _large_constraints(self) -> tuple[list[DiscCandidate], OptimizerConstraints]:
        """An inventory and constraints whose uncapped estimate > COMBO_BUDGET."""
        # 100 discs per slot → 100^6 = 10^12 combos, way over budget.
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(100)]
        constraints = OptimizerConstraints(top_n=1)
        return inv, constraints

    def _large_sizes(self) -> dict[tuple[int, int], int]:
        inv, _ = self._large_constraints()
        return _extract_bucket_sizes({s: [d for d in inv if d.slot == s] for s in range(1, 7)})

    def test_explicit_positive_k_bypasses_auto(self):
        """An explicit prefilter_top_k=5 is used unchanged, even for large spaces."""
        sizes = self._large_sizes()
        constraints = OptimizerConstraints(prefilter_top_k=5, top_n=1)
        assert _compute_effective_k(sizes, constraints, COMBO_BUDGET) == 5

    def test_prefilter_exact_sentinel_forces_no_prefilter(self):
        """PREFILTER_EXACT sentinel → effective_k=None (exact search, no auto-K)."""
        sizes = self._large_sizes()
        constraints = OptimizerConstraints(prefilter_top_k=PREFILTER_EXACT, top_n=1)
        assert _compute_effective_k(sizes, constraints, COMBO_BUDGET) is None

    def test_auto_k_applied_when_no_override(self):
        """With no explicit K, auto-K kicks in when uncapped > budget."""
        sizes = self._large_sizes()
        constraints = OptimizerConstraints(top_n=1)  # prefilter_top_k=None
        k = _compute_effective_k(sizes, constraints, COMBO_BUDGET)
        assert k is not None
        assert k >= 1
        # Verify the resulting estimate is within budget.
        assert _estimate_combo_count(sizes, None, {}, k=k) <= COMBO_BUDGET

    def test_auto_k_is_largest_k_in_budget(self):
        """Selected K is the largest that keeps the estimate ≤ budget (not K+1)."""
        sizes = self._large_sizes()
        constraints = OptimizerConstraints(top_n=1)
        k = _compute_effective_k(sizes, constraints, COMBO_BUDGET)
        assert k is not None
        # K+1 should exceed the budget (K is truly the maximum).
        assert _estimate_combo_count(sizes, None, {}, k=k + 1) > COMBO_BUDGET

    def test_optimize_discs_auto_prefilter_reduces_result_count(self):
        """End-to-end: auto-K fires for large inventory, result is still non-empty.

        Patches the effective combo budget to 100 so the test runs on a tiny inventory:
        3 discs/slot → 3^6=729 combos > 100; K=2 (2^6=64 ≤ 100).
        """
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
        assert len(result.builds) == 1
        # auto_prefilter_k is set when auto-K fires, even if union keeps all discs.
        assert result.auto_prefilter_k is not None

    def test_optimize_discs_exact_sentinel_preserves_exhaustive(self):
        """PREFILTER_EXACT bypasses auto-K; result matches unconstrained auto run.

        Uses the same small budget patch so both runs are fast and we can prove
        the sentinel forces exact mode (prefiltered==0) even when auto-K would fire.
        """
        import app.services.disc_optimizer as _mod

        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(3)]
        with patch.object(_mod, "_effective_combo_budget", return_value=100):
            result_exact = optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(prefilter_top_k=PREFILTER_EXACT, top_n=1),
                conditions=ActiveConditions(),
            )
            optimize_discs(  # auto path (for contrast; not compared here)
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(top_n=1),
                conditions=ActiveConditions(),
            )
        assert result_exact.prefiltered == 0  # sentinel suppresses any prefilter
        assert len(result_exact.builds) == 1


def _repeated_signature_combo(n_signatures: int, repeats: int = 3) -> list[ComboStep]:
    """A combo whose STEP COUNT is n_signatures * repeats but whose unique-signature
    count (n_ctx) is exactly n_signatures — each signature repeated `repeats` times.
    Proves n_ctx tracks deduplicated contexts, not raw combo length.
    """
    steps = []
    for i in range(n_signatures):
        for _r in range(repeats):
            steps.append(
                ComboStep(
                    label=f"S{i}",
                    attack_id=f"att-{i}",
                    attack_name=f"Step {i}",
                    scope=AttackScope.BASIC,
                    multiplier=10000 + i,  # distinct multiplier -> distinct signature
                    element="ice",
                )
            )
    return steps


class TestEffectiveComboBudgetTimeS:
    """Task 6c — time-denominated budget: effective_combo_budget = TIME_S / (a + n/RATE)."""

    def test_large_n_ctx_gets_smaller_budget(self):
        """A stateful/high-fan-out combo (large n_ctx) gets a smaller budget than a plain
        multiplicative combo (small n_ctx) — the whole point of denominating in time."""
        small = _effective_combo_budget(1)
        large = _effective_combo_budget(24)
        assert large < small

    def test_small_n_ctx_matches_measured_rate(self):
        """_effective_combo_budget reproduces the CP7-fit formula exactly."""
        for n_ctx in (1, 6, 24):
            expected = int(COMBO_BUDGET_TIME_S / (RATE_CTX_OVERHEAD_S + n_ctx / RATE_CTX))
            assert _effective_combo_budget(n_ctx) == expected

    def test_n_ctx_zero_treated_as_one(self):
        """n_ctx=0 (degenerate/empty combo) must not divide by zero or blow up the budget."""
        assert _effective_combo_budget(0) == _effective_combo_budget(1)

    def test_n_ctx_signature_count_matches_built_contexts(self):
        """optimize_discs computes n_ctx as unique step signatures, not raw combo length,
        and feeds it to _effective_combo_budget."""
        import app.services.disc_optimizer as _mod

        combo = _repeated_signature_combo(n_signatures=4, repeats=3)  # 12 steps, 4 sigs
        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(2)]
        recorded_n_ctx: list[int] = []
        real_fn = _mod._effective_combo_budget

        def _spy(n_ctx: int) -> int:
            recorded_n_ctx.append(n_ctx)
            return real_fn(n_ctx)

        with patch.object(_mod, "_effective_combo_budget", side_effect=_spy):
            optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=combo,
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(top_n=1),
                conditions=ActiveConditions(),
            )
        assert recorded_n_ctx == [4]  # 4 unique signatures, not 12 raw steps

    def test_explicit_k_and_sentinel_still_override(self):
        """Explicit prefilter_top_k and PREFILTER_EXACT ignore the time-denominated
        budget entirely, even when it would be forced tiny by a huge n_ctx."""
        import app.services.disc_optimizer as _mod

        inv = [_disc(f"d{s}{i}", slot=s) for s in range(1, 7) for i in range(3)]
        with patch.object(_mod, "_effective_combo_budget", return_value=1):
            result_explicit = optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(prefilter_top_k=5, top_n=1),
                conditions=ActiveConditions(),
            )
            result_exact = optimize_discs(
                base_build=_base_build(),
                enemy=_enemy(),
                combo_steps=_combo(),
                inventory=inv,
                disc_set_modifiers={},
                constraints=OptimizerConstraints(prefilter_top_k=PREFILTER_EXACT, top_n=1),
                conditions=ActiveConditions(),
            )
        assert result_explicit.auto_prefilter_k is None
        assert result_exact.prefiltered == 0
        assert len(result_exact.builds) == 1
