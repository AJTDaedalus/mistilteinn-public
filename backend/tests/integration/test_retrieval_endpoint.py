"""D.3 — "no retrievable neighbour" as a stated outcome, never a silent fallback.

DESIGN §3.5:

> A search can still arrive with no cached context. That must be a stated outcome, not a
> silent fallback: simulate it now (a second or two), or say so. It must never be to retrieve
> a distant neighbour and report its score as though it were close.

Every test here is about the *second* sentence. The first is easy — returning nothing is not
hard. What is hard is returning nothing in a shape a caller cannot accidentally ignore, and
never returning something that merely looks close.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from app.services.gcsim_keys import pinned_commit
from app.services.sim_context import ER_BUCKET_PERCENT, context_key
from app.services.sim_retrieval import MAX_NEIGHBOUR_BUCKETS

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

RETRIEVE = "/api/v1/sim-runs/retrieve"

_CONTEXT = {
    "character_key": "kamisatoayaka",
    "weapon_key": "mistsplitterreforged",
    "character_level": 90,
    "constellation": 0,
    "weapon_level": 90,
    "refinement": 1,
    "talent_levels": {"normal_attack": 9, "elemental_skill": 9, "elemental_burst": 9},
    "rotation": ["burst", "skill", "attack:3"],
    "target": {"lvl": 90, "resist": 0.1},
}


def _key(**overrides) -> str:
    return context_key(**{**_CONTEXT, "gcsim_pin": pinned_commit(), **overrides})


async def _cache(client: AsyncClient, key: str, bucket: int, dps: float) -> None:
    response = await client.post(
        "/api/v1/sim-runs",
        params={"gcsim_pin": pinned_commit()},
        json={
            "context_key": key,
            "er_bucket": bucket,
            "result": {"statistics": {"iterations": 50, "dps": {"mean": dps, "sd": 0.0}}},
        },
    )
    assert response.status_code in (200, 201), response.text


async def _get(client: AsyncClient, key: str, er: float):
    return await client.get(RETRIEVE, params={"context_key": key, "energy_recharge": er})


# ── The stated absence ────────────────────────────────────────────────────────


async def test_a_cold_context_is_a_200_that_says_so(authed_client: AsyncClient):
    """Not a 404. An error invites a retry, or a caught exception and carrying on regardless.

    The second of those is the silent fallback this task exists to forbid — and it is the one
    that would never show up in a log.
    """
    response = await _get(authed_client, _key(), 1.80)
    assert response.status_code == 200
    body = response.json()
    assert body["retrieved"] is None
    assert body["not_retrieved_because"] == "cold"
    assert body["requested_bucket"] == 180
    assert "180" in body["detail"], "the caller is told which bucket to simulate"


async def test_a_distant_neighbour_is_refused_and_named(authed_client: AsyncClient):
    """A run four buckets away describes a different part of the ER curve."""
    key = _key()
    await _cache(authed_client, key, 160, 1000.0)

    body = (await _get(authed_client, key, 1.80)).json()
    assert body["retrieved"] is None
    assert body["not_retrieved_because"] == "too_far"
    assert "160" in body["detail"], "the caller is told what was there"
    assert "180" in body["detail"], "and what to simulate instead"


async def test_the_two_absences_are_distinguished(authed_client: AsyncClient):
    """They call for different work: simulate the set, or simulate this one bucket.

    Collapsing them into one "not found" would leave the caller guessing how much it is in
    for, which is the difference between a stated outcome and a shrug.
    """
    cold = (await _get(authed_client, _key(rotation=["nothing"]), 1.80)).json()
    key = _key()
    await _cache(authed_client, key, 160, 1000.0)
    far = (await _get(authed_client, key, 1.80)).json()

    assert cold["not_retrieved_because"] != far["not_retrieved_because"]


async def test_a_refusal_never_carries_a_run(authed_client: AsyncClient):
    """The one thing that must never happen: a distant run reported as though it were close."""
    key = _key()
    await _cache(authed_client, key, 100, 9999.0)
    body = (await _get(authed_client, key, 1.80)).json()
    assert body["retrieved"] is None
    assert "9999" not in json.dumps(body), "the refused run must not leak into the response"


# ── The retrieval, and what it says about itself ──────────────────────────────


async def test_an_exact_bucket_is_retrieved_and_still_reports_a_divergence(
    authed_client: AsyncClient,
):
    """RESEARCH_er_bucketing §1 — the key matched; the answer is still an approximation."""
    key = _key()
    await _cache(authed_client, key, 180, 100.0)
    await _cache(authed_client, key, 185, 113.0)

    body = (await _get(authed_client, key, 1.82)).json()
    assert body["not_retrieved_because"] is None
    got = body["retrieved"]
    assert got["is_exact_bucket"] is True
    assert got["bucket_distance"] == 0
    assert got["divergence"]["reference_bucket"] == 185
    assert got["divergence"]["dps_delta_pct"] == pytest.approx(13.0)


async def test_a_neighbour_is_retrieved_and_labelled_as_one(authed_client: AsyncClient):
    key = _key()
    await _cache(authed_client, key, 180 - ER_BUCKET_PERCENT, 100.0)

    got = (await _get(authed_client, key, 1.80)).json()["retrieved"]
    assert got["is_exact_bucket"] is False
    assert got["bucket_distance"] == MAX_NEIGHBOUR_BUCKETS


async def test_a_lone_run_retrieves_with_a_null_divergence(authed_client: AsyncClient):
    """Absent, not zero. Merging them is how an approximation stops reporting its error."""
    key = _key()
    await _cache(authed_client, key, 180, 100.0)

    got = (await _get(authed_client, key, 1.80)).json()["retrieved"]
    assert got["run"]["er_bucket"] == 180
    assert got["divergence"] is None


async def test_the_outcome_names_the_pin_it_searched(authed_client: AsyncClient):
    """A retrieval from another simulator would be the worst kind of hit."""
    body = (await _get(authed_client, _key(), 1.80)).json()
    assert body["gcsim_pin"] == pinned_commit()


async def test_another_context_is_not_retrieved(authed_client: AsyncClient):
    key = _key()
    await _cache(authed_client, key, 180, 100.0)
    other = (await _get(authed_client, _key(constellation=6), 1.80)).json()
    assert other["retrieved"] is None
    assert other["not_retrieved_because"] == "cold"


async def test_energy_recharge_is_a_fraction_and_a_percent_is_refused(
    authed_client: AsyncClient,
):
    """`1.8` is 180 %. A caller sending `180` must be told, not quietly given a cold context.

    Without the ceiling it buckets at 18000, misses every time, and reports `cold` forever —
    the same shape as the unbucketed read D.1's review caught, from the other direction.
    """
    key = _key()
    await _cache(authed_client, key, 180, 100.0)

    assert (await _get(authed_client, key, 1.80)).json()["retrieved"] is not None
    assert (await _get(authed_client, key, 180.0)).status_code == 422


async def test_retrieval_requires_auth(client: AsyncClient):
    assert (await _get(client, _key(), 1.80)).status_code == 401


async def test_retrieve_is_not_swallowed_by_the_context_key_route(authed_client: AsyncClient):
    """`/{context_key}/{er_bucket}` is two segments and this is one — but route order is the
    kind of thing that regresses silently, and a 404 here would be baffling."""
    assert (await _get(authed_client, _key(), 1.80)).status_code == 200
