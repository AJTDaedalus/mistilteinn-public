"""Per-account caps are enforced on every path that creates rows (security audit F3).

`MAX_ARTIFACTS_PER_USER` and `MAX_ROTATIONS_PER_USER` were configured, delivered to the
container, and read by nothing — one account could fill a Postgres disk shared with another
site. Each test here sets a cap small enough to reach and asserts the request past it is a
4xx that names the limit, not a silent success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.config import Settings, get_settings
from app.services.gcsim_keys import pinned_commit
from tests.conftest import TEST_DATABASE_URL
from tests.integration.test_artifact_endpoints import _artifact, _good, _seed_sets
from tests.integration.test_optimization_runs import a_run
from tests.integration.test_rotation_library import (
    AYAKA,
    BARBARA,
    ROTATIONS,
    Party,
    _party,
    _roster,
    _step,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _capped(db_session: AsyncSession, **caps: int) -> tuple[Party, dict[str, str]]:
    """A user with a two-character team, whose app runs with *caps* in its settings."""
    characters = await _roster(db_session)
    party = await _party(db_session, characters, holding=(AYAKA, BARBARA))
    app = party.client._transport.app
    app.dependency_overrides[get_settings] = lambda: Settings(
        DATABASE_URL=TEST_DATABASE_URL, TESTING=True, **caps,
    )
    return party, characters


def _rotation_body(party: Party) -> dict:
    return {"name": "R", "team_id": party.team_id, "steps": [_step(AYAKA)]}


async def test_builds_past_the_cap_are_refused(db_session: AsyncSession):
    # The party already holds two builds.
    party, characters = await _capped(db_session, MAX_BUILDS_PER_USER=2)

    refused = await party.client.post("/api/v1/builds", json={"character_id": characters[AYAKA]})

    assert refused.status_code == 409
    assert "Build limit reached (2)" in refused.text


async def test_teams_past_the_cap_are_refused(db_session: AsyncSession):
    # The party already holds one team.
    party, _ = await _capped(db_session, MAX_TEAMS_PER_USER=1)

    build_id = (await party.client.get("/api/v1/builds")).json()["items"][0]["id"]

    refused = await party.client.post(
        "/api/v1/teams", json={"name": "Another", "build1_id": build_id},
    )

    assert refused.status_code == 409
    assert "Team limit reached (1)" in refused.text


async def test_rotations_past_the_cap_are_refused(db_session: AsyncSession):
    party, _ = await _capped(db_session, MAX_ROTATIONS_PER_USER=1)

    assert (await party.client.post(ROTATIONS, json=_rotation_body(party))).status_code == 201
    refused = await party.client.post(ROTATIONS, json=_rotation_body(party))

    assert refused.status_code == 409
    assert "Rotation limit reached (1)" in refused.text


async def test_copying_a_rotation_past_the_cap_is_refused(db_session: AsyncSession):
    author, _ = await _capped(db_session)
    created = await author.client.post(ROTATIONS, json=_rotation_body(author))
    rotation_id = created.json()["id"]
    await author.client.patch(f"{ROTATIONS}/{rotation_id}", json={"visibility": "published"})

    copier, _ = await _capped(db_session, MAX_ROTATIONS_PER_USER=1)
    assert (await copier.client.post(ROTATIONS, json=_rotation_body(copier))).status_code == 201

    refused = await copier.client.post(
        f"{ROTATIONS}/{rotation_id}/copy", json={"team_id": copier.team_id},
    )

    assert refused.status_code == 409
    assert "Rotation limit reached (1)" in refused.text


async def test_an_append_import_past_the_artifact_cap_is_refused(db_session: AsyncSession):
    party, _ = await _capped(db_session, MAX_ARTIFACTS_PER_USER=3)
    await _seed_sets(db_session)

    first = await party.client.post("/api/v1/artifacts/import/good", json={
        "mode": "append", "payload": _good(_artifact(), _artifact()),
    })
    assert first.status_code == 200, first.text

    refused = await party.client.post("/api/v1/artifacts/import/good", json={
        "mode": "append", "payload": _good(_artifact(), _artifact()),
    })

    assert refused.status_code == 409
    assert "Artifact limit reached (3)" in refused.text
    listed = await party.client.get("/api/v1/artifacts")
    assert listed.json()["total"] == 2  # nothing from the refused import was written


async def test_a_replace_import_counts_only_what_it_brings(db_session: AsyncSession):
    """A replace deletes the inventory first, so what is already held does not count."""
    party, _ = await _capped(db_session, MAX_ARTIFACTS_PER_USER=3)
    await _seed_sets(db_session)
    await party.client.post("/api/v1/artifacts/import/good", json={
        "mode": "append", "payload": _good(_artifact(), _artifact(), _artifact()),
    })

    replaced = await party.client.post("/api/v1/artifacts/import/good", json={
        "mode": "replace", "payload": _good(_artifact(), _artifact(), _artifact()),
    })
    assert replaced.status_code == 200, replaced.text

    refused = await party.client.post("/api/v1/artifacts/import/good", json={
        "mode": "replace", "payload": _good(*[_artifact() for _ in range(4)]),
    })
    assert refused.status_code == 409


def _sim_run(key: str) -> dict:
    return {
        "context_key": key, "er_bucket": 100,
        "result": {"statistics": {"dps": {"mean": 1.0}}},
    }


async def test_sim_runs_past_the_daily_cap_are_refused(db_session: AsyncSession):
    party, _ = await _capped(db_session, MAX_SIM_RUNS_PER_DAY=1)
    params = {"gcsim_pin": pinned_commit()}

    first = await party.client.post("/api/v1/sim-runs", params=params, json=_sim_run("a" * 64))
    assert first.status_code == 201, first.text

    refused = await party.client.post(
        "/api/v1/sim-runs", params=params, json=_sim_run("b" * 64),
    )
    assert refused.status_code == 429
    assert "200" not in refused.text
    assert "(1)" in refused.text

    # Re-storing a run already held writes no new row, so the cap does not apply.
    again = await party.client.post("/api/v1/sim-runs", params=params, json=_sim_run("a" * 64))
    assert again.status_code == 200, again.text


async def test_optimization_runs_past_the_cap_are_refused(db_session: AsyncSession):
    party, _ = await _capped(db_session, MAX_OPTIMIZATION_RUNS_PER_USER=1)

    assert (await party.client.post("/api/v1/optimization-runs", json=a_run())).status_code == 201
    refused = await party.client.post("/api/v1/optimization-runs", json=a_run())

    assert refused.status_code == 409
    assert "limit reached (1)" in refused.text
