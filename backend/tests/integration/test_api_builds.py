"""Integration tests for Build, Team, Combo, Enemy, Disc CRUD endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.agent import Agent, Attack
from app.models.build import EnemyProfile
from app.models.disc import DiscSet
from app.models.enums import Element, Rarity, Specialty
from app.models.w_engine import WEngine

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_base(db: AsyncSession) -> dict:
    """Seed two agents + w-engine needed for builds."""
    agent = Agent(
        hakushin_id=5000,
        name="BuildAgent",
        element=Element.FIRE,
        specialty=Specialty.ATTACK,
        rarity=Rarity.S,
    )
    agent2 = Agent(
        hakushin_id=5003,
        name="BuildAgent2",
        element=Element.ICE,
        specialty=Specialty.STUN,
        rarity=Rarity.A,
    )
    agent3 = Agent(
        hakushin_id=5004,
        name="BuildAgent3",
        element=Element.ELECTRIC,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
    )
    engine = WEngine(
        hakushin_id=5001,
        name="BuildEngine",
        rarity=Rarity.S,
        specialty=Specialty.ATTACK,
        base_atk=46,
    )
    disc_set = DiscSet(
        hakushin_id=5002,
        name="TestSet",
        two_piece_text="ATK +10%",
        four_piece_text="DMG +25%",
    )
    db.add_all([agent, agent2, agent3, engine, disc_set])
    await db.flush()
    return {
        "agent_id": agent.id,
        "agent2_id": agent2.id,
        "agent3_id": agent3.id,
        "w_engine_id": engine.id,
        "disc_set_id": disc_set.id,
    }


# --- Build CRUD ---


class TestBuildCRUD:
    async def test_create_build(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        resp = await authed_client.post(
            "/api/v1/builds",
            json={
                "name": "My Build",
                "agent_id": base["agent_id"],
                "w_engine_id": base["w_engine_id"],
                "mindscape_level": 0,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "name" not in data
        assert data["agent_id"] == base["agent_id"]

    async def test_list_builds(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        await authed_client.post(
            "/api/v1/builds",
            json={"agent_id": base["agent_id"], "name": "B1"},
        )
        await authed_client.post(
            "/api/v1/builds",
            json={"agent_id": base["agent2_id"], "name": "B2"},
        )
        resp = await authed_client.get("/api/v1/builds")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_duplicate_owner_agent_rejected(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        base = await _seed_base(db_session)
        r1 = await authed_client.post(
            "/api/v1/builds",
            json={"agent_id": base["agent_id"], "name": "First"},
        )
        assert r1.status_code == 201
        r2 = await authed_client.post(
            "/api/v1/builds",
            json={"agent_id": base["agent_id"], "name": "Second"},
        )
        assert r2.status_code == 409

    async def test_update_build(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        create = await authed_client.post(
            "/api/v1/builds",
            json={
                "agent_id": base["agent_id"],
                "name": "Old Name",
            },
        )
        build_id = create.json()["id"]
        resp = await authed_client.patch(
            f"/api/v1/builds/{build_id}",
            json={
                "mindscape_level": 6,
            },
        )
        assert resp.status_code == 200
        assert "name" not in resp.json()
        assert resp.json()["mindscape_level"] == 6

    async def test_delete_build(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        create = await authed_client.post(
            "/api/v1/builds",
            json={
                "agent_id": base["agent_id"],
            },
        )
        build_id = create.json()["id"]
        resp = await authed_client.delete(f"/api/v1/builds/{build_id}")
        assert resp.status_code == 204
        resp = await authed_client.get(f"/api/v1/builds/{build_id}")
        assert resp.status_code == 404

    async def test_get_not_found(self, authed_client: AsyncClient):
        resp = await authed_client.get("/api/v1/builds/fake-id")
        assert resp.status_code == 404

    async def test_patch_w_engine_refinement(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """PATCH w_engine_refinement from 1 to 5; GET reflects the change."""
        base = await _seed_base(db_session)
        create = await authed_client.post(
            "/api/v1/builds",
            json={
                "agent_id": base["agent_id"],
                "name": "Refine Test",
            },
        )
        build_id = create.json()["id"]
        assert create.json()["w_engine_refinement"] == 1

        resp = await authed_client.patch(
            f"/api/v1/builds/{build_id}",
            json={
                "w_engine_refinement": 5,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["w_engine_refinement"] == 5

        get_resp = await authed_client.get(f"/api/v1/builds/{build_id}")
        assert get_resp.json()["w_engine_refinement"] == 5

class TestEquipDisc:
    async def _make_disc(
        self,
        authed_client: AsyncClient,
        disc_set_id: str,
        *,
        slot: int,
    ) -> str:
        resp = await authed_client.post(
            "/api/v1/discs",
            json={
                "disc_set_id": disc_set_id,
                "slot": slot,
                "rarity": "S",
                "main_stat_type": "atk_pct" if slot >= 4 else "hp",
                "main_stat_value": 3000 if slot >= 4 else 2200,
            },
        )
        return resp.json()["id"]

    async def test_equips_disc_to_slot(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        build = (
            await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": base["agent_id"],
                    "name": "Equip test",
                },
            )
        ).json()
        disc_id = await self._make_disc(
            authed_client,
            base["disc_set_id"],
            slot=4,
        )

        resp = await authed_client.put(
            f"/api/v1/builds/{build['id']}/discs/4",
            json={"disc_id": disc_id},
        )
        assert resp.status_code == 204

        # Disc reflects the assignment.
        check = await authed_client.get(f"/api/v1/discs/{disc_id}")
        body = check.json()
        assert body["build_id"] == build["id"]
        assert body["build_slot"] == 4

    async def test_swapping_unequips_the_old_disc(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        build = (
            await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": base["agent_id"],
                },
            )
        ).json()
        first = await self._make_disc(authed_client, base["disc_set_id"], slot=4)
        second = await self._make_disc(authed_client, base["disc_set_id"], slot=4)

        await authed_client.put(
            f"/api/v1/builds/{build['id']}/discs/4",
            json={"disc_id": first},
        )
        await authed_client.put(
            f"/api/v1/builds/{build['id']}/discs/4",
            json={"disc_id": second},
        )

        first_after = (await authed_client.get(f"/api/v1/discs/{first}")).json()
        second_after = (await authed_client.get(f"/api/v1/discs/{second}")).json()
        assert first_after["build_id"] is None
        assert first_after["build_slot"] is None
        assert second_after["build_id"] == build["id"]

    async def test_clearing_slot_with_null_disc_id(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        build = (
            await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": base["agent_id"],
                },
            )
        ).json()
        disc_id = await self._make_disc(authed_client, base["disc_set_id"], slot=4)
        await authed_client.put(
            f"/api/v1/builds/{build['id']}/discs/4",
            json={"disc_id": disc_id},
        )

        resp = await authed_client.put(
            f"/api/v1/builds/{build['id']}/discs/4",
            json={"disc_id": None},
        )
        assert resp.status_code == 204
        after = (await authed_client.get(f"/api/v1/discs/{disc_id}")).json()
        assert after["build_id"] is None

    async def test_rejects_disc_with_wrong_slot(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        build = (
            await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": base["agent_id"],
                },
            )
        ).json()
        slot1_disc = await self._make_disc(authed_client, base["disc_set_id"], slot=1)
        resp = await authed_client.put(
            f"/api/v1/builds/{build['id']}/discs/4",
            json={"disc_id": slot1_disc},
        )
        assert resp.status_code == 422
        assert "slot 1" in resp.json()["detail"]

    async def test_rejects_invalid_slot_number(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        build = (
            await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": base["agent_id"],
                },
            )
        ).json()
        resp = await authed_client.put(
            f"/api/v1/builds/{build['id']}/discs/9",
            json={"disc_id": None},
        )
        assert resp.status_code == 422


# --- Team CRUD ---


class TestTeamCRUD:
    async def test_create_and_get_team(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        builds = []
        for i, agent_key in enumerate(["agent_id", "agent2_id", "agent3_id"]):
            r = await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": base[agent_key],
                    "name": f"Build {i}",
                },
            )
            builds.append(r.json()["id"])

        resp = await authed_client.post(
            "/api/v1/teams",
            json={
                "name": "Team A",
                "build1_id": builds[0],
                "build2_id": builds[1],
                "build3_id": builds[2],
            },
        )
        assert resp.status_code == 201
        team_id = resp.json()["id"]

        resp = await authed_client.get(f"/api/v1/teams/{team_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Team A"

    async def test_update_team(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        builds = []
        for agent_key in ["agent_id", "agent2_id", "agent3_id"]:
            r = await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": base[agent_key],
                },
            )
            builds.append(r.json()["id"])

        r = await authed_client.post(
            "/api/v1/teams",
            json={
                "name": "Old",
                "build1_id": builds[0],
                "build2_id": builds[1],
                "build3_id": builds[2],
            },
        )
        resp = await authed_client.patch(
            f"/api/v1/teams/{r.json()['id']}",
            json={
                "name": "Updated",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"


# --- Team Calculate (Phase 5A: DPS-only with team-context buffs) ---


class TestTeamCalculate:
    async def _seed_team_scenario(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> dict:
        """Seed 3 agents with attacks + an enemy; build Team with 3 builds + a combo.

        Uses distinct specialties/elements so auto-conditions light up.
        """
        dps_agent = Agent(
            hakushin_id=7000,
            name="DpsAgent",
            element=Element.ICE,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
            base_atk=900,
        )
        stun_agent = Agent(
            hakushin_id=7001,
            name="StunAgent",
            element=Element.FIRE,
            specialty=Specialty.STUN,
            rarity=Rarity.S,
            base_atk=800,
        )
        sup_agent = Agent(
            hakushin_id=7002,
            name="SupAgent",
            element=Element.ICE,
            specialty=Specialty.SUPPORT,
            rarity=Rarity.S,
            base_atk=700,
        )
        enemy = EnemyProfile(name="TeamDummy", level=60, defense=60, ice_res=0)
        db_session.add_all([dps_agent, stun_agent, sup_agent, enemy])
        await db_session.flush()

        ba1 = Attack(
            agent_id=dps_agent.id,
            hakushin_skill_id=10,
            skill_key="Basic",
            name="Basic 1",
            hit_index=0,
            element=Element.ICE,
            damage_base=10000,
            damage_growth=500,
        )
        ult = Attack(
            agent_id=dps_agent.id,
            hakushin_skill_id=11,
            skill_key="Ultimate",
            name="Ultimate",
            hit_index=0,
            element=Element.ICE,
            damage_base=60000,
            damage_growth=3000,
        )
        db_session.add_all([ba1, ult])
        await db_session.flush()

        dps_build = (
            await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": dps_agent.id,
                    "name": "DPS",
                },
            )
        ).json()
        stun_build = (
            await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": stun_agent.id,
                    "name": "Stunner",
                },
            )
        ).json()
        sup_build = (
            await authed_client.post(
                "/api/v1/builds",
                json={
                    "agent_id": sup_agent.id,
                    "name": "Support",
                },
            )
        ).json()

        team = (
            await authed_client.post(
                "/api/v1/teams",
                json={
                    "name": "Team Phase5A",
                    "build1_id": dps_build["id"],
                    "build2_id": stun_build["id"],
                    "build3_id": sup_build["id"],
                },
            )
        ).json()

        combo = (
            await authed_client.post(
                "/api/v1/combos",
                json={
                    "name": "BA1 → ULT",
                    "team_id": team["id"],
                    "sequence": [
                        {"attack_id": ba1.id, "label": "BA1"},
                        {"attack_id": ult.id, "label": "ULT"},
                    ],
                },
            )
        ).json()

        return {
            "team_id": team["id"],
            "dps_build_id": dps_build["id"],
            "stun_build_id": stun_build["id"],
            "combo_id": combo["id"],
            "enemy_id": enemy.id,
        }

    async def test_calculate_team_returns_dps_damage_and_auto_conditions(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        ctx = await self._seed_team_scenario(authed_client, db_session)
        resp = await authed_client.post(
            f"/api/v1/teams/{ctx['team_id']}/calculate",
            json={
                "combo_id": ctx["combo_id"],
                "enemy_profile_id": ctx["enemy_id"],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["team_name"] == "Team Phase5A"
        assert data["dps_agent_name"] == "DpsAgent"
        assert data["combo_name"] == "BA1 → ULT"
        assert data["enemy_name"] == "TeamDummy"
        assert len(data["steps"]) == 2

        # Auto-conditions derived from team composition:
        # - DpsAgent (ice) + SupAgent (ice) share an element → SAME_ELEMENT_IN_TEAM
        # - StunAgent's specialty → STUN_IN_TEAM
        # - SupAgent's specialty → SUPPORT_IN_TEAM
        auto = set(data["auto_conditions"])
        assert "same_element_in_team" in auto
        assert "stun_in_team" in auto
        assert "support_in_team" in auto

        # No support target=team modifiers in this seed → empty attribution.
        assert data["applied_team_buffs"] == []

        # Damage structure mirrors combo evaluation.
        assert data["total_damage"] == sum(s["total"] for s in data["steps"])
        assert data["anomaly_total"] == 0

        # Phase 5B: by_agent present; sum equals total.
        assert "by_agent" in data
        assert sum(int(a["damage"]) for a in data["by_agent"]) == data["total_damage"]

    async def test_calculate_team_rejects_combo_mismatch(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        ctx = await self._seed_team_scenario(authed_client, db_session)
        # Create a second team (reusing stun_build) and a combo for it.
        other_team = (
            await authed_client.post(
                "/api/v1/teams",
                json={"name": "OtherTeam", "build1_id": ctx["stun_build_id"]},
            )
        ).json()
        other_combo = (
            await authed_client.post(
                "/api/v1/combos",
                json={"name": "OtherCombo", "team_id": other_team["id"]},
            )
        ).json()
        # Combo belongs to other_team, not the original team → rejected.
        resp = await authed_client.post(
            f"/api/v1/teams/{ctx['team_id']}/calculate",
            json={
                "combo_id": other_combo["id"],
                "enemy_profile_id": ctx["enemy_id"],
            },
        )
        assert resp.status_code == 422

    async def test_calculate_team_not_found(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/teams/missing/calculate",
            json={
                "combo_id": "y",
                "enemy_profile_id": "z",
            },
        )
        assert resp.status_code == 404


# --- Combo CRUD ---


class TestComboCRUD:
    async def test_create_and_list_combos(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ):
        base = await _seed_base(db_session)
        build = await authed_client.post(
            "/api/v1/builds",
            json={
                "agent_id": base["agent_id"],
            },
        )
        build_id = build.json()["id"]
        team = await authed_client.post(
            "/api/v1/teams",
            json={"name": "T", "build1_id": build_id},
        )
        team_id = team.json()["id"]

        resp = await authed_client.post(
            "/api/v1/combos",
            json={
                "name": "Basic Rotation",
                "team_id": team_id,
                "sequence": [
                    {"attack_id": "fake-1", "label": "BA1"},
                    {"attack_id": "fake-2", "label": "BA2"},
                ],
            },
        )
        assert resp.status_code == 201
        assert len(resp.json()["sequence"]) == 2

        resp = await authed_client.get("/api/v1/combos", params={"team_id": team_id})
        assert resp.json()["items"][0]["name"] == "Basic Rotation"


# --- Combo Evaluation ---


class TestComboEvaluate:
    async def test_evaluate_combo(self, authed_client: AsyncClient, db_session: AsyncSession):
        # Seed agent with attacks + an enemy
        agent = Agent(
            hakushin_id=6000,
            name="EvalAgent",
            element=Element.FIRE,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
            base_atk=900,
            base_hp=8000,
            base_def=600,
        )
        db_session.add(agent)
        await db_session.flush()

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
        ex = Attack(
            agent_id=agent.id,
            hakushin_skill_id=2,
            skill_key="EXSpecial",
            name="EX Special",
            hit_index=0,
            element=Element.FIRE,
            damage_base=30000,
            damage_growth=1500,
        )
        enemy = EnemyProfile(name="Dummy", level=60, defense=60, fire_res=0)
        db_session.add_all([ba1, ex, enemy])
        await db_session.flush()

        # Create build + team + combo via API
        build_resp = await authed_client.post(
            "/api/v1/builds",
            json={
                "name": "EvalBuild",
                "agent_id": agent.id,
            },
        )
        build_id = build_resp.json()["id"]
        team_resp = await authed_client.post(
            "/api/v1/teams",
            json={"name": "EvalTeam", "build1_id": build_id},
        )
        team_id = team_resp.json()["id"]

        combo_resp = await authed_client.post(
            "/api/v1/combos",
            json={
                "name": "BA1 → EX",
                "team_id": team_id,
                "sequence": [
                    {"attack_id": ba1.id, "label": "BA1"},
                    {"attack_id": ex.id, "label": "EX"},
                ],
            },
        )
        combo_id = combo_resp.json()["id"]

        # evaluate endpoint removed in team-builder migration
        resp = await authed_client.post(
            f"/api/v1/combos/{combo_id}/evaluate",
            json={"enemy_profile_id": enemy.id},
        )
        assert resp.status_code == 404

    async def test_evaluate_combo_not_found(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/combos/missing/evaluate",
            json={"enemy_profile_id": "anything"},
        )
        assert resp.status_code == 404

    async def test_evaluate_combo_missing_enemy(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        build = await authed_client.post(
            "/api/v1/builds",
            json={
                "agent_id": base["agent_id"],
            },
        )
        build_id = build.json()["id"]
        team = await authed_client.post(
            "/api/v1/teams",
            json={"name": "T", "build1_id": build_id},
        )
        combo = await authed_client.post(
            "/api/v1/combos",
            json={
                "name": "C",
                "team_id": team.json()["id"],
                "sequence": [],
            },
        )
        resp = await authed_client.post(
            f"/api/v1/combos/{combo.json()['id']}/evaluate",
            json={"enemy_profile_id": "missing"},
        )
        assert resp.status_code == 404

    async def test_evaluate_combo_move_name_expands_to_all_hits(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A step with ``move_name`` includes every hit sharing that name.

        Locks the move-based combo semantics: picking a move once at the
        UI yields summed damage across all of its hits at calc time.
        """
        agent = Agent(
            hakushin_id=6100,
            name="MoveAgent",
            element=Element.FIRE,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
            base_atk=900,
            base_hp=8000,
            base_def=600,
        )
        db_session.add(agent)
        await db_session.flush()

        # Two hits sharing the same name — different hit_index, different
        # multipliers. The move_name step should sum them.
        hit0 = Attack(
            agent_id=agent.id,
            hakushin_skill_id=1,
            skill_key="Basic",
            name="BA Combo Hit",
            hit_index=0,
            element=Element.FIRE,
            damage_base=10000,
            damage_growth=500,
        )
        hit1 = Attack(
            agent_id=agent.id,
            hakushin_skill_id=1,
            skill_key="Basic",
            name="BA Combo Hit",
            hit_index=1,
            element=Element.FIRE,
            damage_base=20000,
            damage_growth=1000,
        )
        # An unrelated attack — must NOT be summed in.
        other = Attack(
            agent_id=agent.id,
            hakushin_skill_id=2,
            skill_key="Basic",
            name="Different",
            hit_index=0,
            element=Element.FIRE,
            damage_base=99000,
            damage_growth=4000,
        )
        enemy = EnemyProfile(name="Dummy", level=60, defense=60, fire_res=0)
        db_session.add_all([hit0, hit1, other, enemy])
        await db_session.flush()

        build_resp = await authed_client.post(
            "/api/v1/builds",
            json={
                "name": "MoveBuild",
                "agent_id": agent.id,
            },
        )
        build_id = build_resp.json()["id"]
        team_resp = await authed_client.post(
            "/api/v1/teams",
            json={"name": "MoveTeam", "build1_id": build_id},
        )
        team_id = team_resp.json()["id"]

        # Save with the new move-name shape — no attack_id.
        combo_resp = await authed_client.post(
            "/api/v1/combos",
            json={
                "name": "Move-based combo",
                "team_id": team_id,
                "sequence": [{"move_name": "BA Combo Hit", "label": "BA"}],
            },
        )
        combo_id = combo_resp.json()["id"]

        # evaluate endpoint removed in team-builder migration
        resp = await authed_client.post(
            f"/api/v1/combos/{combo_id}/evaluate",
            json={"enemy_profile_id": enemy.id},
        )
        assert resp.status_code == 404

    async def test_evaluate_combo_move_name_unknown_returns_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        enemy = EnemyProfile(name="X", level=60, defense=60, fire_res=0)
        db_session.add(enemy)
        await db_session.flush()
        build = await authed_client.post(
            "/api/v1/builds",
            json={
                "agent_id": base["agent_id"],
                "name": "B",
            },
        )
        build_id = build.json()["id"]
        team = await authed_client.post(
            "/api/v1/teams",
            json={"name": "T", "build1_id": build_id},
        )
        combo = await authed_client.post(
            "/api/v1/combos",
            json={
                "name": "C",
                "team_id": team.json()["id"],
                "sequence": [{"move_name": "Nonexistent", "label": "?"}],
            },
        )
        resp = await authed_client.post(
            f"/api/v1/combos/{combo.json()['id']}/evaluate",
            json={"enemy_profile_id": enemy.id},
        )
        assert resp.status_code == 404


# --- Enemy CRUD ---


class TestEnemyCRUD:
    async def test_create_and_get_enemy(self, authed_client: AsyncClient):
        resp = await authed_client.post(
            "/api/v1/enemies",
            json={
                "name": "Test Boss",
                "level": 60,
                "defense": 60,
                "fire_res": -2000,
                "rarity": 3,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["fire_res"] == -2000
        assert data["rarity"] == 3

        resp = await authed_client.get(f"/api/v1/enemies/{data['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Boss"

    async def test_update_enemy(self, authed_client: AsyncClient):
        r = await authed_client.post("/api/v1/enemies", json={"name": "Mob"})
        enemy_id = r.json()["id"]
        resp = await authed_client.patch(
            f"/api/v1/enemies/{enemy_id}",
            json={
                "fire_res": -3000,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["fire_res"] == -3000

    async def test_list_filter_by_rarity(self, authed_client: AsyncClient):
        await authed_client.post("/api/v1/enemies", json={"name": "Common", "rarity": 1})
        await authed_client.post("/api/v1/enemies", json={"name": "Boss", "rarity": 3})
        resp = await authed_client.get("/api/v1/enemies", params={"rarity": 3})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["name"] == "Boss"


# --- Disc CRUD ---


class TestDiscCRUD:
    async def test_create_and_get_disc(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        resp = await authed_client.post(
            "/api/v1/discs",
            json={
                "disc_set_id": base["disc_set_id"],
                "slot": 4,
                "rarity": "S",
                "level": 15,
                "main_stat_type": "crit_rate",
                "main_stat_value": 2400,
                "substats": [
                    {"stat": "crit_dmg", "value": 480, "rolls": 1},
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["main_stat_type"] == "crit_rate"
        assert data["substats"][0]["stat"] == "crit_dmg"

    async def test_update_disc(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        r = await authed_client.post(
            "/api/v1/discs",
            json={
                "disc_set_id": base["disc_set_id"],
                "slot": 1,
                "rarity": "S",
                "main_stat_type": "hp",
                "main_stat_value": 2000,
            },
        )
        disc_id = r.json()["id"]
        resp = await authed_client.patch(
            f"/api/v1/discs/{disc_id}",
            json={
                "level": 15,
                "main_stat_value": 4600,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["level"] == 15

    async def test_delete_disc(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        r = await authed_client.post(
            "/api/v1/discs",
            json={
                "disc_set_id": base["disc_set_id"],
                "slot": 1,
                "rarity": "S",
                "main_stat_type": "hp",
                "main_stat_value": 2000,
            },
        )
        disc_id = r.json()["id"]
        resp = await authed_client.delete(f"/api/v1/discs/{disc_id}")
        assert resp.status_code == 204

    async def test_list_disc_sets(self, authed_client: AsyncClient, db_session: AsyncSession):
        await _seed_base(db_session)
        resp = await authed_client.get("/api/v1/disc-sets")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1


class TestDiscFilterAPI:
    """Tests for GET /discs filter parameters (T4.3)."""

    async def _seed_discs(self, authed_client: AsyncClient, base: dict) -> dict:
        """Create two S-rank slot-4 discs and one A-rank slot-1 disc."""

        async def post(slot, rarity, main_stat):
            r = await authed_client.post(
                "/api/v1/discs",
                json={
                    "disc_set_id": base["disc_set_id"],
                    "slot": slot,
                    "rarity": rarity,
                    "main_stat_type": main_stat,
                    "main_stat_value": 2000,
                },
            )
            assert r.status_code == 201
            return r.json()["id"]

        s4a = await post(4, "S", "crit_rate")
        s4b = await post(4, "S", "crit_dmg")
        a1 = await post(1, "A", "hp")
        return {"s4a": s4a, "s4b": s4b, "a1": a1}

    async def test_filter_by_slot(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        ids = await self._seed_discs(authed_client, base)
        resp = await authed_client.get("/api/v1/discs?slot=4")
        assert resp.status_code == 200
        returned = {d["id"] for d in resp.json()["items"]}
        assert ids["s4a"] in returned
        assert ids["s4b"] in returned
        assert ids["a1"] not in returned

    async def test_filter_by_rarity(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        ids = await self._seed_discs(authed_client, base)
        resp = await authed_client.get("/api/v1/discs?rarity=A")
        assert resp.status_code == 200
        returned = {d["id"] for d in resp.json()["items"]}
        assert ids["a1"] in returned
        assert ids["s4a"] not in returned

    async def test_filter_by_set_id(self, authed_client: AsyncClient, db_session: AsyncSession):
        base = await _seed_base(db_session)
        ids = await self._seed_discs(authed_client, base)
        resp = await authed_client.get(f"/api/v1/discs?set_id={base['disc_set_id']}")
        assert resp.status_code == 200
        returned = {d["id"] for d in resp.json()["items"]}
        assert ids["s4a"] in returned
        assert ids["a1"] in returned

    async def test_filter_slot_and_rarity_combined(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        ids = await self._seed_discs(authed_client, base)
        resp = await authed_client.get("/api/v1/discs?slot=4&rarity=S")
        assert resp.status_code == 200
        returned = {d["id"] for d in resp.json()["items"]}
        assert ids["s4a"] in returned
        assert ids["s4b"] in returned
        assert ids["a1"] not in returned

    async def test_filter_equipped_unequipped(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        ids = await self._seed_discs(authed_client, base)

        # Equip s4a to a build.
        build_r = await authed_client.post(
            "/api/v1/builds",
            json={
                "agent_id": base["agent_id"],
                "name": "EquipTest",
            },
        )
        build_id = build_r.json()["id"]
        await authed_client.put(f"/api/v1/builds/{build_id}/discs/4", json={"disc_id": ids["s4a"]})

        resp = await authed_client.get("/api/v1/discs?equipped=unequipped")
        assert resp.status_code == 200
        returned = {d["id"] for d in resp.json()["items"]}
        assert ids["s4a"] not in returned  # equipped → excluded
        assert ids["s4b"] in returned  # unequipped → included

    async def test_filter_equipped_by_build_id(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ):
        base = await _seed_base(db_session)
        ids = await self._seed_discs(authed_client, base)

        build_r = await authed_client.post(
            "/api/v1/builds",
            json={
                "agent_id": base["agent_id"],
                "name": "PickerTest",
            },
        )
        build_id = build_r.json()["id"]
        await authed_client.put(f"/api/v1/builds/{build_id}/discs/4", json={"disc_id": ids["s4a"]})

        # Filter to "for this build" — should return unequipped + equipped-to-this-build.
        resp = await authed_client.get(f"/api/v1/discs?equipped={build_id}")
        assert resp.status_code == 200
        returned = {d["id"] for d in resp.json()["items"]}
        assert ids["s4a"] in returned  # equipped to THIS build → included
        assert ids["s4b"] in returned  # unequipped → included


# --- D-IM1 regression: buffs endpoint tolerates empty team slots ---


class TestBuildBuffsPartialTeam:
    """`GET /builds/{id}/buffs?team_id=` must skip empty team slots.

    Slots 2/3 have been nullable since 0ffce792bc1e and slot 1 became
    nullable in b1a2c3d4e5f6 (D-IM1, ON DELETE SET NULL). A `None` slot
    reached `support_build.agent` and raised AttributeError -> 500.
    """

    async def _agent(self, db: AsyncSession, hid: int, name: str) -> Agent:
        a = Agent(
            hakushin_id=hid,
            name=name,
            element=Element.FIRE,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
        )
        db.add(a)
        await db.flush()
        return a

    async def test_one_member_team_returns_dps_buffs(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        agent = await self._agent(db_session, 7100, "SoloAgent")
        build = (
            await authed_client.post("/api/v1/builds", json={"agent_id": agent.id})
        ).json()
        team = (
            await authed_client.post(
                "/api/v1/teams", json={"name": "Solo", "build1_id": build["id"]}
            )
        ).json()

        resp = await authed_client.get(
            f"/api/v1/builds/{build['id']}/buffs",
            params={"team_id": team["id"], "active_index": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["build_id"] == build["id"]

    async def test_team_with_deleted_slot1_build_still_serves_buffs(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Deleting the slot-1 build SET NULLs the slot; slot 2 must still work."""
        agent1 = await self._agent(db_session, 7101, "Slot1Agent")
        agent2 = await self._agent(db_session, 7102, "Slot2Agent")
        b1 = (
            await authed_client.post("/api/v1/builds", json={"agent_id": agent1.id})
        ).json()
        b2 = (
            await authed_client.post("/api/v1/builds", json={"agent_id": agent2.id})
        ).json()
        team = (
            await authed_client.post(
                "/api/v1/teams",
                json={"name": "Pair", "build1_id": b1["id"], "build2_id": b2["id"]},
            )
        ).json()

        assert (await authed_client.delete(f"/api/v1/builds/{b1['id']}")).status_code == 204

        # Team survived the delete with slot 1 emptied (D-IM1).
        refreshed = (await authed_client.get(f"/api/v1/teams/{team['id']}")).json()
        assert refreshed["build1_id"] is None
        assert refreshed["build2_id"] == b2["id"]

        resp = await authed_client.get(
            f"/api/v1/builds/{b2['id']}/buffs",
            params={"team_id": team["id"], "active_index": 1},
        )
        assert resp.status_code == 200
