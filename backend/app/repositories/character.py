"""Data access for the Character catalogue.

Read-only in practice: the rows come from the nanoka importer (Chunk D), and nothing over
HTTP creates or edits a character. `BaseRepository`'s write methods are inherited rather
than blocked because the seeder uses them; the API simply exposes no route that calls them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.character import Character, Talent
from app.repositories.base import BaseRepository, ilike_contains

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Select

    from app.models.enums import Element, Rarity, WeaponType


class CharacterRepository(BaseRepository[Character]):
    """Sole data-access point for the Character catalogue."""

    model = Character

    def _filtered(
        self,
        *,
        element: Element | None,
        weapon_type: WeaponType | None,
        rarity: Rarity | None,
        name: str | None,
    ) -> Select[tuple[Character]]:
        stmt = select(Character)
        if element is not None:
            stmt = stmt.where(Character.element == element)
        if weapon_type is not None:
            stmt = stmt.where(Character.weapon_type == weapon_type)
        if rarity is not None:
            stmt = stmt.where(Character.rarity == rarity)
        if name:
            stmt = stmt.where(ilike_contains(Character.name, name))
        return stmt

    async def search(
        self,
        *,
        element: Element | None = None,
        weapon_type: WeaponType | None = None,
        rarity: Rarity | None = None,
        name: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[Character]:
        """Filtered, paginated list. No relationships — a list of 150 does not need them."""
        stmt = (
            self._filtered(
                element=element, weapon_type=weapon_type, rarity=rarity, name=name,
            )
            .order_by(Character.name, Character.nanoka_id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_filtered(
        self,
        *,
        element: Element | None = None,
        weapon_type: WeaponType | None = None,
        rarity: Rarity | None = None,
        name: str | None = None,
    ) -> int:
        """Total matching `search`'s filters.

        Counted with the **same** filters rather than as a bare table count: a paginated
        envelope whose `total` ignores the filter tells a client there are 150 results and
        then hands it 3, which reads as a broken page rather than a broken count.
        """
        stmt = self._filtered(
            element=element, weapon_type=weapon_type, rarity=rarity, name=name,
        )
        result = await self.session.execute(
            select(func.count()).select_from(stmt.subquery()),
        )
        return int(result.scalar_one())

    async def get_by_nanoka_id(self, nanoka_id: str) -> Character | None:
        """One character by its source key, with talents, constellations and passives.

        The key is a **string** and Traveler variants look like `10000005-2`; see
        `Character`'s docstring. A route that took an int here would 422 on 28 of the 150.
        """
        stmt = (
            select(Character)
            .where(Character.nanoka_id == nanoka_id)
            .options(
                # Down to `scalings`, not just to `talents`. `TalentRead` returns the
                # per-level table, so stopping at the talent leaves Pydantic to touch a
                # lazy relationship on an async session — `MissingGreenlet`, a 500, and a
                # response shape that is correct in the schema and unreachable at runtime.
                selectinload(Character.talents).selectinload(Talent.scalings),
                selectinload(Character.constellations),
                selectinload(Character.ascension_passives),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
