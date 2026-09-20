"""What the stock editor refuses, and why each refusal has to name what it refused.

`docs/DESIGN_planner_materials.md` §3. Three of the four refusals fire before the service
touches the database at all, which is what lets them be unit tests — and is itself the point:
a body with one bad row must change nothing, so every check that *can* run before the write
does. The fourth (an unknown material id) needs the catalogue and lives in
`tests/integration/test_planner_materials.py`, with the zero-deletes-the-row case.
"""

from __future__ import annotations

import pytest

from app.services.planner.stock import MAX_COUNT, StockError, set_stock

#: Nothing may be read off this. Every test here must fail before the service uses a session,
#: and an `AttributeError` from a real call is the signal that one stopped doing so.
_NO_SESSION = object()


async def _set(updates: list[tuple[int, int]]) -> None:
    await set_stock(_NO_SESSION, "owner", updates)  # type: ignore[arg-type]


async def test_a_negative_count_is_refused_by_name() -> None:
    with pytest.raises(StockError) as caught:
        await _set([(104301, -1)])
    assert "104301" in str(caught.value)
    assert "negative" in str(caught.value)


async def test_a_count_above_the_column_is_refused_by_name() -> None:
    """`user_materials.count` is `int4`.

    Unbounded, this number reaches asyncpg and returns a 500 from a route whose job was to say
    no. The message names the bound so a user can see what the ceiling is rather than guess.
    """
    with pytest.raises(StockError) as caught:
        await _set([(104301, MAX_COUNT + 1)])
    assert str(MAX_COUNT) in str(caught.value)


async def test_the_same_material_twice_is_refused_rather_than_last_wins() -> None:
    """Two counts for one material are two answers, and silently keeping one discards a
    number the user typed."""
    with pytest.raises(StockError) as caught:
        await _set([(104301, 5), (104301, 9)])
    assert "104301" in str(caught.value)
    assert "twice" in str(caught.value)


async def test_an_empty_body_writes_nothing_and_is_not_an_error() -> None:
    """Saving a tab with no dirty rows is a no-op, not a failure."""
    assert await set_stock(_NO_SESSION, "owner", []) == []  # type: ignore[arg-type]


async def test_one_bad_row_refuses_the_whole_body() -> None:
    """A partial write is the failure mode where a user fixes five numbers, sees an error, and
    cannot tell which of the five landed. The bad row is checked before anything is written —
    proven here by the session never being touched."""
    with pytest.raises(StockError):
        await _set([(104301, 40), (104302, 12), (104303, -3)])
