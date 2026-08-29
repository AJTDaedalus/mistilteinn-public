"""The rotation library's listing does a fixed number of queries, whatever the page holds.

`TASKS_rotation_library.md` L.7, which is explicit that the guarantee is not asserted by
reading the code:

> This repo has no query-count harness yet, so L.7 includes building the smallest one that
> works — `sqlalchemy.event` on `before_cursor_execute` — or the task is not done, because
> "constant" asserted by reading the code is not asserted at all.

## Why this shape of bug is worth a test of its own

An N+1 does not fail. It returns the right answer, passes every functional test, and gets
slower in proportion to how much the feature is used — so it is discovered by the user whose
library finally got big enough. `like_counts`, `characters_for`, `liked_by` and `dps_by_rotation`
are each written as one aggregate over a list of ids precisely to avoid that, and nothing but
this file notices if one of them is later rewritten as a loop.

**The number is not the point; its independence from the row count is.** So the assertion is
that a two-rotation page and a six-rotation page cost the *same*, not that either costs four.
A refactor that legitimately adds a query stays green until it adds one *per row*.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import event

from tests.integration.test_rotation_library import (  # noqa: F401 — fixtures
    AYAKA,
    BARBARA,
    LIBRARY,
    Party,
    _rotation,
    alice,
    bob,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


@contextlib.contextmanager
def counting(bind: Any) -> Iterator[list[str]]:
    """Record every statement `bind` executes while the block runs.

    Two ways to get this silently wrong, and the first draft managed one of them:

    **The engine has to be the one the request uses.** `conftest` builds its own
    `test_engine`; listening on `app.database.engine` records nothing, and the test then
    passes by comparing zero with zero. Caught by `python -m scripts.inject`, which put a
    real N+1 into the handler and watched this file not notice — the harness doing exactly
    the job it exists for.

    **And it has to be the sync engine underneath.** `AsyncEngine` proxies the events of
    `engine.sync_engine`; registering on the async object records nothing either.
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


async def _publish(party: Party, count: int, label: str) -> None:
    for i in range(count):
        # Alternating character sets, so the rows are not identical and nothing can collapse
        # them into one lookup by accident.
        await _rotation(
            party, f"{label} {i}", AYAKA if i % 2 else BARBARA, publish=True,
        )


async def _count(party: Party, bind: Any) -> tuple[int, int]:
    """`(queries, rows)` for one listing.

    Rows are **observed, not assumed**: the library is cross-user by design, so a second
    account sees everything the first published as well as its own. Asserting a row count
    from what this test published would fail on the feature working correctly.
    """
    with counting(bind) as statements:
        listed = await party.client.get(LIBRARY)
    assert listed.status_code == 200, listed.text
    return len(statements), len(listed.json()["items"])


@pytest.fixture
def bind(db_session: AsyncSession) -> Any:
    """The sync engine the test session actually runs on — see `counting`.

    `get_bind()` on a session bound to a connection already hands back the **sync** `Engine`,
    not the `AsyncEngine`, so there is no `.sync_engine` to reach for here. Written the other
    way first, which failed loudly — the good kind.
    """
    return db_session.get_bind().engine


async def test_the_listing_costs_the_same_for_two_rotations_as_for_six(
    alice: Party, bob: Party, bind: Any,  # noqa: F811
):
    """The load-bearing assertion, and the only one that would catch an N+1.

    Two separate accounts rather than two pages of one, because a second request from the same
    client would reuse rows the first had already loaded into the session's identity map and
    the second count would be lower for the wrong reason.
    """
    await _publish(alice, 2, "Small")
    small, small_rows = await _count(alice, bind)

    await _publish(bob, 6, "Large")
    large, large_rows = await _count(bob, bind)

    assert large_rows > small_rows, "the second listing has to be bigger, or this proves nothing"
    assert small == large, (
        f"a {small_rows}-rotation page cost {small} queries and a {large_rows}-rotation page "
        f"cost {large}. Something in the listing is now per-row: check `characters_for`, "
        f"`like_counts`, `liked_by` and `_your_dps`, each of which takes a list of ids on "
        f"purpose."
    )


async def test_the_listing_is_a_handful_of_queries_rather_than_a_dozen(
    alice: Party, bind: Any,  # noqa: F811
):
    """A loose ceiling, so a refactor that adds one query stays green and one that adds a
    join-per-facet does not.

    **Sixteen is measured, not chosen**: the listing costs fourteen today, and most of that is
    per-request rather than per-listing — the bearer token, the session lookup and its touch,
    the user row. Deliberately not pinned to the exact figure, which would make this a chore
    to update rather than a signal; the load-bearing assertion is the other test, which does
    not care what the constant is as long as it stays one.
    """
    await _publish(alice, 3, "Some")
    count, rows = await _count(alice, bind)

    assert count <= 16, f"the listing issued {count} queries for {rows} rotations"
