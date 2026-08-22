"""Data access for enemy profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models.build import EnemyProfile
from app.repositories.base import BaseRepository, ilike_contains

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Select


class EnemyProfileRepository(BaseRepository[EnemyProfile]):
    """Sole data-access point for enemy profiles."""

    model = EnemyProfile

    def _filtered(self, *, name: str | None) -> Select[tuple[EnemyProfile]]:
        stmt = select(EnemyProfile)
        if name:
            stmt = stmt.where(ilike_contains(EnemyProfile.name, name))
        return stmt

    async def search(
        self, *, name: str | None = None, offset: int = 0, limit: int = 100,
    ) -> Sequence[EnemyProfile]:
        """Filtered, paginated list.

        Ordered by name then id: there are 360 of them and several families share a display
        name, so without the tiebreak two pages of the same query can return the same row
        twice and skip another.
        """
        stmt = (
            self._filtered(name=name)
            .order_by(EnemyProfile.name, EnemyProfile.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_filtered(self, *, name: str | None = None) -> int:
        """Total matching `search`'s filter — see `CharacterRepository.count_filtered`."""
        result = await self.session.execute(
            select(func.count()).select_from(self._filtered(name=name).subquery()),
        )
        return int(result.scalar_one())
