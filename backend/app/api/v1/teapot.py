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
from app.models.teapot import (
    FurnishingSuite,
    FurnishingSuiteFavorite,
    TeapotBuilt,
    TeapotProgress,
)
from app.models.user import User
from app.repositories.roster import CharacterRosterRepository
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
    # **Three states per character per set** — the owner's own vocabulary. Every favouring
    # character is in exactly one, and the tracker exists for the first: which set to build
    # next, because it has characters you have not invited yet.
    #: Available and owned — worth 20 primogems each.
    available: list[str]
    #: Completed and owned — already invited, worth nothing more.
    completed: list[str]
    #: Available and not owned — why a set can be worth less than its favourite count says.
    unowned: list[str]
    #: Has the user built this set?
    #:
    #: A different axis from the invitations: building costs materials and time, inviting to
    #: a set already standing costs a walk. Two sets worth 60 primogems are not equal work.
    built: bool
    #: Nothing left to claim from the characters this user owns.
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
    # **The roster, not builds.** This joined `builds.owned` until 2026-09-03, which meant a
    # character had to be *holding gear* to count as owned — so twelve characters the owner has
    # were invisible here, worth 22 sets and 440 Primogems. `DESIGN_character_roster.md`.
    #
    # `services/teapot.py` is unchanged: `progress_for` takes the id set as an argument, so the
    # source of truth could move without the tracker's logic knowing. That is what passing it in
    # rather than querying inside bought.
    owned_ids = await CharacterRosterRepository(session, str(user.id)).owned_nanoka_ids()

    # `(suite, character)` pairs, because the reward is **per character per set**: the same
    # character invited to one of their two favourite sets is still owed the other.
    invited = {
        (suite_id, character)
        for suite_id, character in await session.execute(
            select(TeapotProgress.suite_id, TeapotProgress.character_nanoka_id)
            .where(TeapotProgress.owner_id == user.id),
        )
    }

    built = set((await session.execute(
        select(TeapotBuilt.suite_id).where(TeapotBuilt.owner_id == user.id),
    )).scalars())

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
        invited,
        built,
    )
    return TeapotRead(
        suites=[
            SuiteRow(
                suite_id=row.suite_id, name=row.name, icon=row.icon,
                placement=row.placement,
                available=list(row.available), completed=list(row.completed),
                unowned=list(row.unowned), built=row.built, done=row.done,
                remaining=row.remaining, remaining_primogems=row.remaining_primogems,
            )
            for row in rows
        ],
        reward_per_character=REWARD_PER_CHARACTER,
    )


@router.put("/suites/{suite_id}/invited/{character_nanoka_id}", status_code=204)
async def mark_invited(
    suite_id: str, character_nanoka_id: str, session: _Session, user: _User,
) -> None:
    """Record that this character has been invited to this set.

    **Per character per set**, because that is how the reward is given: a set favoured by three
    characters you own is worth three invitations and 60 primogems. Ticking the set as a whole
    would either lose the two you had not done or ask you to repeat the one you had.

    Idempotent — ticking twice is not an error, and a client retrying a request it is not sure
    landed should not have to care.
    """
    suite = await session.get(FurnishingSuite, suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="no such furnishing set")
    existing = await session.get(
        TeapotProgress,
        {
            "owner_id": user.id, "suite_id": suite_id,
            "character_nanoka_id": character_nanoka_id,
        },
    )
    if existing is None:
        session.add(TeapotProgress(
            owner_id=user.id, suite_id=suite_id,
            character_nanoka_id=character_nanoka_id,
        ))
        await session.commit()


@router.delete("/suites/{suite_id}/invited/{character_nanoka_id}", status_code=204)
async def mark_not_invited(
    suite_id: str, character_nanoka_id: str, session: _Session, user: _User,
) -> None:
    """Un-tick one character on one set.

    **The reason a completed character stays on the row rather than vanishing**: a user has to
    be able to undo a tick, which means they have to be able to see it.
    """
    await session.execute(
        delete(TeapotProgress).where(
            TeapotProgress.owner_id == user.id,
            TeapotProgress.suite_id == suite_id,
            TeapotProgress.character_nanoka_id == character_nanoka_id,
        ),
    )
    await session.commit()


@router.put("/suites/{suite_id}/built", status_code=204)
async def mark_built(suite_id: str, session: _Session, user: _User) -> None:
    """Record that this set has been built.

    **Separate from the invitations, because it is separate work.** Owner, 2026-09-03:
    *"it takes time and effort to build them so that's different from the invites."* A set can
    be built with nobody invited yet, and every character can be invited to a set the user
    never told us they built — neither implies the other.

    Idempotent, like the invitation endpoints.
    """
    if await session.get(FurnishingSuite, suite_id) is None:
        raise HTTPException(status_code=404, detail="no such furnishing set")
    existing = await session.get(
        TeapotBuilt, {"owner_id": user.id, "suite_id": suite_id},
    )
    if existing is None:
        session.add(TeapotBuilt(owner_id=user.id, suite_id=suite_id))
        await session.commit()


@router.delete("/suites/{suite_id}/built", status_code=204)
async def mark_not_built(suite_id: str, session: _Session, user: _User) -> None:
    """Un-mark a set as built — a set can be dismantled, and a tick can be a mistake."""
    await session.execute(
        delete(TeapotBuilt).where(
            TeapotBuilt.owner_id == user.id, TeapotBuilt.suite_id == suite_id,
        ),
    )
    await session.commit()
