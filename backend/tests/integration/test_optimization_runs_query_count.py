"""Listing saved runs costs the same whatever the page holds.

`TASKS_account_tracking.md` 2.7. The same shape of bug as the rotation library's, and the
same reason it deserves a test: **an N+1 does not fail.** It returns the right answer, passes
every functional test, and gets slower in proportion to how much the feature is used — so it
is found by the user whose list finally got big enough.

This list is the *first thing* on the optimize page, which is what makes it worth pinning
here rather than later: a slow list is a slow page, before anybody has asked for anything.

**The number is not the point; its independence from the row count is.** The assertion is
that a two-run page and a ten-run page cost the same, not that either costs three.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import event

from tests.integration.test_optimization_runs import RUNS, a_run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


@contextlib.contextmanager
def counting(bind: Any) -> Iterator[list[str]]:
    """Record every statement `bind` executes while the block runs.

    Two ways to get this silently wrong, both recorded by the rotation library's version and
    both repeated here because the trap does not go away:

    **The engine has to be the one the request uses.** Listening on `app.database.engine`
    when `conftest` built its own records nothing, and the test then passes by comparing zero
    with zero — which this repo has actually shipped.

    **And it has to be the sync engine underneath**, because `AsyncEngine` proxies the events
    of `engine.sync_engine`.
    """
    seen: list[str] = []

    def before(conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any) -> None:
        del conn, cursor, args, kwargs
        seen.append(statement)

    event.listen(bind, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(bind, "before_cursor_execute", before)


async def _save(client: AsyncClient, count: int, label: str) -> None:
    for index in range(count):
        response = await client.post(RUNS, json=a_run(name=f"{label} {index}"))
        assert response.status_code == 201, response.text


async def _count(client: AsyncClient, bind: Any) -> tuple[int, int]:
    """`(queries, rows)` for one listing."""
    with counting(bind) as statements:
        listed = await client.get(RUNS)
    assert listed.status_code == 200, listed.text
    return len(statements), len(listed.json())


async def test_the_listing_does_not_grow_a_query_per_run(
    authed_client: AsyncClient, test_engine: Any,
) -> None:
    bind = test_engine.sync_engine

    await _save(authed_client, 2, "small")
    small_queries, small_rows = await _count(authed_client, bind)

    await _save(authed_client, 8, "large")
    large_queries, large_rows = await _count(authed_client, bind)

    # The rows must actually differ, or the comparison proves nothing about scaling.
    assert large_rows > small_rows, "the second listing must be bigger to be a test at all"
    assert small_queries == large_queries, (
        f"{small_rows} runs cost {small_queries} queries and {large_rows} cost "
        f"{large_queries} — the listing grows with the page, which is an N+1."
    )


async def test_the_counter_actually_observes_the_request(
    authed_client: AsyncClient, test_engine: Any,
) -> None:
    """**The guard on the guard.**

    A query counter listening to the wrong engine records nothing and then passes by comparing
    zero with zero. This repo has shipped exactly that, so the counter is asserted to have
    seen something before its silence is trusted.
    """
    await _save(authed_client, 1, "one")

    queries, _ = await _count(authed_client, test_engine.sync_engine)

    assert queries > 0, "the counter saw no statements at all, so it is measuring nothing"
