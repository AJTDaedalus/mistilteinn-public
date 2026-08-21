"""Integration tests for Agent.ex_energy_cost column (Task 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.enums import Element, Rarity, Specialty

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _make_agent(hakushin_id: int, name: str, ex_energy_cost: int | None = None) -> Agent:
    return Agent(
        hakushin_id=hakushin_id,
        name=name,
        element=Element.ELECTRIC,
        specialty=Specialty.STUN,
        rarity=Rarity.S,
        ex_energy_cost=ex_energy_cost,
    )


@pytest.mark.asyncio
async def test_ex_energy_cost_set_and_read(db_session: AsyncSession) -> None:
    agent = _make_agent(hakushin_id=9001, name="TestAgentCost60", ex_energy_cost=60)
    db_session.add(agent)
    await db_session.flush()

    result = await db_session.execute(select(Agent).where(Agent.hakushin_id == 9001))
    row = result.scalar_one()
    assert row.ex_energy_cost == 60


@pytest.mark.asyncio
async def test_ex_energy_cost_none_round_trips(db_session: AsyncSession) -> None:
    agent = _make_agent(hakushin_id=9002, name="TestAgentCostNone", ex_energy_cost=None)
    db_session.add(agent)
    await db_session.flush()

    result = await db_session.execute(select(Agent).where(Agent.hakushin_id == 9002))
    row = result.scalar_one()
    assert row.ex_energy_cost is None


@pytest.mark.asyncio
async def test_ex_energy_cost_default_is_none(db_session: AsyncSession) -> None:
    agent = _make_agent(hakushin_id=9003, name="TestAgentCostDefault")
    db_session.add(agent)
    await db_session.flush()

    result = await db_session.execute(select(Agent).where(Agent.hakushin_id == 9003))
    row = result.scalar_one()
    assert row.ex_energy_cost is None


@pytest.mark.asyncio
async def test_ex_energy_cost_update(db_session: AsyncSession) -> None:
    agent = _make_agent(hakushin_id=9004, name="TestAgentCostUpdate", ex_energy_cost=40)
    db_session.add(agent)
    await db_session.flush()

    result = await db_session.execute(select(Agent).where(Agent.hakushin_id == 9004))
    row = result.scalar_one()
    row.ex_energy_cost = 45
    await db_session.flush()

    result2 = await db_session.execute(select(Agent).where(Agent.hakushin_id == 9004))
    updated = result2.scalar_one()
    assert updated.ex_energy_cost == 45
