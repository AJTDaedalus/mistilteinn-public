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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.character import Character, Talent
from app.models.user import User
from app.repositories.roster import CharacterRosterRepository
from app.services import gcsim_keys, traveler
from app.services.roster import is_mannequin, is_unreleased

router = APIRouter(prefix="/roster", tags=["roster"])

_Session = Annotated[AsyncSession, Depends(get_db)]
_User = Annotated[User, Depends(get_current_user)]


class RosterEntryRead(BaseModel):
    """One catalogue character and this user's answer about them."""

    character_id: str
    name: str
    #: The name to put on the row, which for sixteen characters is not `name`.
    #:
    #: Every `Traveler` row is *named* `Traveler`, so this tab drew Aether Pyro and Lumine Pyro
    #: as the same row twice and the two unreleased bodies — no element, so no chip —
    #: identically. Sixteen checkboxes all announcing "I have Traveler", on the one tab whose
    #: whole purpose is letting a user correct ownership by hand.
    #: `app/services/traveler.py`, `docs/RESEARCH_traveler_identity.md`.
    display_name: str
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
    #: Whether gcsim implements this character at the pinned commit.
    #:
    #: **Owning them and being able to search them are different questions**, and this tab was
    #: answering only the first. gcsim has six Traveler elements, not seven — there is no Cryo
    #: Traveler — so the one Traveler on the owner's account is the one element that cannot be
    #: compiled, and nothing said so until a search failed. `character_key` has always refused
    #: it correctly; what was missing was anybody asking before offering the build.
    simulatable: bool = True
    #: Why not, in gcsim's own terms, when `simulatable` is false. Null otherwise.
    unsimulatable_reason: str | None = None


def _entry(
    character: Character, *, owned: bool | None, source: str | None,
) -> RosterEntryRead:
    """One row, built the same way on both routes.

    They were built separately, and `PATCH` therefore returned a row shaped slightly unlike the
    one `GET` had produced — harmless while the fields were few and exactly the kind of drift
    that puts a name on one route and not the other.
    """
    element = getattr(character.element, "value", None)
    try:
        gcsim_keys.character_key(character.nanoka_id, character.name, element)
    except gcsim_keys.GcsimKeyError as refusal:
        simulatable, reason = False, str(refusal)
    else:
        simulatable, reason = True, None

    return RosterEntryRead(
        character_id=str(character.id),
        name=character.name,
        display_name=traveler.display_name(
            name=character.name, icon=character.icon, element=element,
        ),
        icon=character.icon,
        element=element,
        weapon_type=getattr(character.weapon_type, "value", None),
        rarity=getattr(character.rarity, "value", None),
        owned=owned,
        source=source,
        simulatable=simulatable,
        unsimulatable_reason=reason,
    )


class RosterRead(BaseModel):
    """The whole roster in one response."""

    entries: list[RosterEntryRead]
    #: Counted server-side so the client does not have to agree with it separately.
    owned_count: int
    #: Catalogue rows this response left out because the game has not shipped them.
    #:
    #: **Published rather than silent**, and that is the point of the number. Withholding rows
    #: is the one thing this endpoint does that a user cannot see, so a rule that misfired
    #: would empty the roster with no symptom at all. Two at nanoka 7.0.51; anything else is a
    #: seed to look at.
    withheld: int = 0


class RosterEntryUpdate(BaseModel):
    """The user's own answer."""

    owned: bool = Field(description="Does this account have this character?")


@router.get("", response_model=RosterRead)
async def list_roster(session: _Session, user: _User) -> RosterRead:
    """Every character that can be owned, with this user's answer where they have given one.

    **The catalogue left-joined to the roster**, rather than the roster alone: the tab has to
    offer a toggle for a character the user has never touched, and a row that does not exist
    cannot carry one.

    **Two exclusions, for two different reasons.** Mannequins are never characters and go by
    nanoka id prefix; the unreleased bodies will be characters and go by having no talents.
    `services/roster.py` argues both, and keeps them apart on purpose.

    Ordered by `display_name`, not `name` — sixteen rows sharing one `name` have no order
    among themselves under the latter, so the Travelers appeared in whatever order the database
    returned and could shuffle between requests.
    """
    counts = dict((await session.execute(
        select(Talent.character_id, func.count(Talent.id)).group_by(Talent.character_id),
    )).all())
    characters = (await session.execute(
        select(Character).order_by(Character.name),
    )).scalars().all()

    repository = CharacterRosterRepository(session, str(user.id))
    answers = {
        entry.character_id: (entry.owned, entry.source)
        for entry in await repository.entries()
    }

    entries = []
    withheld = 0
    for character in characters:
        if is_mannequin(character.nanoka_id):
            continue
        if is_unreleased(character.element, counts.get(str(character.id), 0)):
            withheld += 1
            continue
        answer = answers.get(str(character.id))
        entries.append(_entry(
            character,
            owned=answer[0] if answer else None,
            source=answer[1] if answer else None,
        ))
    entries.sort(key=lambda entry: entry.display_name)
    return RosterRead(
        entries=entries,
        owned_count=sum(1 for entry in entries if entry.owned),
        withheld=withheld,
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

    talents = (await session.execute(
        select(func.count(Talent.id)).where(Talent.character_id == character_id),
    )).scalar_one()
    if is_unreleased(character.element, talents):
        # Refused by name for the same reason, and with a *different* message: "cannot be
        # owned" and "is not in the game yet" are different facts, and a user who reads the
        # first about a character they are waiting for learns nothing.
        raise HTTPException(
            status_code=422,
            detail=(
                "This character has no element and no talents at the pinned patch, so they "
                "cannot be built, simulated, or owned yet."
            ),
        )

    repository = CharacterRosterRepository(session, str(user.id))
    await repository.set_owned(character_id, owned=payload.owned)
    await session.commit()

    return _entry(character, owned=payload.owned, source="manual")
