"""Task 4 end to end: the kit numbers reach the database and the API equal to the payloads.

The mapping is pinned offline in `tests/unit/test_nanoka_gi_kit_numbers.py`. What needs a
database is that the importer writes the rows, rebuilds them on a re-import rather than
doubling them, and that `GET /characters/{id}` serves them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.character import (
    AscensionPassive,
    Character,
    CharacterAttack,
    CharacterEnergyDrop,
    Constellation,
)
from tests.unit.nanoka_transport import FixtureTransport

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"
_KEYS = sorted(path.stem.removeprefix("character_") for path in _FIX.glob("character_*.json"))


def _payload(key: str) -> dict:
    return json.loads((_FIX / f"character_{key}.json").read_text())


def _transport() -> FixtureTransport:
    return FixtureTransport(
        indexes={"character": {key: {} for key in _KEYS}},
        details={("character", key): _payload(key) for key in _KEYS},
    )


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def _kit_counts(db: AsyncSession) -> tuple[int, int]:
    return await _count(db, CharacterAttack), await _count(db, CharacterEnergyDrop)


async def _id(db: AsyncSession, key: str) -> str:
    return await db.scalar(select(Character.id).where(Character.nanoka_id == key))


@pytest.mark.parametrize("key", _KEYS)
async def test_the_database_holds_the_payloads_numbers(db_session: AsyncSession, key: str):
    await NanokaGIImporter(db_session, transport=_transport()).import_characters()
    payload = _payload(key)
    character_id = await _id(db_session, key)

    passives = (await db_session.scalars(
        select(AscensionPassive).where(AscensionPassive.character_id == character_id),
    )).all()
    by_id = {p.nanoka_id: p.param_list for p in passives}
    assert by_id == {entry["id"]: entry["param_list"] for entry in payload["passives"]}

    constellations = (await db_session.scalars(
        select(Constellation).where(Constellation.character_id == character_id)
        .order_by(Constellation.position),
    )).all()
    assert [c.param_list for c in constellations] == [
        entry["param_list"] for entry in payload["constellations"]
    ]

    attacks = (await db_session.scalars(
        select(CharacterAttack).where(CharacterAttack.character_id == character_id)
        .order_by(CharacterAttack.position),
    )).all()
    assert [(a.name, a.element, a.gauge, a.damage_param) for a in attacks] == [
        (e["name"], e["element"], e["gauge"], e["damage_param"]) for e in payload["attack"]
    ]

    drops = (await db_session.scalars(
        select(CharacterEnergyDrop).where(CharacterEnergyDrop.character_id == character_id)
        .order_by(CharacterEnergyDrop.position),
    )).all()
    assert [(d.skill, d.per_drop, d.chance, d.cd) for d in drops] == [
        (e["skill"], e["per_drop"], e["chance"], e["cd"]) for e in payload["energy"]
    ]


async def test_a_second_import_replaces_the_rows_rather_than_doubling_them(
    db_session: AsyncSession,
):
    await NanokaGIImporter(db_session, transport=_transport()).import_characters()
    first = await _kit_counts(db_session)
    await NanokaGIImporter(db_session, transport=_transport()).import_characters()
    second = await _kit_counts(db_session)

    assert first == second == (14 + 42 + 59 + 10, 2 + 2 + 2 + 1)


async def test_the_character_detail_serves_them(client: AsyncClient, db_session: AsyncSession):
    await NanokaGIImporter(db_session, transport=_transport()).import_characters()
    await db_session.commit()
    payload = _payload("10000002")

    body = (await client.get("/api/v1/characters/10000002")).json()

    assert [p["param_list"] for p in body["ascension_passives"]] == [
        e["param_list"] for e in sorted(payload["passives"], key=lambda e: (e["unlock"], e["id"]))
    ]
    assert body["constellations"][0]["param_list"] == payload["constellations"][0]["param_list"]
    assert len(body["attacks"]) == len(payload["attack"])
    assert body["attacks"][4]["element"] == payload["attack"][4]["element"]
    assert body["energy_drops"][0]["per_drop"] == payload["energy"][0]["per_drop"]
    assert body["energy_drops"][0]["chance"] == 50.0  # a percent, as published
