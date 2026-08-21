"""W-Engine repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models.w_engine import WEngine
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class WEngineRepository(BaseRepository[WEngine]):
    """Sole data-access point for the WEngine (weapon) entity."""

    model = WEngine

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        specialty: str | None = None,
        rarity: str | None = None,
    ) -> Sequence[WEngine]:
        """List w-engines, paginated and optionally filtered by specialty/rarity."""
        stmt = select(WEngine)
        if specialty:
            stmt = stmt.where(WEngine.specialty == specialty)
        if rarity:
            stmt = stmt.where(WEngine.rarity == rarity)
        stmt = stmt.order_by(WEngine.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(
        self,
        *,
        specialty: str | None = None,
        rarity: str | None = None,
    ) -> int:
        """Count w-engines matching the same specialty/rarity filters as ``get_all``."""
        stmt = select(func.count()).select_from(WEngine)
        if specialty:
            stmt = stmt.where(WEngine.specialty == specialty)
        if rarity:
            stmt = stmt.where(WEngine.rarity == rarity)
        result = await self.session.execute(stmt)
        return result.scalar_one()
