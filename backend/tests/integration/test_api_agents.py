"""Integration tests for Agent API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.agent import Agent, AgentSkill, Attack, CoreSkill, Mindscape
from app.models.enums import Element, Rarity, Specialty

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_agents(db: AsyncSession) -> list[Agent]:
    """Create a few agents with sub-resources for testing."""
    agents = []
    for i, (name, element, specialty) in enumerate(
        [
            ("Anby", Element.ELECTRIC, Specialty.STUN),
            ("Lycaon", Element.ICE, Specialty.STUN),
            ("Soldier 11", Element.FIRE, Specialty.ATTACK),
        ]
    ):
        agent = Agent(
            hakushin_id=1000 + i,
            name=name,
            full_name=f"{name} Full",
            element=element,
            specialty=specialty,
            rarity=Rarity.S if i > 0 else Rarity.A,
            faction="Test",
            base_hp=500 + i * 100,
            base_atk=100 + i * 10,
            base_def=50,
        )
        db.add(agent)
        agents.append(agent)
    await db.flush()

    # Add sub-resources to first agent
    db.add(AgentSkill(agent_id=agents[0].id, skill_key="Basic", name="Test BA"))
    db.add(
        Attack(
            agent_id=agents[0].id,
            hakushin_skill_id=100001,
            skill_key="Basic",
            name="Hit 1",
            hit_index=0,
            element=Element.ELECTRIC,
            damage_base=3120,
            damage_growth=290,
        )
    )
    db.add(
        CoreSkill(
            agent_id=agents[0].id,
            hakushin_id=100501,
            level=1,
            name="Core A",
            description="Test core",
        )
    )
    db.add(
        Mindscape(
            agent_id=agents[0].id,
            level=1,
            name="M1: Test",
            description="Test M1",
        )
    )
    await db.flush()
    return agents


class TestListAgents:
    async def test_list_all(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_agents(db_session)
        resp = await client.get("/api/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    async def test_filter_by_element(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_agents(db_session)
        resp = await client.get("/api/v1/agents", params={"element": "fire"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Soldier 11"

    async def test_filter_by_specialty(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_agents(db_session)
        resp = await client.get("/api/v1/agents", params={"specialty": "stun"})
        data = resp.json()
        assert data["total"] == 2

    async def test_filter_by_rarity(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_agents(db_session)
        resp = await client.get("/api/v1/agents", params={"rarity": "S"})
        data = resp.json()
        assert data["total"] == 2

    async def test_pagination(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_agents(db_session)
        resp = await client.get("/api/v1/agents", params={"offset": 0, "limit": 2})
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 3


class TestGetAgent:
    async def test_get_by_id(self, client: AsyncClient, db_session: AsyncSession):
        agents = await _seed_agents(db_session)
        resp = await client.get(f"/api/v1/agents/{agents[0].id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Anby"
        assert len(data["skills"]) == 1
        assert len(data["attacks"]) == 1
        assert data["attacks"][0]["damage_base"] == 3120
        assert len(data["core_skills"]) == 1
        assert len(data["mindscapes"]) == 1

    async def test_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/agents/nonexistent-id")
        assert resp.status_code == 404
