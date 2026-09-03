"""Data access for a user's character roster.

`DESIGN_character_roster.md`. Sole data-access point for `character_roster`.

**Not a `BaseRepository` subclass.** That base is written against a surrogate `id` primary key
— `get_by_id`, `update`, `delete` all address a row by one — and this table is composite-keyed
on `(owner_id, character_id)` deliberately, because the tuple *is* the identity. Inheriting it
would mean a `get_by_id` that cannot work sitting on the class as an invitation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.character import Character
from app.models.roster import SOURCE_IMPORT, SOURCE_MANUAL, CharacterRosterEntry

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class CharacterRosterRepository:
    """One user's ownership answers, and the only place they are written."""

    def __init__(self, session: AsyncSession, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    async def entries(self) -> Sequence[CharacterRosterEntry]:
        """Every row this user has. Absent characters are absent — see the model docstring."""
        result = await self.session.execute(
            select(CharacterRosterEntry).where(
                CharacterRosterEntry.owner_id == self.owner_id,
            ),
        )
        return result.scalars().all()

    async def owned_nanoka_ids(self) -> set[str]:
        """The nanoka ids of characters this user owns.

        The shape `progress_for` wants — `suite.json`'s `favorite` lists are nanoka ids, so the
        teapot join needs no translation. That is the finding that made the tracker cheap, and
        it survives the move off `builds` unchanged.
        """
        result = await self.session.execute(
            select(Character.nanoka_id)
            .join(
                CharacterRosterEntry,
                CharacterRosterEntry.character_id == Character.id,
            )
            .where(
                CharacterRosterEntry.owner_id == self.owner_id,
                CharacterRosterEntry.owned.is_(True),
            ),
        )
        return {row for row in result.scalars() if row}

    async def set_owned(self, character_id: str, *, owned: bool) -> None:
        """Record the user's own answer. Always `manual`, so no import overwrites it."""
        await self.session.execute(
            insert(CharacterRosterEntry)
            .values(
                owner_id=self.owner_id,
                character_id=character_id,
                owned=owned,
                source=SOURCE_MANUAL,
            )
            .on_conflict_do_update(
                index_elements=["owner_id", "character_id"],
                set_={"owned": owned, "source": SOURCE_MANUAL},
            ),
        )

    async def upsert_imported(self, character_ids: Iterable[str]) -> int:
        """Mark these characters owned from an import, **without touching manual rows**.

        The `WHERE` on the conflict clause is the whole point and is easy to leave off: a
        re-import must refresh what a previous import said and stay silent about what the user
        said. Without it, a character someone deliberately un-owned comes back every time they
        rescan — which reads as the app ignoring them.

        Returns the number of rows actually written, so the caller can report it rather than
        assume the count it passed in.
        """
        ids = list(dict.fromkeys(character_ids))
        if not ids:
            return 0
        statement = (
            insert(CharacterRosterEntry)
            .values([
                {
                    "owner_id": self.owner_id,
                    "character_id": character_id,
                    "owned": True,
                    "source": SOURCE_IMPORT,
                }
                for character_id in ids
            ])
        )
        result = await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["owner_id", "character_id"],
                set_={"owned": True, "source": SOURCE_IMPORT},
                where=CharacterRosterEntry.source == SOURCE_IMPORT,
            ),
        )
        return result.rowcount or 0
