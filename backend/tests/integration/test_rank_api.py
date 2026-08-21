"""Integration tests for POST /scorer/rank (R2.7, R3.19).

Tests are split into classes:
  - TestSubmitRankJobEndpoint: HTTP-level tests with a mock runner (202, 404s).
  - TestRankPipelineResults: Direct resolve + pipeline calls against the real DB.
  - TestSupportContextPipeline: R3.19 — support-context scoring end-to-end.
  - TestSupportContextResolution: R3.17 — support_slot resolution/404.
  - TestJobDetailResultType: R3.2 — result field loosening.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.disc import Disc, DiscSet
from app.models.enums import DiscSlot, Element, Rarity, Specialty, StatType
from app.models.w_engine import WEngine
from app.repositories.attack import AttackRepository
from app.repositories.build import BuildRepository, ComboRepository, EnemyProfileRepository
from app.repositories.optimization_job import OptimizationJobRepository
from app.schemas.scorer import RankContextSchema, RankRequest
from app.services.modifiers import AttackScope, Condition, Modifier, ModifierSource, ModifierTarget
from app.services.rank_pipeline import resolve_rank_payload, run_rank_pipeline_with_progress

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

_MAXED_SUBSTATS = [
    {"stat": "hp_pct", "value": 900, "rolls": 3},
    {"stat": "crit_rate", "value": 720, "rolls": 3},
    {"stat": "crit_dmg", "value": 1440, "rolls": 3},
]


async def _seed_rank_scenario(
    authed_client: AsyncClient,
    db: AsyncSession,
) -> dict:
    """Seed two builds (same agent) + one enemy + two disc sets.

    Build1: 6 S-rank maxed (lv15) discs — slot1-4 from SetA, slot5-6 from SetB.
    Build2: 6 S-rank lv0 discs — all from SetC.
    Unequipped pool: one SetA disc (cand_a) and one SetC disc (cand_c).
    Both builds have a single-attack combo.
    """
    agent = Agent(
        hakushin_id=97000,
        name="RankAgent",
        element=Element.ELECTRIC,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    agent2 = Agent(
        hakushin_id=97005,
        name="RankAgent2",
        element=Element.ELECTRIC,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    engine = WEngine(
        hakushin_id=97001,
        name="RankEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=600,
    )
    enemy = EnemyProfile(name="RankDummy", level=60, defense=60, electric_res=0)
    set_a = DiscSet(
        hakushin_id=97100,
        name="RankSetA",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +10%",
    )
    set_b = DiscSet(
        hakushin_id=97200,
        name="RankSetB",
        two_piece_text="DEF +16%",
        four_piece_text="ATK +10%",
    )
    set_c = DiscSet(
        hakushin_id=97300,
        name="RankSetC",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +10%",
    )
    db.add_all([agent, agent2, engine, enemy, set_a, set_b, set_c])
    await db.flush()

    attack = Attack(
        agent_id=agent.id,
        hakushin_skill_id=9700,
        skill_key="Basic",
        name="RankHit",
        hit_index=0,
        element=Element.ELECTRIC,
        damage_base=10000,
        damage_growth=0,
    )
    attack2 = Attack(
        agent_id=agent2.id,
        hakushin_skill_id=9701,
        skill_key="Basic",
        name="RankHit2",
        hit_index=0,
        element=Element.ELECTRIC,
        damage_base=10000,
        damage_growth=0,
    )
    db.add_all([attack, attack2])
    await db.flush()

    # Build1 — equipped with 6 maxed S-rank discs (remaining_rolls=0).
    b1_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "RankBuild1",
            "agent_id": str(agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    build1_id = b1_resp.json()["id"]

    # Build2 — equipped with 6 S-rank lv0 discs (remaining_rolls=9 each).
    b2_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "RankBuild2",
            "agent_id": str(agent2.id),
            "w_engine_id": str(engine.id),
        },
    )
    build2_id = b2_resp.json()["id"]

    # Equip Build1 — maxed discs (level=15, substats with 9 total rolls).
    for slot in DiscSlot:
        s = int(slot.value)
        set_id = set_a.id if s <= 4 else set_b.id
        d = Disc(
            disc_set_id=set_id,
            slot=slot,
            rarity=Rarity.S,
            level=15,
            main_stat_type=StatType.ATK_PCT,
            main_stat_value=3000,
            substats=_MAXED_SUBSTATS,
            build_id=build1_id,
            build_slot=s,
        )
        db.add(d)

    # Equip Build2 — fresh discs (level=0, 3 substats x 1 roll = 3 rolls, 6 remaining).
    b2_substats = [
        {"stat": "hp_pct", "value": 300, "rolls": 1},
        {"stat": "crit_rate", "value": 240, "rolls": 1},
        {"stat": "crit_dmg", "value": 480, "rolls": 1},
    ]
    for slot in DiscSlot:
        s = int(slot.value)
        d = Disc(
            disc_set_id=set_c.id,
            slot=slot,
            rarity=Rarity.S,
            level=0,
            main_stat_type=StatType.ATK_PCT,
            main_stat_value=3000,
            substats=b2_substats,
            build_id=build2_id,
            build_slot=s,
        )
        db.add(d)
    await db.flush()

    # Unequipped candidates — main_stat=ATK_PCT so substats (hp_pct/cr/cd) don't clash.
    cand_substats = [
        {"stat": "hp_pct", "value": 300, "rolls": 1},
        {"stat": "crit_rate", "value": 240, "rolls": 1},
        {"stat": "crit_dmg", "value": 480, "rolls": 1},
    ]
    cand_a = Disc(
        disc_set_id=set_a.id,
        slot=DiscSlot.FOUR,
        rarity=Rarity.S,
        level=0,
        main_stat_type=StatType.ATK_PCT,
        main_stat_value=3000,
        substats=cand_substats,
    )
    cand_c = Disc(
        disc_set_id=set_c.id,
        slot=DiscSlot.FOUR,
        rarity=Rarity.S,
        level=0,
        main_stat_type=StatType.ATK_PCT,
        main_stat_value=3000,
        substats=cand_substats,
    )
    db.add_all([cand_a, cand_c])
    await db.flush()

    t1_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "RankTeam1", "build1_id": build1_id},
    )
    team1_id = t1_resp.json()["id"]
    t2_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "RankTeam2", "build1_id": build2_id},
    )
    team2_id = t2_resp.json()["id"]

    c1_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "RankCombo1",
            "team_id": team1_id,
            "sequence": [{"attack_id": str(attack.id), "label": "Hit1"}],
        },
    )
    c2_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "RankCombo2",
            "team_id": team2_id,
            "sequence": [{"attack_id": str(attack2.id), "label": "Hit2"}],
        },
    )

    return {
        "agent_id": str(agent.id),
        "agent2_id": str(agent2.id),
        "build1_id": build1_id,
        "build2_id": build2_id,
        "combo1_id": c1_resp.json()["id"],
        "combo2_id": c2_resp.json()["id"],
        "enemy_id": str(enemy.id),
        "set_a_id": set_a.hakushin_id,
        "set_b_id": set_b.hakushin_id,
        "set_c_id": set_c.hakushin_id,
        "cand_a_id": str(cand_a.id),
        "cand_c_id": str(cand_c.id),
    }


def _ctx_dict(s: dict, build_key: str, combo_key: str, **kwargs) -> dict:
    d = {
        "build_id": s[build_key],
        "combo_id": s[combo_key],
        "enemy_profile_id": s["enemy_id"],
        "weight": 1.0,
    }
    d.update(kwargs)
    return d


# ---------------------------------------------------------------------------
# HTTP-level tests (mock runner)
# ---------------------------------------------------------------------------


class TestSubmitRankJobEndpoint:
    async def test_single_context_returns_202_queued(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        s = await _seed_rank_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/rank",
            json={
                "contexts": [_ctx_dict(s, "build1_id", "combo1_id")],
            },
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["status"] == "queued"
        assert "id" in data

    async def test_two_context_returns_202_queued(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        s = await _seed_rank_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/rank",
            json={
                "contexts": [
                    _ctx_dict(s, "build1_id", "combo1_id"),
                    _ctx_dict(s, "build2_id", "combo2_id"),
                ],
            },
        )
        assert resp.status_code == 202, resp.text
        assert resp.json()["status"] == "queued"

    async def test_runner_submit_rank_job_called(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        s = await _seed_rank_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/rank",
            json={
                "contexts": [_ctx_dict(s, "build1_id", "combo1_id")],
            },
        )
        assert resp.status_code == 202
        job_id = resp.json()["id"]
        runner = authed_client._transport.app.state.job_runner  # type: ignore[attr-defined]
        runner.submit_rank_job.assert_called_once()
        call_job_id = runner.submit_rank_job.call_args[0][0]
        assert call_job_id == job_id

    async def test_combo_not_found_returns_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        s = await _seed_rank_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/rank",
            json={
                "contexts": [
                    {
                        "build_id": s["build1_id"],
                        "combo_id": "00000000-0000-0000-0000-000000000000",
                        "enemy_profile_id": s["enemy_id"],
                    }
                ],
            },
        )
        assert resp.status_code == 404
        assert "Combo" in resp.json()["detail"]

    async def test_build_not_found_returns_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        s = await _seed_rank_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/rank",
            json={
                "contexts": [
                    {
                        "build_id": "00000000-0000-0000-0000-000000000000",
                        "combo_id": s["combo1_id"],
                        "enemy_profile_id": s["enemy_id"],
                    }
                ],
            },
        )
        assert resp.status_code == 404
        assert "Build" in resp.json()["detail"]

    async def test_enemy_not_found_returns_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        s = await _seed_rank_scenario(authed_client, db_session)
        resp = await authed_client.post(
            "/api/v1/scorer/rank",
            json={
                "contexts": [
                    {
                        "build_id": s["build1_id"],
                        "combo_id": s["combo1_id"],
                        "enemy_profile_id": "00000000-0000-0000-0000-000000000000",
                    }
                ],
            },
        )
        assert resp.status_code == 404
        assert "Enemy" in resp.json()["detail"]

    async def test_empty_contexts_rejected(self, authed_client: AsyncClient):
        resp = await authed_client.post("/api/v1/scorer/rank", json={"contexts": []})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Pipeline result tests (resolve → run directly against real DB)
# ---------------------------------------------------------------------------


class TestRankPipelineResults:
    """Calls resolve_rank_payload + run_rank_pipeline_with_progress directly.

    This sidesteps the committed-session complexity of a running JobRunner
    while still exercising the full DB resolve + computation path.
    """

    async def _resolve(
        self,
        db: AsyncSession,
        body: RankRequest,
    ) -> object:
        return await resolve_rank_payload(
            db,
            body,
            build_repo=BuildRepository(db),
            combo_repo=ComboRepository(db),
            attack_repo=AttackRepository(db),
            enemy_repo=EnemyProfileRepository(db),
        )

    async def test_maxed_equipped_disc_scores_near_zero(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A disc with 0 remaining rolls produces ~0% avg and max potential."""
        s = await _seed_rank_scenario(authed_client, db_session)
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["build1_id"],
                    combo_id=s["combo1_id"],
                    enemy_profile_id=s["enemy_id"],
                ),
            ],
            scope="all",
        )
        payload = await self._resolve(db_session, body)

        results = run_rank_pipeline_with_progress(payload, lambda p: None, max_workers=2)

        # Build1's equipped discs are all maxed — they must score ≈0% "vs
        # equipped" (per_build[0].avg_pct/max_pct — build1 has discs equipped,
        # so R4/D1 leaves this displayed value unchanged from the raw
        # baseline-relative computation). Other discs (build2 equipped,
        # unequipped) may score higher.
        #
        # NOT best_build_avg/best_build_max: since R5, those are norm_pct —
        # this disc's % gap to whichever candidate scores best in that
        # context (D3/D4) — a different quantity that a maxed-but-not-best
        # disc has no reason to be near zero on.
        near_zero = [
            r
            for r in results
            if r["per_build"][0]["avg_pct"] is not None
            and r["per_build"][0]["max_pct"] is not None
            and abs(r["per_build"][0]["avg_pct"]) < 0.05
            and abs(r["per_build"][0]["max_pct"]) < 0.05
        ]
        # At least the 6 build1 maxed discs should be near zero.
        assert len(near_zero) >= 6

    async def test_multi_context_per_build_breakdown_length(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Each result has per_build with one entry per context."""
        s = await _seed_rank_scenario(authed_client, db_session)
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["build1_id"],
                    combo_id=s["combo1_id"],
                    enemy_profile_id=s["enemy_id"],
                ),
                RankContextSchema(
                    build_id=s["build2_id"],
                    combo_id=s["combo2_id"],
                    enemy_profile_id=s["enemy_id"],
                ),
            ]
        )
        payload = await self._resolve(db_session, body)
        results = run_rank_pipeline_with_progress(payload, lambda p: None, max_workers=2)

        assert len(results) > 0
        for r in results:
            assert len(r["per_build"]) == 2
            build_ids = {pb["build_id"] for pb in r["per_build"]}
            assert s["build1_id"] in build_ids
            assert s["build2_id"] in build_ids

    async def test_weight_affects_portfolio_avg(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """portfolio_avg is the weight-normalised mean across contexts.

        Since R5, portfolio_avg is derived from norm_pct — a baseline-free
        quantity not exposed per-context in the API response (only the
        aggregate reflects it; per_build.avg_pct stays "vs equipped" per D1) —
        so the exact weighted-avg_pct formula this test used to check is no
        longer the right formula (DESIGN_ranker_discless.md D3). What's still
        testable, and still the point of this test's name, is that weight
        actually moves the result: skewing weight toward one context should
        change at least one disc's portfolio_avg relative to equal weighting.
        """
        s = await _seed_rank_scenario(authed_client, db_session)

        async def _portfolio_by_disc(weight1: float, weight2: float) -> dict[str, float]:
            body = RankRequest(
                contexts=[
                    RankContextSchema(
                        build_id=s["build1_id"],
                        combo_id=s["combo1_id"],
                        enemy_profile_id=s["enemy_id"],
                        weight=weight1,
                    ),
                    RankContextSchema(
                        build_id=s["build2_id"],
                        combo_id=s["combo2_id"],
                        enemy_profile_id=s["enemy_id"],
                        weight=weight2,
                    ),
                ]
            )
            payload = await self._resolve(db_session, body)
            results = run_rank_pipeline_with_progress(payload, lambda p: None, max_workers=2)
            return {r["disc_id"]: r["portfolio_avg"] for r in results}

        equal_weight = await _portfolio_by_disc(1.0, 1.0)
        skewed_weight = await _portfolio_by_disc(1.0, 3.0)

        assert any(
            abs(equal_weight[disc_id] - skewed_weight[disc_id]) > 1e-6
            for disc_id in equal_weight
            if disc_id in skewed_weight
        )

    async def test_per_context_set_filter_disc_excluded_from_one_context(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A disc in SetA is scored for ctx1 (SetA filter) but not ctx2 (SetC filter).

        With two contexts and the cand_a disc only matching ctx1's allowed_set_ids,
        cand_a's per_build should have None for ctx2.
        """
        s = await _seed_rank_scenario(authed_client, db_session)
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["build1_id"],
                    combo_id=s["combo1_id"],
                    enemy_profile_id=s["enemy_id"],
                    allowed_set_ids=[s["set_a_id"]],
                ),
                RankContextSchema(
                    build_id=s["build2_id"],
                    combo_id=s["combo2_id"],
                    enemy_profile_id=s["enemy_id"],
                    allowed_set_ids=[s["set_c_id"]],
                ),
            ],
            disc_ids=[s["cand_a_id"], s["cand_c_id"]],
        )
        payload = await self._resolve(db_session, body)
        results = run_rank_pipeline_with_progress(payload, lambda p: None, max_workers=2)

        by_id = {r["disc_id"]: r for r in results}

        # cand_a (SetA) is scored only in ctx1 (SetA filter).
        assert s["cand_a_id"] in by_id
        a_pb = {pb["build_id"]: pb for pb in by_id[s["cand_a_id"]]["per_build"]}
        assert a_pb[s["build1_id"]]["avg_pct"] is not None
        assert a_pb[s["build2_id"]]["avg_pct"] is None

        # cand_c (SetC) is scored only in ctx2 (SetC filter).
        assert s["cand_c_id"] in by_id
        c_pb = {pb["build_id"]: pb for pb in by_id[s["cand_c_id"]]["per_build"]}
        assert c_pb[s["build1_id"]]["avg_pct"] is None
        assert c_pb[s["build2_id"]]["avg_pct"] is not None

    async def test_scope_all_includes_disc_from_other_build(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """scope='all' scores discs equipped on build2 even when context is build1."""
        s = await _seed_rank_scenario(authed_client, db_session)
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["build1_id"],
                    combo_id=s["combo1_id"],
                    enemy_profile_id=s["enemy_id"],
                ),
            ],
            scope="all",
        )
        payload = await self._resolve(db_session, body)

        # scope=all should include more discs than just build1's + unequipped.
        body_default = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["build1_id"],
                    combo_id=s["combo1_id"],
                    enemy_profile_id=s["enemy_id"],
                ),
            ]
        )
        payload_default = await self._resolve(db_session, body_default)

        assert len(payload.inventory) > len(payload_default.inventory)

    async def test_disc_dropped_when_excluded_from_all_contexts(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A disc matching no context's allowed_set_ids is absent from results."""
        s = await _seed_rank_scenario(authed_client, db_session)
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["build1_id"],
                    combo_id=s["combo1_id"],
                    enemy_profile_id=s["enemy_id"],
                    allowed_set_ids=[s["set_a_id"]],
                ),
            ],
            disc_ids=[s["cand_a_id"], s["cand_c_id"]],
        )
        payload = await self._resolve(db_session, body)
        results = run_rank_pipeline_with_progress(payload, lambda p: None, max_workers=2)

        disc_ids = {r["disc_id"] for r in results}
        assert s["cand_a_id"] in disc_ids
        # cand_c is SetC; ctx only allows SetA → dropped entirely.
        assert s["cand_c_id"] not in disc_ids

    async def test_non_default_buff_context_changes_baseline_damage(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A non-default active_conditions/stack_counts must move rank output.

        Regression for DESIGN §1.1 defect 2 (Task A5): the *frontend*
        hardcodes active_conditions=['always'] / stack_counts={} today
        (fixed in Task A9) -- this test proves the backend itself already
        varies correctly with the context it's given, at the service/schema
        layer, independent of what the client currently sends.
        """
        agent = Agent(
            hakushin_id=97900,
            name="RankContextAgent",
            element=Element.ELECTRIC,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
            base_atk=1000,
            base_hp=8000,
            base_def=600,
        )
        db_session.add(agent)
        await db_session.flush()

        attack = Attack(
            agent_id=agent.id,
            hakushin_skill_id=9790,
            skill_key="Basic",
            name="RankContextHit",
            hit_index=0,
            element=Element.ELECTRIC,
            damage_base=10000,
            damage_growth=0,
        )
        db_session.add(attack)

        enemy = EnemyProfile(name="RankContextDummy", level=60, defense=50, electric_res=0)
        db_session.add(enemy)
        await db_session.flush()

        build_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "RankContextBuild", "agent_id": str(agent.id)},
        )
        assert build_resp.status_code == 201, build_resp.text
        build_id = build_resp.json()["id"]

        team_resp = await authed_client.post(
            "/api/v1/teams",
            json={"name": "RankContextTeam", "build1_id": build_id},
        )
        assert team_resp.status_code == 201, team_resp.text
        team_id = team_resp.json()["id"]

        combo_resp = await authed_client.post(
            "/api/v1/combos",
            json={
                "name": "RankContextCombo",
                "team_id": team_id,
                "sequence": [{"attack_id": str(attack.id), "label": "hit"}],
            },
        )
        assert combo_resp.status_code == 201, combo_resp.text
        combo_id = combo_resp.json()["id"]

        conditional_atk = Modifier(
            stat="atk_pct",
            value=5000,
            source=ModifierSource.EXTERNAL,
            source_label="test:rank_conditional_atk",
            target=ModifierTarget.SELF,
            conditions=(Condition.HP_ABOVE_50,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        )

        def _body(active_conditions: list[str]) -> RankRequest:
            return RankRequest(
                contexts=[
                    RankContextSchema(
                        build_id=build_id,
                        combo_id=combo_id,
                        enemy_profile_id=str(enemy.id),
                        active_conditions=active_conditions,
                    ),
                ],
            )

        with patch(
            "app.services.snapshot_builder.load_agent_modifiers",
            return_value=[conditional_atk],
        ):
            default_payload = await self._resolve(db_session, _body(["always"]))
            active_payload = await self._resolve(db_session, _body(["always", "hp_above_50"]))

        default_baseline = default_payload.contexts[0].baseline_damage
        active_baseline = active_payload.contexts[0].baseline_damage

        assert active_baseline > default_baseline, (
            "activating hp_above_50 should raise baseline_damage via the "
            f"conditional buff, got default={default_baseline} "
            f"active={active_baseline}"
        )

    async def test_two_contexts_in_one_job_resolve_independent_buff_state(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Two contexts in ONE request must not share buff state.

        The frontend relies on this: DESIGN §2.5 (#95) has each rank context
        seeded from its own build, because a rank job routinely spans unrelated
        builds. The test above varies the context across two *requests*, which
        cannot catch cross-context bleed inside a single job -- this one puts
        both contexts in the same `RankRequest` and asserts they still resolve
        to different baselines.
        """
        agent = Agent(
            hakushin_id=97901,
            name="RankPerContextAgent",
            element=Element.ELECTRIC,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
            base_atk=1000,
            base_hp=8000,
            base_def=600,
        )
        db_session.add(agent)
        await db_session.flush()

        attack = Attack(
            agent_id=agent.id,
            hakushin_skill_id=9791,
            skill_key="Basic",
            name="RankPerContextHit",
            hit_index=0,
            element=Element.ELECTRIC,
            damage_base=10000,
            damage_growth=0,
        )
        db_session.add(attack)

        enemy = EnemyProfile(name="RankPerContextDummy", level=60, defense=50, electric_res=0)
        db_session.add(enemy)
        await db_session.flush()

        build_resp = await authed_client.post(
            "/api/v1/builds",
            json={"name": "RankPerContextBuild", "agent_id": str(agent.id)},
        )
        assert build_resp.status_code == 201, build_resp.text
        build_id = build_resp.json()["id"]

        team_resp = await authed_client.post(
            "/api/v1/teams",
            json={"name": "RankPerContextTeam", "build1_id": build_id},
        )
        assert team_resp.status_code == 201, team_resp.text
        team_id = team_resp.json()["id"]

        combo_resp = await authed_client.post(
            "/api/v1/combos",
            json={
                "name": "RankPerContextCombo",
                "team_id": team_id,
                "sequence": [{"attack_id": str(attack.id), "label": "hit"}],
            },
        )
        assert combo_resp.status_code == 201, combo_resp.text
        combo_id = combo_resp.json()["id"]

        conditional_atk = Modifier(
            stat="atk_pct",
            value=5000,
            source=ModifierSource.EXTERNAL,
            source_label="test:rank_per_context_atk",
            target=ModifierTarget.SELF,
            conditions=(Condition.HP_ABOVE_50,),
            scopes=(AttackScope.ALL,),
            max_stacks=1,
        )

        def _ctx(active_conditions: list[str]) -> RankContextSchema:
            return RankContextSchema(
                build_id=build_id,
                combo_id=combo_id,
                enemy_profile_id=str(enemy.id),
                active_conditions=active_conditions,
            )

        body = RankRequest(contexts=[_ctx(["always"]), _ctx(["always", "hp_above_50"])])

        with patch(
            "app.services.snapshot_builder.load_agent_modifiers",
            return_value=[conditional_atk],
        ):
            payload = await self._resolve(db_session, body)

        off_baseline = payload.contexts[0].baseline_damage
        on_baseline = payload.contexts[1].baseline_damage

        assert on_baseline > off_baseline, (
            "each context must resolve its own active_conditions within a "
            "single rank job -- one context's buff state leaked into the "
            f"other, got contexts[0]={off_baseline} contexts[1]={on_baseline}"
        )


# ---------------------------------------------------------------------------
# R3.19 — support-context pipeline (seed helper + tests)
# ---------------------------------------------------------------------------


async def _seed_support_scenario(
    authed_client: AsyncClient,
    db: AsyncSession,
) -> dict:
    """Seed a primary build with a support build attached at slot 1.

    Primary: DPS agent, W-Engine, 6 maxed discs, one-attack combo.
    Support: second agent, same W-Engine, 6 discs (all from SupportSetA).
    Primary.support1 = support build.
    Candidate: one unequipped slot-1 disc from SupportSetA (not maxed).
    Maxed candidate: one unequipped slot-1 disc from SupportSetA (maxed).
    """
    primary_agent = Agent(
        hakushin_id=98000,
        name="SuppPrimary",
        element=Element.ELECTRIC,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
        base_atk=900,
        base_hp=8000,
        base_def=600,
    )
    support_agent = Agent(
        hakushin_id=98001,
        name="SuppSupport",
        element=Element.FIRE,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
        base_atk=500,
        base_hp=12000,
        base_def=400,
    )
    engine = WEngine(
        hakushin_id=98002,
        name="SuppEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=600,
    )
    enemy = EnemyProfile(name="SuppDummy", level=60, defense=60, electric_res=0)
    support_set = DiscSet(
        hakushin_id=98100,
        name="SuppSetA",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +10%",
    )
    db.add_all([primary_agent, support_agent, engine, enemy, support_set])
    await db.flush()

    attack = Attack(
        agent_id=primary_agent.id,
        hakushin_skill_id=9800,
        skill_key="Basic",
        name="SuppHit",
        hit_index=0,
        element=Element.ELECTRIC,
        damage_base=10000,
        damage_growth=0,
    )
    db.add(attack)
    await db.flush()

    # Create primary and support builds.
    pb_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "SuppPrimaryBuild",
            "agent_id": str(primary_agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    primary_build_id = pb_resp.json()["id"]

    sb_resp = await authed_client.post(
        "/api/v1/builds",
        json={
            "name": "SuppSupportBuild",
            "agent_id": str(support_agent.id),
            "w_engine_id": str(engine.id),
        },
    )
    support_build_id = sb_resp.json()["id"]

    # Equip primary with 6 maxed discs.
    _MAXED = [
        {"stat": "hp_pct", "value": 900, "rolls": 3},
        {"stat": "crit_rate", "value": 720, "rolls": 3},
        {"stat": "crit_dmg", "value": 1440, "rolls": 3},
    ]
    primary_set = DiscSet(
        hakushin_id=98200,
        name="SuppPrimarySet",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +10%",
    )
    db.add(primary_set)
    await db.flush()
    for slot in DiscSlot:
        s = int(slot.value)
        db.add(
            Disc(
                disc_set_id=primary_set.id,
                slot=slot,
                rarity=Rarity.S,
                level=15,
                main_stat_type=StatType.ATK_PCT,
                main_stat_value=3000,
                substats=_MAXED,
                build_id=primary_build_id,
                build_slot=s,
            )
        )

    # Equip support with 6 discs from SupportSetA (level=0, a few rolls).
    _SUP_SUBS = [
        {"stat": "hp_pct", "value": 300, "rolls": 1},
        {"stat": "crit_rate", "value": 240, "rolls": 1},
    ]
    for slot in DiscSlot:
        s = int(slot.value)
        db.add(
            Disc(
                disc_set_id=support_set.id,
                slot=slot,
                rarity=Rarity.S,
                level=0,
                main_stat_type=StatType.HP_PCT,
                main_stat_value=3000,
                substats=_SUP_SUBS,
                build_id=support_build_id,
                build_slot=s,
            )
        )
    await db.flush()

    # Unequipped candidate for support scoring — not maxed (has remaining rolls).
    # Main stat = HP_PCT; substats must not duplicate main stat (atk_pct is safe).
    cand = Disc(
        disc_set_id=support_set.id,
        slot=DiscSlot.ONE,
        rarity=Rarity.S,
        level=0,
        main_stat_type=StatType.HP_PCT,
        main_stat_value=3000,
        substats=[
            {"stat": "atk_pct", "value": 300, "rolls": 1},
            {"stat": "crit_rate", "value": 240, "rolls": 1},
            {"stat": "crit_dmg", "value": 480, "rolls": 1},
        ],
    )
    # Maxed candidate — remaining_rolls=0.
    cand_maxed = Disc(
        disc_set_id=support_set.id,
        slot=DiscSlot.ONE,
        rarity=Rarity.S,
        level=15,
        main_stat_type=StatType.HP_PCT,
        main_stat_value=3000,
        substats=_MAXED,
    )
    db.add_all([cand, cand_maxed])
    await db.flush()

    team_resp = await authed_client.post(
        "/api/v1/teams",
        json={"name": "SuppTeam", "build1_id": primary_build_id},
    )
    team_id = team_resp.json()["id"]

    combo_resp = await authed_client.post(
        "/api/v1/combos",
        json={
            "name": "SuppCombo",
            "team_id": team_id,
            "sequence": [{"attack_id": str(attack.id), "label": "SuppHit"}],
        },
    )

    return {
        "primary_build_id": primary_build_id,
        "support_build_id": support_build_id,
        "combo_id": combo_resp.json()["id"],
        "enemy_id": str(enemy.id),
        "cand_id": str(cand.id),
        "cand_maxed_id": str(cand_maxed.id),
        "support_set_hakushin_id": support_set.hakushin_id,
    }


class TestSupportContextPipeline:
    """R3.19 — /scorer/rank support-context integration tests."""

    async def _resolve(
        self,
        db: AsyncSession,
        body: RankRequest,
        support_builds_by_build_id: dict | None = None,
    ) -> object:
        return await resolve_rank_payload(
            db,
            body,
            build_repo=BuildRepository(db),
            combo_repo=ComboRepository(db),
            attack_repo=AttackRepository(db),
            enemy_repo=EnemyProfileRepository(db),
            support_builds_by_build_id=support_builds_by_build_id,
        )

    async def test_single_support_context_produces_results(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A support_slot=1 context resolves and runs, producing per-disc aggregates."""
        s = await _seed_support_scenario(authed_client, db_session)
        sup = await BuildRepository(db_session).get_by_id(s["support_build_id"])
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["primary_build_id"],
                    combo_id=s["combo_id"],
                    enemy_profile_id=s["enemy_id"],
                    support_slot=1,
                )
            ],
            disc_ids=[s["cand_id"]],
        )
        payload = await self._resolve(
            db_session, body, support_builds_by_build_id={s["primary_build_id"]: [sup]}
        )
        results = run_rank_pipeline_with_progress(payload, lambda p: None, max_workers=2)

        assert len(results) == 1
        r = results[0]
        assert r["disc_id"] == s["cand_id"]
        assert "best_build_avg" in r
        assert "per_build" in r
        assert len(r["per_build"]) == 1
        assert r["per_build"][0]["build_id"] == s["primary_build_id"]

    async def test_maxed_equipped_support_disc_scores_near_zero(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A maxed candidate for a support context scores ~0% avg and max."""
        s = await _seed_support_scenario(authed_client, db_session)
        sup = await BuildRepository(db_session).get_by_id(s["support_build_id"])
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["primary_build_id"],
                    combo_id=s["combo_id"],
                    enemy_profile_id=s["enemy_id"],
                    support_slot=1,
                )
            ],
            disc_ids=[s["cand_maxed_id"]],
        )
        payload = await self._resolve(
            db_session, body, support_builds_by_build_id={s["primary_build_id"]: [sup]}
        )
        results = run_rank_pipeline_with_progress(payload, lambda p: None, max_workers=2)

        assert len(results) == 1
        r = results[0]
        assert abs(r["best_build_avg"]) < 0.05
        assert abs(r["best_build_max"]) < 0.05

    async def test_mixed_dps_and_support_contexts_both_in_aggregates(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A request with one DPS context and one support context aggregates both."""
        s = await _seed_support_scenario(authed_client, db_session)
        sup = await BuildRepository(db_session).get_by_id(s["support_build_id"])
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["primary_build_id"],
                    combo_id=s["combo_id"],
                    enemy_profile_id=s["enemy_id"],
                ),
                RankContextSchema(
                    build_id=s["primary_build_id"],
                    combo_id=s["combo_id"],
                    enemy_profile_id=s["enemy_id"],
                    support_slot=1,
                ),
            ],
            disc_ids=[s["cand_id"]],
        )
        payload = await self._resolve(
            db_session, body, support_builds_by_build_id={s["primary_build_id"]: [sup]}
        )
        results = run_rank_pipeline_with_progress(payload, lambda p: None, max_workers=2)

        assert len(results) == 1
        r = results[0]
        assert len(r["per_build"]) == 2

    async def test_support_slot_empty_raises_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """support_slot=2 on a build with only one support → 404."""
        s = await _seed_support_scenario(authed_client, db_session)
        sup = await BuildRepository(db_session).get_by_id(s["support_build_id"])
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["primary_build_id"],
                    combo_id=s["combo_id"],
                    enemy_profile_id=s["enemy_id"],
                    support_slot=2,
                )
            ],
        )
        with pytest.raises(HTTPException) as exc_info:
            await self._resolve(
                db_session, body, support_builds_by_build_id={s["primary_build_id"]: [sup]}
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# R3.17 — support context resolution in resolve_rank_payload


class TestSupportContextResolution:
    """Tests for support_slot resolution in resolve_rank_payload."""

    async def _resolve(self, db: AsyncSession, body: RankRequest) -> object:
        return await resolve_rank_payload(
            db,
            body,
            build_repo=BuildRepository(db),
            combo_repo=ComboRepository(db),
            attack_repo=AttackRepository(db),
            enemy_repo=EnemyProfileRepository(db),
        )

    async def test_empty_support_slot_raises_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """support_slot=1 on a build with no team supports → HTTPException 404."""
        s = await _seed_rank_scenario(authed_client, db_session)
        body = RankRequest(
            contexts=[
                RankContextSchema(
                    build_id=s["build1_id"],
                    combo_id=s["combo1_id"],
                    enemy_profile_id=s["enemy_id"],
                    support_slot=1,
                ),
            ],
            scope="all",
        )

        with pytest.raises(HTTPException) as exc_info:
            await self._resolve(db_session, body)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# R3.2 — OptimizationJobRead.result loosened to dict | list | None


class TestJobDetailResultType:
    async def test_rank_job_list_result_serialises(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        authed_user: tuple,
    ):
        """A succeeded rank job with a list result is returned intact."""
        user, _ = authed_user
        list_result = [{"disc_id": "abc", "avg_improvement": 0.05}]
        repo = OptimizationJobRepository(db_session, owner_id=str(user.id))
        job = await repo.create(
            {
                "status": "succeeded",
                "job_type": "rank",
                "request": {"contexts": []},
                "result": list_result,
                "agent_name": "Agent",
                "enemy_name": "Enemy",
                "combo_name": "Combo",
            }
        )

        resp = await authed_client.get(f"/api/v1/optimizer/jobs/{job.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data["result"], list)
        assert data["result"] == list_result

    async def test_optimize_job_dict_result_still_serialises(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        authed_user: tuple,
    ):
        """An optimizer job with a dict result is unaffected by the type change."""
        user, _ = authed_user
        dict_result = {"top_builds": [], "metadata": {}}
        repo = OptimizationJobRepository(db_session, owner_id=str(user.id))
        job = await repo.create(
            {
                "status": "succeeded",
                "job_type": "optimize",
                "request": {"combo_id": "x"},
                "result": dict_result,
                "agent_name": "Agent",
                "enemy_name": "Enemy",
                "combo_name": "Combo",
            }
        )

        resp = await authed_client.get(f"/api/v1/optimizer/jobs/{job.id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data["result"], dict)
        assert data["result"] == dict_result

    async def test_stateful_rank_endpoint_queues_job(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """POST /scorer/rank runs stateful simulations and queues a job when stateful=True."""
        ctx = await _seed_rank_scenario(authed_client, db_session)

        resp = await authed_client.post(
            "/api/v1/scorer/rank",
            json={
                "contexts": [
                    {
                        "build_id": ctx["build2_id"],
                        "combo_id": ctx["combo2_id"],
                        "enemy_profile_id": ctx["enemy_id"],
                        "weight": 1.0,
                        "stateful": True,
                    }
                ],
                "disc_ids": [ctx["cand_c_id"]],
            },
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert "id" in data
        assert data["status"] == "queued"
