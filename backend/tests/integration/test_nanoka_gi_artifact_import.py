"""D.5 — the artifact-set pass end to end."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.artifact import ArtifactSet, ArtifactSetAffix
from tests.unit.nanoka_transport import FixtureTransport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nanoka_gi" / "detail"

_PRAYERS = {
    "id": 15009,
    "need": [1],
    "rank": [4],
    "icon": "UI_RelicIcon_15009_3",
    "affix": [
        {
            "level": 0,
            "name": "Prayers for Illumination",
            "desc": "Decreases opponents' Pyro RES.",
            "add_props": [],
            "param_list": [0.12],
        },
    ],
}


def _deepwood() -> dict:
    return json.loads((_FIX / "artifact_15025.json").read_text())


def _transport(payloads: dict[str, dict]) -> FixtureTransport:
    return FixtureTransport(
        indexes={"artifact": {key: {} for key in payloads}},
        details={("artifact", key): payload for key, payload in payloads.items()},
    )


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_the_pass_imports_a_set_and_its_affixes(db_session: AsyncSession):
    importer = NanokaGIImporter(db_session, transport=_transport({"15025": _deepwood()}))

    imported = await importer.import_artifact_sets()

    assert imported == 1
    artifact_set = await db_session.scalar(select(ArtifactSet))
    assert artifact_set.name == "Deepwood Memories"
    assert artifact_set.piece_thresholds == [2, 4]
    await db_session.refresh(artifact_set, ["affixes"])
    assert [affix.pieces_required for affix in artifact_set.affixes] == [2, 4]


async def test_a_one_piece_set_keeps_its_single_threshold(db_session: AsyncSession):
    """A model hardcoding 2pc/4pc gets the five "Prayers" circlets wrong (C.5)."""
    importer = NanokaGIImporter(db_session, transport=_transport({"15009": _PRAYERS}))

    await importer.import_artifact_sets()

    artifact_set = await db_session.scalar(select(ArtifactSet))
    assert artifact_set.piece_thresholds == [1]
    assert await _count(db_session, ArtifactSetAffix) == 1


async def test_a_second_run_is_a_no_op(db_session: AsyncSession):
    payloads = {"15025": _deepwood(), "15009": _PRAYERS}
    for _ in range(2):
        await NanokaGIImporter(
            db_session, transport=_transport(payloads),
        ).import_artifact_sets()

    assert await _count(db_session, ArtifactSet) == 2
    assert await _count(db_session, ArtifactSetAffix) == 3


async def test_a_reworked_set_leaves_no_orphaned_affixes(db_session: AsyncSession):
    await NanokaGIImporter(
        db_session, transport=_transport({"15025": _deepwood()}),
    ).import_artifact_sets()

    trimmed = copy.deepcopy(_deepwood())
    trimmed["affix"] = trimmed["affix"][:1]
    trimmed["need"] = [2]
    await NanokaGIImporter(
        db_session, transport=_transport({"15025": trimmed}),
    ).import_artifact_sets()

    assert await _count(db_session, ArtifactSetAffix) == 1


async def test_a_set_that_leaves_the_index_is_pruned(db_session: AsyncSession):
    await NanokaGIImporter(
        db_session, transport=_transport({"15025": _deepwood(), "15009": _PRAYERS}),
    ).import_artifact_sets()

    importer = NanokaGIImporter(db_session, transport=_transport({"15025": _deepwood()}))
    await importer.import_artifact_sets()

    assert await _count(db_session, ArtifactSet) == 1
    assert importer.results[-1].pruned == 1
    assert await _count(db_session, ArtifactSetAffix) == 2
