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
from app.services.practice_dummies import DUMMY_BODIES
from app.services.unreleased import UNRELEASED_WEAPON_CLASSES

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
        # The practice mannequins are 14 of the 150 rows and are never used in combat, so
        # they are hidden from every list and count rather than left to pad the grid (owner
        # ruling, 2026-08-28). Matched on the **body id**: their rows are `10000117-2` …
        # `10000118-8`, one per element, and `name` is a localised display string.
        # `app/services/practice_dummies.py` on why they are hidden rather than unseeded.
        stmt = stmt.where(
            func.split_part(Character.nanoka_id, "-", 1).notin_(DUMMY_BODIES),
        )
        # And the two Traveler variants carrying a weapon class the game has not shipped.
        # Their names are generic but the class is not, and a datamined class name on a public
        # catalogue page is the leak the report was about — `app/services/unreleased.py`.
        # `weapon_type` is non-nullable, so `notin_` cannot swallow a NULL row here.
        stmt = stmt.where(Character.weapon_type.notin_(UNRELEASED_WEAPON_CLASSES))
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
