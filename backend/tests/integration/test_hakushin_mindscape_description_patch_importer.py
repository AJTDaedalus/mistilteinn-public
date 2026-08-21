"""Integration tests for HakushinMindscapeDescriptionPatchImporter (Task 29)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy import select

from app.data.importers.hakushin_mindscape_description_patch_importer import (
    RAW_BASE_URL,
    HakushinMindscapeDescriptionPatchImporter,
)
from app.models.agent import Agent, Mindscape
from app.models.enums import Element, Rarity, Specialty

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_VELINA_FIXTURE = {
    "Talent": {
        "1": {
            "Level": 1,
            "Name": "Orderly Elegance",
            "Desc": "Velina ignores 20% of the target's <color=#FFFFFF>All-Attribute RES</color>.",
        },
        "2": {
            "Level": 2,
            "Name": "Saturation Project",
            "Desc": "L2 text.",
        },
    }
}


def _agent(hakushin_id: int, name: str) -> Agent:
    return Agent(
        hakushin_id=hakushin_id,
        name=name,
        element=Element.ETHER,
        specialty=Specialty.SUPPORT,
        rarity=Rarity.S,
    )


def _mindscape(agent: Agent, level: int, name: str, description: str) -> Mindscape:
    return Mindscape(
        agent_id=agent.id,
        level=level,
        name=name,
        description=description,
    )


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_patches_blank_rows_from_mirror(db_session: AsyncSession) -> None:
    agent = _agent(1561, "Velina")
    db_session.add(agent)
    await db_session.flush()
    db_session.add_all(
        [
            _mindscape(agent, 1, "Orderly Elegance", ""),
            _mindscape(agent, 2, "Saturation Project", ""),
        ]
    )
    await db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == f"{RAW_BASE_URL}/character/1561.json"
        return httpx.Response(200, json=_VELINA_FIXTURE)

    importer = HakushinMindscapeDescriptionPatchImporter(db_session, client=_mock_client(handler))
    patched = await importer.patch_blank_mindscape_descriptions()
    assert patched == 2

    rows = (
        (
            await db_session.execute(
                select(Mindscape).where(Mindscape.agent_id == agent.id).order_by(Mindscape.level)
            )
        )
        .scalars()
        .all()
    )
    assert rows[0].description == "Velina ignores 20% of the target's All-Attribute RES."
    assert rows[1].description == "L2 text."


@pytest.mark.asyncio
async def test_does_not_touch_populated_rows(db_session: AsyncSession) -> None:
    agent = _agent(1561, "Velina")
    db_session.add(agent)
    await db_session.flush()
    db_session.add(_mindscape(agent, 1, "Orderly Elegance", "Already has real text."))
    await db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not fetch when nothing is blank")

    importer = HakushinMindscapeDescriptionPatchImporter(db_session, client=_mock_client(handler))
    patched = await importer.patch_blank_mindscape_descriptions()
    assert patched == 0

    row = (
        await db_session.execute(select(Mindscape).where(Mindscape.agent_id == agent.id))
    ).scalar_one()
    assert row.description == "Already has real text."


@pytest.mark.asyncio
async def test_leaves_row_blank_when_mirror_also_blank(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    agent = _agent(1571, "Norma")
    db_session.add(agent)
    await db_session.flush()
    db_session.add(_mindscape(agent, 1, "Visionary Extremism", ""))
    await db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        blank_talent = {"Talent": {"x": {"Level": 1, "Desc": ""}}}
        return httpx.Response(200, json=blank_talent)

    import logging

    logger_name = "app.data.importers.hakushin_mindscape_description_patch_importer"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        importer = HakushinMindscapeDescriptionPatchImporter(
            db_session, client=_mock_client(handler)
        )
        patched = await importer.patch_blank_mindscape_descriptions()

    assert patched == 0
    assert any("also blank" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_warns_and_continues_on_fetch_failure(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    agent = _agent(9999, "Unknown")
    db_session.add(agent)
    await db_session.flush()
    db_session.add(_mindscape(agent, 1, "Unknown M1", ""))
    await db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    import logging

    logger_name = "app.data.importers.hakushin_mindscape_description_patch_importer"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        importer = HakushinMindscapeDescriptionPatchImporter(
            db_session, client=_mock_client(handler)
        )
        patched = await importer.patch_blank_mindscape_descriptions()

    assert patched == 0
    assert any("fetch failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_no_blank_rows_short_circuits_without_fetch(db_session: AsyncSession) -> None:
    agent = _agent(1561, "Velina")
    db_session.add(agent)
    await db_session.flush()
    db_session.add(_mindscape(agent, 1, "Orderly Elegance", "Real text already here."))
    await db_session.flush()

    importer = HakushinMindscapeDescriptionPatchImporter(db_session, client=None)
    patched = await importer.patch_blank_mindscape_descriptions()
    assert patched == 0


@pytest.mark.asyncio
async def test_json_serializable_fixture_sanity() -> None:
    # Guards the literal fixture above against accidental non-JSON content.
    json.dumps(_VELINA_FIXTURE)
