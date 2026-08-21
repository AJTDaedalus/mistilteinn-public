"""BuffPresetRepository — data access for saved stage-buff presets (issue #64)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models.buff_preset import BuffPreset
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class BuffPresetRepository(BaseRepository[BuffPreset]):
    """Sole data-access point for the BuffPreset entity.

    ``BaseRepository`` already scopes every read and write to ``owner_id`` when one is
    set; the two overrides here exist only to order the listing by name and to make
    ``count()`` owner-scoped — an unscoped total would make a paginated list report
    other users' presets in its ``total`` field, which is a (small) cross-tenant leak
    rather than a cosmetic bug.
    """

    model = BuffPreset

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[BuffPreset]:
        """List presets, paginated, ordered by name and scoped to ``owner_id`` when set."""
        stmt = select(BuffPreset)
        if self.owner_id is not None:
            stmt = stmt.where(BuffPreset.owner_id == self.owner_id)
        stmt = stmt.order_by(BuffPreset.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update(self, entity_id: str, data: dict) -> BuffPreset | None:
        """Patch a preset, then reload it so ``updated_at`` is readable.

        ``TimestampMixin.updated_at`` carries ``onupdate=func.now()``, so the flush
        leaves the attribute expired with its new value known only to the database.
        Reading it afterwards — which the response schema does — would then trigger a
        lazy load from a synchronous context and raise ``MissingGreenlet``. Refresh here
        rather than in the route: "the row you get back is fully loaded" is a property of
        the data-access layer, and pushing it up would mean every future caller
        rediscovering this the same way.
        """
        instance = await super().update(entity_id, data)
        if instance is not None:
            await self.session.refresh(instance)
        return instance

    async def count(self) -> int:
        """Total preset count, scoped to ``owner_id`` when set."""
        stmt = select(func.count()).select_from(BuffPreset)
        if self.owner_id is not None:
            stmt = stmt.where(BuffPreset.owner_id == self.owner_id)
        result = await self.session.execute(stmt)
        return result.scalar_one()
