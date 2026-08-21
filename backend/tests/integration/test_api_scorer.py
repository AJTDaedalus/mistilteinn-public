"""Integration tests for the disc potential scorer endpoints (Phase 7b).

Exercises ``POST /api/v1/scorer/disc`` and ``POST /api/v1/scorer/inventory``
end-to-end against a real PostgreSQL database. Confirms the
baseline-equals-current-build semantics, the inventory default scope, and
the eager-loading wiring (Build.discs.disc_set) needed by the snapshot
builder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.models.w_engine import WEngine
from app.services.modifiers import (
    AttackScope,
    Condition,
    Modifier,
    ModifierSource,
    ModifierTarget,
)
from app.services.snapshot_builder import buff_id

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_scorer_scenario(
    authed_client: AsyncClient,
    db: AsyncSession,
) -> dict:
    """Build a complete scoring scenario.

    Seeds an agent + w-engine + 2 disc sets, attaches 6 A-rank discs to a
    build (4 of set A, 2 of set B), plus a couple of unequipped slot-4 / 5
    candidates and a single-step combo against a fire-vulnerable dummy.
    A-rank keeps the multinomial PMF tractable (target 3 substats, 5 max
    rolls → 2 remaining after the seeded 3 baseline rolls).
    """
    agent = Agent(
        hakushin_id=8000,
        name="ScoreAgent",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    engine = WEngine(
        hakushin_id=8001,
        name="ScoreEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=46,
    )
    enemy = EnemyProfile(name="ScoreDummy", level=60, defense=60, fire_res=0)
    set_a = DiscSet(
        hakushin_id=8100,
        name="SetA",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +25%",
    )
    set_b = DiscSet(
        hakushin_id=8200,
        name="SetB",
        two_piece_text="DEF +16%",
        four_piece_text="ATK +25%",
    )
    agent2 = Agent(
        hakushin_id=8005,
        name="ScoreAgent2",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    db.add_all([agent, agent2, engine, enemy, set_a, set_b])
    await db.flush()

    ba1 = Attack(
        agent_id=agent.id,
        hakushin_skill_id=1,
        skill_key="Basic",
        name="Basic 1",
        hit_index=0,
        element=Element.FIRE,
        damage_base=10000,
        damage_growth=500,
    )
    db.add(ba1)
    await db.flush()

    build_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "ScoreBuild",
            "agent_id": agent.id,
            "w_engine_id": engine.id,
        },
    )
    build_id = build_resp.json()["id"]

    # 4 pieces of set A (slots 1-4), 2 of set B (slots 5-6).
    equipped_specs = [
        (1, set_a.id, StatType.HP, 2200),
        (2, set_a.id, StatType.ATK, 316),
        (3, set_a.id, StatType.DEF, 200),
        (4, set_a.id, StatType.CRIT_RATE, 2400),
        (5, set_b.id, StatType.ATK_PCT, 3000),
        (6, set_b.id, StatType.ATK_PCT, 3000),
    ]
    # 3 substats x 1 roll baseline so A-rank scorer has 2 rolls to project.
    # Substats avoid the main stat so all are legal. Values are real A-rank
    # per-roll bases (issue #65 — A-rank rolls are smaller than S-rank's;
    # using S-rank-sized values here previously masked the roll-counter
    # rarity bug rather than exercising it).
    baseline_substats = [
        {"stat": "atk_pct", "value": 200, "rolls": 1},
        {"stat": "crit_dmg", "value": 320, "rolls": 1},
        {"stat": "pen_flat", "value": 6, "rolls": 1},
    ]
    slot4_substats = [
        {"stat": "atk_pct", "value": 200, "rolls": 1},
        {"stat": "crit_dmg", "value": 320, "rolls": 1},
        {"stat": "anomaly_proficiency", "value": 6, "rolls": 1},
    ]
    equipped: list[Disc] = []
    for slot, set_id, main_type, main_val in equipped_specs:
        subs = slot4_substats if slot == 4 else baseline_substats
        d = Disc(
            disc_set_id=set_id,
            slot=DiscSlot(slot),
            rarity=Rarity.A,
            level=0,
            main_stat_type=main_type,
            main_stat_value=main_val,
            substats=subs,
            build_id=build_id,
            build_slot=slot,
        )
        equipped.append(d)
    db.add_all(equipped)
    await db.flush()

    # Unequipped candidates that could replace slots 4/5.
    cand_4 = Disc(
        disc_set_id=set_a.id,
        slot=DiscSlot.FOUR,
        rarity=Rarity.A,
        level=0,
        main_stat_type=StatType.CRIT_DMG,
        main_stat_value=4800,
        substats=[
            {"stat": "atk_pct", "value": 200, "rolls": 1},
            {"stat": "crit_rate", "value": 160, "rolls": 1},
            {"stat": "pen_flat", "value": 6, "rolls": 1},
        ],
    )
    cand_5 = Disc(
        disc_set_id=set_b.id,
        slot=DiscSlot.FIVE,
        rarity=Rarity.A,
        level=0,
        main_stat_type=StatType.FIRE_DMG,
        main_stat_value=3000,
        substats=baseline_substats,
    )
    db.add_all([cand_4, cand_5])
    await db.flush()

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "ScoreTeam", "build1_id": build_id},
    )
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "BA1",
            "team_id": team_id,
            "sequence": [{"attack_id": ba1.id, "label": "BA1"}],
        },
    )

    return {
        "agent_id": agent.id,
        "agent2_id": str(agent2.id),
        "build_id": build_id,
        "team_id": team_id,
        "combo_id": combo_resp.json()["id"],
        "enemy_id": enemy.id,
        "equipped_slot4_id": str(equipped[3].id),
        "equipped_ids": [str(d.id) for d in equipped],
        "cand_4_id": str(cand_4.id),
        "cand_5_id": str(cand_5.id),
    }


class TestScoreDiscEndpoint:
    async def test_score_equipped_disc_returns_full_response(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_id": ctx["equipped_slot4_id"],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["combo_id"] == ctx["combo_id"]
        assert data["combo_name"] == "BA1"
        assert data["agent_name"] == "ScoreAgent"
        assert data["enemy_name"] == "ScoreDummy"

        score = data["score"]
        assert score["disc_id"] == ctx["equipped_slot4_id"]
        # A-rank, 3 substats x 1 roll = 3 placed, 2 remaining of max 5.
        assert score["rolls_used"] == 3
        assert score["remaining_rolls"] == 2
        # Damage values are positive floats.
        assert score["current_damage"] > 0
        assert score["baseline_damage"] > 0
        # When we score the *currently equipped* slot-4 disc, the build is
        # unchanged from baseline → current_damage matches baseline.
        assert score["current_damage"] == score["baseline_damage"]
        # No rolls used yet → upgrades are pure improvements over baseline.
        assert score["mean_improvement"] >= 0
        assert score["max_improvement"] >= score["mean_improvement"]
        # Distribution is suppressed by default.
        assert score["distribution"] is None

    async def test_score_unequipped_disc_baseline_matches_current_build(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Baseline is always the current build; current_damage swaps the disc.

        For an unequipped candidate, current_damage (post-swap, pre-leveling)
        diverges from baseline because the equipped slot-4 disc has been
        replaced. Baseline must match the saved-build damage exactly.
        """
        ctx = await _seed_scorer_scenario(authed_client, db_session)

        # Score the equipped slot-4 disc to capture baseline.
        equipped_resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_id": ctx["equipped_slot4_id"],
            },
        )
        equipped_baseline = equipped_resp.json()["score"]["baseline_damage"]

        # Now score an unequipped candidate — the baseline is still the
        # current build's damage, not the candidate's swapped state.
        cand_resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_id": ctx["cand_4_id"],
            },
        )
        cand_score = cand_resp.json()["score"]
        assert cand_score["baseline_damage"] == equipped_baseline
        # Different disc → different current_damage post-swap.
        assert cand_score["current_damage"] != cand_score["baseline_damage"]

    async def test_include_distribution_returns_pmf(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_id": ctx["equipped_slot4_id"],
                "include_distribution": True,
            },
        )
        assert resp.status_code == 200, resp.text
        dist = resp.json()["score"]["distribution"]
        assert dist is not None
        assert len(dist) > 0
        # Probabilities sum to ~1.
        total_prob = sum(p for _, p in dist)
        assert abs(total_prob - 1.0) < 1e-6

    async def test_combo_not_found_returns_404(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": "missing-combo",
                "enemy_profile_id": "anything",
                "disc_id": "anything",
            },
        )
        assert resp.status_code == 404
        assert "Combo" in resp.json()["detail"]

    async def test_enemy_not_found_returns_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": "missing-enemy",
                "disc_id": ctx["equipped_slot4_id"],
            },
        )
        assert resp.status_code == 404
        assert "Enemy" in resp.json()["detail"]

    async def test_disc_not_found_returns_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_id": "missing-disc",
            },
        )
        assert resp.status_code == 404
        assert "Disc" in resp.json()["detail"]

    async def test_invalid_crit_mode_returns_422(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_id": ctx["equipped_slot4_id"],
                "crit_mode": "garbage",
            },
        )
        assert resp.status_code == 422


class TestScoreInventoryEndpoint:
    async def test_explicit_disc_ids_returns_sorted_scores(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        target_ids = [
            ctx["equipped_slot4_id"],
            ctx["cand_4_id"],
            ctx["cand_5_id"],
        ]
        resp = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_ids": target_ids,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["combo_name"] == "BA1"
        assert data["agent_name"] == "ScoreAgent"
        assert len(data["scores"]) == 3
        # Sorted by mean_improvement desc.
        means = [s["mean_improvement"] for s in data["scores"]]
        assert means == sorted(means, reverse=True)
        # All scores share the same baseline (current build damage).
        baselines = {s["baseline_damage"] for s in data["scores"]}
        assert len(baselines) == 1
        assert next(iter(baselines)) > 0
        # Returned IDs cover all requested.
        assert {s["disc_id"] for s in data["scores"]} == set(target_ids)

    async def test_default_scope_includes_equipped_and_unequipped(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """disc_ids=None scopes to the build's equipped discs + every
        unequipped disc. Discs equipped to *other* builds must be excluded.
        """
        ctx = await _seed_scorer_scenario(authed_client, db_session)

        # Stash a disc on a different build → must be excluded from scope.
        other_build_resp = await authed_client.post(
            "/api/v1/builds",
            json={
                "name": "OtherBuild",
                "agent_id": ctx["agent2_id"],
            },
        )
        other_build_id = other_build_resp.json()["id"]
        set_a_row = (
            await db_session.execute(
                DiscSet.__table__.select().where(
                    DiscSet.hakushin_id == 8100,
                ),
            )
        ).first()
        other_disc = Disc(
            disc_set_id=set_a_row.id,
            slot=DiscSlot.FOUR,
            rarity=Rarity.A,
            level=0,
            main_stat_type=StatType.CRIT_RATE,
            main_stat_value=2400,
            substats=[
                {"stat": "atk_pct", "value": 300, "rolls": 1},
                {"stat": "crit_dmg", "value": 480, "rolls": 1},
                {"stat": "pen_flat", "value": 9, "rolls": 1},
            ],
            build_id=other_build_id,
            build_slot=4,
        )
        db_session.add(other_disc)
        await db_session.flush()

        resp = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
            },
        )
        assert resp.status_code == 200, resp.text
        scored_ids = {s["disc_id"] for s in resp.json()["scores"]}

        # All 6 equipped + 2 unequipped candidates included.
        for disc_id in ctx["equipped_ids"]:
            assert disc_id in scored_ids
        assert ctx["cand_4_id"] in scored_ids
        assert ctx["cand_5_id"] in scored_ids
        # Disc equipped to a different build is excluded.
        assert str(other_disc.id) not in scored_ids

    async def test_scope_all_includes_discs_on_other_builds(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """scope='all' must include discs equipped to other builds."""
        ctx = await _seed_scorer_scenario(authed_client, db_session)

        other_build_resp = await authed_client.post(
            "/api/v1/builds",
            json={
                "name": "OtherBuildAll",
                "agent_id": ctx["agent2_id"],
            },
        )
        other_build_id = other_build_resp.json()["id"]
        set_a_row = (
            await db_session.execute(
                DiscSet.__table__.select().where(DiscSet.hakushin_id == 8100),
            )
        ).first()
        other_disc = Disc(
            disc_set_id=set_a_row.id,
            slot=DiscSlot.FOUR,
            rarity=Rarity.A,
            level=0,
            main_stat_type=StatType.CRIT_RATE,
            main_stat_value=2400,
            substats=[
                {"stat": "atk_pct", "value": 300, "rolls": 1},
                {"stat": "crit_dmg", "value": 480, "rolls": 1},
                {"stat": "pen_flat", "value": 9, "rolls": 1},
            ],
            build_id=other_build_id,
            build_slot=4,
        )
        db_session.add(other_disc)
        await db_session.flush()

        resp = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "scope": "all",
            },
        )
        assert resp.status_code == 200, resp.text
        scored_ids = {s["disc_id"] for s in resp.json()["scores"]}
        assert str(other_disc.id) in scored_ids

    async def test_default_scope_unchanged_when_scope_omitted(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Default behavior unchanged — disc_ids=None, scope not passed."""
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
            },
        )
        assert resp.status_code == 200, resp.text
        # Should include build's own discs.
        scored_ids = {s["disc_id"] for s in resp.json()["scores"]}
        for disc_id in ctx["equipped_ids"]:
            assert disc_id in scored_ids

    async def test_combo_not_found_returns_404(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": "missing-combo",
                "enemy_profile_id": "anything",
            },
        )
        assert resp.status_code == 404

    async def test_allowed_set_ids_filters_to_matching_set(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """allowed_set_ids=[X] returns only discs whose DiscSet.hakushin_id == X."""
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        # set_a hakushin_id=8100: 4 equipped (slots 1-4) + cand_4 = 5 discs.
        # set_b hakushin_id=8200: 2 equipped (slots 5-6) + cand_5 = 3 discs.
        resp = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "allowed_set_ids": [8100],
            },
        )
        assert resp.status_code == 200, resp.text
        scores = resp.json()["scores"]
        assert len(scores) == 5
        # cand_5 (set_b) must not appear.
        scored_ids = {s["disc_id"] for s in scores}
        assert ctx["cand_5_id"] not in scored_ids
        assert ctx["cand_4_id"] in scored_ids

    async def test_allowed_set_ids_none_does_not_filter(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """allowed_set_ids=None is the same as omitting it — no filtering."""
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        resp_default = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
            },
        )
        resp_explicit_none = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "allowed_set_ids": None,
            },
        )
        assert resp_default.status_code == 200
        assert resp_explicit_none.status_code == 200
        ids_default = {s["disc_id"] for s in resp_default.json()["scores"]}
        ids_none = {s["disc_id"] for s in resp_explicit_none.json()["scores"]}
        assert ids_default == ids_none

    async def test_allowed_set_ids_composes_with_scope_all(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """scope='all' + allowed_set_ids=[Y] returns only set-Y discs DB-wide."""
        ctx = await _seed_scorer_scenario(authed_client, db_session)

        other_build_resp = await authed_client.post(
            "/api/v1/builds",
            json={
                "name": "OtherBuildFilter",
                "agent_id": ctx["agent2_id"],
            },
        )
        other_build_id = other_build_resp.json()["id"]
        set_a_row = (
            await db_session.execute(
                DiscSet.__table__.select().where(DiscSet.hakushin_id == 8100),
            )
        ).first()
        other_disc = Disc(
            disc_set_id=set_a_row.id,
            slot=DiscSlot.FOUR,
            rarity=Rarity.A,
            level=0,
            main_stat_type=StatType.CRIT_RATE,
            main_stat_value=2400,
            substats=[
                {"stat": "atk_pct", "value": 300, "rolls": 1},
                {"stat": "crit_dmg", "value": 480, "rolls": 1},
                {"stat": "pen_flat", "value": 9, "rolls": 1},
            ],
            build_id=other_build_id,
            build_slot=4,
        )
        db_session.add(other_disc)
        await db_session.flush()

        # scope=all + filter to set_b (8200) → only set_b discs (2 equipped + cand_5).
        resp = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "scope": "all",
                "allowed_set_ids": [8200],
            },
        )
        assert resp.status_code == 200, resp.text
        scores = resp.json()["scores"]
        scored_ids = {s["disc_id"] for s in scores}
        # set_b: 2 equipped slots 5-6 + cand_5.
        assert len(scores) == 3
        assert ctx["cand_5_id"] in scored_ids
        # other_disc is set_a → must be excluded.
        assert str(other_disc.id) not in scored_ids

    async def test_allowed_set_ids_composes_with_explicit_disc_ids(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """explicit disc_ids + allowed_set_ids intersect: only matching-set discs scored."""
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        # Pass one set_a disc (cand_4) and one set_b disc (cand_5); filter to set_a only.
        resp = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_ids": [ctx["cand_4_id"], ctx["cand_5_id"]],
                "allowed_set_ids": [8100],
            },
        )
        assert resp.status_code == 200, resp.text
        scores = resp.json()["scores"]
        assert len(scores) == 1
        assert scores[0]["disc_id"] == ctx["cand_4_id"]

    async def test_stateful_scorer_endpoints_execute_simulations(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Stateful=True scorer endpoints execute simulations (disc + inventory)."""
        ctx = await _seed_scorer_scenario(authed_client, db_session)

        # Test single disc endpoint
        resp = await authed_client.post(
            "/api/v1/scorer/disc",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_id": ctx["cand_4_id"],
                "stateful": True,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "score" in data
        assert data["score"]["current_damage"] >= 0.0

        # Test inventory endpoint
        resp2 = await authed_client.post(
            "/api/v1/scorer/inventory",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
                "disc_ids": [ctx["cand_4_id"], ctx["cand_5_id"]],
                "stateful": True,
            },
        )
        assert resp2.status_code == 200, resp2.text
        data2 = resp2.json()
        assert "scores" in data2
        assert len(data2["scores"]) == 2


_SCORER_DISABLE_ME = Modifier(
    stat="atk_pct",
    value=3000,
    source=ModifierSource.EXTERNAL,
    source_label="test:scorer_disable_me",
    target=ModifierTarget.SELF,
    conditions=(Condition.ALWAYS,),
    scopes=(AttackScope.ALL,),
    max_stacks=1,
)
_SCORER_MODULE_TARGET = "app.services.snapshot_builder.load_agent_modifiers"


class TestScorerDisabledBuffsFromRequest:
    """``disabled_buffs`` on the request must reach the scorer's calc.

    DESIGN_buff_context.md §2.1. ``_ScorerContextBase`` carries the field for
    all three of its subclasses, but ``/scorer/disc`` and ``/scorer/inventory``
    accepted it and dropped it on the floor — they read
    ``build.disabled_buffs`` instead, which is the exact dual-source ambiguity
    #59 exists to remove. The four-endpoint matrix lives in
    ``test_buff_context_parity.py``; these two cases guard the two entry
    points that matrix does not cover.
    """

    async def _baseline(
        self,
        authed_client: AsyncClient,
        ctx: dict,
        route: str,
        disabled_buffs: list[str],
    ) -> float:
        body = {
            "combo_id": ctx["combo_id"],
            "enemy_profile_id": ctx["enemy_id"],
            "disabled_buffs": disabled_buffs,
        }
        if route.endswith("/disc"):
            body["disc_id"] = ctx["equipped_slot4_id"]
            resp = await authed_client.post(route, json=body)
            assert resp.status_code == 200, resp.text
            return resp.json()["score"]["baseline_damage"]
        body["disc_ids"] = [ctx["cand_4_id"]]
        resp = await authed_client.post(route, json=body)
        assert resp.status_code == 200, resp.text
        return resp.json()["scores"][0]["baseline_damage"]

    @pytest.mark.parametrize("route", ["/api/v1/scorer/disc", "/api/v1/scorer/inventory"])
    async def test_request_disabled_buffs_changes_baseline(
        self,
        route: str,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        disabled_id = buff_id(8000, "test:scorer_disable_me")

        with patch(_SCORER_MODULE_TARGET, return_value=[_SCORER_DISABLE_ME]):
            enabled = await self._baseline(authed_client, ctx, route, [])
            disabled = await self._baseline(authed_client, ctx, route, [disabled_id])

        assert disabled < enabled, (
            f"{route}: a request-level disabled_buffs did not exclude "
            f"'test:scorer_disable_me' from the calc (baseline {disabled} "
            f"vs {enabled} with it enabled)."
        )

    @pytest.mark.parametrize("route", ["/api/v1/scorer/disc", "/api/v1/scorer/inventory"])
    async def test_build_column_does_not_affect_scorer_calculation(
        self,
        route: str,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """The build's own ``disabled_buffs`` column is not a server fallback."""
        ctx = await _seed_scorer_scenario(authed_client, db_session)
        disabled_id = buff_id(8000, "test:scorer_disable_me")

        with patch(_SCORER_MODULE_TARGET, return_value=[_SCORER_DISABLE_ME]):
            before = await self._baseline(authed_client, ctx, route, [])

            patch_resp = await authed_client.patch(
                f"/api/v1/builds/{ctx['build_id']}",
                json={"disabled_buffs": [disabled_id]},
            )
            assert patch_resp.status_code == 200, patch_resp.text

            after = await self._baseline(authed_client, ctx, route, [])

        assert after == before, (
            f"{route}: mutating build.disabled_buffs changed the result "
            f"({before} -> {after}) for a fixed request context. DESIGN §2.1 "
            f"— the column is a client-read default, never a server fallback."
        )
