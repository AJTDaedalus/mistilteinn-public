"""Data access for a user's weapon inventory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.build import Build
from app.models.weapon import OwnedWeapon
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Select


class OwnedWeaponRepository(BaseRepository[OwnedWeapon]):
    """The weapons a user owns, as opposed to the ones the catalogue describes."""

    model = OwnedWeapon

    def _filtered(self, *, equipped: bool | None) -> Select[tuple[OwnedWeapon]]:
        stmt = select(OwnedWeapon)
        if self.owner_id is not None:
            stmt = stmt.where(OwnedWeapon.owner_id == self.owner_id)
        if equipped is True:
            stmt = stmt.where(OwnedWeapon.build_id.is_not(None))
        elif equipped is False:
            stmt = stmt.where(OwnedWeapon.build_id.is_(None))
        return stmt

    async def search(
        self, *, equipped: bool | None = None, offset: int = 0, limit: int = 50,
    ) -> Sequence[OwnedWeapon]:
        """Equipped first, then by refinement and level, then by name.

        **Equipped first is the default, not a sort option**, because it is what the owner
        asked for and because it is the only ordering that answers "what am I actually using"
        without a filter. Refinement before level within that: an R5 is a materially different
        weapon from an R1, and level is the easier of the two to change.

        Eager-loads the catalogue row and the holding build's character — the inventory shows
        the holder's portrait, and a lazy hop per row is a `MissingGreenlet` inside a request.
        """
        stmt = (
            self._filtered(equipped=equipped)
            .options(
                selectinload(OwnedWeapon.weapon),
                selectinload(OwnedWeapon.build).selectinload(Build.character),
            )
            .order_by(
                OwnedWeapon.build_id.is_(None),
                OwnedWeapon.refinement.desc(),
                OwnedWeapon.level.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def count_filtered(self, *, equipped: bool | None = None) -> int:
        """How many rows the same filter matches, for the paginated total."""
        stmt = self._filtered(equipped=equipped).with_only_columns(
            func.count(), maintain_column_froms=True,
        )
        return int((await self.session.execute(stmt)).scalar_one())
