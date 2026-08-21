"""Unit tests for the rank pipeline (Phase 2 — R2.6 Part A).

Uses maxed-out (remaining_rolls=0) discs so scoring is instant.
Verifies pickle round-trip, aggregation correctness, and set-filter behaviour.
"""

from __future__ import annotations

import pickle

import pytest

from app.schemas.scorer import RankFilters
from app.services.build_damage_service import BuildSnapshot, EnemySnapshot
from app.services.damage_calculator import CritMode
from app.services.disc_optimizer import DiscCandidate
from app.services.modifiers import ActiveConditions, Condition
from app.services.rank_pipeline import (
    PlainBuildDisc,
    ResolvedRankContext,
    ResolvedRankPayload,
    _aggregate,
    _apply_rank_filters,
    run_rank_pipeline_with_progress,
)
from app.services.support_recompute import SupportRecomputeKit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap() -> BuildSnapshot:
    return BuildSnapshot(agent_base_atk=900, wengine_base_atk=600, agent_element="electric")


def _enemy() -> EnemySnapshot:
    return EnemySnapshot(level=60, base_def=50, element_res=0)


def _conditions() -> ActiveConditions:
    return ActiveConditions(active={Condition.ALWAYS})


def _maxed_disc(disc_id: str, slot: int = 1, set_id: int = 100) -> DiscCandidate:
    """S-rank disc with 9 rolls used → remaining_rolls = 0, instant scoring."""
    return DiscCandidate(
        disc_id=disc_id,
        slot=slot,
        set_id=set_id,
        main_stat_type="hp_pct",
        main_stat_value=3000,
        substats=[
            {"stat": "atk_pct", "value": 900},  # 3 rolls × 300
            {"stat": "crit_rate", "value": 720},  # 3 rolls × 240
            {"stat": "crit_dmg", "value": 1440},  # 3 rolls × 480
        ],
    )


def _plain_build_disc(slot: int = 2, set_id: int = 100) -> PlainBuildDisc:
    return PlainBuildDisc(
        slot=slot,
        main_stat_type="atk_pct",
        main_stat_value=3000,
        substats=[],
        set_hakushin_id=set_id,
    )


def _ctx(
    build_id: str = "b1",
    build_name: str = "Build1",
    weight: float = 1.0,
    allowed_set_ids: list[int] | None = None,
    baseline_damage: float = 0.0,
    team_id: str | None = None,
    combo_id: str | None = None,
    enemy_profile_id: str | None = None,
    active_index: int | None = None,
) -> ResolvedRankContext:
    return ResolvedRankContext(
        build_id=build_id,
        build_name=build_name,
        scoring_base=_snap(),
        enemy_snap=_enemy(),
        combo_steps=[],
        conditions=_conditions(),
        crit_mode=CritMode.EXPECTED,
        is_stunned=False,
        stun_dmg_mult=15000,
        weight=weight,
        baseline_damage=baseline_damage,
        disc_set_modifiers={},
        allowed_set_ids=allowed_set_ids,
        build_discs=[_plain_build_disc()],
        team_id=team_id,
        combo_id=combo_id,
        enemy_profile_id=enemy_profile_id,
        active_index=active_index,
    )


def _payload(
    contexts: list[ResolvedRankContext],
    discs: list[DiscCandidate],
) -> ResolvedRankPayload:
    return ResolvedRankPayload(
        contexts=contexts,
        inventory=discs,
        disc_rarity_map={d.disc_id: "S" for d in discs},
    )


# ---------------------------------------------------------------------------
# Pickle round-trip
# ---------------------------------------------------------------------------


class TestPickle:
    def test_resolved_rank_payload_pickle_round_trip(self):
        ctx = _ctx()
        disc = _maxed_disc("d1")
        payload = _payload([ctx], [disc])
        restored = pickle.loads(pickle.dumps(payload))
        assert len(restored.contexts) == 1
        assert len(restored.inventory) == 1
        assert restored.inventory[0].disc_id == "d1"

    def test_plain_build_disc_pickle_round_trip(self):
        d = _plain_build_disc()
        r = pickle.loads(pickle.dumps(d))
        assert r.slot == d.slot
        assert r.disc_set.hakushin_id == d.set_hakushin_id

    def test_resolved_rank_context_with_support_kit_pickle_round_trip(self):
        """A context carrying a SupportRecomputeKit must survive pickle round-trip."""
        kit = SupportRecomputeKit(
            agent_base_hp=12000,
            core_hp_pct=0,
            we_initial_hp_pct=0,
            we_combat_hp_pct=0,
            we_secondary_hp_pct=0,
            disc_set_modifiers={},
            build_discs=[_plain_build_disc()],
            agent_hakushin_id="97000",
            agent_name="TestSupport",
            agent_specialty="support",
            agent_element="electric",
        )
        ctx = _ctx()
        ctx.support_recompute_kit = kit
        payload = _payload([ctx], [_maxed_disc("d1")])
        restored = pickle.loads(pickle.dumps(payload))
        rkit = restored.contexts[0].support_recompute_kit
        assert rkit is not None
        assert rkit.agent_base_hp == 12000
        assert rkit.agent_name == "TestSupport"
        assert len(rkit.build_discs) == 1


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


class TestPipelineExecution:
    def test_empty_inventory_returns_empty(self):
        payload = _payload([_ctx()], [])
        results = run_rank_pipeline_with_progress(payload, lambda p: None)
        assert results == []

    def test_single_maxed_disc_scores_zero_pct(self):
        """A maxed disc has no remaining rolls → ~0% improvement."""
        payload = _payload([_ctx(build_id="b1", weight=1.0)], [_maxed_disc("d1")])
        results = run_rank_pipeline_with_progress(payload, lambda p: None)
        assert len(results) == 1
        r = results[0]
        assert r["disc_id"] == "d1"
        assert r["best_build_avg"] == pytest.approx(0.0, abs=0.01)
        assert r["best_build_max"] == pytest.approx(0.0, abs=0.01)

    def test_progress_callback_fires(self):
        """Pipeline fires progress callback at least once per disc."""
        fired: list = []
        payload = _payload([_ctx()], [_maxed_disc("d1"), _maxed_disc("d2", slot=2)])

        def cb(p):
            fired.append((p.discs_done, p.discs_total))

        run_rank_pipeline_with_progress(payload, cb)
        assert len(fired) >= 1
        assert fired[-1][1] == 2  # discs_total = 2

    def test_set_filter_drops_unmatched_discs(self):
        ctx = _ctx(allowed_set_ids=[100])
        disc_match = _maxed_disc("d1", set_id=100)
        disc_no_match = _maxed_disc("d2", set_id=999)
        payload = _payload([ctx], [disc_match, disc_no_match])
        results = run_rank_pipeline_with_progress(payload, lambda p: None)
        ids = {r["disc_id"] for r in results}
        assert "d1" in ids
        assert "d2" not in ids

    def test_multi_context_per_build_breakdown_length(self):
        """Each result has per_build with one entry per context."""
        ctx1 = _ctx(build_id="b1")
        ctx2 = _ctx(build_id="b2")
        disc = _maxed_disc("d1")
        payload = _payload([ctx1, ctx2], [disc])
        results = run_rank_pipeline_with_progress(payload, lambda p: None)
        assert len(results) == 1
        assert len(results[0]["per_build"]) == 2

    def test_per_build_surfaces_keystone_deep_link_context(self):
        """B6 — per_build carries team/combo/enemy/active_index for the deep-link.

        These are pure request pass-through (no scorer math), so the frontend
        can call POST /teams/{team_id}/evaluate-discs without re-deriving
        context by positionally zipping results back to the request.
        """
        ctx = _ctx(
            build_id="b1",
            team_id="team-1",
            combo_id="combo-1",
            enemy_profile_id="enemy-1",
            active_index=1,
        )
        disc = _maxed_disc("d1")
        payload = _payload([ctx], [disc])
        results = run_rank_pipeline_with_progress(payload, lambda p: None)
        pb = results[0]["per_build"][0]
        assert pb["team_id"] == "team-1"
        assert pb["combo_id"] == "combo-1"
        assert pb["enemy_profile_id"] == "enemy-1"
        assert pb["active_index"] == 1


# ---------------------------------------------------------------------------
# R3.18 — support context dispatch
# ---------------------------------------------------------------------------


def _support_kit() -> SupportRecomputeKit:
    return SupportRecomputeKit(
        agent_base_hp=12000,
        core_hp_pct=0,
        we_initial_hp_pct=0,
        we_combat_hp_pct=0,
        we_secondary_hp_pct=0,
        disc_set_modifiers={},
        build_discs=[_plain_build_disc(slot=2, set_id=100)],
        agent_hakushin_id="97000",
        agent_name="TestSupport",
        agent_specialty="support",
        agent_element="electric",
    )


def _support_ctx(build_id: str = "b1") -> ResolvedRankContext:
    return ResolvedRankContext(
        build_id=build_id,
        build_name="PrimaryBuild",
        scoring_base=_snap(),
        enemy_snap=_enemy(),
        combo_steps=[],
        conditions=_conditions(),
        crit_mode=CritMode.EXPECTED,
        is_stunned=False,
        stun_dmg_mult=15000,
        weight=1.0,
        baseline_damage=0.0,
        disc_set_modifiers={},
        allowed_set_ids=None,
        build_discs=[_plain_build_disc()],
        support_recompute_kit=_support_kit(),
        primary_snap_without_support=_snap(),
    )


class TestSupportContextDispatch:
    """R3.18 — _score_pair dispatches to score_support_disc_potential for support contexts."""

    def test_support_context_produces_aggregates(self):
        """Pipeline with a support context runs and produces valid per-disc aggregates."""
        payload = _payload([_support_ctx()], [_maxed_disc("d1")])
        results = run_rank_pipeline_with_progress(payload, lambda p: None)
        assert len(results) == 1
        r = results[0]
        assert r["disc_id"] == "d1"
        assert r["best_build_avg"] == pytest.approx(0.0, abs=0.01)
        assert r["per_build"][0]["build_id"] == "b1"

    def test_mixed_dps_and_support_contexts(self):
        """A mixed payload (one DPS context + one support context) aggregates both."""
        dps_ctx = _ctx(build_id="dps")
        sup_ctx = _support_ctx(build_id="sup")
        disc = _maxed_disc("d1")
        payload = _payload([dps_ctx, sup_ctx], [disc])
        results = run_rank_pipeline_with_progress(payload, lambda p: None)
        assert len(results) == 1
        build_ids = {pb["build_id"] for pb in results[0]["per_build"]}
        assert build_ids == {"dps", "sup"}


# ---------------------------------------------------------------------------
# _apply_rank_filters — pure unit tests
# ---------------------------------------------------------------------------


class _FakeDiscSet:
    """Minimal stand-in for DiscSet (only hakushin_id needed)."""

    def __init__(self, hakushin_id: int) -> None:
        self.hakushin_id = hakushin_id


class _FakeDisc:
    """Minimal stand-in for a Disc ORM row."""

    def __init__(
        self,
        *,
        slot: int = 1,
        rarity: str = "S",
        level: int = 15,
        main_stat_type: str = "hp_pct",
        set_id: int = 100,
    ) -> None:
        self.slot = slot
        self.rarity = rarity
        self.level = level
        self.main_stat_type = main_stat_type
        self.disc_set = _FakeDiscSet(set_id)


def _discs(*specs: dict) -> list[_FakeDisc]:
    return [_FakeDisc(**s) for s in specs]


class TestApplyRankFilters:
    """Unit tests for _apply_rank_filters — no DB required."""

    def test_none_filters_returns_all(self):
        discs = _discs({}, {"slot": 2})
        assert _apply_rank_filters(discs, None) == discs

    def test_empty_filters_returns_all(self):
        discs = _discs({}, {"slot": 2})
        assert _apply_rank_filters(discs, RankFilters()) == discs

    # --- slot ---

    def test_slot_keeps_matching(self):
        d1 = _FakeDisc(slot=1)
        d2 = _FakeDisc(slot=2)
        result = _apply_rank_filters([d1, d2], RankFilters(slot=1))
        assert result == [d1]

    def test_slot_none_keeps_all(self):
        discs = _discs({"slot": 1}, {"slot": 3})
        assert _apply_rank_filters(discs, RankFilters(slot=None)) == discs

    # --- rarities ---

    def test_rarities_keeps_matching(self):
        d_s = _FakeDisc(rarity="S")
        d_a = _FakeDisc(rarity="A")
        result = _apply_rank_filters([d_s, d_a], RankFilters(rarities=["A"]))
        assert result == [d_a]

    def test_rarities_empty_keeps_all(self):
        discs = _discs({"rarity": "S"}, {"rarity": "A"})
        assert _apply_rank_filters(discs, RankFilters(rarities=[])) == discs

    def test_rarities_multi(self):
        discs = [_FakeDisc(rarity="S"), _FakeDisc(rarity="A"), _FakeDisc(rarity="B")]
        result = _apply_rank_filters(discs, RankFilters(rarities=["S", "A"]))
        assert len(result) == 2

    # --- main_stats ---

    def test_main_stats_keeps_matching(self):
        d1 = _FakeDisc(main_stat_type="atk_pct")
        d2 = _FakeDisc(main_stat_type="crit_rate")
        result = _apply_rank_filters([d1, d2], RankFilters(main_stats=["atk_pct"]))
        assert result == [d1]

    def test_main_stats_empty_keeps_all(self):
        discs = _discs({"main_stat_type": "atk_pct"}, {"main_stat_type": "hp_pct"})
        assert _apply_rank_filters(discs, RankFilters(main_stats=[])) == discs

    # --- set_ids ---

    def test_set_ids_keeps_matching(self):
        d1 = _FakeDisc(set_id=100)
        d2 = _FakeDisc(set_id=200)
        result = _apply_rank_filters([d1, d2], RankFilters(set_ids=[100]))
        assert result == [d1]

    def test_set_ids_empty_keeps_all(self):
        discs = _discs({"set_id": 100}, {"set_id": 200})
        assert _apply_rank_filters(discs, RankFilters(set_ids=[])) == discs

    def test_set_ids_multi(self):
        discs = [_FakeDisc(set_id=100), _FakeDisc(set_id=200), _FakeDisc(set_id=300)]
        result = _apply_rank_filters(discs, RankFilters(set_ids=[100, 300]))
        assert len(result) == 2

    # --- level_mode ---

    def test_level_min(self):
        discs = [_FakeDisc(level=10), _FakeDisc(level=13), _FakeDisc(level=15)]
        result = _apply_rank_filters(discs, RankFilters(level_value=13, level_mode="min"))
        levels = [d.level for d in result]
        assert levels == [13, 15]

    def test_level_max(self):
        discs = [_FakeDisc(level=10), _FakeDisc(level=13), _FakeDisc(level=15)]
        result = _apply_rank_filters(discs, RankFilters(level_value=13, level_mode="max"))
        levels = [d.level for d in result]
        assert levels == [10, 13]

    def test_level_exact(self):
        discs = [_FakeDisc(level=10), _FakeDisc(level=13), _FakeDisc(level=15)]
        result = _apply_rank_filters(discs, RankFilters(level_value=13, level_mode="exact"))
        assert len(result) == 1
        assert result[0].level == 13

    def test_level_value_none_keeps_all(self):
        discs = _discs({"level": 0}, {"level": 15})
        assert _apply_rank_filters(discs, RankFilters(level_value=None)) == discs

    # --- combined filters ---

    def test_combined_slot_and_rarity(self):
        """Filters are ANDed — only discs matching ALL criteria pass."""
        d_match = _FakeDisc(slot=1, rarity="S")
        d_wrong_slot = _FakeDisc(slot=2, rarity="S")
        d_wrong_rarity = _FakeDisc(slot=1, rarity="A")
        result = _apply_rank_filters(
            [d_match, d_wrong_slot, d_wrong_rarity],
            RankFilters(slot=1, rarities=["S"]),
        )
        assert result == [d_match]

    def test_combined_set_ids_and_level(self):
        d_match = _FakeDisc(set_id=100, level=15)
        d_wrong_set = _FakeDisc(set_id=200, level=15)
        d_wrong_level = _FakeDisc(set_id=100, level=5)
        result = _apply_rank_filters(
            [d_match, d_wrong_set, d_wrong_level],
            RankFilters(set_ids=[100], level_value=10, level_mode="min"),
        )
        assert result == [d_match]

    def test_rarity_enum_value_coerced(self):
        """Disc.rarity may be a Rarity enum — filter should coerce via str()."""
        from enum import Enum

        class Rarity(Enum):
            S = "S"
            A = "A"

        d_s = _FakeDisc(rarity="S")
        d_s.rarity = Rarity.S  # simulate ORM enum
        d_a = _FakeDisc(rarity="A")
        result = _apply_rank_filters([d_s, d_a], RankFilters(rarities=["S"]))
        assert result == [d_s]


# ---------------------------------------------------------------------------
# R2 — pin the disc-less baseline defects (docs/DESIGN_ranker_discless.md)
# ---------------------------------------------------------------------------


class TestDisclessBaselineDefects:
    """R2 — reproduces the two defects in DESIGN_ranker_discless.md's Problem
    section, against _aggregate directly, before any fix lands.

    disc_results is injected directly (bypassing score_disc_potential) to
    isolate the aggregation-layer defect from the physics engine: the values
    used are exactly what _score_pair produces today for a disc-less context,
    whose baseline_damage is agent + W-Engine only (no discs).

    Once R4/R5 land, per-context reference-mode switching makes every
    disc-less avg_pct a norm_pct, which is <= 0 by construction (D4) — so
    these thresholds become satisfiable. Today they are not: _aggregate does
    not look at ctx.build_discs at all, so a disc-less context's inflated pct
    passes straight through.
    """

    def test_discless_context_reports_absurd_avg_pct(self):
        """(a) A disc-less context's tiny baseline inflates avg_pct to an
        unreadable magnitude even though the disc's absolute improvement is
        modest. Fixed by R4's norm_pct switch, which is bounded <= 0 (D4)."""
        discless_ctx = _ctx(build_id="discless")
        discless_ctx.build_discs = []  # no equipped discs -> disc-less context
        payload = _payload([discless_ctx], [_maxed_disc("d1")])

        # What _score_pair computes today for a tiny agent-only baseline:
        # mean_improvement=4000 / baseline_damage=50 * 100 = 8000%.
        # abs_mean/abs_max = baseline_damage + improvement (R3's "The measure").
        disc_results = {"d1": {"discless": (8000.0, 9500.0, 4050.0, 4800.0)}}

        output = _aggregate(payload, disc_results)
        avg_pct = output[0]["per_build"][0]["avg_pct"]
        assert avg_pct <= 0.01, f"disc-less avg_pct should be norm_pct (<=0), got {avg_pct}"

    def test_discless_context_dominates_cross_context_aggregates(self):
        """(b) The worse defect: a disc-less context's inflated pct captures
        best_build_avg / best_build_avg_build_id and skews portfolio_avg away
        from the geared context that actually matters for a "should I swap?"
        decision. Fixed by D3 (baseline-free aggregates from norm_pct, always
        <= 0) + D4 (saturation at 0.0)."""
        geared_ctx = _ctx(build_id="geared", weight=1.0)
        discless_ctx = _ctx(build_id="discless", weight=1.0)
        discless_ctx.build_discs = []
        disc = _maxed_disc("d1")
        payload = _payload([geared_ctx, discless_ctx], [disc])

        # geared: a modest, realistic 5% swap upgrade against a large baseline.
        # discless: same disc, same absolute improvement, but the tiny
        # agent-only baseline inflates the pct to 8000%.
        disc_results = {
            "d1": {
                "geared": (5.0, 8.0, 105000.0, 108000.0),
                "discless": (8000.0, 9500.0, 4050.0, 4800.0),
            }
        }
        output = _aggregate(payload, disc_results)
        result = output[0]

        # Post-fix invariant: every norm_pct-derived aggregate is <= 0 (D4).
        assert result["best_build_avg"] <= 0.01, (
            f"best_build_avg should saturate at <=0 (D4), got {result['best_build_avg']}"
        )
        assert result["portfolio_avg"] <= 0.01, (
            f"portfolio_avg should be a baseline-free mean (D3), got {result['portfolio_avg']}"
        )


# ---------------------------------------------------------------------------
# Task 4 — global set_ids AND per-context allowed_set_ids composition
# ---------------------------------------------------------------------------


class TestSetIdFilterComposition:
    """Guard: global RankFilters.set_ids (inventory-level) and per-context
    allowed_set_ids (scoring-level) are AND-composed and operate independently.

    These two filters act at different layers:
      - _apply_rank_filters removes discs from the inventory before the pipeline runs.
      - allowed_set_ids is checked per-disc inside run_rank_pipeline_with_progress.
    A disc excluded by either layer must be absent from final results.
    """

    def test_per_context_allowed_set_ids_excludes_disc_that_passed_global_filter(self):
        """A disc that survives global set_ids filter is still excluded by per-context
        allowed_set_ids — the two filters are genuinely independent."""
        # Simulate post-global-filter inventory: sets [100, 200] both survived.
        disc_a = _maxed_disc("da", set_id=100)  # in allowed_set_ids
        disc_b = _maxed_disc("db", set_id=200)  # NOT in allowed_set_ids

        ctx = _ctx(allowed_set_ids=[100])
        payload = _payload([ctx], [disc_a, disc_b])
        results = run_rank_pipeline_with_progress(payload, lambda p: None)
        ids = {r["disc_id"] for r in results}

        assert "da" in ids  # passes per-context filter
        assert "db" not in ids  # excluded by per-context allowed_set_ids

    def test_global_set_ids_removes_disc_before_per_context_filter_sees_it(self):
        """_apply_rank_filters (global) removes a disc from the inventory entirely;
        it never reaches the per-context filter and is absent from results."""
        # Three fake ORM discs: set 100 and 200 survive, set 300 is excluded.
        d_100 = _FakeDisc(set_id=100)
        d_200 = _FakeDisc(set_id=200)
        d_300 = _FakeDisc(set_id=300)

        post_global = _apply_rank_filters([d_100, d_200, d_300], RankFilters(set_ids=[100, 200]))
        assert len(post_global) == 2
        surviving_set_ids = {d.disc_set.hakushin_id for d in post_global}
        assert surviving_set_ids == {100, 200}
        assert all(d.disc_set.hakushin_id != 300 for d in post_global)

    def test_neither_excluded_disc_appears_when_both_filters_active(self):
        """End-to-end composition: with global set_ids=[100, 200] and per-context
        allowed_set_ids=[100]:
          - set 100: passes both → present in results
          - set 200: passes global, fails per-context → absent from results
          - set 300: excluded by global before pipeline → absent from results
        """
        disc_a = _maxed_disc("da", set_id=100)  # passes both
        disc_b = _maxed_disc("db", set_id=200)  # passes global, excluded by per-context
        # disc_c (set 300) excluded by global filter; simulate by omitting from inventory

        ctx = _ctx(allowed_set_ids=[100])
        # Inventory reflects global filter result: da and db survived; dc did not.
        payload = _payload([ctx], [disc_a, disc_b])
        results = run_rank_pipeline_with_progress(payload, lambda p: None)
        ids = {r["disc_id"] for r in results}

        assert "da" in ids  # passes both filters
        assert "db" not in ids  # excluded by per-context allowed_set_ids=[100]
        # "dc" is not in payload.inventory (global filter excluded it); trivially absent
