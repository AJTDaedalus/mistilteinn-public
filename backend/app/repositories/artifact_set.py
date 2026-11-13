"""Data access for the artifact-set catalogue."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.artifact import ArtifactSet
from app.repositories.base import BaseRepository, ilike_contains

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy import Select


class ArtifactSetRepository(BaseRepository[ArtifactSet]):
    """Sole data-access point for the ArtifactSet catalogue."""

    model = ArtifactSet

    def _filtered(self, *, name: str | None) -> Select[tuple[ArtifactSet]]:
        stmt = select(ArtifactSet)
        if name:
            stmt = stmt.where(ilike_contains(ArtifactSet.name, name))
        return stmt

    async def search(
        self, *, name: str | None = None, offset: int = 0, limit: int | None = 100,
    ) -> Sequence[ArtifactSet]:
        """Filtered, paginated list, each set with its affixes.

        The affixes come along because a set without its bonus text is not useful to
        anything asking for a list of sets, and there are 65 of them — not a page size that
        makes the join worth avoiding.
        """
        stmt = (
            self._filtered(name=name)
            .options(selectinload(ArtifactSet.affixes))
            .order_by(ArtifactSet.name, ArtifactSet.nanoka_id)
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

    async def ids_by_nanoka_ids(self, nanoka_ids: Iterable[int]) -> dict[int, str]:
        """`{nanoka id: row id}` for the ids this pin has. See `WeaponRepository`'s twin."""
        ids = list(dict.fromkeys(nanoka_ids))
        if not ids:
            return {}
        result = await self.session.execute(
            select(ArtifactSet.nanoka_id, ArtifactSet.id).where(
                ArtifactSet.nanoka_id.in_(ids),
            ),
        )
        return dict(result.all())  # type: ignore[arg-type]

    async def get_by_nanoka_id(self, nanoka_id: int) -> ArtifactSet | None:
        """One set by its source id, with its affixes."""
        stmt = (
            select(ArtifactSet)
            .where(ArtifactSet.nanoka_id == nanoka_id)
            .options(selectinload(ArtifactSet.affixes))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
