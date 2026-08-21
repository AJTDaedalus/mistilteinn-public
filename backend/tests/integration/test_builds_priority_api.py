"""Integration tests for PUT /builds/priority endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.agent import Agent
from app.models.enums import Element, Rarity, Specialty

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_agent(db: AsyncSession) -> str:
    return (await _seed_agents(db, 1))[0]


async def _seed_agents(db: AsyncSession, count: int = 3) -> list[str]:
    agents = [
        Agent(
            hakushin_id=7700 + i,
            name=f"PrioApiAgent{i}",
            element=Element.ELECTRIC,
            specialty=Specialty.ATTACK,
            rarity=Rarity.S,
        )
        for i in range(count)
    ]
    db.add_all(agents)
    await db.flush()
    return [str(a.id) for a in agents]


async def _create_build(authed_client: AsyncClient, agent_id: str, name: str) -> str:
    resp = await authed_client.post("/api/v1/builds", json={"name": name, "agent_id": agent_id})
    assert resp.status_code == 201
    return resp.json()["id"]


class TestPutBuildsPriority:
    async def test_assigns_dense_ranks(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        agent_ids = await _seed_agents(db_session, 3)
        b1 = await _create_build(authed_client, agent_ids[0], "B1")
        b2 = await _create_build(authed_client, agent_ids[1], "B2")
        b3 = await _create_build(authed_client, agent_ids[2], "B3")

        resp = await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1, b2, b3]},
        )
        assert resp.status_code == 200
        items = {r["id"]: r["optimizer_priority"] for r in resp.json()}
        assert items[b1] == 1
        assert items[b2] == 2
        assert items[b3] == 3

    async def test_nulls_omitted_builds(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        agent_ids = await _seed_agents(db_session, 2)
        b1 = await _create_build(authed_client, agent_ids[0], "B1")
        b2 = await _create_build(authed_client, agent_ids[1], "B2")

        # First give b2 a priority so we can confirm it's cleared.
        await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1, b2]},
        )

        resp = await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1]},
        )
        assert resp.status_code == 200
        # Response only contains the ordered builds; verify b1 rank.
        items = {r["id"]: r for r in resp.json()}
        assert items[b1]["optimizer_priority"] == 1

        # Confirm b2 is now NULL via GET.
        b2_resp = await authed_client.get(f"/api/v1/builds/{b2}")
        assert b2_resp.status_code == 200
        assert b2_resp.json()["optimizer_priority"] is None

    async def test_422_on_unknown_id(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        agent_id = await _seed_agent(db_session)
        b1 = await _create_build(authed_client, agent_id, "B1")
        fake_id = "00000000-0000-0000-0000-000000000000"

        resp = await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1, fake_id]},
        )
        assert resp.status_code == 422

    async def test_422_on_duplicate_ids(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        agent_id = await _seed_agent(db_session)
        b1 = await _create_build(authed_client, agent_id, "B1")

        resp = await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1, b1]},
        )
        assert resp.status_code == 422

    async def test_empty_list_clears_all_priorities(
        self, authed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        agent_id = await _seed_agent(db_session)
        b1 = await _create_build(authed_client, agent_id, "B1")

        await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": [b1]},
        )

        resp = await authed_client.put(
            "/api/v1/builds/priority",
            json={"ordered_build_ids": []},
        )
        assert resp.status_code == 200
        assert resp.json() == []

        b1_resp = await authed_client.get(f"/api/v1/builds/{b1}")
        assert b1_resp.json()["optimizer_priority"] is None
