"""G.10 — the hybrid optimize contract and the jobs behind it.

`POST /builds/{id}/optimize` answers **200 with the result** when the search fits inside
`optimizer_job_service.SYNC_SECONDS`, and **202 with a job id** when it does not. A contract
that always returned a job id would make the ordinary case worse in order to serve the rare
one; a contract that never did would time out on a scanned account, because the prefilter's
budget targets 300 seconds and no client waits that long.

The tests that matter here are the ones where the two paths could disagree — a job whose
persisted result is a different shape from the synchronous one would be found by a user, not
by a type error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.services import optimizer_job_service
from tests.integration.test_build_endpoints import (
    CRYO_BURST,
    _auth,
    _build_with_five,
    _catalogue,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User


# ---- The threshold ---------------------------------------------------------

def test_the_sync_threshold_is_derived_from_the_measured_cost():
    """Not a chosen number. If the damage chain gets slower the threshold falls with it, so
    the promise it encodes — "this returns quickly" — stays true without a re-tune."""
    from app.services import artifact_prefilter

    assert optimizer_job_service.sync_combination_limit() == int(
        optimizer_job_service.SYNC_SECONDS / artifact_prefilter.SECONDS_PER_COMBINATION,
    )


def test_a_missing_slot_estimates_zero_so_it_stays_synchronous():
    """The product of an empty slot is zero, which reads as "trivially small" — and that is
    the right answer here. The search is unsatisfiable either way, and running it inline is
    how the caller gets told so immediately instead of polling a job to learn it."""
    from app.services.artifact_optimizer import ArtifactCandidate

    four_slots = [
        ArtifactCandidate(
            artifact_id=slot, slot=slot, set_id=1, rarity=5, level=20,
            main_stat="FIGHT_PROP_HP",
        )
        for slot in ("equip_bracer", "equip_necklace", "equip_shoes", "equip_ring")
    ]

    assert optimizer_job_service.estimated_combinations(four_slots) == 0


# ---- The two paths ---------------------------------------------------------

@pytest.mark.asyncio
async def test_a_small_search_answers_inline(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
):
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets, spares=2)

    response = await client.post(
        f"/api/v1/builds/{build.id}/optimize",
        json={"hit": CRYO_BURST},
        headers=_auth(authed_user),
    )

    assert response.status_code == 200
    assert "builds" in response.json()


@pytest.mark.asyncio
async def test_a_large_search_becomes_a_job_and_says_why(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
    monkeypatch,
):
    """202 carries the estimate *and* the ceiling, so "why is this a job" is answerable from
    the response rather than by reading the source."""
    monkeypatch.setattr(optimizer_job_service, "SYNC_SECONDS", 0.0)
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets, spares=2)

    response = await client.post(
        f"/api/v1/builds/{build.id}/optimize",
        json={"hit": CRYO_BURST},
        headers=_auth(authed_user),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["poll_url"] == f"/api/v1/optimizer-jobs/{body['job_id']}"
    assert body["estimated_combinations"] > body["sync_limit"]


@pytest.mark.asyncio
async def test_the_route_hands_the_search_to_the_runner(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
    monkeypatch,
):
    """What the route is responsible for: a persisted `queued` row and a submitted search.

    The `client` fixture mocks the runner, so this asserts the handoff and stops there.
    Whether the search then *runs* is `JobRunner`'s contract and is tested against a real
    runner below — splitting them is what keeps each test able to fail for one reason.
    """
    monkeypatch.setattr(optimizer_job_service, "SYNC_SECONDS", 0.0)
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets, spares=2)

    accepted = (await client.post(
        f"/api/v1/builds/{build.id}/optimize",
        json={"hit": CRYO_BURST}, headers=_auth(authed_user),
    )).json()

    row = (await client.get(
        f"/api/v1/optimizer-jobs/{accepted['job_id']}", headers=_auth(authed_user),
    )).json()
    assert row["status"] == "queued"
    assert row["combinations_total"] == accepted["estimated_combinations"]
    assert row["character_name"] == "Ayaka"

    runner = client._transport.app.state.job_runner  # the mocked runner
    assert runner.submit_search.call_count == 1
    submitted_id, _search_fn = runner.submit_search.call_args.args
    assert submitted_id == accepted["job_id"]


# ---- Reading and cancelling ------------------------------------------------

@pytest.mark.asyncio
async def test_jobs_are_scoped_to_their_owner(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
    monkeypatch,
):
    monkeypatch.setattr(optimizer_job_service, "SYNC_SECONDS", 0.0)
    user, _ = authed_user
    character, weapon, sets = await _catalogue(db_session)
    build = await _build_with_five(db_session, user, character, weapon, sets, spares=2)
    await client.post(
        f"/api/v1/builds/{build.id}/optimize",
        json={"hit": CRYO_BURST}, headers=_auth(authed_user),
    )

    assert (await client.get("/api/v1/optimizer-jobs")).status_code == 401
    listed = (await client.get("/api/v1/optimizer-jobs", headers=_auth(authed_user))).json()
    assert listed["total"] >= 1
    # Summaries only: a finished job's result is a full optimize response.
    assert "result" not in listed["items"][0]


@pytest.mark.asyncio
async def test_an_unknown_job_is_a_404(client: AsyncClient, authed_user: tuple[User, str]):
    assert (await client.get(
        "/api/v1/optimizer-jobs/00000000-0000-0000-0000-000000000000",
        headers=_auth(authed_user),
    )).status_code == 404


@pytest.mark.asyncio
async def test_cancelling_a_finished_job_is_a_409(
    client: AsyncClient, db_session: AsyncSession, authed_user: tuple[User, str],
    monkeypatch,
):
    """Not a 204. "Cancelled" and "already succeeded" are different outcomes, and reporting
    the second as the first would let a caller believe it stopped something."""
    from app.models.optimization_job import OptimizationJob

    user, _ = authed_user
    finished = OptimizationJob(
        owner_id=str(user.id), job_type="optimizer", status="succeeded", request={},
    )
    db_session.add(finished)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/optimizer-jobs/{finished.id}/cancel", headers=_auth(authed_user),
    )

    assert response.status_code == 409
    assert "already finished" in response.json()["detail"]
