"""Integration tests for DimbreathResourceCostImporter (Task 4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.data.importers.dimbreath_resource_cost_importer import DimbreathResourceCostImporter
from app.models.agent import Agent
from app.models.enums import Element, Rarity, Specialty

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _agent(hakushin_id: int, name: str) -> Agent:
    return Agent(
        hakushin_id=hakushin_id,
        name=name,
        element=Element.ELECTRIC,
        specialty=Specialty.STUN,
        rarity=Rarity.S,
    )


async def _seed_agents(session: AsyncSession, agents: list[Agent]) -> None:
    for agent in agents:
        session.add(agent)
    await session.flush()


@pytest.mark.asyncio
async def test_importer_sets_known_costs(db_session: AsyncSession) -> None:
    """anby(1011)=60, velina(1561)=45 — standard Energy agents."""
    await _seed_agents(
        db_session,
        [_agent(1011, "Anby"), _agent(1561, "Velina")],
    )

    importer = DimbreathResourceCostImporter(db_session)
    count = await importer.seed_ex_energy_costs()
    assert count == 2

    anby = (
        await db_session.execute(select(Agent).where(Agent.hakushin_id == 1011))
    ).scalar_one()
    velina = (
        await db_session.execute(select(Agent).where(Agent.hakushin_id == 1561))
    ).scalar_one()

    assert anby.ex_energy_cost == 60
    assert velina.ex_energy_cost == 45


@pytest.mark.asyncio
async def test_importer_sets_null_for_non_energy_agent(db_session: AsyncSession) -> None:
    """starlight-billy(1531) has no Energy cost — ex_energy_cost must be NULL."""
    await _seed_agents(db_session, [_agent(1531, "Starlight - Billy")])

    importer = DimbreathResourceCostImporter(db_session)
    await importer.seed_ex_energy_costs()

    billy = (
        await db_session.execute(select(Agent).where(Agent.hakushin_id == 1531))
    ).scalar_one()
    assert billy.ex_energy_cost is None


@pytest.mark.asyncio
async def test_importer_sets_corrected_default_agent(db_session: AsyncSession) -> None:
    """alice(1401)=40 — a default-corrected agent (was 60 in old energy_costs.py)."""
    await _seed_agents(db_session, [_agent(1401, "Alice")])

    importer = DimbreathResourceCostImporter(db_session)
    await importer.seed_ex_energy_costs()

    alice = (
        await db_session.execute(select(Agent).where(Agent.hakushin_id == 1401))
    ).scalar_one()
    assert alice.ex_energy_cost == 40


@pytest.mark.asyncio
async def test_importer_is_idempotent(db_session: AsyncSession) -> None:
    """Running the importer twice must produce the same result."""
    await _seed_agents(db_session, [_agent(1011, "Anby")])

    importer = DimbreathResourceCostImporter(db_session)
    await importer.seed_ex_energy_costs()
    await importer.seed_ex_energy_costs()

    anby = (
        await db_session.execute(select(Agent).where(Agent.hakushin_id == 1011))
    ).scalar_one()
    assert anby.ex_energy_cost == 60


@pytest.mark.asyncio
async def test_importer_warns_on_unmatched_extract_agent(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """Extract agent with no DB row must log a warning, not crash."""
    # Seed only velina; anby is absent → warning expected for anby
    await _seed_agents(db_session, [_agent(1561, "Velina")])

    import logging

    logger_name = "app.data.importers.dimbreath_resource_cost_importer"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        importer = DimbreathResourceCostImporter(db_session)
        await importer.seed_ex_energy_costs()

    warned_ids = [r.message for r in caplog.records if "no DB row" in r.message]
    # anby(1011) is in extract but absent from DB → at least one warning
    assert any("1011" in m for m in warned_ids)
