"""Integration tests for W-Engine API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.enums import Rarity, Specialty
from app.models.w_engine import WEngine

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_engines(db: AsyncSession) -> list[WEngine]:
    engines = []
    for i, (name, spec, rarity) in enumerate(
        [
            ("Steel Cushion", Specialty.ATTACK, Rarity.S),
            ("Starlight Engine", Specialty.ATTACK, Rarity.A),
            ("The Restrained", Specialty.STUN, Rarity.S),
        ]
    ):
        e = WEngine(
            hakushin_id=2000 + i,
            name=name,
            rarity=rarity,
            specialty=spec,
            base_atk=46 + i * 2,
            secondary_stat_type="crit_rate",
            secondary_stat_value=960,
            passive_name=f"Passive {i}",
            passive_descriptions={"1": f"Effect R1 {i}"},
        )
        db.add(e)
        engines.append(e)
    await db.flush()
    return engines


class TestWEngineAPI:
    async def test_list_all(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_engines(db_session)
        resp = await client.get("/api/v1/w-engines")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

    async def test_filter_by_specialty(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_engines(db_session)
        resp = await client.get("/api/v1/w-engines", params={"specialty": "attack"})
        assert resp.json()["total"] == 2

    async def test_get_by_id(self, client: AsyncClient, db_session: AsyncSession):
        engines = await _seed_engines(db_session)
        resp = await client.get(f"/api/v1/w-engines/{engines[0].id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Steel Cushion"
        assert data["passive_descriptions"]["1"] == "Effect R1 0"

    async def test_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/w-engines/nonexistent")
        assert resp.status_code == 404
