"""The character roster: which characters this user actually has.

`DESIGN_character_roster.md` §5. Two routes — read the roster, correct one row.

The correction route exists because an import is a guess made from gear, and the owner asked
for a way to overrule it: *"we need a tab for both so users can change ownership manually if
needed."*
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.character import Character
from app.models.user import User
from app.repositories.roster import CharacterRosterRepository
from app.services.roster import is_mannequin
from app.services.unreleased import is_unreleased_class

router = APIRouter(prefix="/roster", tags=["roster"])

_Session = Annotated[AsyncSession, Depends(get_db)]
_User = Annotated[User, Depends(get_current_user)]


class RosterEntryRead(BaseModel):
    """One catalogue character and this user's answer about them."""

    character_id: str
    name: str
    icon: str | None = None
    element: str | None = None
    weapon_type: str | None = None
    rarity: str | None = None
    #: **Tri-state.** `null` means nobody has said — see `CharacterRosterEntry`'s docstring.
    #: It is not the same as `false`, and collapsing the two here would make a fresh account
    #: read as "you own none of the 150 characters".
    owned: bool | None = None
    #: `"import"`, `"manual"`, or null when there is no row. Lets the tab show which answers
    #: came from a scan and which the user gave.
    source: str | None = None


class RosterRead(BaseModel):
    """The whole roster in one response."""

    entries: list[RosterEntryRead]
    #: Counted server-side so the client does not have to agree with it separately.
    owned_count: int


class RosterEntryUpdate(BaseModel):
    """The user's own answer."""

    owned: bool = Field(description="Does this account have this character?")


@router.get("", response_model=RosterRead)
async def list_roster(session: _Session, user: _User) -> RosterRead:
    """Every character that can be owned, with this user's answer where they have given one.

    **The catalogue left-joined to the roster**, rather than the roster alone: the tab has to
    offer a toggle for a character the user has never touched, and a row that does not exist
    cannot carry one.

    Mannequins are excluded — `services/roster.py` says why, and by id rather than by name.
    So are the two Traveler variants carrying a weapon class the game has not shipped: this
    list asks *"do you own this character?"* about every row it draws, and nobody owns one that
    does not exist. `app/services/unreleased.py`, and #271.

    **This route reads `select(Character)` directly**, not `CharacterRepository`, so it does
    not inherit the catalogue's exclusions and has to state them — which is how the mannequin
    rule already came to be written out here twice.
    """
    characters = (await session.execute(
        select(Character).order_by(Character.name),
    )).scalars().all()

    repository = CharacterRosterRepository(session, str(user.id))
    answers = {
        entry.character_id: (entry.owned, entry.source)
        for entry in await repository.entries()
    }

    entries = []
    for character in characters:
        if is_mannequin(character.nanoka_id) or is_unreleased_class(character.weapon_type):
            continue
        answer = answers.get(str(character.id))
        entries.append(RosterEntryRead(
            character_id=str(character.id),
            name=character.name,
            icon=character.icon,
            element=getattr(character.element, "value", None),
            weapon_type=getattr(character.weapon_type, "value", None),
            rarity=getattr(character.rarity, "value", None),
            owned=answer[0] if answer else None,
            source=answer[1] if answer else None,
        ))
    return RosterRead(
        entries=entries,
        owned_count=sum(1 for entry in entries if entry.owned),
    )


@router.patch("/{character_id}", response_model=RosterEntryRead)
async def set_owned(
    character_id: str,
    payload: RosterEntryUpdate,
    session: _Session,
    user: _User,
) -> RosterEntryRead:
    """Record the user's own answer about one character.

    Always written as `manual`, which is what stops the next import overwriting it. A user who
    un-owns a character they have gear for means it; an import that undid that every rescan
    would read as the app ignoring them.
    """
    character = (await session.execute(
        select(Character).where(Character.id == character_id),
    )).scalar_one_or_none()
    if character is None:
        raise HTTPException(status_code=404, detail="No such character")
    if is_mannequin(character.nanoka_id):
        # Refused **by name**, matching how the rotation compiler refuses a condition it does
        # not model: a silent no-op would leave a toggle that appears to work and does not.
        raise HTTPException(
            status_code=422,
            detail="Practice mannequins cannot be owned",
        )
    if is_unreleased_class(character.weapon_type):
        # `list_roster` hides these, and a write route that accepts what the read route will
        # not show writes a row nobody can see or undo. The mannequin rule guards both
        # surfaces for exactly this reason; this one had guarded only the list.
        raise HTTPException(
            status_code=422,
            detail="That character is not in the game",
        )

    repository = CharacterRosterRepository(session, str(user.id))
    await repository.set_owned(character_id, owned=payload.owned)
    await session.commit()

    return RosterEntryRead(
        character_id=character_id,
        name=character.name,
        icon=character.icon,
        element=getattr(character.element, "value", None),
        weapon_type=getattr(character.weapon_type, "value", None),
        rarity=getattr(character.rarity, "value", None),
        owned=payload.owned,
        source="manual",
    )
