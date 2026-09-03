"""Data access for saved optimization runs."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, select

from app.models.enums import Visibility
from app.models.optimization_run import OptimizationRun
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence

#: How many runs one list page returns.
#:
#: The list is the first thing on the optimize page, so it has to be fast before it is
#: complete — the owner's ask is *"see a list of previous runs when first going to the
#: optimization page"*, which is a glance rather than an archive.
PAGE = 50


class OptimizationRunRepository(BaseRepository[OptimizationRun]):
    """Reads and writes of saved runs."""

    model = OptimizationRun

    def _filtered(self, statement: Select, filters: dict[str, Any]) -> Select:
        """Apply the list filters that are actually answerable from a row.

        **Ordered by recency and never by score.** A score is a damage number for one
        character against one enemy, so ranking two runs for different characters by it would
        invent a comparison the data does not support.
        """
        if character := filters.get("character_id"):
            statement = statement.where(OptimizationRun.character_id == character)
        if rotation := filters.get("rotation_id"):
            statement = statement.where(OptimizationRun.rotation_id == rotation)
        if signature := filters.get("rotation_signature"):
            statement = statement.where(OptimizationRun.rotation_signature == signature)
        if pin := filters.get("gcsim_pin"):
            statement = statement.where(OptimizationRun.gcsim_pin == pin)
        if (since := filters.get("since")) is not None:
            statement = statement.where(OptimizationRun.created_at >= since)
        return statement.order_by(OptimizationRun.created_at.desc())

    async def for_owner(
        self, owner_id: str, *, limit: int = PAGE, **filters: Any,
    ) -> Sequence[OptimizationRun]:
        """This user's runs, newest first."""
        statement = self._filtered(
            select(OptimizationRun).where(OptimizationRun.owner_id == owner_id), filters,
        )
        rows = await self.session.execute(statement.limit(limit))
        return rows.scalars().all()

    async def public(self, *, limit: int = PAGE, **filters: Any) -> Sequence[OptimizationRun]:
        """Everyone's published runs, newest first."""
        statement = self._filtered(
            select(OptimizationRun).where(OptimizationRun.visibility == Visibility.PUBLISHED),
            filters,
        )
        rows = await self.session.execute(statement.limit(limit))
        return rows.scalars().all()

    async def by_share_key(self, share_key: str) -> OptimizationRun | None:
        """A published run by its key.

        **Only a public one.** A private run must be indistinguishable from one that does not
        exist, or a share key becomes something worth guessing at.
        """
        rows = await self.session.execute(
            select(OptimizationRun).where(
                OptimizationRun.share_key == share_key,
                OptimizationRun.visibility == Visibility.PUBLISHED,
            ),
        )
        return rows.scalar_one_or_none()

    @staticmethod
    def new_share_key() -> str:
        """A key for a newly published run.

        `token_urlsafe` rather than the row's uuid: a share key is handed out, and deriving it
        from the primary key would make one public run's key tell you another's.
        """
        return secrets.token_urlsafe(12)[:16]
