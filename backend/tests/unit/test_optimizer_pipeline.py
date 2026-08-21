"""Unit tests for optimizer_pipeline: run_optimizer_pipeline."""

from app.schemas.optimizer import DiscOptimizeResponse
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.disc_optimizer import (
    DiscCandidate,
    OptimizerConstraints,
)
from app.services.modifiers import ActiveConditions
from app.services.optimizer_pipeline import ResolvedPayload, run_optimizer_pipeline


def _make_payload(inventory: list[DiscCandidate] | None = None) -> ResolvedPayload:
    """Build a minimal ResolvedPayload using real services."""
    from app.services.combo_types import ComboStep
    from app.services.modifiers import AttackScope

    base_build = BuildSnapshot(
        agent_base_atk=900,
        wengine_base_atk=600,
        agent_element="ice",
        modifiers=[],
    )
    enemy = EnemySnapshot(level=60, base_def=50, element_res=0)
    step = ComboStep(
        label="BA1",
        attack_id="att-1",
        attack_name="Basic",
        scope=AttackScope.BASIC,
        multiplier=10000,
        element="ice",
    )

    if inventory is None:
        inventory = [
            DiscCandidate(
                disc_id=f"d{i}",
                slot=i,
                set_id=1,
                main_stat_type="atk",
                main_stat_value=0,
                substats=[],
            )
            for i in range(1, 7)
        ]

    return ResolvedPayload(
        scoring_base=base_build,
        scoring_snap=base_build,
        enemy_snap=enemy,
        all_step_lists=[[step]],
        inventory=inventory,
        disc_summary_map={},
        disc_set_modifiers={},
        constraints=OptimizerConstraints(top_n=5),
        conditions=ActiveConditions(),
        crit_mode=None,  # type: ignore[arg-type]
        is_stunned=False,
        stun_dmg_mult=15000,
        combo_ids_ordered=["c1"],
        combo_id="c1",
        combo_name="DPS Combo",
        agent_name="Zhu Yuan",
        enemy_name="Metal Crab",
    )


class TestRunOptimizerPipeline:
    def test_returns_disc_optimize_response(self):
        payload = _make_payload()
        response = run_optimizer_pipeline(payload)
        assert isinstance(response, DiscOptimizeResponse)

    def test_builds_populated(self):
        payload = _make_payload()
        response = run_optimizer_pipeline(payload)
        assert len(response.builds) >= 1

    def test_metadata_propagated(self):
        payload = _make_payload()
        response = run_optimizer_pipeline(payload)
        assert response.agent_name == "Zhu Yuan"
        assert response.enemy_name == "Metal Crab"
        assert response.combo_name == "DPS Combo"

    def test_empty_inventory_returns_empty_builds(self):
        payload = _make_payload(
            inventory=[
                DiscCandidate(
                    disc_id=f"d{i}",
                    slot=i,
                    set_id=1,
                    main_stat_type="atk",
                    main_stat_value=0,
                    substats=[],
                )
                for i in range(1, 6)  # missing slot 6
            ]
        )
        response = run_optimizer_pipeline(payload)
        assert response.builds == []


class TestOptimizerKnobsThreading:
    """prefilter_top_k / energy gating flow through the pipeline into the response."""

    def _inv_two_in_slot1(self) -> list[DiscCandidate]:
        inv = [
            DiscCandidate(disc_id=f"d{i}", slot=i, set_id=1, main_stat_type="atk", substats=[])
            for i in range(2, 7)
        ]
        inv.append(
            DiscCandidate(
                disc_id="d1-strong",
                slot=1,
                set_id=1,
                main_stat_type="atk",
                substats=[{"stat": "atk_pct", "value": 2000}],
            )
        )
        inv.append(
            DiscCandidate(
                disc_id="d1-weak", slot=1, set_id=1, main_stat_type="atk", substats=[]
            )
        )
        return inv

    def test_prefiltered_reported_in_response(self):
        from dataclasses import replace

        payload = _make_payload(inventory=self._inv_two_in_slot1())
        payload = replace(
            payload, constraints=OptimizerConstraints(top_n=5, prefilter_top_k=1)
        )
        response = run_optimizer_pipeline(payload)
        # Union keep may rescue the weak disc when bucket is tiny (size ≤ UNION_STAT_KEEP).
        assert response.prefiltered >= 0
        assert response.builds[0].disc_ids[0] == "d1-strong"

    def test_default_constraints_report_zero_prefiltered(self):
        payload = _make_payload()
        response = run_optimizer_pipeline(payload)
        assert response.prefiltered == 0

    def test_explicit_prefilter_k_reports_no_auto_prefilter_k(self):
        """auto_prefilter_k is None when the caller pins prefilter_top_k explicitly —
        the field only signals the budget's own auto-K choice (Task 7)."""
        from dataclasses import replace

        payload = _make_payload(inventory=self._inv_two_in_slot1())
        payload = replace(
            payload, constraints=OptimizerConstraints(top_n=5, prefilter_top_k=1)
        )
        response = run_optimizer_pipeline(payload)
        assert response.auto_prefilter_k is None

    def test_auto_prefilter_k_reported_when_budget_forces_auto_k(self):
        """When prefilter_top_k is unset and the time-denominated budget auto-selects
        K, the chosen K_dmg threads through to the response (Task 7)."""
        from dataclasses import replace
        from unittest.mock import patch

        import app.services.disc_optimizer as disc_optimizer_module

        inv = [
            DiscCandidate(disc_id=f"d{s}{i}", slot=s, set_id=1, main_stat_type="atk", substats=[])
            for s in range(1, 7)
            for i in range(3)
        ]
        payload = _make_payload(inventory=inv)
        payload = replace(payload, constraints=OptimizerConstraints(top_n=1))
        with (
            patch.object(disc_optimizer_module, "_effective_combo_budget", return_value=100),
            patch.object(
                disc_optimizer_module,
                "_pareto_filter",
                side_effect=lambda sc, *a, **kw: (sc, 0),
            ),
        ):
            response = run_optimizer_pipeline(payload)
        assert response.auto_prefilter_k is not None


class TestSearchTransparency:
    """SearchTransparencySchema + search_summary (Task B5)."""

    def test_exact_run_is_exact_with_no_prefilter_text(self):
        payload = _make_payload()  # 1 disc per slot -> nothing to prefilter
        response = run_optimizer_pipeline(payload)

        st = response.search_transparency
        assert st.is_exact is True
        assert st.prefiltered == 0
        assert st.auto_prefilter_k is None
        assert st.evaluated == response.evaluated
        assert st.total_space == 1  # 1 candidate per slot -> exactly 1 raw combo
        assert "prefilter" not in response.search_summary.lower()
        assert "exact" in response.search_summary.lower()

    def test_explicit_prefilter_surfaces_k_and_near_exact_label(self):
        """12 slot-1 candidates on a crit_rate/crit_dmg trade-off (an antichain, so
        none Pareto-dominate each other) plus one atk_pct disc that wins top-damage
        outright. With prefilter_top_k=1 the K=1-by-damage ∪ top-3-per-union-stat
        keep can't cover all 13 candidates, so some are deterministically pruned
        (verified empirically: 7 survive, 6 pruned) — this fixture exercises a real
        prefilter reduction rather than the union-keep rescuing everything."""
        from dataclasses import replace

        n = 12
        inv = [
            DiscCandidate(
                disc_id=f"d1_{i}",
                slot=1,
                set_id=1,
                main_stat_type="atk",
                substats=[
                    {"stat": "crit_rate", "value": i * 100},
                    {"stat": "crit_dmg", "value": (n - 1 - i) * 100},
                ],
            )
            for i in range(n)
        ]
        inv.append(
            DiscCandidate(
                disc_id="d1_best",
                slot=1,
                set_id=1,
                main_stat_type="atk_pct",
                main_stat_value=20000,
                substats=[],
            )
        )
        inv += [
            DiscCandidate(disc_id=f"d{i}", slot=i, set_id=1, main_stat_type="atk", substats=[])
            for i in range(2, 7)
        ]
        payload = _make_payload(inventory=inv)
        payload = replace(
            payload, constraints=OptimizerConstraints(top_n=20, prefilter_top_k=1)
        )
        response = run_optimizer_pipeline(payload)

        st = response.search_transparency
        assert st.total_space == n + 1  # raw: 13 candidates in slot 1, 1 in each other slot
        assert st.prefiltered == 6
        assert st.evaluated == 7
        assert st.auto_prefilter_k is None  # explicit K, not budget-auto
        assert st.is_exact is False
        assert "K=1" in response.search_summary
        assert "near-exact" in response.search_summary.lower()

    def test_auto_prefilter_surfaces_effective_k_and_near_exact_label(self):
        from dataclasses import replace
        from unittest.mock import patch

        import app.services.disc_optimizer as disc_optimizer_module

        inv = [
            DiscCandidate(disc_id=f"d{s}{i}", slot=s, set_id=1, main_stat_type="atk", substats=[])
            for s in range(1, 7)
            for i in range(3)
        ]
        payload = _make_payload(inventory=inv)
        payload = replace(payload, constraints=OptimizerConstraints(top_n=1))
        with (
            patch.object(disc_optimizer_module, "_effective_combo_budget", return_value=100),
            patch.object(
                disc_optimizer_module,
                "_pareto_filter",
                side_effect=lambda sc, *a, **kw: (sc, 0),
            ),
        ):
            response = run_optimizer_pipeline(payload)

        st = response.search_transparency
        assert st.total_space == 3**6  # raw: 3 candidates per slot, 6 slots
        assert st.auto_prefilter_k is not None
        assert st.is_exact is False
        assert f"K={st.auto_prefilter_k}" in response.search_summary
        assert "near-exact" in response.search_summary.lower()
