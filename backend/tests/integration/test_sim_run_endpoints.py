"""D.1 — the run corpus over HTTP.

The browser computes these numbers, so every route here crosses a trust boundary. Each test
is a way the corpus could go on looking healthy while holding runs that do not describe what
their key claims — which is the dangerous shape, because a miss costs three seconds and a
wrong hit costs a wrong recommendation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.schemas.sim_run import MAX_RESULT_BYTES
from app.services.gcsim_keys import pinned_commit
from app.services.sim_context import ER_BUCKET_PERCENT, context_key, er_bucket

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

OTHER_PIN = "0" * 40

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


def _body(key: str, *, bucket: int = 180, dps: float | None = 1234.5) -> dict:
    """A submission shaped like gcsim's own output — `statistics.dps.mean` is where the
    headline number lives, read off the committed run at the pin rather than invented."""
    return {
        "context_key": key,
        "er_bucket": bucket,
        "result": {
            "statistics": {
                "dps": {"mean": dps, "min": dps, "max": dps},
                "target_aura_uptime": {"cryo": 0.71},
            },
        },
    }


async def _post(client: AsyncClient, body: dict, *, pin: str | None = None):
    return await client.post(
        "/api/v1/sim-runs", params={"gcsim_pin": pin or pinned_commit()}, json=body,
    )


# ── The write path ────────────────────────────────────────────────────────────


async def test_a_run_is_stored_and_read_back(authed_client: AsyncClient):
    key = _key()
    stored = await _post(authed_client, _body(key))
    assert stored.status_code == 201, stored.text
    assert stored.json()["created"] is True

    got = await authed_client.get(f"/api/v1/sim-runs/{key}/180")
    assert got.status_code == 200
    assert got.json()["result"]["statistics"]["target_aura_uptime"]["cryo"] == 0.71
    assert got.json()["gcsim_pin"] == pinned_commit()


async def test_resubmitting_the_same_key_replaces_and_says_so(authed_client: AsyncClient):
    """Two tabs finishing the same context run is ordinary — but a 201 would be a lie."""
    key = _key()
    first = await _post(authed_client, _body(key, dps=1000.0))
    second = await _post(authed_client, _body(key, dps=2000.0))

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert second.status_code == 200
    assert second.json()["created"] is False

    got = await authed_client.get(f"/api/v1/sim-runs/{key}/180")
    assert got.json()["dps_mean"] == 2000.0


# ── The pin ───────────────────────────────────────────────────────────────────


async def test_a_run_from_another_gcsim_is_refused(authed_client: AsyncClient):
    """A stale browser WASM build must not fill the corpus with another simulator's runs."""
    refused = await _post(authed_client, _body(_key()), pin=OTHER_PIN)
    assert refused.status_code == 409
    assert OTHER_PIN[:12] in refused.json()["detail"]
    assert pinned_commit()[:12] in refused.json()["detail"]


async def test_the_refusal_leaves_nothing_behind(authed_client: AsyncClient):
    """A 409 that had already written the row would be the worst of both.

    Note what this does *not* prove. `get_db` rolls back on any exception, so this passes
    even when the pin is checked after the write — verified by injecting that order, which
    left all fourteen tests green. It pins the outcome; the test below pins the ordering.
    """
    key = _key()
    await _post(authed_client, _body(key), pin=OTHER_PIN)
    assert (await authed_client.get(f"/api/v1/sim-runs/{key}/180")).status_code == 404


async def test_the_pin_is_checked_before_the_database_is_touched(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
):
    """The refusal must be a decision, not a write that happens to be rolled back.

    This route is one explicit `session.commit()` away from persisting a refused run, and
    that is not hypothetical: `optimizer_jobs` commits inside its handler for ordering
    reasons. A rollback nobody wrote down is a guarantee nobody is maintaining.
    """
    touched = False

    async def _explode(*args, **kwargs):
        nonlocal touched
        touched = True
        raise AssertionError("store() was reached with a foreign pin")

    monkeypatch.setattr("app.repositories.sim_run.SimRunRepository.store", _explode)
    refused = await _post(authed_client, _body(_key()), pin=OTHER_PIN)
    assert refused.status_code == 409
    assert not touched


async def test_the_pin_is_required_rather_than_defaulted(authed_client: AsyncClient):
    """Omitting it must name it, not be validated against a default nobody chose."""
    response = await authed_client.post("/api/v1/sim-runs", json=_body(_key()))
    assert response.status_code == 422
    assert "gcsim_pin" in response.text


# ── Bucketing ─────────────────────────────────────────────────────────────────


async def test_an_unbucketed_er_value_is_refused(authed_client: AsyncClient):
    """179 is not a bucket boundary, so no reader would ever generate that key.

    Storing it would fill a cache the writer cannot hit, and the miss would look like a cold
    context rather than a bug.
    """
    off_boundary = 180 - 1
    assert off_boundary % ER_BUCKET_PERCENT != 0
    response = await _post(authed_client, _body(_key(), bucket=off_boundary))
    assert response.status_code == 422
    assert "er_bucket" in response.text


async def test_the_boundary_the_bucketer_produces_is_accepted(authed_client: AsyncClient):
    """Whatever `er_bucket()` returns must pass — otherwise the two disagree."""
    bucket = er_bucket(1.79)
    assert bucket == 175
    assert (await _post(authed_client, _body(_key(), bucket=bucket))).status_code == 201


async def test_a_context_key_that_is_not_a_digest_is_refused(authed_client: AsyncClient):
    response = await _post(authed_client, {**_body(_key()), "context_key": "not-a-digest"})
    assert response.status_code == 422


async def test_an_oversized_result_is_refused(authed_client: AsyncClient):
    """The corpus is a cache, not storage the client can point at."""
    body = _body(_key())
    body["result"] = {"log": "x" * (MAX_RESULT_BYTES + 1)}
    assert (await _post(authed_client, body)).status_code == 422


async def test_the_headline_dps_is_derived_from_the_run_not_submitted(
    authed_client: AsyncClient,
):
    """A client cannot claim a mean that disagrees with the run it summarises.

    There is no `dps_mean` field to send. Sending one is ignored rather than believed —
    the stored figure comes from `statistics.dps.mean` in the payload itself.
    """
    key = _key()
    body = _body(key, dps=1000.0)
    body["dps_mean"] = 999_999.0  # a client trying to inflate its own headline number

    await _post(authed_client, body)
    assert (await authed_client.get(f"/api/v1/sim-runs/{key}/180")).json()["dps_mean"] == 1000.0


async def test_a_run_with_no_dps_is_cached_with_none(authed_client: AsyncClient):
    """A context run wanted for uptimes and energy is still worth caching.

    None rather than zero: "no DPS reported" and "a DPS of zero" are different claims.
    """
    key = _key()
    body = _body(key)
    body["result"] = {"statistics": {"target_aura_uptime": {"cryo": 0.71}}}

    assert (await _post(authed_client, body)).status_code == 201
    assert (await authed_client.get(f"/api/v1/sim-runs/{key}/180")).json()["dps_mean"] is None


# ── Coverage, and the stated miss ─────────────────────────────────────────────


async def test_coverage_reports_the_buckets_a_search_already_has(authed_client: AsyncClient):
    key = _key()
    for bucket in (170, 180, 175):
        await _post(authed_client, _body(key, bucket=bucket, dps=float(bucket)))

    coverage = await authed_client.get("/api/v1/sim-runs", params={"context_key": key})
    assert coverage.status_code == 200
    body = coverage.json()
    assert body["er_buckets"] == [170, 175, 180], "buckets must come back ascending"
    assert body["dps_means"] == [170.0, 175.0, 180.0], "dps must align with its bucket"
    assert body["gcsim_pin"] == pinned_commit()


async def test_a_cold_context_reports_no_buckets_rather_than_404(authed_client: AsyncClient):
    """Empty is the ordinary state of a corpus that fills on demand."""
    coverage = await authed_client.get(
        "/api/v1/sim-runs", params={"context_key": _key(rotation=["nothing"])},
    )
    assert coverage.status_code == 200
    assert coverage.json()["er_buckets"] == []


async def test_a_missing_bucket_is_a_404_naming_it(authed_client: AsyncClient):
    """D.3's stated outcome: the caller must simulate, never substitute a neighbour."""
    key = _key()
    await _post(authed_client, _body(key, bucket=180))
    missing = await authed_client.get(f"/api/v1/sim-runs/{key}/100")
    assert missing.status_code == 404
    assert "100" in missing.json()["detail"]


async def test_reading_an_unbucketed_value_is_refused_rather_than_missing_forever(
    authed_client: AsyncClient,
):
    """The reader must refuse what the writer refuses, or the caller loops.

    Ask for 179, miss; simulate; store under 175; ask for 179 again, miss again. A 404 here
    would be an infinite cold context that never once looks like a bug.
    """
    response = await authed_client.get(f"/api/v1/sim-runs/{_key()}/179")
    assert response.status_code == 422
    assert str(ER_BUCKET_PERCENT) in response.json()["detail"]


async def test_coverage_does_not_leak_another_context(authed_client: AsyncClient):
    """The whole point of the key is that a different build is a different context."""
    await _post(authed_client, _body(_key()))
    other = _key(constellation=6)
    assert other != _key()
    coverage = await authed_client.get("/api/v1/sim-runs", params={"context_key": other})
    assert coverage.json()["er_buckets"] == []


# ── Ownership ─────────────────────────────────────────────────────────────────


async def test_the_corpus_requires_auth(client: AsyncClient):
    """Rows are owner-scoped; an anonymous write would have no owner to be scoped to."""
    coverage = await client.get("/api/v1/sim-runs", params={"context_key": _key()})
    assert coverage.status_code == 401
    assert (await _post(client, _body(_key()))).status_code == 401
