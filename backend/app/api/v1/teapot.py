"""The teapot set tracker — `DESIGN_account_tracking.md` Track 3.

Owner: *"a teapot set tracker, backed by the 'owned' flag on user's builds, like seelie.me's
teapot set calculator. This one should be sortable by remaining primogems and lets users mark
off which they've already done like Seelie does."*

The join is `furnishing_suite_favorites.character_nanoka_id` against the characters this user
has an **owned** build for. That works with no translation because nanoka publishes favourites
by the same id `characters.nanoka_id` already holds — verified against the seeded data: all
232 favourite rows resolve.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.build import Build
from app.models.character import Character
from app.models.teapot import FurnishingSuite, FurnishingSuiteFavorite, TeapotProgress
from app.models.user import User
from app.services.teapot import REWARD_PER_CHARACTER, progress_for

router = APIRouter(prefix="/teapot", tags=["teapot"])

_Session = Annotated[AsyncSession, Depends(get_db)]
_User = Annotated[User, Depends(get_current_user)]


class SuiteRow(BaseModel):
    """One set in the tracker."""

    suite_id: str
    name: str
    icon: str
    placement: str
    #: Characters who favour this set and whom the user has.
    owned_favorites: list[str]
    #: Characters who favour it that the user does not have.
    #:
    #: Shown rather than hidden: it is why a set can be worth less than its favourite count
    #: suggests, and a reader who cannot see that will think the tracker is wrong.
    unowned_favorites: list[str]
    done: bool
    remaining: int
    #: `remaining × reward`, or **null while the reward constant is uncited** (OQ-A4).
    remaining_primogems: int | None = None


class TeapotRead(BaseModel):
    """The tracker, ranked."""

    suites: list[SuiteRow]
    #: Null until somebody cites it. Published so a client can say *why* the column is empty
    #: rather than rendering a blank nobody can explain.
    reward_per_character: int | None = None


@router.get("/suites", response_model=TeapotRead)
async def list_suites(session: _Session, user: _User) -> TeapotRead:
    """Every furnishing set, ranked by how much of it this user can still claim.

    **Ordered by remaining owned favourites**, which is the same order the owner's
    "remaining primogems" would give: the reward is one constant per character, and a positive
    constant multiplier cannot change a ranking.
    """
    owned = await session.execute(
        select(Character.nanoka_id)
        .join(Build, Build.character_id == Character.id)
        .where(Build.owner_id == user.id, Build.owned.is_(True)),
    )
    owned_ids = {row for row in owned.scalars() if row}

    done = await session.execute(
        select(TeapotProgress.suite_id).where(TeapotProgress.owner_id == user.id),
    )
    done_ids = set(done.scalars())

    suites = (await session.execute(select(FurnishingSuite))).scalars().all()
    favorites: dict[str, list[str]] = {}
    for suite_id, character in await session.execute(
        select(
            FurnishingSuiteFavorite.suite_id, FurnishingSuiteFavorite.character_nanoka_id,
        ),
    ):
        favorites.setdefault(suite_id, []).append(character)

    rows = progress_for(
        [
            {
                "id": suite.id, "name": suite.name, "icon": suite.icon,
                "placement": suite.placement, "favorite": favorites.get(suite.id, []),
            }
            for suite in suites
        ],
        owned_ids,
        done_ids,
    )
    return TeapotRead(
        suites=[
            SuiteRow(
                suite_id=row.suite_id, name=row.name, icon=row.icon,
                placement=row.placement, owned_favorites=list(row.owned_favorites),
                unowned_favorites=list(row.unowned_favorites), done=row.done,
                remaining=row.remaining, remaining_primogems=row.remaining_primogems,
            )
            for row in rows
        ],
        reward_per_character=REWARD_PER_CHARACTER,
    )


@router.put("/suites/{suite_id}/done", status_code=204)
async def mark_done(suite_id: str, session: _Session, user: _User) -> None:
    """Mark a set as already done.

    Idempotent: ticking a set twice is not an error, and a client that retries a request it
    is not sure landed should not have to care.
    """
    suite = await session.get(FurnishingSuite, suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="no such furnishing set")
    existing = await session.get(TeapotProgress, {"owner_id": user.id, "suite_id": suite_id})
    if existing is None:
        session.add(TeapotProgress(owner_id=user.id, suite_id=suite_id))
        await session.commit()


@router.delete("/suites/{suite_id}/done", status_code=204)
async def mark_not_done(suite_id: str, session: _Session, user: _User) -> None:
    """Un-tick a set.

    **The reason finished sets sink rather than disappear**: a user has to be able to undo a
    tick, which means they have to be able to see it.
    """
    await session.execute(
        delete(TeapotProgress).where(
            TeapotProgress.owner_id == user.id, TeapotProgress.suite_id == suite_id,
        ),
    )
    await session.commit()
