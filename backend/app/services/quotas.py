"""Per-account resource caps.

The layer that assumes every bot defence in `docs/DESIGN_open_registration.md` §5.5
failed. Turnstile, the honeypot, the rate limits and the domain list are all
probabilistic; the correct assumption is that some bots get accounts. What has to be true
is that an account which gets through **cannot cost an unbounded amount** — see §6.

**This app's expensive thing is not CPU.** Fairy's version of this module guards a
server-side numba optimizer; here the search is compiled to wasm and runs in the user's own
browser, so an account that gets through costs *rows*, not cycles. The row caps below are
sized against the owner's real inventory — 2,369 artifacts, 75 builds — so a cap sits clear
of a real player and well under a farm.

**The one that is not about us** is `POST /rotations/import/link`: the only request-time
outbound fetch in `app/`, pointed at gcsim's servers. Open registration would make it a free
proxy, and the owner ruled on exactly this (2026-09-02): *"I don't want to push our compute
load to them."* Its cap is enforced at the endpoint rather than here, because it bounds calls
per day rather than rows held.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import HTTPException, status


class _Countable(Protocol):
    """Anything that can report how many rows the caller already holds.

    A Protocol rather than `BaseRepository` because the clean-import path counts zero by
    construction — it deletes the inventory before inserting — and passing a repository
    there would make it ask the database a question whose answer is irrelevant.
    """

    async def count(self) -> int: ...


async def enforce_quota(repo: _Countable, limit: int, noun: str) -> None:
    """Raise 409 if the caller already holds *limit* rows of this kind.

    409 with the limit spelled out, not a bare 4xx: a real user who has genuinely reached
    10,000 artifacts deserves to know why their next save failed, and "Artifact limit reached
    (10000)." is the difference between a bug report and a decision to tidy up.

    Relies on `BaseRepository.count()` being owner-scoped — an unscoped count would let
    one busy account consume everybody else's allowance.
    """
    if limit <= 0:
        return
    if await repo.count() >= limit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{noun} limit reached ({limit}). Delete some before adding more.",
        )


async def enforce_headroom(repo: _Countable, limit: int, noun: str, incoming: int) -> None:
    """Raise 409 if *incoming* new rows would take the caller past *limit*.

    Bulk import needs this rather than `enforce_quota`: a one-row-under-the-cap account
    importing 5,000 artifacts passes a "are you at the limit yet?" check and lands 5,000 rows
    over it. The cap has to be checked against the size of what is arriving.
    """
    if limit <= 0:
        return
    current = await repo.count()
    if current + incoming > limit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{noun} limit reached ({limit}). This import would add {incoming} to "
                f"{current}. Delete some before importing."
            ),
        )


def enforce_daily(created_today: int, limit: int, noun: str) -> None:
    """Raise 429 if the caller has already created *limit* rows of this kind in a day.

    429 rather than 409: nothing needs deleting, the allowance simply refills. Takes the
    count rather than a repository because "today" is a query each table answers its own way.
    """
    if limit <= 0:
        return
    if created_today >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"{noun} daily limit reached ({limit}). Try again tomorrow.",
        )

