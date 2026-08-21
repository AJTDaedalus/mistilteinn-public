"""Task 4 — seed `agent_resource_costs` from the committed Dimbreath extract.

Verbatim: the importer copies `resource_costs.json[agent].costs[]` as-is. It makes no
judgement about which of an agent's costs is "the" cost — that judgement is exactly what
`Agent.ex_energy_cost` has to make and gets wrong for the multi-mode agents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.data.importers.dimbreath_resource_cost_importer import DimbreathResourceCostImporter
from app.models.agent import Agent, AgentResourceCost
from app.models.enums import Element, Rarity, Specialty

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _agent(hakushin_id: int, name: str) -> Agent:
    return Agent(
        hakushin_id=hakushin_id,
        name=name,
        element=Element.FIRE,
        specialty=Specialty.ANOMALY,
        rarity=Rarity.S,
    )


async def _rows_for(session: AsyncSession, agent: Agent) -> list[AgentResourceCost]:
    result = await session.execute(
        select(AgentResourceCost)
        .where(AgentResourceCost.agent_id == agent.id)
        .order_by(AgentResourceCost.cost_key)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_burnice_gets_all_six_rows(db_session: AsyncSession) -> None:
    """The whole point of the table: six priced actions a single scalar cannot hold."""
    burnice = _agent(1171, "Burnice")
    db_session.add(burnice)
    await db_session.flush()

    importer = DimbreathResourceCostImporter(db_session)
    assert await importer.seed_resource_cost_rows() == 6

    rows = await _rows_for(db_session, burnice)
    assert [(r.cost_key.rsplit("_Property_", 1)[1], r.value, r.per_sec) for r in rows] == [
        ("ExSpecial_01_SpCostValue_01", 40.0, False),
        ("ExSpecial_01_SpCostValue_02", 12.5, True),
        ("ExSpecial_01_SpCostValue_03", 5.0, False),
        ("ExSpecial_02_SpCostValue_01", 10.0, False),
        ("ExSpecial_02_SpCostValue_02", 25.0, True),
        ("ExSpecial_02_SpCostValue_03", 10.0, False),
    ]
    assert {r.resource for r in rows} == {"Energy"}


@pytest.mark.asyncio
async def test_a_per_second_drain_keeps_its_fraction(db_session: AsyncSession) -> None:
    """12.5 must survive the round trip. An Integer column would floor it to 12."""
    burnice = _agent(1171, "Burnice")
    db_session.add(burnice)
    await db_session.flush()

    await DimbreathResourceCostImporter(db_session).seed_resource_cost_rows()

    drain = next(r for r in await _rows_for(db_session, burnice) if r.per_sec)
    assert drain.value == pytest.approx(12.5)


@pytest.mark.asyncio
async def test_single_mode_agent_gets_exactly_one_row(db_session: AsyncSession) -> None:
    """Alice is the ~50-agent majority case: one cost, and `ex_energy_cost` is right for her."""
    alice = _agent(1401, "Alice")
    db_session.add(alice)
    await db_session.flush()

    assert await DimbreathResourceCostImporter(db_session).seed_resource_cost_rows() == 1

    rows = await _rows_for(db_session, alice)
    assert len(rows) == 1
    assert rows[0].value == pytest.approx(40.0)
    assert rows[0].per_sec is False


@pytest.mark.asyncio
async def test_named_resource_banks_are_preserved(db_session: AsyncSession) -> None:
    """Velina Windbloom and Starlight-Billy Heat/Rp are not Energy, and must not be relabelled."""
    velina = _agent(1561, "Velina")
    billy = _agent(1531, "Starlight - Billy")
    db_session.add_all([velina, billy])
    await db_session.flush()

    await DimbreathResourceCostImporter(db_session).seed_resource_cost_rows()

    resources = {r.resource for r in await _rows_for(db_session, velina)}
    resources |= {r.resource for r in await _rows_for(db_session, billy)}
    assert resources & {"Windbloom", "Heat", "Rp"}


@pytest.mark.asyncio
async def test_reseeding_is_idempotent(db_session: AsyncSession) -> None:
    """A re-seed is the normal operation; it must not duplicate or accumulate rows."""
    burnice = _agent(1171, "Burnice")
    db_session.add(burnice)
    await db_session.flush()

    importer = DimbreathResourceCostImporter(db_session)
    first = await importer.seed_resource_cost_rows()
    second = await importer.seed_resource_cost_rows()

    assert first == second == 6
    assert len(await _rows_for(db_session, burnice)) == 6


@pytest.mark.asyncio
async def test_an_agent_absent_from_the_extract_gets_no_rows(db_session: AsyncSession) -> None:
    """A roster agent upstream has not priced yet must land with zero rows, never a guessed one."""
    ghost = _agent(9999, "Not In Extract")
    db_session.add(ghost)
    await db_session.flush()

    await DimbreathResourceCostImporter(db_session).seed_resource_cost_rows()
    assert await _rows_for(db_session, ghost) == []


@pytest.mark.asyncio
async def test_ex_energy_cost_is_untouched(db_session: AsyncSession) -> None:
    """The two paths are independent: the scalar stays the ~50-agent fallback (DESIGN 4.5)."""
    burnice = _agent(1171, "Burnice")
    burnice.ex_energy_cost = 40
    db_session.add(burnice)
    await db_session.flush()

    await DimbreathResourceCostImporter(db_session).seed_resource_cost_rows()
    await db_session.refresh(burnice)
    assert burnice.ex_energy_cost == 40
