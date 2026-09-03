"""Saved, shareable optimization runs — `TASKS_account_tracking.md` Track 2."""
from __future__ import annotations

from httpx import AsyncClient  # noqa: TC002 — a fixture type, resolved at runtime

RUNS = "/api/v1/optimization-runs"


def a_run(**over) -> dict:
    base = {
        "name": "Skirk melt",
        "objective": {"artifact_set_ids": [1, 2], "wait_for_energy": True, "enemy": "hili"},
        "snapshot": {"build": {"character_level": 90}, "artifacts": [{"id": "a", "cr": 0.3}]},
        "result": {"winner": ["a", "b", "c", "d", "e"]},
        "score": 1_376_712.1,
        "margin": 0.031,
        "iterations": 100,
        "gcsim_pin": "abc123",
    }
    return {**base, **over}


async def save(client: AsyncClient, **over) -> dict:
    response = await client.post(RUNS, json=a_run(**over))
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_saved_run_comes_back_in_full(authed_client: AsyncClient):
    body = await save(authed_client)

    assert body["score"] == 1_376_712.1
    assert body["snapshot"]["artifacts"][0]["cr"] == 0.3


async def test_a_run_is_private_when_it_is_saved(authed_client: AsyncClient):
    """**Always**, whatever the client sends. A private thing becoming visible is not a
    mistake anyone can take back, so publishing is a separate act."""
    body = await save(authed_client)

    assert body["visibility"] == "private"
    assert body["share_key"] is None


async def test_the_list_carries_enough_to_choose_between_runs(authed_client: AsyncClient):
    await save(authed_client, name="one")
    await save(authed_client, name="two")

    rows = (await authed_client.get(RUNS)).json()

    assert [r["name"] for r in rows] == ["two", "one"]  # newest first
    assert rows[0]["summary"]["energy_model"] == "waiting"


async def test_the_list_is_newest_first_and_never_by_score(authed_client: AsyncClient):
    """A score is a damage number for one character against one enemy, so ordering two runs
    for different characters by it would invent a comparison the data does not support."""
    await save(authed_client, name="low", score=1.0)
    await save(authed_client, name="high", score=9_000_000.0)

    rows = (await authed_client.get(RUNS)).json()

    assert rows[0]["name"] == "high"      # because it is newer, not because it is bigger
    await save(authed_client, name="newest", score=2.0)
    assert (await authed_client.get(RUNS)).json()[0]["name"] == "newest"


async def test_filtering_by_character(authed_client: AsyncClient):
    await save(authed_client, name="skirk", character_id=None)
    rows = (await authed_client.get(f"{RUNS}?character_id=nobody")).json()

    assert rows == []


async def test_publishing_mints_a_share_key(authed_client: AsyncClient):
    saved = await save(authed_client)

    published = await authed_client.patch(
        f"{RUNS}/{saved['id']}", json={"visibility": "published"},
    )

    assert published.status_code == 200
    assert published.json()["share_key"]


async def test_a_published_run_is_readable_by_its_key(authed_client: AsyncClient):
    saved = await save(authed_client)
    key = (await authed_client.patch(
        f"{RUNS}/{saved['id']}", json={"visibility": "published"},
    )).json()["share_key"]

    shared = await authed_client.get(f"{RUNS}/shared/{key}")

    assert shared.status_code == 200
    assert shared.json()["score"] == 1_376_712.1


async def test_an_unpublished_run_has_no_readable_key(authed_client: AsyncClient):
    """A private run must be indistinguishable from one that does not exist, or a share key
    becomes something worth guessing at."""
    response = await authed_client.get(f"{RUNS}/shared/madeupkey")

    assert response.status_code == 404


async def test_the_result_cannot_be_edited(authed_client: AsyncClient):
    """A saved run records what happened. Rewriting it would make the library a place where
    numbers are asserted rather than measured."""
    saved = await save(authed_client)

    response = await authed_client.patch(
        f"{RUNS}/{saved['id']}", json={"score": 99.0},
    )

    assert response.status_code == 422


async def test_a_run_can_be_renamed(authed_client: AsyncClient):
    saved = await save(authed_client)

    response = await authed_client.patch(f"{RUNS}/{saved['id']}", json={"name": "renamed"})

    assert response.json()["name"] == "renamed"


async def test_a_run_can_be_deleted(authed_client: AsyncClient):
    saved = await save(authed_client)

    assert (await authed_client.delete(f"{RUNS}/{saved['id']}")).status_code == 204
    assert (await authed_client.get(f"{RUNS}/{saved['id']}")).status_code == 404


async def test_a_run_needs_its_question_and_what_it_ran_against(authed_client: AsyncClient):
    """`objective` and `snapshot` are required: a result whose question is unknown cannot be
    interpreted, and one whose inputs are unknown cannot be trusted after the gear changes."""
    body = a_run()
    del body["objective"]

    assert (await authed_client.post(RUNS, json=body)).status_code == 422
