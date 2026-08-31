"""Beta content must not reach the database.

**Owner ruling, 2026-08-31:** *"New builds are usually for the beta characters, which are out
of scope and should be hidden in our app so we don't get in trouble… Including beta weapons,
sets, and enemies."*

nanoka's `latest` is a datamine patch: at 7.0.53 it carried **2 characters, 8 weapons and 1
enemy** that the game had not released, and this repo was importing all of them. The manifest
names them in `gi.new`, which was verified against both indexes to be exactly `latest - live`
for all four entities.

Excluded at the importer rather than filtered in the API, so an unreleased row is never written
in the first place — a filter someone can forget to apply on a new endpoint is not a guarantee.
"""

from __future__ import annotations

import json

import pytest

from app.data.importers.nanoka_gi_importer import NanokaGIImporter
from app.models.artifact import ArtifactSet
from tests.unit.nanoka_transport import FIXTURE_DIR, FixtureTransport


@pytest.mark.asyncio
async def test_a_set_named_in_gi_new_is_not_imported(db_session) -> None:
    index = load_fixture_index("artifact")
    held, kept = sorted(index)[0], sorted(index)[1]
    transport = FixtureTransport(
        indexes={"artifact": index},
        details={("artifact", key): _detail(key) for key in (held, kept)},
        unreleased={"artifact": [int(held)]},
    )

    result = await NanokaGIImporter(db_session, transport=transport)._run_pass(
        "artifact", ArtifactSet, _stub_mapper(db_session),
    )

    assert result.unreleased == [held]
    # **`total` stays the whole index.** It is what `verify_seed` compares against the
    # committed index to detect "the database is from a different patch", and a deliberate
    # exclusion must not trip that detector. The held id is counted beside it, not inside it.
    assert result.total == len(index)
    assert result.unreleased
    assert result.imported < result.total
    # The point of excluding at the importer: it is never even fetched.
    assert ("detail", "artifact", held) not in transport.calls


@pytest.mark.asyncio
async def test_a_travelers_variants_are_all_held_when_the_body_is(db_session) -> None:
    """`gi.new` names bare ids; the character index keys Travelers `10000005-2` … `-8`.

    Matching on the whole key would hold back none of the seven, which is the direction that
    ships unreleased content.
    """
    index = load_fixture_index("character")
    traveler = [key for key in index if key.startswith("10000005-")]
    assert len(traveler) > 1, "the fixture must actually carry Traveler variants"

    transport = FixtureTransport(
        indexes={"character": index}, unreleased={"character": [10000005]},
    )
    importer = NanokaGIImporter(db_session, transport=transport)

    held = await importer._unreleased("character")

    assert all(key.split("-")[0] in held for key in traveler)


@pytest.mark.asyncio
async def test_nothing_is_held_back_when_the_manifest_names_none(db_session) -> None:
    """The pre-existing behaviour, kept: an absent `gi.new` is not an empty seed."""
    transport = FixtureTransport(indexes={"artifact": {}})
    importer = NanokaGIImporter(db_session, transport=transport)

    assert await importer._unreleased("artifact") == frozenset()


def load_fixture_index(entity: str) -> dict:
    """The committed index for one entity, as the importer would receive it."""
    with (FIXTURE_DIR / f"{entity}.json").open() as handle:
        return json.load(handle)


def _detail(key: str) -> dict:
    return {"affix": [{"name": f"set {key}", "level": 0}], "need": [2], "rank": [5]}


def _stub_mapper(_session):
    async def mapper(_key: str, _payload: dict) -> bool:
        return True
    return mapper
