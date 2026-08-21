"""D.7 — `scripts/seed_db`'s orchestration and its provenance row.

The passes themselves are tested per entity; what is under test here is the wrapper: that a
provenance row is written before the work and completed after it, that the counts land in
it, and — the part that matters most — that a failed pass produces a **non-zero exit** and a
row that says `succeeded = False`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.character import Character
from app.models.seed_provenance import SeedRun
from scripts.seed_db import PASSES, run_passes
from tests.unit.nanoka_transport import FixtureTransport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"


def _transport(fail: set[tuple[str, str]] | None = None) -> FixtureTransport:
    """A one-entry index per entity, served from the committed detail payloads."""
    keys = {
        "character": "10000002",
        "weapon": "11501",
        "artifact": "15025",
        "monster": "21010101",
    }
    details = {}
    for entity, key in keys.items():
        name = f"{entity}_{key}"
        details[entity, key] = json.loads((_FIX / f"{name}.json").read_text())
    return FixtureTransport(
        indexes={entity: {key: {}} for entity, key in keys.items()},
        details=details,
        fail=fail,
    )


async def test_a_full_run_records_every_pass_in_one_provenance_row(db_session: AsyncSession):
    importer = NanokaGIImporter(db_session, transport=_transport())

    run, counts, ok = await run_passes(db_session, importer, list(PASSES), commit=False)

    assert ok is True
    assert run.succeeded is True
    assert run.version == "7.0.51"
    assert run.finished_at >= run.started_at
    assert sorted(counts) == ["artifact", "character", "monster", "weapon"]
    assert counts["character"] == {
        "total": 1, "imported": 1, "skipped": 0, "pruned": 0, "failed": [],
    }
    assert await db_session.scalar(select(func.count()).select_from(SeedRun)) == 1


async def test_only_the_requested_passes_run(db_session: AsyncSession):
    importer = NanokaGIImporter(db_session, transport=_transport())

    _run, counts, _ok = await run_passes(db_session, importer, ["character"], commit=False)

    assert list(counts) == ["character"]
    assert await db_session.scalar(select(func.count()).select_from(Character)) == 1


async def test_the_row_exists_before_the_passes_finish(db_session: AsyncSession):
    """A run that dies mid-seed must still leave a row naming the version it was part way
    through — otherwise a half-seeded database is indistinguishable from a complete one."""
    importer = NanokaGIImporter(db_session, transport=_transport())
    seen: list[bool] = []

    original = importer.import_weapons

    async def spy() -> int:
        row = await db_session.scalar(select(SeedRun))
        seen.append(row is not None and row.succeeded is False)
        return await original()

    importer.import_weapons = spy
    await run_passes(db_session, importer, ["weapon"], commit=False)

    assert seen == [True]


async def test_a_failed_pass_is_reported_rather_than_reported_as_success(
    db_session: AsyncSession,
):
    """The whole point of the exit code: a seed that fails must not look like one that worked."""
    importer = NanokaGIImporter(
        db_session, transport=_transport(fail={("character", "10000002")}),
    )

    run, counts, ok = await run_passes(db_session, importer, list(PASSES), commit=False)

    assert ok is False
    assert run.succeeded is False
    assert counts["character"]["failed"] == ["10000002"]
    # The other three passes still ran — one bad payload is not a reason to seed nothing.
    assert counts["weapon"]["imported"] == 1
    assert counts["artifact"]["imported"] == 1


async def test_every_entity_has_a_pass_wired_to_it():
    """A new entity added to ENTITIES without a pass would silently never be seeded."""
    from app.data.importers.nanoka_gi_importer import ENTITIES

    assert list(PASSES) == list(ENTITIES)
    assert all(hasattr(NanokaGIImporter, method) for method in PASSES.values())
